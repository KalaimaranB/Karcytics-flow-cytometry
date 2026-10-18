"""PhenoGraph Analysis — background workers for a PhenoGraph run and a re-cluster.

The clustering itself runs in the plugin daemon (``run_phenograph``): its
neighbour search and Leiden hold the GIL for seconds, which froze the window
in a worker thread. The daemon keeps each run's graph, so a new resolution
costs only Leiden.
"""

from __future__ import annotations

import typing
import uuid
from typing import Any

import numpy as np
from karcytics_sdk.plugin import AnalysisBase, PluginState, get_logger

from .clustering import PHENOGRAPH
from .clustering.phenograph import graph_embedding
from .clustering.run_input import cluster_tables, prepare_run_input

logger = get_logger(__name__, "flow_cytometry")

DAEMON_TIMEOUT_S = 600.0


def compute(
    x: np.ndarray, params: dict[str, Any], run_uid: str, cancelled: Any = None
) -> dict[str, np.ndarray]:
    """Cluster ``x`` in the daemon; the per-event clusters and the cluster graph.

    Raises RuntimeError with the daemon's message on failure. Tests replace
    this with an in-process call.
    """
    import base64
    import io

    from karcytics_sdk.plugin import PluginDaemon

    from .fcs_io import _decode_array

    buf = io.BytesIO()
    np.save(buf, np.asarray(x), allow_pickle=False)
    reply = PluginDaemon.get_instance("flow_cytometry").call(
        "run_phenograph",
        {
            "x_b64": base64.b64encode(buf.getvalue()).decode("ascii"),
            "params": params,
            "run_uid": run_uid,
        },
        cancel_poll=cancelled,
        timeout=DAEMON_TIMEOUT_S,
    )
    if "error" in reply:
        raise RuntimeError(reply["error"])
    return {
        key: _decode_array(reply[f"{key}_b64"])
        for key in ("clusters", "edges", "connectivity", "layout")
    }


def run_params(run: dict[str, Any], resolution: float | None = None) -> dict[str, Any]:
    """What the daemon needs from a run (at ``resolution``, else the run's own)."""
    return {
        "k": int(run.get("n_neighbors", 30)),
        "resolution": float(run["resolution"] if resolution is None else resolution),
        "min_size": int(run.get("min_cluster_size", 10)),
        "random_seed": int(run.get("random_seed", 42)),
    }


class PhenographAnalysis(AnalysisBase):
    """Runs PhenoGraph on one population of one sample."""

    def __init__(self, plugin_id: str = "flow_cytometry"):
        super().__init__(plugin_id)
        self.target_sample_id: str = ""
        self.target_node_id: str | None = None  # None = All Events
        self.name: str = ""
        self.percentage: float = 100.0
        self.n_events: int = 0
        self.n_neighbors: int = 30
        self.resolution: float = 1.0
        self.min_cluster_size: int = 10
        self.random_seed: int = 42
        self.channels: list[str] = []

    def validate(self, state: Any) -> tuple[bool, str]:
        sample = state.data.experiment.samples.get(self.target_sample_id)
        if sample is None:
            return False, f"Sample '{self.target_sample_id}' not found."
        if sample.fcs_data is None or sample.fcs_data.events is None:
            return False, f"Sample '{sample.display_name}' has no loaded FCS data."
        return True, ""

    def run(self, state: PluginState | None = None) -> dict[str, Any]:
        if state is None:
            return {"error": "No state provided"}
        from .state import FlowState

        flow_state = typing.cast(FlowState, state)
        self.signals.analysis_progress.emit(5)
        prepared = prepare_run_input(
            flow_state,
            self.target_sample_id,
            self.target_node_id,
            self.channels,
            self.n_events,
            self.random_seed,
            self.n_neighbors + 1,
            cancelled=self.is_cancelled,
        )
        if isinstance(prepared, str):
            return {"error": prepared}
        if len(prepared.x) <= self.n_neighbors:
            return {
                "error": f"PhenoGraph needs more than {self.n_neighbors} events for "
                f"{self.n_neighbors} neighbours; this run has {len(prepared.x)}."
            }
        self.signals.analysis_progress.emit(15)

        run: dict[str, Any] = {
            "method": PHENOGRAPH.key,
            "run_uid": uuid.uuid4().hex,
            "name": self.name,
            "percentage": self.percentage,
            "n_neighbors": self.n_neighbors,
            "resolution": self.resolution,
            "min_cluster_size": self.min_cluster_size,
            "random_seed": self.random_seed,
            "channels": prepared.channels,
            "channel_labels": prepared.channel_labels,
            "sample_id": self.target_sample_id,
            "node_id": self.target_node_id,
            "n_events": len(prepared.x),
            "parent_total_events": prepared.parent_total,
            "indices": prepared.indices,
            "intensities": prepared.x,
            "embedding_kind": "graph",
        }
        try:
            arrays = compute(prepared.x, run_params(run), run["run_uid"], self.is_cancelled)
        except Exception as e:  # the daemon's own message is the useful part
            logger.exception("PhenographAnalysis: clustering failed")
            return {"error": f"PhenoGraph failed: {e}"}
        if self.is_cancelled():
            return {"error": "Task cancelled."}
        apply_clusters(run, arrays)
        logger.info(
            f"PhenographAnalysis: {len(prepared.x):,} events, "
            f"{len(arrays['layout'])} clusters at resolution {self.resolution}"
        )
        self.signals.analysis_progress.emit(100)
        return run


class PhenographReclusterAnalysis(AnalysisBase):
    """Re-clusters an existing PhenoGraph run at another resolution (the daemon keeps its graph)."""

    def __init__(self, run: dict[str, Any], resolution: float, plugin_id: str = "flow_cytometry"):
        super().__init__(plugin_id)
        self.run_dict = run
        self.resolution = resolution

    def validate(self, state: Any) -> tuple[bool, str]:  # noqa: ARG002 - nothing to check
        return True, ""

    def run(self, state: PluginState | None = None) -> dict[str, Any]:  # noqa: ARG002
        run = self.run_dict
        run.setdefault("run_uid", uuid.uuid4().hex)  # older saves: the daemon rebuilds the graph
        self.signals.analysis_progress.emit(10)
        try:
            arrays = compute(
                np.asarray(run["intensities"]),
                run_params(run, self.resolution),
                run["run_uid"],
                self.is_cancelled,
            )
        except Exception as e:
            logger.exception("PhenographReclusterAnalysis: failed")
            return {"error": f"PhenoGraph failed: {e}"}
        if self.is_cancelled():
            return {"error": "Task cancelled."}
        self.signals.analysis_progress.emit(100)
        return {"resolution": self.resolution, **arrays}


def apply_clusters(run: dict[str, Any], arrays: dict[str, Any]) -> None:
    """Put a clustering (first run or re-cluster) on the run, in place.

    Cells drawn into custom populations stay out of the clusters, and
    cluster names are cleared: they named the old clusters.
    """
    clusters = np.asarray(arrays["clusters"]).astype(np.int64)
    for custom in run.get("custom_clusters", []):
        clusters[np.asarray(custom["mask"], dtype=np.int64)] = -1
    layout = np.asarray(arrays["layout"], dtype=np.float64).reshape(-1, 2)
    run.update(
        {
            "clusters": clusters,
            "cluster_edges": np.asarray(arrays["edges"], dtype=np.int64).reshape(-1, 2),
            "cluster_connectivity": np.asarray(arrays["connectivity"], dtype=np.float64),
            "layout": layout,
            "embedding": graph_embedding(layout, clusters, int(run.get("random_seed", 0))),
            "cluster_names": {},
        }
    )
    if "resolution" in arrays:
        run["resolution"] = float(arrays["resolution"])
    x = np.asarray(run["intensities"])
    keep = clusters >= 0
    run.update(cluster_tables(x[keep], clusters[keep], run["channel_labels"], total=len(x)))
