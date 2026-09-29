"""Statistics Analysis — SDK-aligned background worker for population stats."""

from __future__ import annotations

from typing import Any

from karcytics_sdk.plugin import AnalysisBase, PluginState, get_logger

from .compute.dag_evaluator import DagEvaluator
from .gating.gate_node import GateNode

logger = get_logger(__name__, "flow_cytometry")


class StatisticsAnalysis(AnalysisBase):
    """Background analyzer for computing population statistics.

    Thin wrapper around the shared `DagEvaluator.evaluate` walk (the same
    one `propagation_worker.py` uses) — this used to be its own independent
    recursive tree-walker duplicating the same AND/OR/NOT/gate-mask logic.
    """

    def __init__(self, plugin_id: str = "flow_cytometry"):
        super().__init__(plugin_id)
        self.target_sample_id: str | None = None
        # When set, only these nodes (and their descendants) are recomputed —
        # everything above them is untouched, so `DagEvaluator.evaluate_scoped`
        # reads their ancestors' masks from GateNode's own cache instead of
        # walking the whole tree. `None` (the default) recomputes everything,
        # as before.
        self.target_node_ids: list[str] | None = None

    def run(self, state: PluginState | None = None) -> dict[str, Any]:
        """Compute statistics for a sample.

        The 'state' here is the FlowState.
        """
        sample_id = getattr(self, "target_sample_id", None)
        if not sample_id and state and hasattr(state, "view"):
            sample_id = state.view.current_sample_id

        if not sample_id:
            return {"error": "No sample ID specified"}

        if not state or not hasattr(state, "data"):
            return {"error": "No state data available"}

        sample = state.data.experiment.samples.get(sample_id)
        if not sample or sample.fcs_data is None:
            return {"error": f"Sample {sample_id} not found or has no data"}

        if self.is_cancelled():
            return {"error": "Cancelled"}

        logger.info(f"StatisticsAnalysis: Starting compute for sample {sample_id}")
        events = sample.fcs_data.events
        if events is None:
            return {"error": "No events found"}

        if self.target_node_ids:
            changed_nodes = [
                node
                for nid in self.target_node_ids
                if (node := sample.gate_tree.find_node_by_id(nid)) is not None
            ]
            results = DagEvaluator.evaluate_scoped(
                changed_nodes, events, on_gate_error=self._on_gate_error
            )
        else:
            results = DagEvaluator.evaluate(
                sample.gate_tree, events, on_gate_error=self._on_gate_error
            )

        logger.info(
            f"StatisticsAnalysis: Done for sample {sample_id}, {len(results)} nodes computed"
        )
        return {"sample_id": sample_id, "stats": results}

    def _on_gate_error(self, node: GateNode, exc: Exception) -> None:
        logger.exception(f"Background Stat computation failed for {node.name}: {exc}")
        self.signals.analysis_error.emit(f"Stat computation failed for {node.name}: {exc}")
