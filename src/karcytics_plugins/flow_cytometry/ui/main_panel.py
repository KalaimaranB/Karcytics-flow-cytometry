"""Flow cytometry workspace — the root panel the Hub's plugin runtime shows.

Holds the plugin interface (signals, export/load_workflow, undo/redo,
confirm_close, the Academy entry points) and the tab switching. Everything
else is delegated: services come from `composition_root.build_services`, the
widgets from `builders/workspace_builder.py` (in two phases, see
`startup_sequencer.py`), and the controllers in `controllers/` take the built
widgets as a `WorkspaceViews`.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import TYPE_CHECKING, Any

from karcytics_sdk.plugin import PluginBase, PluginDaemon, get_logger
from karcytics_sdk.plugin.theme_fallback import Colors, theme_manager
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QSizePolicy,
)

from karcytics_plugins.flow_cytometry.analysis import events
from karcytics_plugins.flow_cytometry.analysis.derived import sync_experiment
from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.main_tabs import MainTab
from karcytics_plugins.flow_cytometry.ui.academy_context import AcademyContext
from karcytics_plugins.flow_cytometry.ui.composition_root import build_services
from karcytics_plugins.flow_cytometry.ui.services.bus_subscriptions import subscribe_while_alive
from karcytics_plugins.flow_cytometry.ui.services.workflow_loader import WorkflowLoader
from karcytics_plugins.flow_cytometry.ui.startup_sequencer import StartupSequencer
from karcytics_plugins.flow_cytometry.ui.workspace_theme import (
    palette_key,
    restyle_children,
    ribbon_stack_qss,
    tab_bar_qss,
)
from karcytics_plugins.flow_cytometry.ui.workspace_views import WorkspaceViews

from ..analysis.workspace_document import apply_workspace

if TYPE_CHECKING:
    from .controllers.gating_controller import GatingController
    from .controllers.main_panel_controller import MainPanelController
    from .controllers.workspace_refresher import WorkspaceRefresher

logger = get_logger(__name__, "flow_cytometry")


# Each tab's centre view and ribbon (None: no ribbon), as panel attribute names.
_TAB_VIEWS: dict[MainTab, tuple[str, str | None]] = {
    MainTab.WORKSPACE: ("_graph_manager", "_workspace_ribbon"),
    MainTab.GATING: ("_graph_manager", "_gating_ribbon"),
    MainTab.COMPENSATION: ("_compensation_view", None),
    MainTab.PIPELINE: ("_node_canvas", "_pipeline_ribbon"),
    MainTab.SPECTRAL: ("_spectral_viewer", None),
    MainTab.POPULATION_ANALYSIS: ("_population_analysis_viewer", None),
    MainTab.AUTO_GATING: ("_auto_gating", None),
    MainTab.SAMPLE_LENS: ("_sample_lens", None),
    MainTab.STATISTICS: ("_statistics_explorer", None),
    MainTab.COMPARISONS: ("_comparisons_viewer", None),
}


class FlowCytometryPanel(PluginBase):
    """Root widget for the Flow Cytometry workspace.

    Layout: tab bar and stacked ribbon on top; groups / samples / gate tree
    on the left, the tab's view in the centre, properties on the right (the
    sidebars only on the Workspace and Gating tabs).
    """

    # Dynamically injected UI components from WorkspaceBuilder
    _tab_bar: Any
    _btn_academy: Any
    _ribbon_stack: Any
    _workspace_ribbon: Any
    _compensation_ribbon: Any
    _compensation_view: Any
    _gating_ribbon: Any
    _pipeline_ribbon: Any
    _stats_ribbon: Any
    _spectral_ribbon: Any
    _comparisons_ribbon: Any
    _main_splitter: Any
    _left_sidebar: Any
    _groups_panel: Any
    _left_splitter: Any
    _sample_list: Any
    _gate_hierarchy: Any
    _left_sep: Any
    _center_stack: Any
    _center_placeholder: Any
    _properties_panel: Any
    _graph_manager: Any
    _footer: Any
    _node_canvas: Any
    _spectral_viewer: Any
    _population_analysis_viewer: Any
    _statistics_explorer: Any
    _comparisons_viewer: Any
    _sample_lens: Any
    _auto_gating: Any

    # state_changed and status_message come from PluginBase. The Ready Gate
    # (startup_sequencer.py): panel_ready once the widgets are built, data_ready
    # once the data is in. Academy gate steps wait on gate_added_to_tree.
    panel_ready = Signal()
    data_ready = Signal()
    gate_added_to_tree = Signal()

    def __init__(self, plugin_id: str = "flow_cytometry", parent=None) -> None:
        logger.debug("[phase1] FlowCytometryPanel.__init__: super().__init__ start")
        super().__init__(plugin_id, parent)
        logger.debug("[phase1] FlowCytometryPanel.__init__: super().__init__ done")

        # Academy InteractionSteps (course1/course2 gate steps) target this
        # panel by objectName to wire up gate_added_to_tree — without this,
        # AcademyStepDriver's findChildren lookup finds nothing and those
        # steps never auto-advance.
        self.setObjectName("MainPanel")

        # ── State ─────────────────────────────────────────────────────
        self.state = FlowState()
        # Built by _wire_signals once Phase 2 has created the views.
        self._views: WorkspaceViews | None = None
        self._gating: GatingController | None = None
        self._refresher: WorkspaceRefresher | None = None
        self._wiring: MainPanelController | None = None
        # Startup: a workflow PluginLoaderManager hands over before Phase 2 finishes.
        self._deferred_workflow_payload: dict[str, Any] | None = None
        self._deferred_workflow_filename: str | None = None
        self._deferred_workflow_metadata: dict[str, Any] | None = None
        self._startup = StartupSequencer(self.panel_ready, self.data_ready, self)
        self._themed_palette: Any = None
        self._btn_smart_save: Any = (
            None  # WorkspaceBuilder.build_skeleton; dirtiness can come first
        )
        self._workflow_autosave_controller: Any = None  # end of _setup_services

        # ── Services ──────────────────────────────────────────────────
        logger.debug("[phase1] FlowCytometryPanel.__init__: _setup_services start")
        self._setup_services()
        logger.debug("[phase1] FlowCytometryPanel.__init__: _setup_services done")

        # ── Size policy ───────────────────────────────────────────────
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # ── Build UI skeleton (Phase 1) ───────────────────────────────
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"background: {Colors.BG_DARKEST};")
        logger.debug("[phase1] FlowCytometryPanel.__init__: _setup_ui start")
        self._setup_ui()
        logger.debug("[phase1] FlowCytometryPanel.__init__: _setup_ui done")
        self._setup_footer_events()
        logger.debug("[phase1] FlowCytometryPanel.__init__: _setup_footer_events done")

        # Piped to the core status bar (see workspace_builder.connect_tab_bar
        # for the "Ready" message once Phase 2 completes).
        self.status_message.emit("Loading workspace…")

    def _setup_services(self) -> None:
        """Initialize and wire all core analysis and UI services."""
        self.services = build_services(self.state, self)
        self._academy_widgets = AcademyContext(
            derived_editor=self.services.derived_editor,
            gate_coordinator=self.services.gate_coordinator,
        )

        # ── Undo/redo & unsaved changes ───────────────────────────────
        # PluginBase's undo()/redo() and the isolated window's Edit menu
        # drive the store's history through bind_undo_history. Domain events
        # are turned into steps by the HistoryRecorder MainPanelController wires.
        self.services.store.add_dirty_listener(self.set_dirty)
        # state_changed keeps meaning "a user edit happened" (ui_daemon
        # forwards it to the Hub, e.g. for the Academy's file-import check).
        self.services.store.add_commit_listener(lambda _label: self.state_changed.emit())
        self.services.store.reset()
        self.bind_undo_history(self.services.store.history, self.services.store.restore)

        # Shared SDK loop (PluginBase.setup_workflow_autosave): every 15
        # minutes, silently re-saves a workflow that's already been saved
        # manually at least once (toast on success), or reminds the user
        # it's unsaved otherwise. Also contributes this panel's "Workspace"
        # preferences page automatically (see PluginBase.populate_preferences).
        self._workflow_autosave_controller = self.setup_workflow_autosave(
            has_saved_once=lambda: bool(self.services.document.filename),
            save=self.services.workspace_io_handler.handle_autosave,
            has_unsaved_changes=lambda: self.services.store.is_dirty,
        )

        # Academy courses run inside Academy workflows: pausable, saved as
        # they go, locked while paused (see ui/academy_workflow.py).
        # karcytics: allow KS360 - off the Phase 1 path
        from .academy_workflow import AcademyWorkflowController

        self._academy = AcademyWorkflowController(
            self, self.services.document, self.services.workspace_io_handler
        )
        self._loader = WorkflowLoader(
            self.state,
            self.services,
            self,
            status=self.status_message.emit,
            refresh=self._refresh_all,
            on_loaded=self._academy.on_workflow_loaded,
            data_loaded=self._startup.data_loaded,
        )

    def _setup_footer_events(self) -> None:
        """Say in the footer what just happened (the footer is built by then)."""
        messages = {
            events.SAMPLE_LOADED: "Samples loaded.",
            events.GATE_CREATED: "Gate created.",
            events.GATES_CREATED: "Gates created.",
            events.GATE_DELETED: "Gate deleted.",
            events.UMAP_COMPLETED: "UMAP computation complete.",
            events.COMPENSATION_APPLIED: "Compensation applied.",
            events.STATS_COMPUTED: "Statistics updated.",
        }
        footer = self._footer
        subscribe_while_alive(
            footer,
            {
                topic: partial(_show_footer_message, footer, message)
                for topic, message in messages.items()
            },
        )

    def closeEvent(self, event) -> None:
        """Shutdown plugin daemon on panel close."""
        try:
            PluginDaemon.stop_instance("flow_cytometry")
        except Exception:
            pass
        super().closeEvent(event)

    def shutdown(self) -> None:
        """Module shutdown hook."""
        try:
            PluginDaemon.stop_instance("flow_cytometry")
        except Exception:
            pass

    # ── State Tracking ────────────────────────────────────────────────

    @property
    def _is_dirty(self) -> bool:
        return self.services.store.is_dirty

    def set_dirty(self, dirty: bool) -> None:
        """Show whether the workspace has unsaved changes.

        Driven by ``FlowStore`` (which alone decides dirtiness — see
        ``FlowStore.is_dirty``); also safe to call to re-sync the button.
        """
        if self._btn_smart_save is not None:
            has_wf = bool(self.services.document.filename or self.services.document.path)
            self._btn_smart_save.set_workflow_active(has_wf)
            self._btn_smart_save.set_dirty(dirty)
        # Every point that clears the dirty flag is a point the workspace is
        # known to be in sync with disk (a manual save/update/load, or this
        # controller's own autosave) — restart the 15-minute countdown from
        # here rather than from whenever the plugin happened to start.
        if not dirty and self._workflow_autosave_controller is not None:
            self._workflow_autosave_controller.notify_saved()

    # ── UI Construction ───────────────────────────────────────────────

    def current_tab(self) -> MainTab | None:
        index = self._tab_bar.currentIndex()
        return MainTab(index) if 0 <= index < len(MainTab) else None

    def show_tab(self, tab: MainTab) -> None:
        self._tab_bar.setCurrentIndex(tab)

    def _on_tab_changed(self, index: int) -> None:
        """Handle main tab changes to update ribbon and central view."""
        self.state.view.active_main_tab_index = index
        # Switching tabs flips several sibling widgets' visibility in one
        # go (center stack page + sidebar + properties panel + ribbon),
        # each triggering its own native resize/show pass. Dispatching those
        # as separate native events — with the mouse still sitting over
        # whatever tab button was just clicked — has crashed the app
        # outright (EXC_BREAKPOINT inside Qt's macOS cursor-image
        # synthesis, mid dispatchEnterLeave, while this cascade was still
        # settling). Suppressing repaints until every change below has been
        # applied collapses it to one clean layout/paint/cursor pass instead
        # of several partial ones.
        self.setUpdatesEnabled(False)
        try:
            self._on_tab_changed_locked(index)
        finally:
            self.setUpdatesEnabled(True)

    def _on_tab_changed_locked(self, index: int) -> None:
        if not 0 <= index < len(MainTab):
            return
        tab = MainTab(index)
        view, ribbon = _TAB_VIEWS[tab]
        self._center_stack.setCurrentWidget(getattr(self, view))
        # Workspace and Gating share the sidebars; every other tab takes over the window.
        with_sidebars = tab in (MainTab.WORKSPACE, MainTab.GATING)
        self._left_sidebar.setVisible(with_sidebars)
        self._properties_panel.setVisible(with_sidebars)
        if ribbon is None:
            self._ribbon_stack.hide()
        else:
            self._ribbon_stack.setCurrentWidget(getattr(self, ribbon))
            self._ribbon_stack.show()

        if tab is MainTab.PIPELINE:
            # Auto-select the currently active sample if possible
            sample_id = self.state.view.current_sample_id
            # Selecting a sample on the ribbon shows it on the canvas too.
            if not (sample_id and self._pipeline_ribbon.select_sample(sample_id)):
                self._refresh_node_canvas()
        elif tab is MainTab.STATISTICS:
            self._statistics_explorer.refresh_samples()
        elif tab is MainTab.POPULATION_ANALYSIS:
            self._population_analysis_viewer.refresh_samples()
        elif tab is MainTab.AUTO_GATING:
            self._auto_gating.refresh_samples()
        elif tab is MainTab.COMPARISONS:
            self._comparisons_viewer.refresh_samples()

    def _handle_save(self) -> None:
        """Handle save workspace request."""
        self.services.workspace_io_handler.handle_save()

    def _handle_update(self) -> None:
        """Overwrite the currently loaded workflow using Karcytics SDK services."""
        self.services.workspace_io_handler.handle_update()

    def _setup_ui(self) -> None:
        """Build the workspace skeleton (Phase 1).

        Only the lightweight structural scaffold is created here: tab bar,
        ribbons, sidebar, and an empty center-stack placeholder. Heavy analysis
        views (GraphManager, NodeCanvas, etc.) are built in ``_phase2_build``
        after the GalacticLoader has signalled its warp peak.
        """
        logger.debug("[phase1] _setup_ui: importing workspace_builder")
        # karcytics: allow KS360 - off the Phase 1 path
        from ..ui.builders.workspace_builder import WorkspaceBuilder

        logger.debug("[phase1] _setup_ui: workspace_builder imported, calling build_skeleton()")
        WorkspaceBuilder.build_skeleton(self)
        logger.debug("[phase1] _setup_ui: build_skeleton() done")

        # ── Theme Sync (skeleton widgets only) ────────────────────────
        self._apply_theme_styles()
        theme_manager.theme_changed.connect(self._apply_theme_styles)

    # ── Ready Gate protocol: Phase 2 (see startup_sequencer.py) ───────

    def begin_async_init(self) -> None:
        """Phase 2: the Hub's loader calls this once the skeleton is on screen."""
        # karcytics: allow KS360 - off the Phase 1 path
        from ..ui.builders.workspace_builder import WorkspaceBuilder as B

        # Best-effort, non-blocking: only ever shows a toast if GitHub has a newer release.
        self.check_for_updates(
            repo_url="https://github.com/KalaimaranB/Karcytics-flow-cytometry",
            display_name="Flow Cytometry",
        )
        self._startup.start(
            [
                ("graph_manager", lambda: B.build_step_graph_manager(self)),
                ("node_canvas", lambda: B.build_step_node_canvas(self)),
                ("spectral", lambda: B.build_step_spectral(self)),
                ("population", lambda: B.build_step_population(self)),
                ("statistics", lambda: B.build_step_statistics(self)),
                ("comparisons", lambda: B.build_step_comparisons(self)),
                ("compensation", lambda: B.build_step_compensation(self)),
                ("finalize", self._finish_phase2),
            ],
            take_deferred_load=self._take_deferred_load,
        )

    def _finish_phase2(self) -> None:
        """The heavy widgets exist: stack them, wire them, theme them."""
        # karcytics: allow KS360 - off the Phase 1 path
        from ..ui.builders.workspace_builder import WorkspaceBuilder

        WorkspaceBuilder.finalize_center_stack(self)
        self._wire_signals()
        WorkspaceBuilder.connect_tab_bar(self)
        self._apply_theme_styles()

    def _take_deferred_load(self) -> Callable[[], None] | None:
        """The load of the workflow the SDK staged on `_deferred_workflow_*`, if any."""
        payload = self._deferred_workflow_payload
        if payload is None:
            return None
        filename, metadata = self._deferred_workflow_filename, self._deferred_workflow_metadata
        self._deferred_workflow_payload = None
        self._deferred_workflow_filename = None
        self._deferred_workflow_metadata = None
        return lambda: self.load_workflow(payload, filename=filename, metadata=metadata)

    def _wire_signals(self) -> None:
        """Builds the controllers over the finished views and connects them."""
        # karcytics: allow KS360 - off the Phase 1 path
        from ..ui.controllers.gating_controller import GatingController

        # karcytics: allow KS360 - off the Phase 1 path
        from ..ui.controllers.main_panel_controller import MainPanelController

        # karcytics: allow KS360 - off the Phase 1 path
        from ..ui.controllers.workspace_refresher import WorkspaceRefresher

        views = self._views = WorkspaceViews(
            tab_bar=self._tab_bar,
            workspace_ribbon=self._workspace_ribbon,
            gating_ribbon=self._gating_ribbon,
            pipeline_ribbon=self._pipeline_ribbon,
            groups_panel=self._groups_panel,
            sample_list=self._sample_list,
            gate_hierarchy=self._gate_hierarchy,
            properties_panel=self._properties_panel,
            graph_manager=self._graph_manager,
            node_canvas=self._node_canvas,
            compensation_view=self._compensation_view,
            population_analysis_viewer=self._population_analysis_viewer,
            statistics_explorer=self._statistics_explorer,
            comparisons_viewer=self._comparisons_viewer,
        )
        status, changed = self.status_message.emit, self.state_changed.emit
        gating = self._gating = GatingController(
            self.state, self.services.gate_coordinator, views, self, status, changed
        )
        refresher = self._refresher = WorkspaceRefresher(
            self.state, self.services, views, gating, self, status, changed
        )
        self._wiring = MainPanelController(
            self.state, self.services, views, gating, refresher, self.gate_added_to_tree
        )
        self._wiring.wire()

    def _apply_theme_styles(self) -> None:
        """Restyles the skeleton and every child for the current theme.

        Skips a palette it has already applied: the isolated runtime both
        emits ``theme_changed`` (connected here) and calls this directly, and
        each pass restyles every widget and redraws every plot.
        """
        palette = palette_key()
        if palette == self._themed_palette:
            return
        self._themed_palette = palette
        self.setStyleSheet(f"background: {Colors.BG_DARKEST};")
        self._tab_bar.setStyleSheet(tab_bar_qss())
        self._ribbon_stack.setStyleSheet(ribbon_stack_qss())
        self._left_sidebar.setStyleSheet(f"background: {Colors.BG_DARKEST};")
        self._left_sep.setStyleSheet(f"background: {Colors.BORDER};")
        restyle_children(self, keep=(self._tab_bar, self._ribbon_stack))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.logger.info(f"FlowCytometryPanel resized: {self.width()}x{self.height()}")

    def _refresh_node_canvas(self) -> None:
        if self._gating is not None:
            self._gating.refresh_node_canvas()

    def delete_gate_with_dialog(
        self, sample_id: str, node_id: str, force_silent: bool = False
    ) -> None:
        """Prompt for scope and delete a gate and its children (the Academy calls this)."""
        if self._gating is not None:
            self._gating.delete_gate_with_dialog(sample_id, node_id, force_silent)

    def cleanup(self) -> None:
        """Resource cleanup on plugin close."""
        self.logger.info("Cleaning up Flow Cytometry workspace...")

        if self._wiring is not None:
            self._wiring.unwire()
        self._academy.dispose()
        self.services.gate_coordinator.cleanup()  # its timers and workers
        # The skeleton's and Phase 2's widgets hold their own bus subscriptions.
        self._sample_list.cleanup()
        self._properties_panel.cleanup()
        if self._views is not None:
            self._views.graph_manager.cleanup()
            self._views.compensation_view.cleanup()
        self.services.umap_service.cancel()

        super().cleanup()

    def get_state(self) -> FlowState:
        """Package the workspace state for the SDK."""
        return self.state

    def push_state(self, label: str = "") -> None:
        """Record the current state as an undo step (see ``FlowStore.commit``)."""
        self.services.store.commit(label or "Edit")

    def set_state(self, state: Any) -> None:
        """Adopt `state`'s contents into this panel's own ``FlowState``, in place.

        The panel's ``FlowState`` object is never replaced — every service
        and widget holds a reference to it — so the given state is copied
        in through the workflow document, the same path a load takes.
        """
        if not state:
            return

        apply_workspace(self.state, state.to_dict())
        sync_experiment(self.state.data.experiment)
        self.services.store.reset(clean=False)
        self._refresh_all()

    # ── Undo / redo ───────────────────────────────────────────────────

    def undo(self) -> bool:
        """Edit → Undo (Cmd/Ctrl+Z)."""
        return self._step_history("undo")

    def redo(self) -> bool:
        """Edit → Redo (Cmd+Shift+Z / Ctrl+Y)."""
        return self._step_history("redo")

    def _step_history(self, direction: str) -> bool:
        reason = self.services.document.undo_blocked_reason()
        if reason is not None:
            self.status_message.emit(f"Can't {direction} while {reason}.")
            return False
        if self._views is not None:
            self._views.graph_manager.cancel_active_drawing()
        # A step still waiting for the end of this event-loop turn, or a
        # change nothing announced, must be its own step before we move.
        self.services.document.flush_history()
        self.services.store.record_unannounced_changes()

        history = self.services.store.history
        label = history.undo_label() if direction == "undo" else history.redo_label()
        stepped = super().undo() if direction == "undo" else super().redo()
        if stepped:
            verb = "Undid" if direction == "undo" else "Redid"
            self.status_message.emit(f"{verb} {label}." if label else f"{verb} last change.")
        return stepped

    # ── Unsaved-changes prompts ───────────────────────────────────────

    def confirm_close(self) -> bool:
        """Asked by the isolated window before a user closes it."""
        document = self.services.document

        def _save() -> None:
            if document.filename:
                self._handle_update()
            else:
                self._handle_save()

        return document.confirm_close(self._academy.confirm_close, _save)

    # ── Academy (called by the SDK's open_academy / build_academy_overlay) ──

    def academy_context(self) -> AcademyContext:
        """The tab widgets the Academy validators query (see academy_context.py)."""
        return self._academy_widgets

    def start_academy_course(self, course_id: str) -> None:
        """The catalog's "Start Course": run it in this workflow."""
        self._academy.start_course(course_id)

    def resume_academy_course(self, course_id: str, attempt: dict) -> None:
        """The catalog's "Resume Course" for the latest attempt."""
        self._academy.resume_from_catalog(course_id, attempt)

    def on_academy_pause_requested(self) -> None:
        """The course bubble's ⏸ Pause."""
        self._academy.pause()

    def export_workflow(self) -> dict:
        """Serialize the workspace for saving to disk."""
        pm = self.services.document.project_manager()
        project_dir = pm.project_dir if pm else None
        return self.services.workflow_service.export_workflow(project_dir=project_dir)

    def load_workflow(
        self, payload: dict, filename: str | None = None, metadata: dict | None = None
    ) -> None:
        """Restore the workspace from a saved file (see services/workflow_loader.py)."""
        self._loader.load(payload, filename, metadata)

    # ── Internal helpers ──────────────────────────────────────────────

    def _refresh_all(self) -> None:
        if self._refresher is not None:
            self._refresher.refresh_all()


def _show_footer_message(footer: Any, message: str, _data: Any) -> None:
    footer.show_message(message)
