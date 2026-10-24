"""Flow cytometry workspace — the root panel injected by Karcytics.

This is the main entry point UI class.  It sets up the workspace
layout (toolbar ribbon, left sidebar, center canvas, right properties)
and exposes the Karcytics-required interface: signals, export_workflow,
load_workflow, and undo/redo (backed by ``analysis.store.FlowStore``).

It also instantiates and wires the ``GateController`` and
``GatePropagator`` which coordinate gate lifecycle, statistics
computation, and cross-sample gate propagation.

This file is intentionally thin — all complex widgets live in their
own modules under ``ui/widgets/``, ``ui/graph/``, and ``ui/ribbons/``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from karcytics_sdk.plugin import CentralEventBus, PluginBase, PluginDaemon, get_logger
from karcytics_sdk.plugin.dialogs import show_error, show_warning
from karcytics_sdk.plugin.runtime_services import (
    KarcyticsEvent,
    event_bus,
)
from karcytics_sdk.plugin.runtime_services import (
    tutorial_manager as global_tutorial_manager,
)
from karcytics_sdk.plugin.theme_fallback import Colors, Fonts, theme_manager
from karcytics_sdk.plugin.workflow import WorkflowContext
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QInputDialog,
    QMessageBox,
    QSizePolicy,
    QWidget,
)

from karcytics_plugins.flow_cytometry.analysis import events
from karcytics_plugins.flow_cytometry.analysis.compensation import extract_spill_from_fcs
from karcytics_plugins.flow_cytometry.analysis.derived import sync_experiment
from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.main_tabs import MainTab
from karcytics_plugins.flow_cytometry.ui.academy_context import AcademyContext
from karcytics_plugins.flow_cytometry.ui.composition_root import build_services

from ..analysis.workspace_document import apply_workspace

if TYPE_CHECKING:
    from .controllers.gating_controller import GatingController

logger = get_logger(__name__, "flow_cytometry")


# Each tab's centre view and ribbon (None: no ribbon), as panel attribute names.
_TAB_VIEWS: dict[MainTab, tuple[str, str | None]] = {
    MainTab.WORKSPACE: ("_graph_manager", "_workspace_ribbon"),
    MainTab.GATING: ("_graph_manager", "_gating_ribbon"),
    MainTab.COMPENSATION: ("_compensation_view", None),
    MainTab.PIPELINE: ("_node_canvas", "_pipeline_ribbon"),
    MainTab.SPECTRAL: ("_spectral_viewer", None),
    MainTab.POPULATION_ANALYSIS: ("_population_analysis_viewer", None),
    MainTab.SAMPLE_LENS: ("_sample_lens", None),
    MainTab.STATISTICS: ("_statistics_explorer", None),
    MainTab.COMPARISONS: ("_comparisons_viewer", None),
}


class FlowCytometryPanel(PluginBase):
    """Root widget for the Flow Cytometry workspace.

    Injected by Karcytics's ``ModuleManager`` as the central workspace
    widget.  Provides the full Karcytics plugin interface.

    Layout::

        ┌────────────────────────────────────────────────────┐
        │  Tab Bar: Workspace | Gating | Compensation | ...  │
        │  ┌──────────────────────────────────────────────┐  │
        │  │            Toolbar Ribbon (stacked)          │  │
        │  └──────────────────────────────────────────────┘  │
        ├───────────┬────────────────────────┬───────────────┤
        │ Groups    │                        │ Properties &  │
        │ Panel     │   Graph Canvas Area    │ Statistics    │
        │───────────│   (tabbed graphs)      │               │
        │ Sample    │                        │               │
        │ Tree      │                        │               │
        └───────────┴────────────────────────┴───────────────┘

    Signals:
        state_changed:  Emitted on any structural edit (Karcytics hooks
                        this to ``HistoryManager`` for undo/redo).
        status_message: Piped to the core status bar.
        results_ready:  Emitted when analysis results are available.
    """

    # Dynamically injected UI components from WorkspaceBuilder
    _tab_bar: Any
    _btn_smart_save: Any
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
    _subscriptions: list[Any]

    # ── Karcytics-required signals ───────────────────────────────────────
    # state_changed and status_message are now provided by PluginBase
    results_ready = Signal(object)

    # ── Ready Gate protocol (Proposal A) ──────────────────────────
    # panel_ready: heavy widgets built — PluginLoaderManager updates loader message.
    # data_ready:  data loaded + graphs rendered — PluginLoaderManager cross-fades.
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
        self._gating: GatingController | None = None  # MainPanelController.wire, Phase 2
        # Startup: a workflow PluginLoaderManager hands over before Phase 2 finishes.
        self._deferred_workflow_payload: dict[str, Any] | None = None
        self._deferred_workflow_filename: str | None = None
        self._deferred_workflow_metadata: dict[str, Any] | None = None
        self._data_ready_emitted = False
        self._awaiting_data_ready = False
        self._themed_palette: Any = None
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

        # Numba JIT warm-up waits for Phase 2's heavy widgets to finish
        # building — see _start_numba_warmup for why starting it any earlier
        # is unsafe, not just slow.
        self.panel_ready.connect(self._start_numba_warmup)

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

        self._academy = AcademyWorkflowController(self)

    def _setup_footer_events(self) -> None:
        """Subscribe to events to update the footer message."""

        def update_footer(msg: str) -> None:
            if hasattr(self, "_footer"):
                self._footer.show_message(msg)

        CentralEventBus.subscribe(events.SAMPLE_LOADED, lambda _: update_footer("Samples loaded."))
        CentralEventBus.subscribe(events.GATE_CREATED, lambda _: update_footer("Gate created."))
        CentralEventBus.subscribe(events.GATES_CREATED, lambda _: update_footer("Gates created."))
        CentralEventBus.subscribe(events.GATE_DELETED, lambda _: update_footer("Gate deleted."))
        CentralEventBus.subscribe(
            events.UMAP_COMPLETED, lambda _: update_footer("UMAP computation complete.")
        )
        CentralEventBus.subscribe(
            events.COMPENSATION_APPLIED, lambda _: update_footer("Compensation applied.")
        )
        CentralEventBus.subscribe(
            events.STATS_COMPUTED, lambda _: update_footer("Statistics updated.")
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
        if hasattr(self, "_btn_smart_save"):
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

    # ── Ready Gate protocol — Phase 2 chained construction ────────────

    def _start_numba_warmup(self) -> None:
        """Pre-compile UMAP's numba kernels on a background thread, once
        Phase 2's own heavy widget construction has already finished.

        This used to run at plugin load time, before Phase 1 even started
        (see the removed call in ``__init__.py``'s ``get_panel_class``) —
        the earliest possible moment, on the theory that "in the background"
        made its timing harmless. It doesn't: numba/llvmlite's JIT
        compilation is Python-level orchestration around LLVM codegen that
        holds the GIL through most of a compile, so any other CPU-bound
        Python thread running at the same time — exactly what Phase 1/2's
        own construction is — contends for it. Reproduced directly: a
        single competing plain-Python thread turned this warmup from ~3s
        into 100s+ with no end in sight. That contention was blocking the
        whole process, including the Qt event loop's own request handling
        (a hung ``exit`` request looks identical to a crash from the
        outside), for however long it took to resolve — on a slow enough
        machine, unbounded. Waiting for ``panel_ready`` means the warmup
        only ever competes with genuinely idle time, not startup.
        """
        # karcytics: allow KS360 - off the Phase 1 path
        from ..analysis.numba_warmup import warmup_numba_jit

        warmup_numba_jit()

    def begin_async_init(self) -> None:
        """Chain Phase 2 widget construction via the Qt event loop (one widget per tick).

        Called by Karcytics's ``PluginLoaderManager`` immediately after the skeleton
        panel is added to the layout.  Each step in ``_phase2_queue`` builds
        exactly one heavy widget then yields via ``QTimer.singleShot(0)`` so the
        GalacticLoader QML animation gets a render frame between each construction.
        """
        # karcytics: allow KS360 - off the Phase 1 path
        from ..ui.builders.workspace_builder import WorkspaceBuilder

        # Best-effort, non-blocking: runs on a background thread and only
        # ever shows a toast if GitHub actually has a newer release.
        self.check_for_updates(
            repo_url="https://github.com/KalaimaranB/Karcytics-flow-cytometry",
            display_name="Flow Cytometry",
        )

        logger.debug("[phase2] begin_async_init: scheduling queue")
        self._phase2_queue = [
            ("graph_manager", lambda: WorkspaceBuilder.build_step_graph_manager(self)),
            ("node_canvas", lambda: WorkspaceBuilder.build_step_node_canvas(self)),
            ("spectral", lambda: WorkspaceBuilder.build_step_spectral(self)),
            ("population", lambda: WorkspaceBuilder.build_step_population(self)),
            ("statistics", lambda: WorkspaceBuilder.build_step_statistics(self)),
            ("comparisons", lambda: WorkspaceBuilder.build_step_comparisons(self)),
            ("compensation", lambda: WorkspaceBuilder.build_step_compensation(self)),
            ("finalize", self._phase2_finalize),
        ]
        QTimer.singleShot(0, self._run_next_phase2_step)

    def _run_next_phase2_step(self) -> None:
        """Pop and execute the next Phase 2 step, then re-schedule if more remain."""
        if not self._phase2_queue:
            return
        name, step = self._phase2_queue.pop(0)
        # TEMPORARY diagnostic instrumentation (see PR discussion) — pinpoints
        # which Phase 2 step a Windows CI daemon subprocess stalls/dies in.
        # logger.info() doesn't surface here: Python's logging module only
        # emits to its default last-resort handler at WARNING+, so a silent
        # daemon's captured stderr looked identical whether Phase 2 was
        # running fine or genuinely stuck. .warning() is the lowest level
        # guaranteed visible without any handler configuration.
        logger.debug("[phase2] step start: %s", name)
        step()
        logger.debug("[phase2] step done: %s", name)
        if self._phase2_queue:
            QTimer.singleShot(0, self._run_next_phase2_step)

    def _phase2_finalize(self) -> None:
        """Complete Phase 2: wire signals, inject deferred workflow, emit panel_ready.

        This is the last step in the Phase 2 queue.  After all six widgets are
        built it:

        1. Wires the center-stack and tab bar.
        2. Runs ``_wire_signals`` and ``_apply_theme_styles``.
        3. If a workflow payload was handed off by ``PluginLoaderManager``,
           calls ``load_workflow`` (which may block briefly on FCS I/O) and
           sets up the ``data_ready`` propagation counter.
        4. Emits ``panel_ready`` — ``PluginLoaderManager`` then switches the
           loader message to "Loading data…" and waits for ``data_ready``.
        """
        # karcytics: allow KS360 - off the Phase 1 path
        from ..ui.builders.workspace_builder import WorkspaceBuilder

        logger.debug("[phase2] finalize: finalize_center_stack")
        WorkspaceBuilder.finalize_center_stack(self)
        logger.debug("[phase2] finalize: _wire_signals")
        self._wire_signals()
        logger.debug("[phase2] finalize: connect_tab_bar")
        WorkspaceBuilder.connect_tab_bar(self)
        logger.debug("[phase2] finalize: _apply_theme_styles")
        self._apply_theme_styles()
        logger.debug("[phase2] finalize: done")

        # ── Deferred workflow injection (set up by PluginLoaderManager) ──────
        _payload = self._deferred_workflow_payload
        self._data_ready_emitted = False

        if _payload is not None:
            self._awaiting_data_ready = True
            self._pending_prop_completions = 0
            # Safety: force crossfade after 45 s (covers Numba JIT cold-start)
            QTimer.singleShot(45_000, self._on_load_watchdog_timeout)

            # Emit panel_ready NOW so the loader immediately shows "Loading data…"
            # before the FCS-loading block hits on the next event-loop tick.
            self.panel_ready.emit()

            # Stash payload and defer load_workflow by one tick so the loader message
            # has a chance to render before we freeze on reload_fcs_data I/O.
            _filename = self._deferred_workflow_filename
            _metadata = self._deferred_workflow_metadata
            self._deferred_workflow_payload = None
            self._deferred_workflow_filename = None
            self._deferred_workflow_metadata = None
            QTimer.singleShot(
                0,
                lambda: self.load_workflow(_payload, filename=_filename, metadata=_metadata),
            )
        else:
            # Empty state: emit panel_ready first, then schedule data_ready on the next frame
            self.panel_ready.emit()
            QTimer.singleShot(0, self._emit_data_ready_once)

    def _emit_data_ready_once(self) -> None:
        """Emit data_ready exactly once regardless of how many callers invoke this."""
        if not self._data_ready_emitted:
            self.logger.info("--> [FlowCytometryPanel] Emitting data_ready signal NOW!")
            self._data_ready_emitted = True
            self.data_ready.emit()

    def _on_load_watchdog_timeout(self) -> None:
        """Fired 45 s after a deferred workflow load starts if it hasn't finished.

        ``_awaiting_data_ready`` is only cleared by ``_on_fcs_done`` once the
        background FCS reload genuinely completes. If it's still set here,
        the reload never finished in time — most likely one sample's FCS
        file stalled the load (see WorkflowService.reload_fcs_data). Rather
        than silently crossfading into a workspace with missing samples and
        gates showing 0 events, warn the user before doing so.
        """
        if self._awaiting_data_ready:
            self.logger.error(
                "FCS reload did not complete within 45s — forcing UI to show anyway. "
                "Samples/gates may display as empty or 0 events until the load finishes."
            )
            show_warning(
                self,
                "Workspace Load Taking Too Long",
                "Sample data is still loading after 45 seconds, so the workspace is "
                "opening before it's finished.\n\n"
                "Some samples or gates may show 0 events until loading completes in "
                "the background. If this persists, check the logs for a stuck FCS file.",
            )
        self._emit_data_ready_once()

    def _wire_signals(self) -> None:
        """Connect internal widget signals to each other and to the Karcytics interface signals."""
        # karcytics: allow KS360 - off the Phase 1 path
        from ..ui.controllers.gating_controller import GatingController, GatingViews

        # karcytics: allow KS360 - off the Phase 1 path
        from ..ui.controllers.main_panel_controller import MainPanelController

        views = GatingViews(
            tab_bar=self._tab_bar,
            graph_manager=self._graph_manager,
            gate_hierarchy=self._gate_hierarchy,
            properties_panel=self._properties_panel,
            sample_list=self._sample_list,
            node_canvas=self._node_canvas,
            gating_ribbon=self._gating_ribbon,
            pipeline_ribbon=self._pipeline_ribbon,
            population_analysis_viewer=self._population_analysis_viewer,
        )
        self._gating = GatingController(
            self.state,
            self.services.gate_coordinator,
            views,
            dialog_parent=self,
            status=self.status_message.emit,
            changed=self.state_changed.emit,
        )
        MainPanelController.wire(self, self._gating)

        try:
            event_bus.subscribe(KarcyticsEvent.ACADEMY_COURSE_COMPLETED, self._on_course_completed)
            event_bus.subscribe(
                KarcyticsEvent.ACADEMY_COURSE_PREPARE_PROJECT,
                self._on_course_prepare_project,
            )
        except NameError:
            pass

    def _on_course_prepare_project(self, course_id: str) -> None:
        """Handles a request to start a course by ensuring a fresh project is used."""
        pm = getattr(self.window(), "project_manager", None)

        course = None
        for courses in global_tutorial_manager.courses_by_module.values():
            for c in courses:
                if c.id == course_id:
                    course = c
                    break

        if pm:
            # If the course has prerequisites, they must be currently loaded!
            if course and course.prerequisite_course_ids:
                workflows = pm.workflows.list_all()
                if not workflows:
                    show_error(
                        self,
                        "Prerequisite Required",
                        "This course continues from the workflow you saved in the course before it.\n\n"
                        "Please open the project where you completed that course, or load the workflow.",
                    )
                    return
                # Check if the loaded workflow's hash matches the prerequisite
                current_wf = self.services.document.filename
                if not current_wf:
                    show_error(
                        self,
                        "No Workflow Loaded",
                        "Please load the workflow you saved at the end of the previous course.",
                    )
                    return

                # We no longer check the strict workflow hash here because it is brittle
                # and fails when the user auto-saves or restarts. Instead, we rely on the
                # state validator each later course opens with.
                pass

            # No prerequisites (e.g. Course 1).
            # We no longer strictly require an empty workspace.
            # Convert an empty project to an academy project
            elif not pm.data.get("is_academy"):
                pm.data["is_academy"] = True
                pm.save()

        global_tutorial_manager.start_course_confirmed(course_id)

    def _apply_theme_styles(self) -> None:
        """Dynamically refresh all UI colors based on the current theme.

        Skips a palette it has already applied: the isolated runtime both
        emits ``theme_changed`` (connected here) and calls this directly, and
        each pass restyles every widget and redraws every plot.
        """
        palette = (
            Colors.BG_DARKEST,
            Colors.BG_DARK,
            Colors.BG_MEDIUM,
            Colors.FG_PRIMARY,
            Colors.FG_SECONDARY,
            Colors.ACCENT_PRIMARY,
            Colors.BORDER,
        )
        if palette == self._themed_palette:
            return
        self._themed_palette = palette
        # 1. Base Panel
        self.setStyleSheet(f"background: {Colors.BG_DARKEST};")

        # 2. Tab Bar
        self._tab_bar.setStyleSheet(
            f"QTabBar {{ background: {Colors.BG_DARKEST}; border: none; }}"
            f"QTabBar::tab {{ background: {Colors.BG_DARK}; color: {Colors.FG_SECONDARY}; padding: 10px 20px; border: none; border-bottom: 2px solid transparent; font-size: {Fonts.SIZE_SMALL}px; font-weight: 600; }}"
            f"QTabBar::tab:selected {{ color: {Colors.ACCENT_PRIMARY}; border-bottom: 2px solid {Colors.ACCENT_PRIMARY}; background: {Colors.BG_DARKEST}; }}"
            f"QTabBar::tab:hover {{ color: {Colors.FG_PRIMARY}; background: {Colors.BG_MEDIUM}; }}"
        )

        # 3. Ribbon Stack
        self._ribbon_stack.setStyleSheet(
            f"background: {Colors.BG_DARK}; border-bottom: 1px solid {Colors.BORDER};"
        )

        # 4. Splitters
        splitter_qss = (
            f"QSplitter {{ border: none; background: transparent; }}"
            f"QSplitter::handle {{ background-color: {Colors.BORDER}; background: {Colors.BORDER}; width: 1px; height: 1px; }}"
            f"QSplitter::handle:horizontal {{ width: 1px; background-color: {Colors.BORDER}; background: {Colors.BORDER}; }}"
            f"QSplitter::handle:vertical {{ height: 1px; background-color: {Colors.BORDER}; background: {Colors.BORDER}; }}"
        )
        if hasattr(self, "_main_splitter"):
            self._main_splitter.setStyleSheet(splitter_qss)
        if hasattr(self, "_left_splitter"):
            self._left_splitter.setStyleSheet(splitter_qss)

        # 5. Sidebars and Separators
        self._left_sidebar.setStyleSheet(f"background: {Colors.BG_DARKEST};")
        if hasattr(self, "_left_sep"):
            self._left_sep.setStyleSheet(f"background: {Colors.BORDER};")

        # 6. Deep recursion for sub-widgets
        for child in self.findChildren(QWidget):
            if hasattr(child, "_apply_theme_styles") and child is not self:
                child._apply_theme_styles()
            elif hasattr(child, "refresh_styles"):
                child.refresh_styles()
            elif child.styleSheet() and child not in [
                self._tab_bar,
                self._ribbon_stack,
                self._main_splitter,
                self._left_splitter,
            ]:
                # Force refresh of any local QSS that might be using old hex codes
                child.setStyleSheet(child.styleSheet())
            child.update()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.logger.info(f"FlowCytometryPanel resized: {self.width()}x{self.height()}")

    def _on_course_completed(self, course_id: str, badge_reward: str) -> None:
        """Handle course completion by clearing tutorial state."""
        # 1. Clear the tutorial manager state so the core popover disappears
        try:
            global_tutorial_manager.active_course = None
            global_tutorial_manager.current_step = None
            global_tutorial_manager._emit_step_changed()
        except (AttributeError, NameError) as e:
            self.logger.error(f"Failed to clear tutorial state: {e}")

    def _refresh_node_canvas(self) -> None:
        if self._gating is not None:
            self._gating.refresh_node_canvas()

    def delete_gate_with_dialog(
        self, sample_id: str, node_id: str, force_silent: bool = False
    ) -> None:
        """Prompt for scope and delete a gate and its children (the Academy calls this)."""
        if self._gating is not None:
            self._gating.delete_gate_with_dialog(sample_id, node_id, force_silent)

    # ── Existing callbacks ────────────────────────────────────────────

    def _on_samples_loaded(self) -> None:
        """Callback when new FCS files are loaded via the ribbon."""
        # ── Auto-extract embedded compensation matrix if none exists ──
        if self.state.data.compensation is None:
            for sample in self.state.data.experiment.samples.values():
                if sample.fcs_data and sample.fcs_data.is_compensated:
                    try:
                        comp_matrix = extract_spill_from_fcs(sample.fcs_data)
                        if comp_matrix:
                            self.state.data.compensation = comp_matrix
                            self.logger.info(
                                f"Auto-Compensation: Extracted and applied embedded compensation matrix from {sample.display_name}."
                            )
                            break
                    except Exception as exc:
                        self.logger.warning("Failed to extract auto-spill matrix: %s", exc)

        self._groups_panel.refresh()
        self._sample_list.refresh()
        self._pipeline_ribbon.refresh_samples()
        self._population_analysis_viewer.refresh_samples()
        self._statistics_explorer.refresh_samples()
        self._comparisons_viewer.refresh_samples()
        self.state_changed.emit()
        self.status_message.emit(f"{len(self.state.data.experiment.samples)} samples loaded.")

    def _on_group_requested(self) -> None:
        """Callback when the user clicks 'Create Group'."""
        # karcytics: allow KS360 - off the Phase 1 path
        from karcytics_plugins.flow_cytometry.analysis.services import experiment_edits

        name, ok = QInputDialog.getText(self, "New Group", "Enter name for the new group:")

        group = experiment_edits.create_group(self.state, name) if ok else None
        if group is not None:
            self._groups_panel.refresh()
            self.status_message.emit(f"Group '{group.name}' created.")

    def _on_derived_params_changed(self, payload: dict) -> None:
        """A derived-parameter definition was created, edited or deleted.

        Columns are already re-synced by DerivedParameterService; open graph
        windows rebuild their own axis lists (GraphWindow subscribes itself).
        Here: refresh every other channel picker/label, and recompute stats
        for samples whose gates sit on an edited parameter.
        """
        self._statistics_explorer.refresh_channels()
        self._comparisons_viewer.refresh_channels()
        self._gate_hierarchy.refresh()
        self._properties_panel.refresh()
        self._refresh_node_canvas()

        if payload.get("action") == "updated":
            param_id = payload.get("param_id", "")
            affected = {
                d.sample_id
                for d in self.services.derived_parameter_service.find_dependents(param_id)
            }
            for sample_id in affected:
                self.services.gate_coordinator.recompute_all_stats(sample_id)

    def _on_compensation_changed(self) -> None:
        """Callback when the compensation matrix changes."""
        self._sample_list.refresh()  # Refresh event counts after comp
        self._gate_hierarchy.refresh()
        self._properties_panel.refresh()
        self.state_changed.emit()
        src = self.state.data.compensation.source if self.state.data.compensation else "none"
        self.status_message.emit(f"Compensation updated (source: {src}).")

    def cleanup(self) -> None:
        """Resource cleanup on plugin close."""
        self.logger.info("Cleaning up Flow Cytometry workspace...")

        # karcytics: allow KS360 - off the Phase 1 path
        from ..ui.controllers.main_panel_controller import MainPanelController

        MainPanelController.unwire(self)
        self._academy.dispose()

        # Unsubscribe from global events to prevent memory leaks and zombie callbacks
        try:
            event_bus.unsubscribe(
                KarcyticsEvent.ACADEMY_COURSE_COMPLETED, self._on_course_completed
            )
            event_bus.unsubscribe(
                KarcyticsEvent.ACADEMY_COURSE_PREPARE_PROJECT,
                self._on_course_prepare_project,
            )
        except (KeyError, ValueError, AttributeError) as e:
            self.logger.warning(f"Failed to unsubscribe from event bus: {e}")

        # 1. Stop background timers/workers via Coordinator
        self.services.gate_coordinator.cleanup()

        if hasattr(self, "_graph_manager"):
            self._graph_manager.cleanup()

        if hasattr(self, "_sample_list"):
            self._sample_list.cleanup()

        # PropertiesPanel registers its own CentralEventBus subscriptions that
        # MainPanelController.unwire() does not touch — clean those up explicitly.
        if hasattr(self, "_properties_panel"):
            self._properties_panel.cleanup()

        if hasattr(self, "_compensation_view"):
            self._compensation_view.cleanup()

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
        if hasattr(self, "_graph_manager"):
            self._graph_manager.cancel_active_drawing()
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

    def _on_state_restored(self, _payload: Any = None) -> None:
        """Undo/redo replaced the model — make every view re-read it by id."""
        self.services.gate_propagator.cancel_pending()
        for sid, sample in self.state.data.experiment.samples.items():
            if sample.fcs_data is not None and sample.gate_tree.children:
                self.services.gate_coordinator.recompute_all_stats(sid)
        if hasattr(self, "_graph_manager"):
            self._graph_manager.reconcile_with_state()
            self._refresh_all()
            self._refresh_node_canvas()

    # ── Saving ────────────────────────────────────────────────────────

    # ── Unsaved-changes prompts ───────────────────────────────────────

    def confirm_close(self) -> bool:
        """Asked by the isolated window before a user closes it.

        Unsaved changes offer Save / Discard / Cancel. Save starts the usual
        (background) save and closes the window once it succeeds; if that
        save is cancelled or fails, the next close asks again.
        """
        if self.services.document.close_after_save:
            if self.services.document.saving:
                return False  # the save-then-close is still writing
            self.services.document.close_after_save = False  # it was cancelled or failed
        academy_decision = self._academy.confirm_close()
        if academy_decision is not None:
            return academy_decision
        if not self.services.store.is_dirty:
            return True

        Btn = QMessageBox.StandardButton
        choice = self.services.document.ask_unsaved_changes(
            "Save changes to this workspace before closing?",
            Btn.Save | Btn.Discard | Btn.Cancel,
        )
        if choice == Btn.Discard:
            return True
        if choice == Btn.Save:
            self.services.document.close_after_save = True
            if self.services.document.filename:
                self._handle_update()
            else:
                self._handle_save()
            if not self.services.document.saving:
                self.services.document.close_after_save = (
                    False  # no save started (dialog cancelled)
                )
        return False

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

    def load_workflow(  # noqa: PLR0912, PLR0915
        self, payload: dict, filename: str | None = None, metadata: dict | None = None
    ) -> None:
        """Restore the workspace from a saved file."""
        if not self.services.document.confirm_discard_before_load():
            self.status_message.emit("Workflow load cancelled — your workspace is unchanged.")
            return

        # Nothing records while the workspace is being replaced; the history
        # restarts from the loaded state once it's complete
        # (_finish_workflow_load). Undo/redo are refused until then.
        self.services.document.begin_load()

        # Support raw data injection for CI/CD smoke tests
        if filename and str(filename).lower().endswith(".fcs"):
            self.logger.info(f"Direct raw FCS injection detected: {filename}")

            def _on_done(results: dict):
                self.logger.info(f"Raw FCS injection complete. Processed {len(results)} samples.")
                # Raw data was never saved as a workflow — starts unsaved.
                self.services.document.finish_load(clean=False)
                self._refresh_all()
                self._emit_data_ready_once()

            def _on_error(err: str):
                self.logger.error(f"FCS injection failed: {err}")
                self.services.document.finish_load(clean=False)
                self._emit_data_ready_once()

            self.services.data_loader_service.load_samples_async(
                [filename],
                self.state,
                on_done=_on_done,
                on_error_cb=_on_error,
            )
            return
        if filename:
            self.services.document.filename = filename
        if metadata:
            self.services.document.metadata = metadata

        pm = self.services.document.project_manager()
        context = None
        if pm and filename:
            try:
                atts = pm.workflows.load_attachments(filename)
                # Filter out any corrupt legacy attachments
                valid_atts = [a for a in atts if "relative_path" in a]
                context = WorkflowContext.from_attachment_dicts(valid_atts, pm.project_dir)
            except (OSError, KeyError, ValueError) as e:
                self.logger.warning(f"Failed to load attachments: {e}")

        def _on_fcs_done(reload_result: dict[str, list[str]] | None = None):
            self.logger.info(
                "--> [_on_fcs_done] Background FCS reload completed! Refreshing workspace..."
            )
            # 1. Recompute stats for samples with gate trees
            for sid, sample in self.state.data.experiment.samples.items():
                if sample.fcs_data is not None and sample.gate_tree is not None:
                    if len(sample.gate_tree.children) > 0:
                        self.services.gate_coordinator.recompute_all_stats(sid)

            # 2. The loaded workspace is the new, saved baseline.
            self.services.document.finish_load(clean=True)
            self._academy.on_workflow_loaded()

            # 3. Refresh sample list, gate hierarchy, and active graph canvas
            self._refresh_all()

            failed = (reload_result or {}).get("failed") or []
            if failed:
                self.logger.error(f"FCS reload failed for {len(failed)} sample(s): {failed}")
                show_warning(
                    self,
                    "Some Samples Failed to Load",
                    f"{len(failed)} sample(s) could not be reloaded and will show 0 events:\n\n"
                    + "\n".join(f"  • {name}" for name in failed)
                    + "\n\nCheck the logs for details (e.g. a moved or corrupt FCS file).",
                )
                self.status_message.emit(
                    f"Workflow loaded with {len(failed)} sample(s) failed to reload."
                )
            else:
                self.status_message.emit("Workflow loaded successfully.")

            # 3. Workspace state and canvas paint events ready — emit data_ready
            if self._awaiting_data_ready:
                self._awaiting_data_ready = False
                self.logger.info("--> [_on_fcs_done] Scheduling data_ready.emit in 300ms...")
                QTimer.singleShot(300, self._emit_data_ready_once)
            else:
                self.logger.info("--> [_on_fcs_done] Emitting data_ready immediately.")
                self._emit_data_ready_once()

        project_dir = pm.project_dir if pm else None
        if not self.services.workflow_service.load_workflow(
            payload, context=context, project_dir=project_dir, on_complete=_on_fcs_done
        ):
            # Whatever was partially replaced is unsaved, not a clean workflow.
            self.services.document.finish_load(clean=False)
            # Try to grab the last exception if we stored it
            error_msg = self.services.workflow_service.last_error
            show_error(self, "Load Error", f"Failed to restore workflow. {error_msg}")

    # ── Internal helpers ──────────────────────────────────────────────

    def _refresh_all(self) -> None:
        """Rebuild all UI widgets from the current state."""
        self.logger.info("MainPanel: Performing full UI refresh...")

        # 1. Refresh data-driven widgets first
        self._groups_panel.refresh()
        self._sample_list.refresh()
        self._pipeline_ribbon.refresh_samples()
        self._population_analysis_viewer.refresh_samples()
        self._statistics_explorer.refresh_samples()
        self._comparisons_viewer.refresh_samples()

        # 2. Sync the active sample context
        sid = self.state.view.current_sample_id

        # If no active sample is selected but samples exist, auto-select the first one
        if not sid and self.state.data.experiment.samples:
            sid = list(self.state.data.experiment.samples.keys())[0]
            self.state.view.current_sample_id = sid

        if sid:
            self.logger.info(f"MainPanel: Restoring active sample: {sid}")
            self._sample_list.blockSignals(True)
            self._sample_list.select_sample(sid)
            self._sample_list.blockSignals(False)
            self._gate_hierarchy.set_active_sample(sid)

            # Ensure the main graph is loaded for this sample if the canvas is empty
            if self._graph_manager._tabs.count() == 0:
                self._graph_manager.open_graph_for_sample(sid, self.state.view.current_gate_id)
        else:
            self._gate_hierarchy._show_empty(True)
            self._sample_list.blockSignals(True)
            self._sample_list.select_sample(None)
            self._sample_list.blockSignals(False)

        # 3. Restore gate selection
        if self.state.view.current_gate_id:
            self.logger.info(
                f"MainPanel: Restoring gate selection: {self.state.view.current_gate_id}"
            )
            if self._gating is not None:
                self._gating.select_population(self.state.view.current_gate_id)

        # 4. Final refresh for properties and graph
        self._properties_panel.refresh()
        self._graph_manager.refresh()

        self.logger.info("MainPanel: Full UI refresh complete.")

    def _sample_name(self, sample_id: str) -> str:
        """Get a sample's display name by ID."""
        sample = self.state.data.experiment.samples.get(sample_id)
        return sample.display_name if sample else sample_id
