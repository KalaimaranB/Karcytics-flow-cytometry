"""Keeps the workspace's views in step when samples, compensation, derived
parameters or the whole model (a load, undo/redo) change.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from karcytics_sdk.plugin import get_logger
from karcytics_sdk.plugin.dialogs import get_text
from PySide6.QtWidgets import QWidget

from ...analysis.compensation import extract_spill_from_fcs
from ...analysis.services import experiment_edits

if TYPE_CHECKING:
    from ...analysis.state import FlowState
    from ..composition_root import FlowServices
    from ..workspace_views import WorkspaceViews
    from .gating_controller import GatingController

logger = get_logger(__name__, "flow_cytometry")


class WorkspaceRefresher:
    """Re-reads the model into the views after a change no single view owns."""

    def __init__(
        self,
        state: FlowState,
        services: FlowServices,
        views: WorkspaceViews,
        gating: GatingController,
        dialog_parent: QWidget,
        status: Callable[[str], None],
        changed: Callable[[], None],
    ) -> None:
        self._state = state
        self._services = services
        self._views = views
        self._gating = gating
        self._dialog_parent = dialog_parent
        self._status = status  # a line for the status bar
        self._changed = changed  # a user edit happened (panel.state_changed)

    def refresh_all(self) -> None:
        """Rebuilds every view from the current state (after a load or undo/redo)."""
        views, view_state = self._views, self._state.view
        views.refresh_sample_pickers()

        samples = self._state.data.experiment.samples
        sid = view_state.current_sample_id
        if not sid and samples:  # samples but none active: pick the first
            sid = view_state.current_sample_id = next(iter(samples))

        views.sample_list.blockSignals(True)
        views.sample_list.select_sample(sid or None)
        views.sample_list.blockSignals(False)
        if sid:
            views.gate_hierarchy.set_active_sample(sid)
            if views.graph_manager.get_active_graph() is None:
                views.graph_manager.open_graph_for_sample(sid, view_state.current_gate_id)
        else:
            views.gate_hierarchy.show_empty()

        if view_state.current_gate_id:
            self._gating.select_population(view_state.current_gate_id)

        views.properties_panel.refresh()
        views.graph_manager.refresh()

    def on_state_restored(self, _payload: Any = None) -> None:
        """Undo/redo replaced the model: make every view re-read it by id."""
        self._services.gate_propagator.cancel_pending()
        for sid, sample in self._state.data.experiment.samples.items():
            if sample.fcs_data is not None and sample.gate_tree.children:
                self._services.gate_coordinator.recompute_all_stats(sid)
        self._views.graph_manager.reconcile_with_state()
        self.refresh_all()
        self._gating.refresh_node_canvas()

    def on_samples_loaded(self) -> None:
        """The workspace ribbon loaded FCS files."""
        if self._state.data.compensation is None:
            self._adopt_embedded_compensation()
        self._views.refresh_sample_pickers()
        self._changed()
        self._status(f"{len(self._state.data.experiment.samples)} samples loaded.")

    def _adopt_embedded_compensation(self) -> None:
        """Applies the first spillover matrix a compensated FCS file carries."""
        for sample in self._state.data.experiment.samples.values():
            if not (sample.fcs_data and sample.fcs_data.is_compensated):
                continue
            try:
                matrix = extract_spill_from_fcs(sample.fcs_data)
            except Exception as exc:
                logger.warning("Failed to extract auto-spill matrix: %s", exc)
                continue
            if matrix:
                self._state.data.compensation = matrix
                logger.info(
                    "Auto-Compensation: applied the embedded matrix from %s.", sample.display_name
                )
                return

    def on_group_requested(self) -> None:
        """The workspace ribbon's "Create Group"."""
        name = get_text(self._dialog_parent, "New Group", "Enter name for the new group:", "")
        group = experiment_edits.create_group(self._state, name) if name is not None else None
        if group is not None:
            self._views.groups_panel.refresh()
            self._status(f"Group '{group.name}' created.")

    def on_compensation_changed(self) -> None:
        views = self._views
        views.sample_list.refresh()  # event counts change with compensation
        views.gate_hierarchy.refresh()
        views.properties_panel.refresh()
        self._changed()
        comp = self._state.data.compensation
        self._status(f"Compensation updated (source: {comp.source if comp else 'none'}).")

    def on_derived_params_changed(self, payload: dict) -> None:
        """A derived parameter was created, edited or deleted.

        DerivedParameterService has already re-synced the columns and graph
        windows rebuild their own axis lists; this refreshes every other
        channel picker and recomputes stats for gates on an edited parameter.
        """
        views = self._views
        views.statistics_explorer.refresh_channels()
        views.comparisons_viewer.refresh_channels()
        views.gate_hierarchy.refresh()
        views.properties_panel.refresh()
        self._gating.refresh_node_canvas()

        if payload.get("action") == "updated":
            service = self._services.derived_parameter_service
            affected = {d.sample_id for d in service.find_dependents(payload.get("param_id", ""))}
            for sample_id in affected:
                self._services.gate_coordinator.recompute_all_stats(sample_id)
