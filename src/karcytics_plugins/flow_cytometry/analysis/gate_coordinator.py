"""Gate Coordinator — facade for gating operations.

Orchestrates the GateMutationService (analysis logic) and GatePropagator
(background synchronization) to provide a unified API for the UI.
"""

from typing import Any

from karcytics_sdk.plugin import CentralEventBus, get_logger

from . import events
from .axis_manager import AxisManager
from .derived.sync import sync_sample
from .gate_propagator import GatePropagator
from .gating import Gate, GateNode
from .population_service import PopulationService
from .services.gate_mutation_service import GateMutationService
from .services.gate_selection_service import GateSelectionService
from .state import FlowState

logger = get_logger(__name__, "flow_cytometry")


class GateCoordinator:
    """Facade for all gating operations in the flow module."""

    def __init__(
        self,
        state: FlowState,
        axis_manager: AxisManager,
        population_service: PopulationService,
        task_scheduler: Any | None = None,
    ):
        self._state = state
        self._axis_manager = axis_manager
        self._population_service = population_service
        self._scheduler = task_scheduler

        # Sub-services
        self._propagator = GatePropagator(state, task_scheduler, _parent=self)  # type: ignore
        self._selection_service = GateSelectionService(state, self)

        # Instantiate mutation service once
        self._mutation_service = GateMutationService(
            state, self, self._selection_service, axis_manager, population_service
        )

    @property
    def propagator(self):
        return self._propagator

    def set_propagation_enabled(self, enabled: bool) -> None:
        """Enable or disable auto-propagation across samples."""
        self._propagation_enabled = enabled
        logger.info("Propagation %s", "enabled" if enabled else "disabled")

    def request_propagation(self, gate_id: str, source_sample_id: str) -> None:
        """Route propagation request, respecting the enabled flag."""
        if getattr(self, "_propagation_enabled", True):
            self._propagator.request_propagation(gate_id, source_sample_id)

    def propagate_to_all_groups(self, sample_id: str, node_id: str) -> None:
        """Route explicit cross-group propagation request."""
        self._propagator.request_cross_group_propagation(node_id, sample_id)

    # ── Facade API (Mapping to Mutation Service) ────────────────────────────

    def add_gate(
        self,
        gate: Gate,
        sample_id: str,
        name: str | None = None,
        parent_node_id: str | None = None,
    ) -> str | None:
        return self._mutation_service.add_gate(gate, sample_id, name, parent_node_id)

    def remove_population(self, sample_id: str, node_id: str) -> bool:
        return self._mutation_service.remove_population(sample_id, node_id)

    def select_gate(self, sample_id: str, node_id: str | None) -> None:
        self._selection_service.select_gate(sample_id, node_id)

    def add_logic_node(self, sample_id: str, operator: str, name: str | None = None) -> str | None:
        return self._mutation_service.add_logic_node(sample_id, operator, name)

    def add_connection(self, sample_id: str, source_node_id: str, target_node_id: str) -> bool:
        return self._mutation_service.add_connection(sample_id, source_node_id, target_node_id)

    def remove_connection(self, sample_id: str, source_node_id: str, target_node_id: str) -> bool:
        return self._mutation_service.remove_connection(sample_id, source_node_id, target_node_id)

    def remove_connection_for_samples(
        self, source_node_id: str, target_node_id: str, sample_ids: list[str]
    ) -> int:
        """Remove a logic-node connection in each given sample; returns count removed."""
        removed = 0
        for sample_id in sample_ids:
            if self._mutation_service.remove_connection(sample_id, source_node_id, target_node_id):
                removed += 1
        return removed

    def rename_population(
        self,
        sample_id: str,
        node_id: str,
        new_name: str,
        target_sample_ids: list[str] | None = None,
    ) -> bool:
        return self._mutation_service.rename_population(
            sample_id, node_id, new_name, target_sample_ids
        )

    def modify_gate(self, gate_id: str, sample_id: str, **kwargs) -> bool:
        return self._mutation_service.modify_gate(gate_id, sample_id, **kwargs)

    def split_population(self, sample_id: str, node_id: str) -> str | None:
        return self._mutation_service.split_population(sample_id, node_id)

    def copy_gates_to_group(self, source_sample_id: str) -> int:
        return self._mutation_service.copy_gates_to_group(source_sample_id)

    def get_gates_for_display(
        self, sample_id: str, parent_node_id: str | None = None
    ) -> tuple[list[Gate], list[GateNode]]:
        return self._mutation_service.get_gates_for_display(sample_id, parent_node_id)

    # ── Stats Orchestration ────────────────────────────────────────────────

    def recompute_all_stats(
        self, sample_id: str, sync: bool = False, node_ids: list[str] | None = None
    ):
        """Recompute gate statistics for a sample.

        Args:
            sample_id: Target sample ID.
            sync: Run inline instead of on the background task scheduler.
            node_ids: When given, scopes recompute to just these nodes and
                their descendants (Priority 1 analysis #3) instead of the
                whole tree — e.g. a single gate edit or rewire only ever
                affects its own subtree, never its ancestors' masks.
                Structural changes that replace the whole tree (e.g.
                `copy_gates_to_group`) should omit this and recompute
                everything, since "what changed" there really is everything.
        """
        from .services.stats_service import StatsService
        from .statistics_analysis import StatisticsAnalysis

        sample = self._state.data.experiment.samples.get(sample_id)
        if sample is not None:
            # Safety net for derived columns (no-op when already current).
            sync_sample(self._state.data.experiment, sample)
        if sample and sample.gate_tree:
            # Every mutation path funnels through here before stats are
            # considered valid again — the same choke point doubles as the
            # invalidation hook for GateNode's mask cache (Priority 1
            # analysis #1), so cached masks go stale at exactly the rate
            # `.statistics` already does today, no new correctness surface.
            if node_ids:
                for nid in node_ids:
                    node = sample.gate_tree.find_node_by_id(nid)
                    if node:
                        node.invalidate_mask_cache()
            else:
                sample.gate_tree.invalidate_mask_cache()

        if sync or getattr(self, "sync_stats", False):
            analyzer = StatisticsAnalysis()
            analyzer.target_sample_id = sample_id
            analyzer.target_node_ids = node_ids
            results = analyzer.run(self._state)
            self._on_stats_finished(results)
            return

        task_id = StatsService.recompute_all_stats(
            self._state, sample_id, self._on_stats_finished, node_ids=node_ids
        )
        if task_id:
            logger.info(
                "Submitted StatisticsAnalysis for sample %s (task_id: %s)",
                sample_id,
                task_id,
            )

    def _on_stats_finished(self, results: dict) -> None:
        sample_id = results.get("sample_id")
        stats_map = results.get("stats", {})

        if not sample_id:
            return

        sample = self._state.data.experiment.samples.get(sample_id)
        if not sample:
            return

        from .services.gate_event_publisher import GateEventPublisher

        for node_id, stats in stats_map.items():
            node = sample.gate_tree.find_node_by_id(node_id)
            if node:
                node.statistics = stats
                CentralEventBus.publish(
                    events.GATE_STATS_UPDATED,
                    {"sample_id": sample_id, "node_id": node_id},
                )
                GateEventPublisher.publish_stats_computed(sample_id, node_id, stats)
            else:
                logger.warning(
                    f"_on_stats_finished: node_id {node_id} not found in tree for sample {sample_id}"
                )

        CentralEventBus.publish(events.ALL_STATS_UPDATED, {"sample_id": sample_id})
        logger.info(f"Applied background stats for sample {sample_id}")

    def cleanup(self):
        self._propagator.cleanup()
        logger.info("GateCoordinator cleaned up")
