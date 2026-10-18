"""Attachment Manager for handling binary data persistence.

Manages serialization and hydration of heavy binary payloads
(like UMAP numpy arrays) separate from the core workflow JSON logic.
"""

import tempfile
import uuid
from pathlib import Path
from typing import Any

import numpy as np
from karcytics_sdk.plugin import get_logger

from ...analysis.clustering import FLOWSOM, PHENOGRAPH, method_of, tree_embedding
from ...analysis.clustering.phenograph import graph_embedding

logger = get_logger(__name__, "flow_cytometry")

# A FlowSOM run's node-level arrays (stored in the metadata as lists).
FLOWSOM_NODE_ARRAYS = ("codes", "grid", "mst_edges", "layout", "linkage", "node_metaclusters")
# A PhenoGraph run's cluster-level arrays (stored in the metadata as lists).
PHENOGRAPH_CLUSTER_ARRAYS = ("layout", "cluster_edges", "cluster_connectivity")
# Event-level arrays: saved as attachments, or rebuilt on load.
_FLOWSOM_REBUILT = (
    "indices",
    "nodes",
    "embedding",
    "clusters",
    "intensities",
    "cluster_stats",
    "marker_heatmap",
    "cluster_heatmap",
)


class AttachmentManager:
    """Handles persistence of binary data attachments."""

    def __init__(self, axis_manager):
        self._axis_manager = axis_manager
        self.temp_dir = Path(tempfile.gettempdir())

    def serialize_attachments(self, state: Any, context: Any) -> dict:
        """Serialize all known binary attachments from the state."""
        meta = {}
        if getattr(state.data, "umap_results", None):
            meta["umap_results"] = self.serialize_umap_results(state.data.umap_results, context)
        # Register future attachment types here
        return meta

    def hydrate_attachments(self, meta_dict: dict, state: Any, context: Any) -> None:
        """Hydrate all binary attachments into the state."""
        if "umap_results" in meta_dict:
            res = self.hydrate_umap_results(meta_dict["umap_results"], state, context)
            if res:
                state.data.umap_results = res
        # Hydrate future attachment types here

    def serialize_umap_results(self, umap_results: dict, context: Any) -> dict:
        """Serialize UMAP embeddings and indices to binary attachments."""
        meta_dict: dict = {}

        if not context:
            return meta_dict

        for key, runs in umap_results.items():
            meta_dict[key] = []
            for res in runs:
                if method_of(res) is FLOWSOM:
                    meta_dict[key].append(self._serialize_flowsom(res, context))
                    continue
                if method_of(res) is PHENOGRAPH:
                    meta_dict[key].append(self._serialize_phenograph(res, context))
                    continue
                emb_key = res.get("emb_key")
                idx_key = res.get("idx_key")
                cls_key = res.get("cls_key")

                if not emb_key or not idx_key:
                    run_uuid = uuid.uuid4().hex[:8]
                    emb_key = f"umap_emb_{run_uuid}"
                    idx_key = f"umap_idx_{run_uuid}"
                    if "clusters" in res:
                        cls_key = f"umap_cls_{run_uuid}"

                emb_path = self.temp_dir / f"{emb_key}.npy"
                if not emb_path.exists():
                    np.save(emb_path, res["embedding"])
                context.add_attachment(emb_key, emb_path, "UMAP Coordinates")

                idx_path = self.temp_dir / f"{idx_key}.npy"
                if not idx_path.exists():
                    np.save(idx_path, res["indices"])
                context.add_attachment(idx_key, idx_path, "UMAP Indices")

                meta = {
                    k: v
                    for k, v in res.items()
                    if k
                    not in [
                        "embedding",
                        "indices",
                        "clusters",
                        "intensities",
                        "cluster_stats",
                        "marker_heatmap",
                        "cluster_heatmap",
                    ]
                }
                meta.update(
                    {
                        "has_clusters": "clusters" in res,
                        "emb_key": emb_key,
                        "idx_key": idx_key,
                    }
                )

                if "clusters" in res and cls_key:
                    cls_path = self.temp_dir / f"{cls_key}.npy"
                    if not cls_path.exists():
                        np.save(cls_path, res["clusters"])
                    context.add_attachment(cls_key, cls_path, "UMAP Clusters")
                    meta["cls_key"] = cls_key

                res["emb_key"] = emb_key
                res["idx_key"] = idx_key
                if "clusters" in res and cls_key:
                    res["cls_key"] = cls_key

                meta_dict[key].append(meta)

        return meta_dict

    def hydrate_umap_results(self, meta_dict: dict, state: Any, context: Any) -> dict:
        """Hydrate UMAP embeddings from binary attachments."""
        results: dict = {}

        if not context or not isinstance(meta_dict, dict):
            return results

        for key, runs_meta in meta_dict.items():
            results[key] = []
            for meta in runs_meta:
                if method_of(meta) in (FLOWSOM, PHENOGRAPH):
                    hydrate = (
                        self._hydrate_flowsom
                        if method_of(meta) is FLOWSOM
                        else self._hydrate_phenograph
                    )
                    run = hydrate(meta, state, context)
                    if run is not None:
                        results[key].append(run)
                    continue
                emb_path = context.get_path(meta.get("emb_key"))
                idx_path = context.get_path(meta.get("idx_key"))

                if emb_path and emb_path.exists() and idx_path and idx_path.exists():
                    res = meta.copy()

                    res.update({"embedding": np.load(emb_path), "indices": np.load(idx_path)})

                    self._reconstruct_intensities(res, meta, state)

                    if meta.get("has_clusters") and meta.get("cls_key"):
                        cls_path = context.get_path(meta["cls_key"])
                        if cls_path and cls_path.exists():
                            res["clusters"] = np.load(cls_path)
                            self._reconstruct_cluster_stats(res)

                    results[key].append(res)

        return results

    def _attach(self, context: Any, key: str, array: np.ndarray, label: str) -> None:
        path = self.temp_dir / f"{key}.npy"
        if not path.exists():
            np.save(path, array)
        context.add_attachment(key, path, label)

    def _serialize_flowsom(self, res: dict, context: Any) -> dict:
        """Indices and each event's node go to attachments; node-level arrays are small,
        so they stay in the metadata; the map and labels are rebuilt from them on load.
        """
        if not res.get("idx_key"):
            run_uuid = uuid.uuid4().hex[:8]
            res["idx_key"], res["nodes_key"] = f"umap_idx_{run_uuid}", f"flowsom_nodes_{run_uuid}"
        self._attach(context, res["idx_key"], res["indices"], "FlowSOM Indices")
        nodes = np.asarray(res["nodes"]).astype(np.int32)
        self._attach(context, res["nodes_key"], nodes, "FlowSOM Nodes")
        meta = {k: v for k, v in res.items() if k not in _FLOWSOM_REBUILT}
        for k in FLOWSOM_NODE_ARRAYS:
            meta[k] = np.asarray(res[k]).tolist()
        return meta

    def _hydrate_flowsom(self, meta: dict, state: Any, context: Any) -> dict | None:
        idx_path = context.get_path(meta.get("idx_key"))
        nodes_path = context.get_path(meta.get("nodes_key"))
        if not (idx_path and idx_path.exists() and nodes_path and nodes_path.exists()):
            return None
        res = meta.copy()
        for k in FLOWSOM_NODE_ARRAYS:
            res[k] = np.asarray(meta[k])
        res["indices"] = np.load(idx_path)
        res["nodes"] = np.load(nodes_path).astype(np.int64)
        res["embedding"] = tree_embedding(res["layout"], res["nodes"], meta.get("random_seed", 0))
        res["clusters"] = res["node_metaclusters"][res["nodes"]]
        self._reconstruct_intensities(res, meta, state)
        self._reconstruct_cluster_stats(res)
        return res

    def _serialize_phenograph(self, res: dict, context: Any) -> dict:
        """Indices and clusters go to attachments; the cluster graph is small, so it stays
        in the metadata. The map is rebuilt on load; the neighbour graph isn't saved
        (the daemon rebuilds it the first time the resolution changes).
        """
        if not res.get("idx_key"):
            run_uuid = uuid.uuid4().hex[:8]
            res["idx_key"], res["cls_key"] = f"umap_idx_{run_uuid}", f"phenograph_cls_{run_uuid}"
        self._attach(context, res["idx_key"], res["indices"], "PhenoGraph Indices")
        clusters = np.asarray(res["clusters"]).astype(np.int32)
        self._attach(context, res["cls_key"], clusters, "PhenoGraph Clusters")
        meta = {k: v for k, v in res.items() if k not in _FLOWSOM_REBUILT}
        for k in PHENOGRAPH_CLUSTER_ARRAYS:
            meta[k] = np.asarray(res[k]).tolist()
        return meta

    def _hydrate_phenograph(self, meta: dict, state: Any, context: Any) -> dict | None:
        idx_path = context.get_path(meta.get("idx_key"))
        cls_path = context.get_path(meta.get("cls_key"))
        if not (idx_path and idx_path.exists() and cls_path and cls_path.exists()):
            return None
        res = meta.copy()
        res["layout"] = np.asarray(meta["layout"], dtype=np.float64).reshape(-1, 2)
        res["cluster_edges"] = np.asarray(meta["cluster_edges"], dtype=np.int64).reshape(-1, 2)
        res["cluster_connectivity"] = np.asarray(meta["cluster_connectivity"], dtype=np.float64)
        res["indices"] = np.load(idx_path)
        res["clusters"] = np.load(cls_path).astype(np.int64)
        res["embedding"] = graph_embedding(
            res["layout"], res["clusters"], meta.get("random_seed", 0)
        )
        self._reconstruct_intensities(res, meta, state)
        self._reconstruct_cluster_stats(res)
        return res

    def _reconstruct_intensities(self, res: dict, meta: dict, state: Any):
        """Dynamically reconstruct transformed intensities."""
        sample_id = meta["sample_id"]
        sample = state.data.experiment.samples.get(sample_id)
        if sample and sample.fcs_data is not None:
            from ...analysis.transforms import biexponential_transform

            events_df = sample.fcs_data.events
            channels = list(events_df.columns)
            # Runs store event row labels, not positions.
            sub_events = events_df.to_numpy()[events_df.index.get_indexer(res["indices"])]

            transformed_cols = []
            for ch in meta["channels"]:
                raw_ch = ch.split("(")[-1].strip(")") if "(" in ch else ch
                if raw_ch in channels:
                    col_idx = channels.index(raw_ch)
                    raw_vals = sub_events[:, col_idx].astype(np.float64)
                    scale = self._axis_manager.get_scale(raw_ch, sample_id)

                    top = getattr(scale, "logicle_t", 262144.0)
                    width = getattr(scale, "logicle_w", 1.0)
                    positive = getattr(scale, "logicle_m", 4.5)
                    negative = getattr(scale, "logicle_a", 0.0)

                    trans_vals = biexponential_transform(
                        raw_vals,
                        top=top,
                        width=width,
                        positive=positive,
                        negative=negative,
                    )
                    transformed_cols.append(trans_vals)
                else:
                    transformed_cols.append(np.zeros(len(sub_events)))

            res["intensities"] = np.column_stack(transformed_cols)
        else:
            logger.error(
                f"Could not reconstruct intensities for sample {sample_id} because FCS data is missing."
            )
            res["intensities"] = np.zeros((len(res["embedding"]), len(meta["channels"])))

    def _reconstruct_cluster_stats(self, res: dict):
        """Reconstruct the cluster statistical properties."""
        import pandas as pd

        df_cluster = pd.DataFrame(res["intensities"], columns=res["channels"])
        df_cluster["Cluster_ID"] = res["clusters"]

        counts = df_cluster["Cluster_ID"].value_counts().sort_index()
        percentages = (counts / len(df_cluster)) * 100
        stats_df = pd.DataFrame(
            {
                "Cluster ID": counts.index,
                "Cell Count": counts.values,
                "% of Total": percentages.values,
            }
        )
        res["cluster_stats"] = stats_df.to_dict(orient="split")

        heatmap_df = df_cluster.groupby("Cluster_ID").median()
        res["marker_heatmap"] = heatmap_df.to_dict(orient="split")
