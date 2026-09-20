"""Flow cytometry workspace — the root panel injected by Karcytics.

This is the main entry point UI class.  It sets up the workspace
layout (toolbar ribbon, left sidebar, center canvas, right properties)
and exposes the Karcytics-required interface: signals, export_state,
load_state, export_workflow, load_workflow.

It also instantiates and wires the ``GateController`` and
``GatePropagator`` which coordinate gate lifecycle, statistics
computation, and cross-sample gate propagation.

This file is intentionally thin — all complex widgets live in their
own modules under ``ui/widgets/``, ``ui/graph/``, and ``ui/ribbons/``.
"""

from __future__ import annotations

from typing import Any

from karcytics_sdk.plugin import PluginBase, get_logger
from karcytics_sdk.plugin.runtime_services import (
    KarcyticsEvent,
    event_bus,
)
from karcytics_sdk.plugin.runtime_services import (
    tutorial_manager as global_tutorial_manager,
)
from karcytics_sdk.plugin.theme_fallback import Colors, Fonts, theme_manager
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QMessageBox,
    QSizePolicy,
    QWidget,
)

from karcytics_plugins.flow_cytometry.analysis.state import FlowState

logger = get_logger(__name__, "flow_cytometry")


def _collect_descendants_into(node, result: set) -> None:
    """Recursively collect node_ids of *node* and all its descendants."""
    result.add(node.node_id)
    for child in node.children:
        _collect_descendants_into(child, result)


class FlowCytometryPanel(PluginBase):
    """Root widget for the Flow Cytometry workspace.

    Injected by Karcytics's ``ModuleManager`` as the central workspace
    widget.  Provides the full Karcytics plugin interface.

    Layout::

        ┌────────────────────────────────────────────────────┐
        │  Tab Bar: Workspace | Compensation | Gating | ...  │
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
    _subscriptions: list[Any]

    # ── Karcytics-required signals ───────────────────────────────────────
    # state_changed and status_message are now provided by PluginBase
    results_ready = pyqtSignal(object)

    # ── Ready Gate protocol (Proposal A) ──────────────────────────
    # panel_ready: heavy widgets built — PluginLoaderManager updates loader message.
    # data_ready:  data loaded + graphs rendered — PluginLoaderManager cross-fades.
    panel_ready = pyqtSignal()
    data_ready = pyqtSignal()
    gate_added_to_tree = pyqtSignal()

    def __init__(self, plugin_id: str = "flow_cytometry", parent=None) -> None:
        logger.warning("[phase1] FlowCytometryPanel.__init__: super().__init__ start")
        super().__init__(plugin_id, parent)
        logger.warning("[phase1] FlowCytometryPanel.__init__: super().__init__ done")

        # Academy InteractionSteps (course1/course2 gate steps) target this
        # panel by objectName to wire up gate_added_to_tree — without this,
        # AcademyStepDriver's findChildren lookup finds nothing and those
        # steps never auto-advance.
        self.setObjectName("MainPanel")

        # ── State ─────────────────────────────────────────────────────
        self.state = FlowState()
        self._propagation_active = True  # matches PropagationToggle default (ON)

        # ── Services ──────────────────────────────────────────────────
        logger.warning("[phase1] FlowCytometryPanel.__init__: _setup_services start")
        self._setup_services()
        logger.warning("[phase1] FlowCytometryPanel.__init__: _setup_services done")

        # ── Size policy ───────────────────────────────────────────────
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # ── Build UI skeleton (Phase 1) ───────────────────────────────
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"background: {Colors.BG_DARKEST};")
        logger.warning("[phase1] FlowCytometryPanel.__init__: _setup_ui start")
        self._setup_ui()
        logger.warning("[phase1] FlowCytometryPanel.__init__: _setup_ui done")
        self._setup_footer_events()
        logger.warning("[phase1] FlowCytometryPanel.__init__: _setup_footer_events done")

        # Piped to the core status bar (see workspace_builder.connect_tab_bar
        # for the "Ready" message once Phase 2 completes).
        self.status_message.emit("Loading workspace…")

        # Numba JIT warm-up waits for Phase 2's heavy widgets to finish
        # building — see _start_numba_warmup for why starting it any earlier
        # is unsafe, not just slow.
        self.panel_ready.connect(self._start_numba_warmup)

    def _setup_services(self) -> None:
        """Initialize and wire all core analysis and UI services."""
        logger.warning("[phase1] _setup_services: importing composition_root")
        from .composition_root import ServiceFactory

        self._factory = ServiceFactory(self.state, self)
        logger.warning("[phase1] _setup_services: calling ServiceFactory.build_all()")
        self._factory.build_all()
        logger.warning("[phase1] _setup_services: ServiceFactory.build_all() done")

        self._gate_coordinator = self._factory.get("gate_coordinator")
        self._gate_controller = self._gate_coordinator
        self._gate_propagator = self._factory.get("gate_propagator")
        self._workflow_service = self._factory.get("workflow_service")
        self._umap_service = self._factory.get("umap_service")
        self._fluor_service = self._factory.get("fluor_service")
        self._workspace_io_handler = self._factory.get("workspace_io_handler")

        self._is_dirty = False

    def _setup_footer_events(self) -> None:
        """Subscribe to events to update the footer message."""
        from karcytics_sdk.plugin import CentralEventBus

        from karcytics_plugins.flow_cytometry.analysis import events

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
            from karcytics_sdk.plugin import PluginDaemon

            PluginDaemon.stop_instance("flow_cytometry")
        except Exception:
            pass
        super().closeEvent(event)

    def shutdown(self) -> None:
        """Module shutdown hook."""
        try:
            from karcytics_sdk.plugin import PluginDaemon

            PluginDaemon.stop_instance("flow_cytometry")
        except Exception:
            pass

    # ── State Tracking ────────────────────────────────────────────────

    def set_dirty(self, dirty: bool) -> None:
        """Mark the workflow as containing unsaved changes."""
        self._is_dirty = dirty
        if hasattr(self, "_btn_smart_save"):
            has_wf = bool(
                getattr(self, "_current_workflow_filename", None)
                or getattr(self, "_current_workflow_path", None)
            )
            self._btn_smart_save.set_workflow_active(has_wf)
            self._btn_smart_save.set_dirty(dirty)

    # ── UI Construction ───────────────────────────────────────────────

    def _on_tab_changed(self, index: int) -> None:
        """Handle main tab changes to update ribbon and central view."""
        self.state.view.active_main_tab_index = index
        self._ribbon_stack.setCurrentIndex(index)

        # 3=Pipeline, 4=Statistics, 5=Spectral, 6=Population Analysis
        if index == 3:  # noqa: PLR2004
            self._center_stack.setCurrentIndex(1)  # NodeCanvas
            self._left_sidebar.hide()
            self._properties_panel.hide()
            self._ribbon_stack.show()

            # Auto-select the currently active sample if possible
            if self.state.view.current_sample_id:
                idx = self._pipeline_ribbon._sample_combo.findData(
                    self.state.view.current_sample_id
                )
                if idx >= 0 and self._pipeline_ribbon._sample_combo.currentIndex() != idx:
                    # This will trigger _on_combo_changed which calls set_sample implicitly
                    self._pipeline_ribbon._sample_combo.setCurrentIndex(idx)
                else:
                    self._refresh_node_canvas()
            else:
                self._refresh_node_canvas()
        elif index == 4:  # noqa: PLR2004
            self._center_stack.setCurrentIndex(4)  # StatisticsExplorer
            self._left_sidebar.hide()
            self._properties_panel.hide()
            self._ribbon_stack.hide()
            self._statistics_explorer.refresh_samples()
        elif index == 5:  # noqa: PLR2004
            self._center_stack.setCurrentIndex(2)  # SpectralViewer
            self._left_sidebar.hide()
            self._properties_panel.hide()
            self._ribbon_stack.hide()
        elif index == 6:  # noqa: PLR2004
            self._center_stack.setCurrentIndex(3)  # PopulationAnalysisViewer
            self._left_sidebar.hide()
            self._properties_panel.hide()
            self._ribbon_stack.hide()
            self._population_analysis_viewer.refresh_samples()
        elif index == 7:  # noqa: PLR2004
            self._center_stack.setCurrentIndex(5)  # ComparisonsViewer
            self._left_sidebar.hide()
            self._properties_panel.hide()
            self._ribbon_stack.hide()
            self._comparisons_viewer.refresh_samples()
        else:
            self._center_stack.setCurrentIndex(0)  # GraphManager
            self._left_sidebar.show()
            self._properties_panel.show()
            self._ribbon_stack.show()

    def _get_project_manager(self):
        return self._workspace_io_handler._get_project_manager()

    def _handle_save(self) -> None:
        """Handle save workspace request."""
        self._workspace_io_handler.handle_save()

    def _handle_update(self) -> None:
        """Overwrite the currently loaded workflow using Karcytics SDK services."""
        self._workspace_io_handler.handle_update()

    def _handle_load(self) -> None:
        """Handle load workspace request."""
        self._workspace_io_handler.handle_load()

    def _setup_ui(self) -> None:
        """Build the workspace skeleton (Phase 1).

        Only the lightweight structural scaffold is created here: tab bar,
        ribbons, sidebar, and an empty center-stack placeholder. Heavy analysis
        views (GraphManager, NodeCanvas, etc.) are built in ``_phase2_build``
        after the GalacticLoader has signalled its warp peak.
        """
        logger.warning("[phase1] _setup_ui: importing workspace_builder")
        from ..ui.builders.workspace_builder import WorkspaceBuilder

        logger.warning("[phase1] _setup_ui: workspace_builder imported, calling build_skeleton()")
        WorkspaceBuilder.build_skeleton(self)
        logger.warning("[phase1] _setup_ui: build_skeleton() done")

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
        from ..analysis.numba_warmup import warmup_numba_jit

        warmup_numba_jit()

    def begin_async_init(self) -> None:
        """Chain Phase 2 widget construction via the Qt event loop (one widget per tick).

        Called by Karcytics's ``PluginLoaderManager`` immediately after the skeleton
        panel is added to the layout.  Each step in ``_phase2_queue`` builds
        exactly one heavy widget then yields via ``QTimer.singleShot(0)`` so the
        GalacticLoader QML animation gets a render frame between each construction.
        """
        from ..ui.builders.workspace_builder import WorkspaceBuilder

        logger.warning("[phase2] begin_async_init: scheduling queue")
        self._phase2_queue = [
            ("graph_manager", lambda: WorkspaceBuilder.build_step_graph_manager(self)),
            ("node_canvas", lambda: WorkspaceBuilder.build_step_node_canvas(self)),
            ("spectral", lambda: WorkspaceBuilder.build_step_spectral(self)),
            ("population", lambda: WorkspaceBuilder.build_step_population(self)),
            ("statistics", lambda: WorkspaceBuilder.build_step_statistics(self)),
            ("comparisons", lambda: WorkspaceBuilder.build_step_comparisons(self)),
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
        logger.warning("[phase2] step start: %s", name)
        step()
        logger.warning("[phase2] step done: %s", name)
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
        from ..ui.builders.workspace_builder import WorkspaceBuilder

        logger.warning("[phase2] finalize: finalize_center_stack")
        WorkspaceBuilder.finalize_center_stack(self)
        logger.warning("[phase2] finalize: _wire_signals")
        self._wire_signals()
        logger.warning("[phase2] finalize: connect_tab_bar")
        WorkspaceBuilder.connect_tab_bar(self)
        logger.warning("[phase2] finalize: _apply_theme_styles")
        self._apply_theme_styles()
        logger.warning("[phase2] finalize: done")

        # ── Deferred workflow injection (set up by PluginLoaderManager) ──────
        _has_deferred = (
            hasattr(self, "_deferred_workflow_payload")
            and self._deferred_workflow_payload is not None  # type: ignore
        )

        self._data_ready_emitted = False

        if _has_deferred:
            self._awaiting_data_ready = True
            self._pending_prop_completions = 0
            # Safety: force crossfade after 45 s (covers Numba JIT cold-start)
            QTimer.singleShot(45_000, self._on_load_watchdog_timeout)

            # Emit panel_ready NOW so the loader immediately shows "Loading data…"
            # before the FCS-loading block hits on the next event-loop tick.
            self.panel_ready.emit()

            # Stash payload and defer load_workflow by one tick so the loader message
            # has a chance to render before we freeze on reload_fcs_data I/O.
            _payload = self._deferred_workflow_payload  # type: ignore
            _filename = getattr(self, "_deferred_workflow_filename", None)
            _metadata = getattr(self, "_deferred_workflow_metadata", None)
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
        if not getattr(self, "_data_ready_emitted", False):
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
        if getattr(self, "_awaiting_data_ready", False):
            self.logger.error(
                "FCS reload did not complete within 45s — forcing UI to show anyway. "
                "Samples/gates may display as empty or 0 events until the load finishes."
            )
            QMessageBox.warning(
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
        from ..ui.controllers.main_panel_controller import MainPanelController

        MainPanelController.wire(self)

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
        from karcytics_sdk.plugin.runtime_services import (
            tutorial_manager as global_tutorial_manager,
        )

        course = None
        for courses in global_tutorial_manager.courses_by_module.values():
            for c in courses:
                if c.id == course_id:
                    course = c
                    break

        if pm:
            from karcytics_sdk.plugin.dialogs import show_error

            # If the course has prerequisites, they must be currently loaded!
            if course and course.prerequisite_course_ids:
                workflows = pm.workflows.list_all()
                if not workflows:
                    show_error(
                        self,
                        "Prerequisite Required",
                        "This course requires you to load the saved workflow from Course 1.\n\n"
                        "Please open the project where you completed Course 1, or load the workflow.",
                    )
                    return
                # Check if the loaded workflow's hash matches the prerequisite
                current_wf = getattr(self, "_current_workflow_filename", None)
                if not current_wf:
                    show_error(
                        self,
                        "No Workflow Loaded",
                        "Please load your completed Course 1 workflow.",
                    )
                    return

                # We no longer check the strict workflow hash here because it is brittle
                # and fails when the user auto-saves or restarts. Instead, we rely on the
                # robust Course1StateValidator at the start of Course 2.
                pass

            # No prerequisites (e.g. Course 1).
            # We no longer strictly require an empty workspace.
            # Convert an empty project to an academy project
            elif not pm.data.get("is_academy"):
                pm.data["is_academy"] = True
                pm.save()

        global_tutorial_manager.start_course_confirmed(course_id)

    def _apply_theme_styles(self) -> None:
        """Dynamically refresh all UI colors based on the current theme."""
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

    def _on_course_overlay_dismissed(self) -> None:
        """User dismissed the completion overlay."""
        self.status_message.emit("Course complete. Workspace restored.")

    def _refresh_node_canvas(self, *args, **kwargs) -> None:
        """Helper to refresh the node canvas if it's currently visible.

        Guards against being called before Phase 2 completes: the CentralEventBus
        subscriptions are set up in ``_wire_signals`` (Phase 2), but if an event
        fires in the brief window between Phase 1 and Phase 2 the attribute won't
        exist yet.  The guard makes this a safe no-op in that case.
        """
        if not hasattr(self, "_node_canvas"):
            return  # Phase 2 not yet complete
        if self._tab_bar.currentIndex() == 3:  # Pipeline tab active  # noqa: PLR2004
            sid = self._pipeline_ribbon._sample_combo.currentData()
            if sid:
                self._node_canvas.set_sample(sid)

    # ── Gate lifecycle callbacks ──────────────────────────────────────

    def _on_gate_drawn(self, gate, sample_id: str, parent_node_id) -> None:
        """Handle a gate drawn on the canvas → add to model."""
        # Get a placeholder name for this gate (e.g., "Gate 1")
        default_name = self._gate_coordinator._mutation_service.generate_unique_name(sample_id)

        if type(gate).__name__ == "QuadrantGate":
            # QuadrantGate.create_nodes() always names its 4 leaves "Q1"-"Q4"
            # and discards whatever name is passed here — prompting for a
            # single name is meaningless (one gate becomes four), and a user
            # who canceled that dialog would silently lose the whole gate.
            # Skip the prompt; leaves get renamed individually afterward.
            name = default_name
        else:
            from PyQt6.QtWidgets import QInputDialog

            # Prompt the user for the name, pausing the event loop here
            typed_name, ok = QInputDialog.getText(
                self, "New Gate", "Enter name for the new gate:", text=default_name
            )

            if not ok or not typed_name.strip():
                # User canceled (Escape/Cancel) or entered a blank name; abort
                # creation but leave the drawing tool exactly as it was — do
                # NOT reset to "select" here. Escape is QInputDialog's own
                # cancel shortcut, so a user who backs out of just the naming
                # step (e.g. to redraw the shape) would otherwise have their
                # tool silently deselected with no visual cue. Any further
                # canvas clicks would then be interpreted as gate *selection*
                # instead of drawing, so nothing ever gets created again —
                # which, for an Academy step waiting on a gate being drawn,
                # looks exactly like the tutorial "not recognizing" a
                # perfectly good redraw when the user tries again.
                return
            name = typed_name.strip()

        node_id = self._gate_coordinator.add_gate(
            gate, sample_id, name=name, parent_node_id=parent_node_id
        )
        if node_id:
            # Switch back to select mode after drawing
            self._gating_ribbon.reset_to_select()

            # AUTO-SELECT the new node so properties are shown immediately
            self._on_gate_selected(node_id)

            # Navigate into the new gate automatically so the user can keep gating
            # We defer this via QTimer (150ms) to ensure the double-click event loop finishes
            # processing first. Otherwise, macOS Native Window handler might misinterpret
            # the orphaned double-click event and force the app out of full screen.
            QTimer.singleShot(
                150,
                lambda: self._graph_manager.open_graph_for_sample(sample_id, node_id),
            )

            if self._propagation_active:
                self.status_message.emit("⟳ Propagating gate to other samples…")

    def _on_gate_added(self, sample_id: str, node_id: str) -> None:
        """Gate added to model → refresh tree and canvas overlays."""
        self._refresh_gate_overlays(sample_id)
        self.state_changed.emit()

        # Ensure the new node is selected
        self._on_gate_selected(node_id)

    def _on_gates_added(self, sample_id: str, node_ids: list[str]) -> None:
        """Several gates added in one action (e.g. quadrant gate) → a single
        refresh/selection instead of one per node.
        """
        self._refresh_gate_overlays(sample_id)
        self.state_changed.emit()

        if node_ids:
            self._on_gate_selected(node_ids[0])

    def _on_gate_removed(self, sample_id: str, node_id: str) -> None:
        """Gate removed → refresh tree and canvas."""
        if node_id == self.state.view.current_gate_id:
            self.state.view.current_gate_id = None
            self._properties_panel.refresh()
        self._refresh_gate_overlays(sample_id)
        self.state_changed.emit()

    def _on_gate_stats_updated(self, sample_id: str, node_id: str) -> None:
        """Gate stats changed → update tree badges and properties."""
        self._gate_hierarchy.update_gate_stats(sample_id, node_id)
        # Update properties if this node is selected
        if node_id == self.state.view.current_gate_id:
            self._properties_panel.refresh()
        self._refresh_gate_overlays(sample_id)

    def _on_all_stats_updated(self, sample_id: str) -> None:
        """All stats for a sample updated → bulk refresh."""
        self._sample_list.update_all_sample_stats(sample_id)
        self._gate_hierarchy.update_all_sample_stats(sample_id)

    def _on_propagated_sample_updated(self, sample_id: str, stats: dict, new_tree: object) -> None:
        """A single sample finished propagation → update its tree."""
        self._sample_list.update_all_sample_stats(sample_id)
        self._gate_hierarchy.update_all_sample_stats(sample_id)
        self._refresh_gate_overlays(sample_id)

    def _on_propagation_complete(self, payload: dict | None = None) -> None:
        """All samples finished propagation.

        `payload` (from GatePropagator, see events.PROPAGATION_COMPLETE) carries
        succeeded/failed counts — a chain-broken sample (e.g. missing the
        gated channel) no longer fails silently into a log line only.
        """
        payload = payload or {}
        total = payload.get("total", len(self.state.data.experiment.samples))
        failed = payload.get("failed", 0)
        succeeded = payload.get("succeeded", total)
        if failed:
            self.status_message.emit(
                f"⚠ Gate propagated to {succeeded}/{total} samples ({failed} failed)."
            )
        else:
            self.status_message.emit(f"✓ Gate propagation complete ({total} samples updated).")
        # Refresh the properties panel and preview to show the new propagated gates/stats
        self._properties_panel.refresh()

    def _on_delete_selected_gate(self, force_silent: bool = False) -> None:
        """Delete the gate currently selected in the hierarchy."""
        graph = self._graph_manager.get_active_graph()
        if graph is None:
            return

        node_id = self.state.view.current_gate_id
        if not node_id:
            self.status_message.emit("No gate selected in hierarchy to delete.")
            return

        self.delete_gate_with_dialog(graph.sample_id, node_id, force_silent=force_silent)

    @staticmethod
    def _resolve_target_samples(
        scope: str,
        group_id: str | None,
        sample_id: str,
        experiment,
    ) -> list[str]:
        """Return the list of sample IDs affected by a gate deletion."""
        if scope == "sample":
            return [sample_id]
        if group_id == "all":
            return list(experiment.samples.keys())
        target_group = experiment.groups.get(group_id) if group_id is not None else None
        return target_group.sample_ids if target_group else [sample_id]

    def delete_gate_with_dialog(  # noqa: PLR0915
        self, sample_id: str, node_id: str, force_silent: bool = False
    ) -> None:
        """Prompt the user and delete a gate and its children."""
        sample = self.state.data.experiment.samples.get(sample_id)
        if not sample:
            return

        selected_node = sample.gate_tree.find_node_by_id(node_id)
        if not selected_node or not selected_node.gate:
            self.status_message.emit("Selected node has no gate to delete.")
            return

        scope: str
        group_id: str | None
        if force_silent:
            scope = "group" if getattr(self, "_propagation_active", True) else "sample"
            group_id = getattr(self.state.view, "active_group_filter", "__all__")
            if group_id != "__all__" and sample.group_ids and group_id not in sample.group_ids:
                group_id = sample.group_ids[0]
            elif group_id == "__all__" and not sample.group_ids:
                group_id = "all"
        else:
            # Prepare groups for the dialog
            group_choices = [("all", "All Samples")]
            for gid in sample.group_ids:
                grp = self.state.data.experiment.groups.get(gid)
                if grp:
                    group_choices.append((gid, grp.name))

            from PyQt6.QtWidgets import QDialog

            from .widgets.gate_deletion_dialog import GateDeletionDialog

            dialog = GateDeletionDialog(
                selected_node.name, sample.display_name, group_choices, self
            )
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return

            scope_raw, group_id = dialog.get_deletion_scope()
            scope = scope_raw or "sample"

        physical_gate_id = selected_node.gate.gate_id

        target_samples = self._resolve_target_samples(
            scope, group_id, sample_id, self.state.data.experiment
        )

        deleted_nodes_by_sample: dict[str, set[str]] = {}
        for s_id in target_samples:
            tgt_sample = self.state.data.experiment.samples.get(s_id)
            if tgt_sample:
                nodes = tgt_sample.gate_tree.find_nodes_by_gate(physical_gate_id)
                deleted_ids: set[str] = set()
                for n in nodes:
                    _collect_descendants_into(n, deleted_ids)

                if deleted_ids:
                    deleted_nodes_by_sample[s_id] = deleted_ids

        # If the active graph is viewing one of the deleted nodes,
        # open the parent graph (if any) first.
        active_graph = self._graph_manager.get_active_graph()
        if active_graph and active_graph.sample_id in deleted_nodes_by_sample:
            if active_graph.node_id in deleted_nodes_by_sample[active_graph.sample_id]:
                parent_node_id = None
                if selected_node.parents and not selected_node.parents[0].is_root:
                    parent_node_id = selected_node.parents[0].node_id
                self._graph_manager.open_graph_for_sample(active_graph.sample_id, parent_node_id)

        for s_id in target_samples:
            tgt_sample = self.state.data.experiment.samples.get(s_id)
            if tgt_sample:
                # Delete ALL populations sharing this physical gate in this sample
                nodes = tgt_sample.gate_tree.find_nodes_by_gate(physical_gate_id)
                for n in nodes:
                    self._gate_coordinator.remove_population(s_id, n.node_id)

        if hasattr(self._graph_manager, "close_graphs_for_nodes"):
            self._graph_manager.close_graphs_for_nodes(deleted_nodes_by_sample)

        scope_msg = "this sample" if scope == "sample" else "the group"
        self.status_message.emit(f"Gate deleted for {scope_msg}.")

    def _on_propagation_mode_changed(self, enabled: bool) -> None:
        """Handle AUTO-PROPAGATE toggle flip from GateHierarchy."""
        self._propagation_active = enabled
        # Actually gate the propagation in the model layer
        self._gate_coordinator.set_propagation_enabled(enabled)
        if enabled:
            self.status_message.emit("Auto-propagation ON — gates will propagate on every change.")
        else:
            self.status_message.emit(
                "Auto-propagation OFF — gates stay local until manually applied."
            )

    def _on_copy_gates(self, sample_id: str) -> None:
        """Copy gates from a sample to all others in its group."""
        count = self._gate_coordinator.copy_gates_to_group(sample_id)
        self._gate_hierarchy.refresh()
        self.state_changed.emit()
        self.status_message.emit(f"Gates copied to {count} sample{'s' if count != 1 else ''}.")

    def _on_copy_gates_from_active(self) -> None:
        """Copy gates from the active graph's sample."""
        graph = self._graph_manager.get_active_graph()
        if graph:
            self._on_copy_gates(graph.sample_id)

    def _on_gate_selected_on_canvas(self, gate_id: str | None) -> None:
        """Gate clicked on canvas → update selection state."""
        graph = self._graph_manager.get_active_graph()
        if graph is None:
            return

        if gate_id:
            sample = self.state.data.experiment.samples.get(graph.sample_id)
            if sample:
                # Map gate_id back to a primary node_id
                nodes = sample.gate_tree.find_nodes_by_gate(gate_id)
                if nodes:
                    self._on_gate_selected(nodes[0].node_id)
        else:
            self._on_gate_selected(None)

    def _on_active_graph_changed(self, sample_id: str | None, node_id: str | None) -> None:
        """When the user switches tabs in the GraphManager."""
        self.state.view.current_sample_id = sample_id or None

        if sample_id:
            # Keep the global selected-gate state in sync with whatever tab is actually
            # visible. Without this, navigating via the parent/child breadcrumb buttons
            # (which switch tabs without going through GateSelectionService) leaves
            # current_gate_id pointing at a stale population — so a later legitimate
            # select_gate() call for that same node_id gets silently swallowed by its
            # dedup guard, and GroupPreviewPanel never learns the population changed.
            self._gate_controller.select_gate(sample_id, node_id)
            self._gate_hierarchy.set_active_sample(sample_id)
            self._properties_panel.show_sample_properties(sample_id, node_id)

            self._sample_list.blockSignals(True)
            self._sample_list.select_sample(sample_id)
            self._sample_list.blockSignals(False)
        else:
            self._gate_hierarchy._show_empty(True)
            self._properties_panel._show_empty()
            self._sample_list.select_sample(None)

    def _on_sample_selection_changed(self, sample_id: str) -> None:
        """Sample selection changed in list."""
        self._gate_hierarchy.set_active_sample(sample_id)

    def _on_gate_selection_changed(self, node_id: str) -> None:
        """Gate selection changed in tree → update canvas and properties."""
        self._on_gate_selected(node_id)

    def _on_gate_double_clicked(self, node_id: str) -> None:  # noqa: PLR0912, PLR0915
        """Gate double clicked → open new graph viewing this population."""
        sample_id = None
        if self._tab_bar.currentIndex() == 3:  # noqa: PLR2004
            sample_id = self._node_canvas.current_sample_id

        if not sample_id:
            sample_id = self._gate_hierarchy._active_sample_id or self.state.view.current_sample_id

        if sample_id:
            sample = self.state.data.experiment.samples.get(sample_id)
            if sample and sample.gate_tree:
                node = sample.gate_tree.find_node_by_id(node_id)
                if node and getattr(node, "is_umap_parent", False):
                    # Find the run in history
                    run_idx = None
                    target_gate_id = None
                    for k, runs in self.state.data.umap_results.items():
                        if k.startswith(f"{sample_id}::"):
                            for i, r in enumerate(runs):
                                if r.get("exported_node_id") == node.node_id:
                                    run_idx = i
                                    target_gate_id = k.split("::")[1]
                                    if target_gate_id == "root":
                                        target_gate_id = None
                                    break
                            if run_idx is not None:
                                break

                    if run_idx is not None:
                        self._tab_bar.setCurrentIndex(6)  # Population Analysis
                        viewer = self._population_analysis_viewer

                        viewer._sample_combo.blockSignals(True)
                        idx = viewer._sample_combo.findData(sample_id)
                        if idx >= 0:
                            viewer._sample_combo.setCurrentIndex(idx)
                        viewer._sample_combo.blockSignals(False)

                        viewer._refresh_gates()

                        viewer._gate_combo.blockSignals(True)
                        idx = viewer._gate_combo.findData(target_gate_id)
                        if idx >= 0:
                            viewer._gate_combo.setCurrentIndex(idx)
                        viewer._gate_combo.blockSignals(False)

                        viewer.refresh_history()

                        viewer._history_combo.blockSignals(True)
                        idx = viewer._history_combo.findData(run_idx)
                        if idx >= 0:
                            viewer._history_combo.setCurrentIndex(idx)
                        viewer._history_combo.blockSignals(False)

                        if idx >= 0:
                            viewer._on_history_changed(idx)
                    return

            # If we are in Pipeline view, switch back to Gating view automatically
            if self._tab_bar.currentIndex() == 3:  # noqa: PLR2004
                self._tab_bar.setCurrentIndex(2)
                if self._gate_hierarchy._active_sample_id != sample_id:
                    self.state.view.current_sample_id = sample_id
                    self._gate_hierarchy.set_active_sample(sample_id)

            self._graph_manager.open_graph_for_sample(sample_id, node_id)

            # Also select the gate so the properties panel and group preview
            # update their context to this node. Without this, GroupPreviewPanel
            # never receives the correct node_id and renders thumbnails with no gates.
            self._gate_controller.select_gate(sample_id, node_id)

    def _on_gate_selected(self, node_id: str | None) -> None:
        """Central selection handler for populations across all UI components."""
        sample_id = None
        if self._tab_bar.currentIndex() == 3:  # noqa: PLR2004
            sample_id = self._node_canvas.current_sample_id

        if not sample_id:
            graph = self._graph_manager.get_active_graph()
            sample_id = graph.sample_id if graph else self._gate_hierarchy._active_sample_id

        if sample_id:
            self._gate_controller.select_gate(sample_id, node_id)

    def _on_gate_selected_from_controller(self, sample_id: str, node_id: str | None) -> None:
        """Global selection update from the model layer."""
        # Sync tree selection
        self._gate_hierarchy.refresh()

        # Update properties panel
        self._properties_panel.show_sample_properties(sample_id, node_id)

        node_name = "None"
        if sample_id and node_id:
            sample = self.state.data.experiment.samples.get(sample_id)
            if sample and sample.gate_tree:
                node = sample.gate_tree.find_node_by_id(node_id)
                if node:
                    node_name = node.name or node_id

        self.status_message.emit(f"Population selected: {node_name}")

    # ── Helper: refresh gate overlays on canvas ───────────────────────

    def _refresh_gate_overlays(self, sample_id: str) -> None:
        """Refresh gate overlays on all open graphs for a sample."""
        # Determine which parent gate each open graph is viewing
        for graph in self._graph_manager._graphs.values():
            if graph.sample_id != sample_id:
                continue

            gates, nodes = self._gate_coordinator.get_gates_for_display(sample_id, graph.node_id)
            graph.refresh_gates(gates, nodes)

    # ── Existing callbacks ────────────────────────────────────────────

    def _on_samples_loaded(self) -> None:
        """Callback when new FCS files are loaded via the ribbon."""
        # ── Auto-extract embedded compensation matrix if none exists ──
        if self.state.data.compensation is None:
            from karcytics_plugins.flow_cytometry.analysis.compensation import (
                extract_spill_from_fcs,
            )

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
        import uuid

        from PyQt6.QtWidgets import QInputDialog

        from karcytics_plugins.flow_cytometry.analysis.experiment import Group, GroupRole

        name, ok = QInputDialog.getText(self, "New Group", "Enter name for the new group:")

        if ok and name.strip():
            new_group = Group(group_id=str(uuid.uuid4()), name=name.strip(), role=GroupRole.CUSTOM)
            self.state.data.experiment.add_group(new_group)
            self._groups_panel.refresh()
            self.state_changed.emit()
            self.status_message.emit(f"Group '{name.strip()}' created.")

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

        from ..ui.controllers.main_panel_controller import MainPanelController

        MainPanelController.unwire(self)

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

        # Cancel the startup stats subscription if it was never consumed
        if hasattr(self, "_startup_stats_cb"):
            try:
                from karcytics_sdk.plugin import CentralEventBus as _CentralEventBus

                _CentralEventBus.unsubscribe("flow.gate.all_stats_updated", self._startup_stats_cb)
            except Exception:
                pass
            del self._startup_stats_cb

        # 1. Stop background timers/workers via Coordinator
        if hasattr(self, "_gate_coordinator"):
            self._gate_coordinator.cleanup()

        if hasattr(self, "_graph_manager"):
            self._graph_manager.cleanup()

        if hasattr(self, "_sample_list"):
            self._sample_list.cleanup()

        # PropertiesPanel registers its own CentralEventBus subscriptions that
        # MainPanelController.unwire() does not touch — clean those up explicitly.
        if hasattr(self, "_properties_panel"):
            self._properties_panel.cleanup()

        if hasattr(self, "_umap_service"):
            self._umap_service.cancel()

        super().cleanup()

    def get_state(self) -> FlowState:
        """Package the workspace state for the SDK."""
        return self.state

    def push_state(self) -> None:
        """Override SDK push_state to exclude UMAP results from undo history.

        PluginBase.push_state() calls get_state().to_dict() which includes all
        UMAP embedding arrays (100k+ floats each).  We strip them here so the
        in-memory undo stack stays lightweight.  UMAP persistence is handled
        separately by the workflow save/attachment pipeline.
        """
        state_dict = self.state.to_dict()
        if "data" in state_dict and "umap_results" in state_dict["data"]:
            state_dict["data"]["umap_results"] = {}
        self.history.get_module_history(self.plugin_id).push(state_dict)
        self.state_changed.emit()

    def set_state(self, state: Any) -> None:
        """Restore the workspace from an SDK state object."""
        if not state:
            return
        self.state = state
        self._refresh_all()

    def export_state(self) -> dict:
        """Package the workspace state for undo/redo history snapshots.

        UMAP results are intentionally excluded: they contain large embedding
        arrays (100k+ floats) and are managed separately by the attachment /
        workflow-save pipeline.  Including them in every undo snapshot would
        create gigabytes of in-memory history and cause multi-second freezes
        on close while Python's GC tears down the nested lists.
        """
        state_dict = self.state.to_dict()
        # Strip the heavy binary payload — workflow save/load handles persistence.
        if "data" in state_dict and "umap_results" in state_dict["data"]:
            state_dict["data"]["umap_results"] = {}
        return {
            "flow_state": state_dict,
            "active_tab": self._tab_bar.currentIndex(),
        }

    def load_state(self, state_dict: dict) -> None:
        """Restore the workspace for backward compatibility."""
        if not state_dict:
            return

        current_umap = self.state.data.umap_results if hasattr(self, "state") and self.state else {}

        flow_data = state_dict.get("flow_state", {})
        self.state = FlowState.from_dict(flow_data)

        self.state.data.umap_results = current_umap

        # Clear active view context so UI starts blank on load
        self.state.view.current_sample_id = None
        self.state.view.current_gate_id = None

        tab_idx = state_dict.get("active_tab", 0)
        self._tab_bar.setCurrentIndex(tab_idx)

        # Refresh all UI widgets from the new state
        self._refresh_all()

    def export_workflow(self) -> dict:
        """Serialize the workspace for saving to disk."""
        pm = self._get_project_manager()
        project_dir = pm.project_dir if pm else None
        return self._workflow_service.export_workflow(project_dir=project_dir)

    def load_workflow(  # noqa: PLR0912, PLR0915
        self, payload: dict, filename: str | None = None, metadata: dict | None = None
    ) -> None:
        """Restore the workspace from a saved file."""
        # Support raw data injection for CI/CD smoke tests
        if filename and str(filename).lower().endswith(".fcs"):
            self.logger.info(f"Direct raw FCS injection detected: {filename}")

            def _on_done(results: dict):
                self.logger.info(f"Raw FCS injection complete. Processed {len(results)} samples.")
                self._refresh_all()
                self._emit_data_ready_once()

            def _on_error(err: str):
                self.logger.error(f"FCS injection failed: {err}")
                self._emit_data_ready_once()

            data_loader = self._factory.get("data_loader_service")
            data_loader.load_samples_async(
                [filename],
                self.state,
                on_done=_on_done,
                on_error_cb=_on_error,
            )
            return
        if filename:
            self._current_workflow_filename = filename
        if metadata:
            self._current_workflow_metadata = metadata

        pm = self._get_project_manager()
        context = None
        if pm and filename:
            from karcytics_sdk.plugin.workflow import WorkflowContext

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
                        self._gate_controller.recompute_all_stats(sid)

            # 2. Refresh sample list, gate hierarchy, and active graph canvas
            self._refresh_all()

            failed = (reload_result or {}).get("failed") or []
            if failed:
                self.logger.error(f"FCS reload failed for {len(failed)} sample(s): {failed}")
                QMessageBox.warning(
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
            if getattr(self, "_awaiting_data_ready", False):
                self._awaiting_data_ready = False
                self.logger.info("--> [_on_fcs_done] Scheduling data_ready.emit in 300ms...")
                QTimer.singleShot(300, self._emit_data_ready_once)
            else:
                self.logger.info("--> [_on_fcs_done] Emitting data_ready immediately.")
                self._emit_data_ready_once()

        project_dir = pm.project_dir if pm else None
        if self._workflow_service.load_workflow(
            payload, context=context, project_dir=project_dir, on_complete=_on_fcs_done
        ):
            # Scrub legacy UMAP bloat from in-memory history
            try:
                history_mod = getattr(self.history, "get_module_history", lambda x: None)(
                    self.plugin_id
                )
                if history_mod and hasattr(history_mod, "undo_stack"):
                    for stack in (
                        getattr(history_mod, "undo_stack", []),
                        getattr(history_mod, "redo_stack", []),
                    ):
                        for snapshot in stack:
                            if "data" in snapshot and "umap_results" in snapshot["data"]:
                                if snapshot["data"]["umap_results"]:
                                    snapshot["data"]["umap_results"] = {}
                            elif "umap_results" in snapshot:
                                if snapshot["umap_results"]:
                                    snapshot["umap_results"] = {}
            except (KeyError, TypeError, AttributeError) as e:
                self.logger.warning(f"Failed to scrub legacy history: {e}")

        else:
            # Try to grab the last exception if we stored it
            error_msg = getattr(self._workflow_service, "_last_error", "Check logs for details.")
            QMessageBox.critical(self, "Load Error", f"Failed to restore workflow. {error_msg}")

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
            self._on_gate_selected(self.state.view.current_gate_id)

        # 4. Final refresh for properties and graph
        self._properties_panel.refresh()
        self._graph_manager.refresh()

        self.logger.info("MainPanel: Full UI refresh complete.")

    def _sample_name(self, sample_id: str) -> str:
        """Get a sample's display name by ID."""
        sample = self.state.data.experiment.samples.get(sample_id)
        return sample.display_name if sample else sample_id
