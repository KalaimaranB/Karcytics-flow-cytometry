"""Gate lifecycle, selection, deletion and copying across the workspace's views.

Built once Phase 2 has created every view (MainPanelController.wire), so each
view it touches is a constructor argument rather than a panel attribute.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from karcytics_sdk.plugin.dialogs import get_text
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog, QTabBar, QWidget

from ...analysis.services.experiment_edits import exported_run
from ...main_tabs import MainTab

if TYPE_CHECKING:
    from ...analysis.gate_coordinator import GateCoordinator
    from ...analysis.state import FlowState
    from ..graph.graph_manager import GraphManager
    from ..ribbons.gating_ribbon import GatingRibbon
    from ..ribbons.pipeline_ribbon import PipelineRibbon
    from ..widgets.gate_hierarchy.widget import GateHierarchy
    from ..widgets.node_canvas.canvas_view import NodeCanvas
    from ..widgets.population_analysis_viewer import PopulationAnalysisViewer
    from ..widgets.properties_panel import PropertiesPanel
    from ..widgets.sample_list import SampleList


@dataclass(frozen=True)
class GatingViews:
    """The views a gate change has to keep in step."""

    tab_bar: QTabBar
    graph_manager: GraphManager
    gate_hierarchy: GateHierarchy
    properties_panel: PropertiesPanel
    sample_list: SampleList
    node_canvas: NodeCanvas
    gating_ribbon: GatingRibbon
    pipeline_ribbon: PipelineRibbon
    population_analysis_viewer: PopulationAnalysisViewer


class GatingController:
    """Turns gate events from the canvas, tree and model into view updates."""

    def __init__(
        self,
        state: FlowState,
        coordinator: GateCoordinator,
        views: GatingViews,
        dialog_parent: QWidget,
        status: Callable[[str], None],
        changed: Callable[[], None],
    ) -> None:
        self._state = state
        self._coordinator = coordinator
        self._views = views
        self._dialog_parent = dialog_parent
        self._status = status  # a line for the status bar
        self._changed = changed  # a user edit happened (panel.state_changed)
        self._propagation_active = True  # matches PropagationToggle default (ON)

    def refresh_node_canvas(self, *args, **kwargs) -> None:
        """Re-shows the Pipeline canvas's sample when that tab is open."""
        if self._views.tab_bar.currentIndex() == MainTab.PIPELINE:
            sid = self._views.pipeline_ribbon.current_sample_id
            if sid:
                self._views.node_canvas.set_sample(sid)

    # ── Gate lifecycle ──────────────────────────────────────────────────

    def on_gate_drawn(self, gate, sample_id: str, parent_node_id) -> None:
        """Handle a gate drawn on the canvas → add to model."""
        # Get a placeholder name for this gate (e.g., "Gate 1")
        default_name = self._coordinator.unique_name(sample_id)

        if not gate.takes_population_name:
            # A quadrant gate names its own four leaves; prompting would be
            # meaningless, and canceling the prompt would lose the gate.
            name = default_name
        else:
            typed_name = get_text(
                self._dialog_parent, "New Gate", "Enter name for the new gate:", default_name
            )
            if not typed_name or not typed_name.strip():
                # Cancelled or blank: no gate, but keep the drawing tool, so a
                # redraw still draws (resetting it silently made later clicks
                # select instead, and Academy steps looked stuck).
                return
            name = typed_name.strip()

        node_id = self._coordinator.add_gate(
            gate, sample_id, name=name, parent_node_id=parent_node_id
        )
        if node_id:
            # Switch back to select mode after drawing
            self._views.gating_ribbon.reset_to_select()

            # AUTO-SELECT the new node so properties are shown immediately
            self.select_population(node_id)

            # Navigate into the new gate automatically so the user can keep gating
            # We defer this via QTimer (150ms) to ensure the double-click event loop finishes
            # processing first. Otherwise, macOS Native Window handler might misinterpret
            # the orphaned double-click event and force the app out of full screen.
            QTimer.singleShot(
                150,
                lambda: self._views.graph_manager.open_graph_for_sample(sample_id, node_id),
            )

            if self._propagation_active:
                self._status("⟳ Propagating gate to other samples…")

    def on_gate_added(self, sample_id: str, node_id: str) -> None:
        """Gate added to model → refresh tree and canvas overlays."""
        self.refresh_gate_overlays(sample_id)
        self._changed()

        # Ensure the new node is selected
        self.select_population(node_id)

    def on_gates_added(self, sample_id: str, node_ids: list[str]) -> None:
        """Several gates added in one action (e.g. quadrant gate) → a single
        refresh/selection instead of one per node.
        """
        self.refresh_gate_overlays(sample_id)
        self._changed()

        if node_ids:
            self.select_population(node_ids[0])

    def on_gate_removed(self, sample_id: str, node_id: str) -> None:
        """Gate removed → refresh tree and canvas."""
        if node_id == self._state.view.current_gate_id:
            self._state.view.current_gate_id = None
            self._views.properties_panel.refresh()
        self.refresh_gate_overlays(sample_id)
        self._changed()

    def on_gate_stats_updated(self, sample_id: str, node_id: str) -> None:
        """Gate stats changed → update tree badges and properties."""
        self._views.gate_hierarchy.update_gate_stats(sample_id, node_id)
        # Update properties if this node is selected
        if node_id == self._state.view.current_gate_id:
            self._views.properties_panel.refresh()
        self.refresh_gate_overlays(sample_id)

    def on_all_stats_updated(self, sample_id: str) -> None:
        """All stats for a sample updated → bulk refresh."""
        self._views.sample_list.update_all_sample_stats(sample_id)
        self._views.gate_hierarchy.update_all_sample_stats(sample_id)

    def on_propagated_sample_updated(self, sample_id: str, stats: dict, new_tree: object) -> None:
        """A single sample finished propagation → update its tree."""
        self._views.sample_list.update_all_sample_stats(sample_id)
        self._views.gate_hierarchy.update_all_sample_stats(sample_id)
        self.refresh_gate_overlays(sample_id)

    def on_propagation_complete(self, payload: dict | None = None) -> None:
        """All samples finished propagation.

        `payload` (from GatePropagator, see events.PROPAGATION_COMPLETE) carries
        succeeded/failed counts — a chain-broken sample (e.g. missing the
        gated channel) no longer fails silently into a log line only.
        """
        payload = payload or {}
        total = payload.get("total", len(self._state.data.experiment.samples))
        failed = payload.get("failed", 0)
        succeeded = payload.get("succeeded", total)
        if failed:
            self._status(f"⚠ Gate propagated to {succeeded}/{total} samples ({failed} failed).")
        else:
            self._status(f"✓ Gate propagation complete ({total} samples updated).")
        # Refresh the properties panel and preview to show the new propagated gates/stats
        self._views.properties_panel.refresh()

    def on_delete_selected_gate(self, force_silent: bool = False) -> None:
        """Delete the gate currently selected in the hierarchy."""
        graph = self._views.graph_manager.get_active_graph()
        if graph is None:
            return

        node_id = self._state.view.current_gate_id
        if not node_id:
            self._status("No gate selected in hierarchy to delete.")
            return

        self.delete_gate_with_dialog(graph.sample_id, node_id, force_silent=force_silent)

    def delete_gate_with_dialog(  # noqa: PLR0915 - resolve scope, close graphs, delete, report
        self, sample_id: str, node_id: str, force_silent: bool = False
    ) -> None:
        """Prompt the user and delete a gate and its children."""
        sample = self._state.data.experiment.samples.get(sample_id)
        if not sample:
            return

        selected_node = sample.gate_tree.find_node_by_id(node_id)
        if not selected_node or not selected_node.gate:
            self._status("Selected node has no gate to delete.")
            return

        scope: str
        group_id: str | None
        if force_silent:
            scope = "group" if self._propagation_active else "sample"
            group_id = getattr(self._state.view, "active_group_filter", "__all__")
            if group_id != "__all__" and sample.group_ids and group_id not in sample.group_ids:
                group_id = sample.group_ids[0]
            elif group_id == "__all__" and not sample.group_ids:
                group_id = "all"
        else:
            # Prepare groups for the dialog
            group_choices = [("all", "All Samples")]
            for gid in sample.group_ids:
                grp = self._state.data.experiment.groups.get(gid)
                if grp:
                    group_choices.append((gid, grp.name))

            # karcytics: allow KS360 - off the Phase 1 path
            from ..widgets.scope_selection_dialog import ScopeSelectionDialog

            dialog = ScopeSelectionDialog(
                f"Are you sure you want to delete the gate '<b>{selected_node.name}</b>'?",
                sample.display_name,
                group_choices,
                self._dialog_parent,
                title="Confirm Gate Deletion",
            )
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return

            scope_raw, group_id = dialog.get_scope()
            scope = scope_raw or "sample"

        physical_gate_id = selected_node.gate.gate_id

        # karcytics: allow KS360 - off the Phase 1 path
        from ...analysis.scope_resolution import resolve_target_samples

        target_samples = resolve_target_samples(
            scope, group_id, sample_id, self._state.data.experiment
        )

        deleted_nodes_by_sample = self._coordinator.populations_under_gate(
            physical_gate_id, target_samples
        )

        # If the active graph is viewing one of the deleted nodes,
        # open the parent graph (if any) first.
        active_graph = self._views.graph_manager.get_active_graph()
        if active_graph and active_graph.sample_id in deleted_nodes_by_sample:
            if active_graph.node_id in deleted_nodes_by_sample[active_graph.sample_id]:
                parent_node_id = None
                if selected_node.parents and not selected_node.parents[0].is_root:
                    parent_node_id = selected_node.parents[0].node_id
                self._views.graph_manager.open_graph_for_sample(
                    active_graph.sample_id, parent_node_id
                )

        removed = self._coordinator.delete_gate(physical_gate_id, target_samples)

        if hasattr(self._views.graph_manager, "close_graphs_for_nodes"):
            self._views.graph_manager.close_graphs_for_nodes(removed)

        scope_msg = "this sample" if scope == "sample" else "the group"
        self._status(f"Gate deleted for {scope_msg}.")

    def on_propagation_mode_changed(self, enabled: bool) -> None:
        """Handle AUTO-PROPAGATE toggle flip from GateHierarchy."""
        self._propagation_active = enabled
        # Actually gate the propagation in the model layer
        self._coordinator.set_propagation_enabled(enabled)
        if enabled:
            self._status("Auto-propagation ON — gates will propagate on every change.")
        else:
            self._status("Auto-propagation OFF — gates stay local until manually applied.")

    def on_copy_gates(self, sample_id: str) -> None:
        """Copy gates from a sample to all others in its group."""
        count = self._coordinator.copy_gates_to_group(sample_id)
        self._views.gate_hierarchy.refresh()
        self._changed()
        self._status(f"Gates copied to {count} sample{'s' if count != 1 else ''}.")

    def on_copy_gates_from_active(self) -> None:
        """Copy gates from the active graph's sample."""
        graph = self._views.graph_manager.get_active_graph()
        if graph:
            self.on_copy_gates(graph.sample_id)

    def on_gate_selected_on_canvas(self, gate_id: str | None) -> None:
        """Gate clicked on canvas → update selection state."""
        graph = self._views.graph_manager.get_active_graph()
        if graph is None:
            return

        if gate_id:
            sample = self._state.data.experiment.samples.get(graph.sample_id)
            if sample:
                # Map gate_id back to a primary node_id
                nodes = sample.gate_tree.find_nodes_by_gate(gate_id)
                if nodes:
                    self.select_population(nodes[0].node_id)
        else:
            self.select_population(None)

    def on_active_graph_changed(self, sample_id: str | None, node_id: str | None) -> None:
        """When the user switches tabs in the GraphManager."""
        self._state.view.current_sample_id = sample_id or None
        self._views.properties_panel.set_displayed_population(sample_id or None, node_id)

        if sample_id:
            # Keep the global selected-gate state in sync with whatever tab is actually
            # visible. Without this, navigating via the parent/child breadcrumb buttons
            # (which switch tabs without going through GateCoordinator.select_gate) leaves
            # current_gate_id pointing at a stale population — so a later legitimate
            # select_gate() call for that same node_id gets silently swallowed by its
            # dedup guard, and GroupPreviewPanel never learns the population changed.
            self._coordinator.select_gate(sample_id, node_id)
            self._views.gate_hierarchy.set_active_sample(sample_id)
            self._views.properties_panel.show_sample_properties(sample_id, node_id)

            self._views.sample_list.blockSignals(True)
            self._views.sample_list.select_sample(sample_id)
            self._views.sample_list.blockSignals(False)
        else:
            self._views.gate_hierarchy.show_empty()
            self._views.properties_panel.show_empty()
            self._views.sample_list.select_sample(None)

    def on_sample_selection_changed(self, sample_id: str) -> None:
        """Sample selection changed in list."""
        self._views.gate_hierarchy.set_active_sample(sample_id)

    def on_gate_selection_changed(self, node_id: str) -> None:
        """Gate selection changed in tree → update canvas and properties."""
        self.select_population(node_id)

    def on_gate_double_clicked(self, node_id: str) -> None:
        """Gate double clicked → open new graph viewing this population."""
        sample_id = None
        if self._views.tab_bar.currentIndex() == MainTab.PIPELINE:
            sample_id = self._views.node_canvas.current_sample_id

        if not sample_id:
            sample_id = (
                self._views.gate_hierarchy.active_sample_id or self._state.view.current_sample_id
            )

        if sample_id:
            sample = self._state.data.experiment.samples.get(sample_id)
            if sample and sample.gate_tree:
                node = sample.gate_tree.find_node_by_id(node_id)
                if node and node.is_umap_parent:
                    # An exported clustering: reopen the run it came from.
                    run = exported_run(self._state, sample_id, node.node_id)
                    if run is not None:
                        self._views.tab_bar.setCurrentIndex(MainTab.POPULATION_ANALYSIS)
                        self._views.population_analysis_viewer.show_run(sample_id, *run)
                    return

            # If we are in Pipeline view, switch back to Gating view automatically
            if self._views.tab_bar.currentIndex() == MainTab.PIPELINE:
                self._views.tab_bar.setCurrentIndex(MainTab.GATING)
                if self._views.gate_hierarchy.active_sample_id != sample_id:
                    self._state.view.current_sample_id = sample_id
                    self._views.gate_hierarchy.set_active_sample(sample_id)

            self._views.graph_manager.open_graph_for_sample(sample_id, node_id)

            # Also select the gate so the properties panel and group preview
            # update their context to this node. Without this, GroupPreviewPanel
            # never receives the correct node_id and renders thumbnails with no gates.
            self._coordinator.select_gate(sample_id, node_id)

    def select_population(self, node_id: str | None) -> None:
        """Central selection handler for populations across all UI components."""
        sample_id = None
        if self._views.tab_bar.currentIndex() == MainTab.PIPELINE:
            sample_id = self._views.node_canvas.current_sample_id

        if not sample_id:
            graph = self._views.graph_manager.get_active_graph()
            sample_id = graph.sample_id if graph else self._views.gate_hierarchy.active_sample_id

        if sample_id:
            self._coordinator.select_gate(sample_id, node_id)

    def on_gate_selected_from_controller(self, sample_id: str, node_id: str | None) -> None:
        """Global selection update from the model layer."""
        # Sync tree selection
        self._views.gate_hierarchy.refresh()

        # Nothing selected (e.g. a click on empty plot): describe the population the
        # active plot shows, not All Events, so the properties and Group Preview
        # still match the main plot.
        if node_id is None:
            graph = self._views.graph_manager.get_active_graph()
            if graph is not None and graph.sample_id == sample_id:
                node_id = graph.node_id

        # Update properties panel
        self._views.properties_panel.show_sample_properties(sample_id, node_id)

        node_name = "None"
        if sample_id and node_id:
            sample = self._state.data.experiment.samples.get(sample_id)
            if sample and sample.gate_tree:
                node = sample.gate_tree.find_node_by_id(node_id)
                if node:
                    node_name = node.name or node_id

        self._status(f"Population selected: {node_name}")

    def refresh_gate_overlays(self, sample_id: str) -> None:
        """Refresh gate overlays on all open graphs for a sample."""
        # Determine which parent gate each open graph is viewing
        for graph in self._views.graph_manager.graphs_of(sample_id):
            gates, nodes = self._coordinator.get_gates_for_display(sample_id, graph.node_id)
            graph.refresh_gates(gates, nodes)
