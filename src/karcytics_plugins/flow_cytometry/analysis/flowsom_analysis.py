"""FlowSOM Analysis — background worker for a FlowSOM clustering run."""

from __future__ import annotations

import typing
from typing import Any

from karcytics_sdk.plugin import AnalysisBase, PluginState, get_logger

from .clustering import FLOWSOM, fit_flowsom, tree_embedding
from .clustering.run_input import cluster_tables, prepare_run_input

logger = get_logger(__name__, "flow_cytometry")


class FlowsomAnalysis(AnalysisBase):
    """Runs FlowSOM on one population of one sample.

    Numpy and scipy only, so it runs in the worker thread (no daemon round
    trip): a million events take a few seconds.
    """

    def __init__(self, plugin_id: str = "flow_cytometry"):
        super().__init__(plugin_id)
        self.target_sample_id: str = ""
        self.target_node_id: str | None = None  # None = All Events
        self.name: str = ""
        self.percentage: float = 100.0
        self.n_events: int = 0
        self.xdim: int = 10
        self.ydim: int = 10
        self.k: int = 10
        self.passes: int = 10
        self.random_seed: int = 42
        self.channels: list[str] = []

    @property
    def min_events(self) -> int:
        return self.xdim * self.ydim

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
            self.min_events,
            cancelled=self.is_cancelled,
        )
        if isinstance(prepared, str):
            return {"error": prepared}
        if len(prepared.x) < self.min_events:
            return {
                "error": f"FlowSOM needs at least {self.min_events} events for a "
                f"{self.xdim}×{self.ydim} grid; this run has {len(prepared.x)}."
            }
        self.signals.analysis_progress.emit(15)

        result = fit_flowsom(
            prepared.x,
            xdim=self.xdim,
            ydim=self.ydim,
            k=self.k,
            passes=self.passes,
            seed=self.random_seed,
            progress=lambda f: self.signals.analysis_progress.emit(15 + int(80 * f)),
            cancelled=self.is_cancelled,
        )
        if result is None:
            return {"error": "Task cancelled."}
        logger.info(f"FlowsomAnalysis: {len(prepared.x):,} events, k={self.k}")

        clusters = result.clusters
        run = {
            "method": FLOWSOM.key,
            "name": self.name,
            "percentage": self.percentage,
            "xdim": self.xdim,
            "ydim": self.ydim,
            "k": result.k,
            "passes": self.passes,
            "random_seed": self.random_seed,
            "channels": prepared.channels,
            "channel_labels": prepared.channel_labels,
            "sample_id": self.target_sample_id,
            "node_id": self.target_node_id,
            "n_events": len(prepared.x),
            "parent_total_events": prepared.parent_total,
            "indices": prepared.indices,
            "intensities": prepared.x,
            "embedding": tree_embedding(result.layout, result.nodes, self.random_seed),
            "embedding_kind": "tree",
            "clusters": clusters,
            **flowsom_arrays(result),
            **cluster_tables(prepared.x, clusters, prepared.channel_labels),
        }
        self.signals.analysis_progress.emit(100)
        return run


def flowsom_arrays(result: Any) -> dict[str, Any]:
    """The FlowSOM-only arrays a run keeps (node level, plus each event's node)."""
    return {
        "nodes": result.nodes,
        "codes": result.codes,
        "grid": result.grid,
        "mst_edges": result.mst_edges,
        "layout": result.layout,
        "linkage": result.linkage,
        "node_metaclusters": result.node_metaclusters,
    }
