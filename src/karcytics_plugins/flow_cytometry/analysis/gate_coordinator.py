"""Gate Coordinator — the one entry point for changing a sample's gates.

Each operation edits the gate tree (`gating.tree_edits`), recomputes the
affected statistics, publishes what changed on the event bus, and hands
cross-sample updates to the GatePropagator.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any

from karcytics_sdk.plugin import CentralEventBus, get_logger
from karcytics_sdk.plugin.runtime_services import task_scheduler

from . import events
from .derived.sync import sync_sample
from .gate_propagator import GatePropagator
from .gating import Gate, GateNode, tree_edits
from .statistics_analysis import StatisticsAnalysis

if TYPE_CHECKING:
    from .axis_manager import AxisManager
    from .experiment import Sample
    from .population_service import PopulationService
    from .state import FlowState

logger = get_logger(__name__, "flow_cytometry")


def _publish(topic: str, **payload: Any) -> None:
    CentralEventBus.publish(topic, payload)


class GateCoordinator:
    """Adds, edits and removes gates, and keeps their statistics current."""

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
        self._propagator = GatePropagator(state, task_scheduler)
        self._propagation_enabled = True
        # Compute statistics inline instead of on the task scheduler (tests).
        self.sync_stats = False

    @property
    def propagator(self) -> GatePropagator:
        return self._propagator

    def _sample(self, sample_id: str) -> Sample | None:
        return self._state.data.experiment.samples.get(sample_id)

    # ── Propagation ─────────────────────────────────────────────────────

    def set_propagation_enabled(self, enabled: bool) -> None:
        """Enable or disable auto-propagation across samples."""
        self._propagation_enabled = enabled
        logger.info("Propagation %s", "enabled" if enabled else "disabled")

    def request_propagation(self, gate_id: str, source_sample_id: str) -> None:
        if self._propagation_enabled:
            self._propagator.request_propagation(gate_id, source_sample_id)

    def propagate_to_all_groups(self, sample_id: str, node_id: str) -> None:
        self._propagator.request_cross_group_propagation(node_id, sample_id)

    # ── Queries ─────────────────────────────────────────────────────────

    def unique_name(self, sample_id: str, prefix: str = "Gate") -> str:
        """A population name not yet used in the sample ('Gate 3')."""
        return tree_edits.unique_name(self._sample(sample_id), prefix)

    def get_gates_for_display(
        self, sample_id: str, parent_node_id: str | None = None
    ) -> tuple[list[Gate], list[GateNode]]:
        sample = self._sample(sample_id)
        return tree_edits.gates_for_display(sample, parent_node_id) if sample else ([], [])

    def populations_under_gate(self, gate_id: str, sample_ids: list[str]) -> dict[str, set[str]]:
        """Per sample, every population at or below a node drawn with `gate_id`."""
        affected: dict[str, set[str]] = {}
        for sample_id in sample_ids:
            sample = self._sample(sample_id)
            if sample is None:
                continue
            ids = {
                n.node_id
                for node in sample.gate_tree.find_nodes_by_gate(gate_id)
                for n in node.iter_dag()
            }
            if ids:
                affected[sample_id] = ids
        return affected

    # ── Gates and populations ───────────────────────────────────────────

    def add_gate(
        self,
        gate: Gate,
        sample_id: str,
        name: str | None = None,
        parent_node_id: str | None = None,
    ) -> str | None:
        """Add `gate` under `parent_node_id` (the root when None); returns the first new node's id."""
        sample = self._sample(sample_id)
        if sample is None:
            logger.warning("Cannot add gate — sample %s not found.", sample_id)
            return None
        parent = (
            sample.gate_tree.find_node_by_id(parent_node_id) if parent_node_id else sample.gate_tree
        )
        if parent is None:
            logger.warning("Parent node %s not found in sample %s", parent_node_id, sample_id)
            return None

        self._record_derived_formulas(gate)
        nodes = gate.create_nodes(parent, name or self.unique_name(sample_id))
        if not nodes:
            return None
        self.recompute_all_stats(sample_id, node_ids=[n.node_id for n in nodes])
        if not parent.creation_view:
            parent.creation_view = self._creation_view(gate, sample_id)

        if len(nodes) == 1:
            node = nodes[0]
            _publish(
                events.GATE_CREATED,
                sample_id=sample_id,
                node_id=node.node_id,
                gate_id=gate.gate_id,
                name=node.name,
                is_split=False,
            )
        else:
            # e.g. quadrant gates create 4 nodes at once — publish a single
            # aggregate event so refresh-on-create consumers (hierarchy tree,
            # canvas overlays, undo history) do their work once instead of
            # once per node.
            _publish(
                events.GATES_CREATED,
                sample_id=sample_id,
                gate_id=gate.gate_id,
                nodes=[{"node_id": n.node_id, "name": n.name} for n in nodes],
                is_split=False,
            )
        logger.info(
            "%d population(s) added to sample '%s' using %s.",
            len(nodes),
            sample.display_name,
            type(gate).__name__,
        )

        self.request_propagation(gate.gate_id, sample_id)
        self.select_gate(sample_id, nodes[0].node_id)
        return nodes[0].node_id

    def _record_derived_formulas(self, gate: Gate) -> None:
        """Snapshot the formula of any derived-parameter axis onto the gate."""
        definitions = {
            d.param_id: d.formula for d in self._state.data.experiment.derived_parameters
        }
        gate.derived_formulas = {
            p: definitions[p] for p in (gate.x_param, gate.y_param) if p in definitions
        }

    def _creation_view(self, gate: Gate, sample_id: str) -> dict:
        """The plot the gate was drawn on, for the pipeline thumbnail of its parent."""
        view = self._state.view
        x_scale = self._axis_manager.get_scale(gate.x_param, sample_id)
        y_scale = self._axis_manager.get_scale(gate.y_param, sample_id) if gate.y_param else None

        # For range gates (y_param=None) drawn while in pseudocolor mode, the user
        # was looking at a 2D scatter. Record the view's current Y-axis so the
        # pipeline thumbnail can reconstruct that scatter with vertical range lines.
        view_y_param = None
        view_y_scale = None
        if gate.y_param is None and view.active_plot_type.lower() == "pseudocolor":
            view_y_param = view.active_y_param or None
            if view_y_param:
                vy_scale = self._axis_manager.get_scale(view_y_param, sample_id)
                view_y_scale = vy_scale.to_dict() if vy_scale else None

        return {
            "x_param": gate.x_param,
            "y_param": gate.y_param,
            "view_y_param": view_y_param,
            "x_scale": x_scale.to_dict(),
            "y_scale": y_scale.to_dict() if y_scale else None,
            "view_y_scale": view_y_scale,
            "plot_type": view.active_plot_type,
        }

    def modify_gate(self, gate_id: str, sample_id: str, **kwargs: Any) -> bool:
        sample = self._sample(sample_id)
        nodes = tree_edits.modify_gate(sample, gate_id, **kwargs) if sample else []
        if not nodes:
            return False
        self.recompute_all_stats(sample_id, node_ids=[n.node_id for n in nodes])
        for node in nodes:
            _publish(events.GATE_STATS_UPDATED, sample_id=sample_id, node_id=node.node_id)
        _publish(events.GATE_MODIFIED, sample_id=sample_id, gate_id=gate_id)
        self.request_propagation(gate_id, sample_id)
        return True

    def split_population(self, sample_id: str, node_id: str) -> str | None:
        sample = self._sample(sample_id)
        sibling = tree_edits.split_population(sample, node_id) if sample else None
        if sibling is None or sibling.gate is None:
            return None
        self.recompute_all_stats(sample_id, node_ids=[sibling.node_id])
        _publish(events.GATE_STATS_UPDATED, sample_id=sample_id, node_id=sibling.node_id)
        _publish(
            events.GATE_CREATED,
            sample_id=sample_id,
            node_id=sibling.node_id,
            gate_id=sibling.gate.gate_id,
            name=sibling.name,
            is_split=True,
        )
        logger.info("Split population created: '%s'", sibling.name)
        return sibling.node_id

    def remove_population(self, sample_id: str, node_id: str) -> bool:
        """Remove a population and everything below it."""
        return bool(self._remove_population(sample_id, node_id))

    def _remove_population(self, sample_id: str, node_id: str) -> set[str]:
        sample = self._sample(sample_id)
        node = sample.gate_tree.find_node_by_id(node_id) if sample else None
        if sample is None or node is None:
            return set()
        gate_id = node.gate.gate_id if node.gate else None
        removed = tree_edits.remove_subtree(sample, node_id)
        if removed:
            _publish(events.GATE_DELETED, sample_id=sample_id, node_id=node_id, gate_id=gate_id)
            logger.info("Population %s removed from sample %s.", node_id, sample_id)
        return removed

    def delete_gate(self, gate_id: str, sample_ids: list[str]) -> dict[str, set[str]]:
        """Remove every population drawn with `gate_id` in each of `sample_ids`.

        Returns, per sample, the ids of the populations that are gone.
        """
        removed: dict[str, set[str]] = {}
        for sample_id in sample_ids:
            sample = self._sample(sample_id)
            if sample is None:
                continue
            for node in sample.gate_tree.find_nodes_by_gate(gate_id):
                ids = self._remove_population(sample_id, node.node_id)
                if ids:
                    removed.setdefault(sample_id, set()).update(ids)
        return removed

    def rename_population(
        self,
        sample_id: str,
        node_id: str,
        new_name: str,
        target_sample_ids: list[str] | None = None,
    ) -> bool:
        """Rename a population here and in `target_sample_ids` (default: propagation targets)."""
        sample = self._sample(sample_id)
        if sample is None or sample.gate_tree.find_node_by_id(node_id) is None:
            return False

        if target_sample_ids is not None:
            target_ids = set(target_sample_ids)
        else:
            target_ids = {t.sample_id for t in self._propagator.find_targets(sample_id)}
        target_ids.add(sample_id)

        renamed_any = False
        for sid in target_ids:
            target = self._sample(sid)
            node = target.gate_tree.find_node_by_id(node_id) if target else None
            if node is not None:
                node.name = new_name
                # A rename changes no statistics or geometry: GATE_RENAMED only,
                # and no propagation (that would re-evaluate the subtree).
                _publish(events.GATE_RENAMED, sample_id=sid, node_id=node_id, new_name=new_name)
                renamed_any = True
        return renamed_any

    def copy_gates_to_group(self, source_sample_id: str) -> int:
        targets = tree_edits.copy_gates_to_group(self._state.data.experiment, source_sample_id)
        for target in targets:
            self.recompute_all_stats(target.sample_id)
        logger.info("Copied gate tree from source to %d samples.", len(targets))
        return len(targets)

    def select_gate(self, sample_id: str, node_id: str | None) -> None:
        """Make `node_id` the current population (None deselects)."""
        if self._state.view.current_gate_id == node_id:
            return
        self._state.view.current_gate_id = node_id
        _publish(events.GATE_SELECTED, sample_id=sample_id, node_id=node_id)

    # ── Logic nodes ─────────────────────────────────────────────────────

    def add_logic_node(self, sample_id: str, operator: str, name: str | None = None) -> str | None:
        sample = self._sample(sample_id)
        if sample is None:
            return None

        # Created with NO parents: the user wires gate nodes into it on the
        # pipeline canvas. It still hangs off root.children so find_node_by_id
        # and the stats walk reach it; the canvas hides that root edge.
        node = GateNode(
            name=name or f"{operator} Logic",
            logic_operator=operator,
            parents=[],
            is_logic_node=True,
        )
        sample.gate_tree.children.append(node)

        # No stats yet: with no real parents it would compute against every event.
        _publish(events.LOGIC_NODE_CREATED, sample_id=sample_id, node_id=node.node_id)
        return node.node_id

    def add_connection(self, sample_id: str, source_node_id: str, target_node_id: str) -> bool:
        sample = self._sample(sample_id)
        if sample is None:
            return False
        source = sample.gate_tree.find_node_by_id(source_node_id)
        target = sample.gate_tree.find_node_by_id(target_node_id)
        if not source or not target:
            return False
        if target is sample.gate_tree:
            logger.warning("Cannot wire nodes: target is the root 'All Events' node")
            return False
        if target.find_node_by_id(source_node_id):
            logger.warning("Cannot wire nodes: creates a cycle")
            return False

        if source not in target.parents:
            target.parents.append(source)
        if target not in source.children:
            source.children.append(target)
        # Once real parents are wired in, drop the root sentinel so the
        # AND/OR/NOT logic doesn't include root. The node stays in
        # root.children, which is how the stats walk finds it.
        if sample.gate_tree in target.parents and len(target.parents) > 1:
            target.parents.remove(sample.gate_tree)

        self._after_rewire(sample_id, target, events.CONNECTION_ADDED)
        return True

    def remove_connection(self, sample_id: str, source_node_id: str, target_node_id: str) -> bool:
        sample = self._sample(sample_id)
        if sample is None:
            return False
        source = sample.gate_tree.find_node_by_id(source_node_id)
        target = sample.gate_tree.find_node_by_id(target_node_id)
        if not source or not target:
            return False

        if source in target.parents:
            target.parents.remove(source)
        if target in source.children:
            source.children.remove(target)
        if not target.parents:
            target.parents.append(sample.gate_tree)
            # A logic node stays in root.children while wired (see
            # add_connection), so it may already be there.
            if not any(child is target for child in sample.gate_tree.children):
                sample.gate_tree.children.append(target)

        if target.is_incomplete and target.is_logic_node:
            target.statistics = {
                "count": 0,
                "pct_parent": 0.0,
                "pct_total": 0.0,
                "per_parent_pcts": {},
            }
        self._after_rewire(sample_id, target, events.CONNECTION_REMOVED)
        return True

    def remove_connection_for_samples(
        self, source_node_id: str, target_node_id: str, sample_ids: list[str]
    ) -> int:
        """Remove a logic-node connection in each given sample; returns count removed."""
        return sum(
            self.remove_connection(sample_id, source_node_id, target_node_id)
            for sample_id in sample_ids
        )

    def _after_rewire(self, sample_id: str, target: GateNode, pending_topic: str) -> None:
        """Recompute a rewired node, or, while it is under-wired, only redraw its wire."""
        if target.is_incomplete:
            # Skip the expensive recompute and full canvas refresh: the canvas
            # just draws the wire and updates this one card.
            _publish(pending_topic, sample_id=sample_id, node_id=target.node_id)
            return
        self.recompute_all_stats(sample_id, node_ids=[target.node_id])
        _publish(events.GATE_STATS_UPDATED, sample_id=sample_id, node_id=target.node_id)

    # ── Statistics ──────────────────────────────────────────────────────

    def recompute_all_stats(
        self, sample_id: str, sync: bool = False, node_ids: list[str] | None = None
    ) -> None:
        """Recompute gate statistics for a sample.

        Args:
            sample_id: Target sample ID.
            sync: Run inline instead of on the background task scheduler.
            node_ids: When given, recompute just these nodes and their
                descendants — a gate edit or rewire never changes its
                ancestors. Changes that replace the whole tree (e.g.
                `copy_gates_to_group`) omit it.
        """
        sample = self._sample(sample_id)
        if sample is None:
            return
        # Safety net for derived columns (no-op when already current).
        sync_sample(self._state.data.experiment, sample)
        # Every edit funnels through here, so this is also where GateNode's
        # mask cache is invalidated.
        if node_ids:
            for node_id in node_ids:
                node = sample.gate_tree.find_node_by_id(node_id)
                if node:
                    node.invalidate_mask_cache()
        else:
            sample.gate_tree.invalidate_mask_cache()

        analyzer = StatisticsAnalysis()
        analyzer.target_sample_id = sample_id
        analyzer.target_node_ids = node_ids
        if sync or self.sync_stats:
            self._on_stats_finished(analyzer.run(self._state))
        elif sample.fcs_data is not None:
            self._submit_stats(analyzer)

    def _submit_stats(self, analyzer: StatisticsAnalysis) -> None:
        worker = task_scheduler.submit(analyzer, self._state)
        task_id = getattr(worker, "task_id", "")
        logger.info(
            "Submitted StatisticsAnalysis for %s (task %s)", analyzer.target_sample_id, task_id
        )

        # task_finished fires after the scheduler's own handler and before it
        # disconnects worker.finished.
        def _on_finished(finished_task_id: str, results: dict) -> None:
            if finished_task_id == task_id:
                with contextlib.suppress(TypeError, RuntimeError):
                    task_scheduler.task_finished.disconnect(_on_finished)
                self._on_stats_finished(results)

        task_scheduler.task_finished.connect(_on_finished)

    def _on_stats_finished(self, results: dict) -> None:
        sample_id = results.get("sample_id")
        sample = self._sample(sample_id) if sample_id else None
        if sample is None:
            return

        for node_id, stats in results.get("stats", {}).items():
            node = sample.gate_tree.find_node_by_id(node_id)
            if node is None:
                logger.warning(
                    "Stats for node %s, which sample %s no longer has", node_id, sample_id
                )
                continue
            node.statistics = stats
            _publish(events.GATE_STATS_UPDATED, sample_id=sample_id, node_id=node_id)
            _publish(events.STATS_COMPUTED, sample_id=sample_id, node_id=node_id, stats=stats)

        _publish(events.ALL_STATS_UPDATED, sample_id=sample_id)
        logger.info("Applied background stats for sample %s", sample_id)

    def cleanup(self) -> None:
        self._propagator.cleanup()
        logger.info("GateCoordinator cleaned up")
