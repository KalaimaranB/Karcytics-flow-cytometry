"""UMAP Analysis — SDK-aligned background worker for UMAP dimensionality reduction."""

from __future__ import annotations

from typing import Any

import numpy as np
from karcytics_sdk.plugin import AnalysisBase, PluginState, get_logger

from .clustering.methods import UMAP_HDBSCAN
from .clustering.run_input import cluster_tables, prepare_run_input
from .constants import UMAP_MIN_EVENTS

logger = get_logger(__name__, "flow_cytometry")


class UmapAnalysis(AnalysisBase):
    """Background analyzer for running UMAP dimensionality reduction."""

    def __init__(self, plugin_id: str = "flow_cytometry"):
        super().__init__(plugin_id)
        self.target_sample_id: str = ""
        self.target_node_id: str | None = None  # None = All Events
        self.name: str = ""
        self.percentage: float = 10.0
        self.n_neighbors: int = 15
        self.min_dist: float = 0.1
        self.n_events: int = 10000
        self.metric: str = "euclidean"
        self.random_seed: int = 42
        self.run_hdbscan: bool = False
        self.hdbscan_space: str = "high_dim"
        self.min_cluster_size: int = 100
        self.channels: list[str] = []

    def validate(self, state: Any) -> tuple[bool, str]:
        """Verify sample has FCS data loaded."""
        sample_id = getattr(self, "target_sample_id", "")
        if not sample_id:
            sample_id = getattr(state, "current_sample_id", None)

        if not sample_id:
            return False, "No sample selected."

        sample = state.data.experiment.samples.get(sample_id)
        if not sample:
            return False, f"Sample '{sample_id}' not found."

        if sample.fcs_data is None or sample.fcs_data.events is None:
            return False, f"Sample '{sample.display_name}' has no loaded FCS data."

        if len(sample.fcs_data.events) < UMAP_MIN_EVENTS:
            return (
                False,
                f"Sample '{sample.display_name}' has too few events ({len(sample.fcs_data.events)}) for UMAP analysis.",
            )

        return True, ""

    def run(self, state: PluginState | None = None) -> dict[str, Any]:  # noqa: C901, PLR0911
        """Transforms FCS data with Logicle, subsamples, runs UMAP."""
        if state is None:
            return {"error": "No state provided"}

        import typing

        from .state import FlowState

        flow_state = typing.cast(FlowState, state)

        sample_id = getattr(self, "target_sample_id", "")
        if not sample_id:
            sample_id = flow_state.view.current_sample_id

        if not isinstance(sample_id, str) or not sample_id:
            return {"error": "Invalid or missing sample ID"}

        logger.info(f"UmapAnalysis: Starting run for sample {sample_id}")
        self.signals.analysis_progress.emit(5)
        prepared = prepare_run_input(
            flow_state,
            sample_id,
            self.target_node_id,
            self.channels,
            self.n_events,
            self.random_seed,
            UMAP_MIN_EVENTS,
            cancelled=self.is_cancelled,
        )
        if isinstance(prepared, str):
            logger.error(f"UmapAnalysis: {prepared}")
            return {"error": prepared}
        fluo_channels = prepared.channels
        x_mat = prepared.x
        n_events = len(x_mat)
        num_total_events = prepared.parent_total

        self.signals.analysis_progress.emit(20)
        if self.is_cancelled():
            return {"error": "Task cancelled."}

        # 5. Fit UMAP
        logger.info(
            f"UmapAnalysis: Fitting UMAP on shape {x_mat.shape} with n_neighbors={self.n_neighbors}, min_dist={self.min_dist}"
        )
        self.signals.analysis_progress.emit(30)

        try:
            import base64
            import io

            from karcytics_sdk.plugin import PluginDaemon

            from .fcs_io import _decode_array

            buf = io.BytesIO()
            np.save(buf, x_mat, allow_pickle=False)
            x_b64 = base64.b64encode(buf.getvalue()).decode("ascii")

            params = {
                "n_neighbors": self.n_neighbors,
                "min_dist": self.min_dist,
                "metric": self.metric,
                "random_seed": self.random_seed,
                "run_hdbscan": getattr(self, "run_hdbscan", False),
                "hdbscan_space": getattr(self, "hdbscan_space", "high_dim"),
                "min_cluster_size": getattr(self, "min_cluster_size", 100),
            }

            daemon = PluginDaemon.get_instance("flow_cytometry")
            res_dict = daemon.call(
                "run_umap",
                {"x_b64": x_b64, "params": params},
                cancel_poll=self.is_cancelled,
                timeout=300.0,
            )

            if "error" in res_dict:
                raise RuntimeError(res_dict["error"])

            embedding = _decode_array(res_dict["embedding_b64"])
            clusters = None
            if "clusters_b64" in res_dict:
                clusters = _decode_array(res_dict["clusters_b64"])

        except Exception as e:
            logger.exception(f"UmapAnalysis: UMAP reduction failed: {e}")
            self.signals.analysis_error.emit(f"UMAP failed: {e}")
            return {"error": f"UMAP calculation failed: {e}"}

        self.signals.analysis_progress.emit(90)
        if self.is_cancelled():
            return {"error": "Task cancelled."}

        logger.info("UmapAnalysis: Completed run successfully")
        self.signals.analysis_progress.emit(100)

        result_dict = {
            "method": UMAP_HDBSCAN.key,
            "name": getattr(self, "name", ""),
            "percentage": getattr(self, "percentage", 10.0),
            "n_neighbors": self.n_neighbors,
            "min_dist": self.min_dist,
            "metric": self.metric,
            "random_seed": self.random_seed,
            "run_hdbscan": getattr(self, "run_hdbscan", False),
            "hdbscan_space": getattr(self, "hdbscan_space", "high_dim"),
            "min_cluster_size": getattr(self, "min_cluster_size", 100),
            "channels": fluo_channels,
            "channel_labels": prepared.channel_labels,
            "embedding": embedding,
            "intensities": x_mat,
            "sample_id": sample_id,
            "node_id": self.target_node_id,
            "n_events": n_events,
            "parent_total_events": num_total_events,
            "indices": prepared.indices,
        }
        if clusters is not None:
            result_dict["clusters"] = clusters
            result_dict.update(cluster_tables(x_mat, clusters, prepared.channel_labels))

        return result_dict
