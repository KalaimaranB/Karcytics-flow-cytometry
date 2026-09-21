"""Graph window — interactive 2-D scatter / histogram display.

Equivalent to a standard software Graph Window.  Each GraphWindow displays one
plot of a single population (sample or gated subset) with:
- X/Y axis dropdowns for parameter selection
- Transform buttons (linear / log / biexponential)
- Gate overlay rendering with named, color-coded patches
- Breadcrumb navigation bar showing the gating hierarchy path
- Active gate info and statistics display
- Multiple display modes (dot, pseudocolor, contour, density, histogram)

GraphWindows are managed by :class:`GraphManager` which handles tabbing
and tiling.
"""

from __future__ import annotations

from typing import Any

from karcytics_sdk.plugin import CentralEventBus, get_logger
from karcytics_sdk.plugin.theme_fallback import Colors
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QLabel,
    QVBoxLayout,
    QWidget,
)

from karcytics_plugins.flow_cytometry.analysis import events
from karcytics_plugins.flow_cytometry.analysis.fcs_io import get_channel_marker_label
from karcytics_plugins.flow_cytometry.analysis.gating import Gate, GateNode
from karcytics_plugins.flow_cytometry.analysis.protocols import (
    IGateCoordinator,
    IPopulationService,
)
from karcytics_plugins.flow_cytometry.analysis.scaling import (
    AxisScale,
    calculate_auto_range,
    detect_logicle_top,
    estimate_logicle_params,
)
from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.analysis.transforms import TransformType

from .flow_canvas import FlowCanvas, GateDrawingMode
from .render_window import RenderWindow
from .transform_dialog import TransformDialog

logger = get_logger(__name__, "flow_cytometry")

# Map tool names to drawing modes
_TOOL_MODE_MAP = {
    "select": GateDrawingMode.NONE,
    "rectangle": GateDrawingMode.RECTANGLE,
    "polygon": GateDrawingMode.POLYGON,
    "ellipse": GateDrawingMode.ELLIPSE,
    "quadrant": GateDrawingMode.QUADRANT,
    "range": GateDrawingMode.RANGE,
}


class GraphWindow(QWidget):
    """Interactive flow cytometry plot widget.

    Displays a single bivariate (scatter) or univariate (histogram)
    plot of events.  Gate drawing, axis selection, and display mode
    changes are handled here.

    Signals:
        gate_drawn(Gate, str, str):   Emitted when a gate is drawn.
                                       (gate, sample_id, parent_gate_id)
        gate_selection_changed(str):  Emitted when a gate overlay is clicked.
        axis_changed:                 Emitted when axis selection changes.
    """

    gate_drawn = pyqtSignal(object, str, object)  # Gate, sample_id, parent_node_id
    gate_selection_changed = pyqtSignal(object)  # gate_id or None
    axis_changed = pyqtSignal()
    axis_scale_sync_requested = pyqtSignal(str, object)  # channel_name, AxisScale
    navigation_requested = pyqtSignal(str)  # "next_sample", "prev_sample", "parent_gate"
    tool_change_requested = pyqtSignal(
        str
    )  # "select", "rectangle", "polygon", "ellipse", "quadrant", "range"

    def __init__(  # noqa: PLR0913
        self,
        state: FlowState,
        sample_id: str,
        node_id: str | None = None,
        axis_manager: Any | None = None,
        population_service: IPopulationService | None = None,
        controller: IGateCoordinator | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._state = state
        self._axis_manager = axis_manager
        self._population_service = population_service
        self._sample_id = sample_id
        self._node_id = node_id
        if controller is None:
            raise ValueError("IGateCoordinator must be injected")
        self._controller = controller

        self._x_scale = AxisScale(TransformType.LINEAR)
        self._y_scale = AxisScale(TransformType.LINEAR)

        # Debounce timer: 100 ms after the last axis change before re-rendering.
        # Prevents 5-10 redundant full redraws when the user scrolls through the combo.
        self._axis_debounce = QTimer(self)
        self._axis_debounce.setSingleShot(True)
        self._axis_debounce.setInterval(100)
        self._axis_debounce.timeout.connect(self._do_axis_render)

        # Store references to modeless render windows to prevent GC
        self._render_windows: list[RenderWindow] = []

        self._setup_ui()
        self._setup_events()
        logger.info(f"GraphWindow initialized for sample {sample_id}, node {node_id}")

        # Size watcher: some layouts are lazy on macOS, especially in QTabWidget.
        # We poll for a few seconds until we get a non-zero size.
        self._size_watcher = QTimer(self)
        self._size_watcher.timeout.connect(self._check_size_and_render)
        self._size_watcher.start(250)
        self._size_attempts = 0

    def _check_size_and_render(self) -> None:
        self._size_attempts += 1
        if self.width() > 0 and self.height() > 0:
            logger.info(
                f"GraphWindow size watcher: Found size {self.width()}x{self.height()} at attempt {self._size_attempts}"
            )
            self._size_watcher.stop()
            self._render_initial()
        elif self._size_attempts > 20:  # 5 seconds  # noqa: PLR2004
            logger.warning("GraphWindow size watcher: Timed out waiting for non-zero size")
            self._size_watcher.stop()

    def _setup_events(self) -> None:
        """Subscribe to relevant state events."""
        CentralEventBus.subscribe(events.GATE_RENAMED, self._on_gate_renamed)
        CentralEventBus.subscribe(events.SAMPLE_UPDATED, self._on_sample_updated)
        self.destroyed.connect(self._cleanup_events)

    def _cleanup_events(self) -> None:
        """Unsubscribe from CentralEventBus when this window is destroyed.

        Without this, an event published after a tab is closed (delivery is
        queued, so it can land after destruction) still reaches these
        callbacks and touches a deleted Qt C++ object.
        """
        try:
            CentralEventBus.unsubscribe(events.GATE_RENAMED, self._on_gate_renamed)
            CentralEventBus.unsubscribe(events.SAMPLE_UPDATED, self._on_sample_updated)
        except Exception:
            pass

    def _on_gate_renamed(self, data: dict) -> None:
        """Handle incoming gate rename events."""
        try:
            # Refresh if it's our sample and node
            if data.get("sample_id") == self._sample_id:
                # We update the breadcrumb even if it's a parent gate that was renamed
                self._update_breadcrumb()
        except RuntimeError as e:
            if "has been deleted" in str(e):
                self._cleanup_events()
            else:
                raise

    def _on_sample_updated(self, data: dict) -> None:
        """Handle sample updates, such as role changes."""
        try:
            self._populate_fmo_combo()
        except RuntimeError as e:
            if "has been deleted" in str(e):
                self._cleanup_events()
            else:
                raise

    @property
    def sample_id(self) -> str:
        return self._sample_id

    @property
    def node_id(self) -> str | None:
        return self._node_id

    @property
    def canvas(self) -> FlowCanvas:
        """Expose the canvas for external signal wiring."""
        return self._canvas

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # ── Navigation & Breadcrumb bar ───────────────────────────────
        from .components.graph_toolbar import GraphToolbar

        self._toolbar = GraphToolbar(self)
        self._toolbar.navigation_requested.connect(self.navigation_requested.emit)
        self._toolbar.set_parent_button_visible(self._node_id is not None)
        layout.addWidget(self._toolbar)

        # ── Axis selection row ────────────────────────────────────────
        from .components.axis_control_panel import AxisControlPanel

        self._axis_panel = AxisControlPanel(self)
        self._axis_panel.axis_changed.connect(self._on_axis_changed)
        self._axis_panel.display_mode_changed.connect(self._on_mode_changed)
        self._axis_panel.fmo_overlay_changed.connect(self._on_fmo_changed)
        self._axis_panel.transforms_requested.connect(self._open_transform_dialog)
        self._axis_panel.settings_requested.connect(self._open_render_settings_dialog)

        layout.addWidget(self._axis_panel)

        # ── Flow Canvas (the actual matplotlib plot) ──────────────────
        self._canvas = FlowCanvas(self._state, self._controller, self)
        self._canvas.setMinimumSize(400, 400)
        layout.addWidget(self._canvas, stretch=1)
        logger.info(
            f"GraphWindow._setup_ui: Canvas added to layout, canvas_size={self._canvas.width()}x{self._canvas.height()}"
        )
        self._canvas.show()

        # Inherit the global plot type silently so we don't trigger premature redraws
        # before the canvas has its axes and scales initialized.
        if hasattr(self._state.view, "active_plot_type"):
            self._axis_panel.blockSignals(True)
            self._axis_panel.set_display_mode(self._state.view.active_plot_type)
            self._axis_panel.blockSignals(False)

            mode = self._axis_panel.get_current_display_mode()
            if mode:
                self._canvas._display_mode = mode  # type: ignore

        # Wire canvas signals
        self._canvas.gate_created.connect(self._on_gate_created)
        self._canvas.gate_selected.connect(self._on_gate_selected)
        self._canvas.render_requested.connect(self._on_render_full_quality)
        self._canvas.drawing_cancelled.connect(lambda: self.tool_change_requested.emit("select"))

        # ── Gate info bar ─────────────────────────────────────────────
        self._gate_info = QLabel()
        self._gate_info.setVisible(False)
        layout.addWidget(self._gate_info)

        # Populate axis combos and trigger initial scale sync and render
        self._populate_axis_combos()
        self._on_axis_changed()

        self._apply_theme_styles()

    def _apply_theme_styles(self) -> None:
        """Dynamically refresh colors based on current theme."""
        if hasattr(self, "_toolbar") and hasattr(self._toolbar, "_apply_theme_styles"):
            self._toolbar._apply_theme_styles()
        if hasattr(self, "_axis_panel") and hasattr(self._axis_panel, "_apply_theme_styles"):
            self._axis_panel._apply_theme_styles()
        if hasattr(self, "_canvas") and hasattr(self._canvas, "_apply_theme_styles"):
            self._canvas._apply_theme_styles()
        if hasattr(self, "_gate_info"):
            self._gate_info.setStyleSheet(
                f"color: {Colors.FG_SECONDARY}; font-size: 10px;"
                f" background: {Colors.BG_DARK}; padding: 3px 8px;"
                f" border-radius: 3px;"
            )

    def set_drawing_mode(self, tool_name: str) -> None:
        """Set the canvas drawing mode from a tool name.

        Args:
            tool_name: One of "select", "rectangle", "polygon",
                       "ellipse", "quadrant", "range".
        """
        mode = _TOOL_MODE_MAP.get(tool_name, GateDrawingMode.NONE)
        self._canvas.set_drawing_mode(mode)

    def refresh_gates(self, gates: list[Gate], gate_nodes: list[GateNode]) -> None:
        """Refresh the gate overlays on this canvas.

        Args:
            gates:      Gates to render.
            gate_nodes: Matching GateNode list for stat labels.
        """
        self._canvas.set_gates(gates, gate_nodes)

    def update_gate_info(self, gate: Gate | None, stats: dict) -> None:
        """Update the gate info bar at the bottom of the window.

        Args:
            gate:  The currently selected gate (None to hide).
            stats: Statistics dictionary {count, pct_parent, pct_total}.
        """
        if gate is None:
            self._gate_info.setVisible(False)
            return

        count = stats.get("count", 0)
        pct_parent = stats.get("pct_parent", 0.0)
        pct_total = stats.get("pct_total", 0.0)

        text = (
            f"  ⊳ {stats.get('name', 'Population')}  │  "
            f"{int(count):,} events  │  "
            f"{pct_parent:.1f}% of parent  │  "
            f"{pct_total:.1f}% of total"
        )
        self._gate_info.setText(text)
        self._gate_info.setVisible(True)

    def _populate_axis_combos(self) -> None:  # noqa: PLR0912, PLR0915
        """Fill axis dropdowns with parameter names from the sample."""
        sample = self._state.data.experiment.samples.get(self._sample_id)

        # Block signals during population to avoid premature redraws
        self._axis_panel.block_combos(True)

        if sample is None or sample.fcs_data is None:
            defaults = ["FSC-A", "SSC-A", "FSC-H", "SSC-H"]
            self._axis_panel.set_defaults(defaults)
        else:
            self._axis_panel.clear_combos()
            fcs = sample.fcs_data
            for ch in fcs.channels:
                label = get_channel_marker_label(fcs, ch)
                self._axis_panel.add_channel(label, ch)

            self._populate_fmo_combo()

            # Determine Smart Defaults - Default to globally active parameters
            default_x = (
                self._state.view.active_x_param
                if hasattr(self._state.view, "active_x_param")
                else "FSC-A"
            )
            default_y = (
                self._state.view.active_y_param
                if hasattr(self._state.view, "active_y_param")
                else "SSC-A"
            )

            # Check sample's memory (traverse up gate hierarchy)
            node_id_to_check = self._node_id
            found_memory = False

            # 1. Prefer the "creation view" anchored to this exact node. A freshly
            # gated-out node never has its own creation_view — it's recorded on the
            # *parent* (the node that was actually being viewed when the gate was
            # drawn — see GateMutationService.add_gate) — so fall back to the
            # parent's record. This is what lets a child population inherit the
            # exact view (axes + plot type) it was carved out of, e.g. staying in
            # Pseudocolor after drawing a range gate on a 2D scatter, instead of
            # falling back to whatever the last-touched tab's global mode was.
            if self._node_id:
                node = sample.gate_tree.find_node_by_id(self._node_id)
                cv_source = node
                if node and not node.creation_view and node.parents:
                    cv_source = node.parents[0]
                if cv_source and cv_source.creation_view:
                    cv = cv_source.creation_view
                    if "x_param" in cv:
                        default_x = cv["x_param"]
                        default_y = cv.get("y_param") or cv.get("view_y_param") or default_y

                        # Restore exact scales into AxisManager
                        from ...analysis.scaling import AxisScale

                        if cv.get("x_scale") is not None:
                            assert self._axis_manager is not None
                            self._axis_manager.set_scale(
                                default_x,
                                AxisScale.from_dict(cv["x_scale"]),
                                sample_id=self._sample_id,
                                notify=False,
                            )
                        if cv.get("y_scale") is not None and default_y:
                            assert self._axis_manager is not None
                            self._axis_manager.set_scale(
                                default_y,
                                AxisScale.from_dict(cv["y_scale"]),
                                sample_id=self._sample_id,
                                notify=False,
                            )

                        if "plot_type" in cv:
                            self._state.view.active_plot_type = cv["plot_type"]
                            self._axis_panel.set_display_mode(cv["plot_type"])

                        found_memory = True

            # 2. Fallback to last viewed axes
            while not found_memory:
                key = node_id_to_check or "root"
                if key in sample.last_viewed_axes:
                    mem = sample.last_viewed_axes[key]
                    if "x_param" in mem and "y_param" in mem:
                        default_x = mem["x_param"]
                        default_y = mem["y_param"]
                        found_memory = True
                        break

                if not node_id_to_check:
                    break

                node = sample.gate_tree.find_node_by_id(node_id_to_check)
                p_node = node.parents[0] if node and node.parents else None
                if p_node and not p_node.is_root:
                    node_id_to_check = p_node.node_id
                elif p_node and p_node.is_root:
                    node_id_to_check = None
                else:
                    break

            if not found_memory and self._node_id:
                node = sample.gate_tree.find_node_by_id(self._node_id)
                if node:
                    # Smart default 1: if it has sub-populations, show the axes they were drawn on
                    if node.children and node.children[0].gate:
                        gate_x = getattr(node.children[0].gate, "x_param", None)
                        gate_y = getattr(node.children[0].gate, "y_param", None)
                        if gate_x == "Subset" or not gate_y:
                            # Preserve whatever default_x/default_y was (usually synced from previous view)
                            pass
                        else:
                            default_x = gate_x or default_x
                            default_y = gate_y or default_y

            # Apply defaults
            self._axis_panel.set_current_x(default_x)
            self._axis_panel.set_current_y(default_y)

        self._axis_panel.block_combos(False)

    def _populate_fmo_combo(self) -> None:
        """Populate the FMO overlay dropdown based on sample roles."""
        current_fmo = self._axis_panel.get_current_fmo()
        self._axis_panel.clear_fmo_combo()
        from ...analysis.experiment import SampleRole

        for sid, s in self._state.data.experiment.samples.items():
            if s.role == SampleRole.FMO_CONTROL:
                self._axis_panel.add_fmo_option(s.display_name, sid)
        if current_fmo:
            self._axis_panel.set_current_fmo(current_fmo)

    def _render_initial(self) -> None:  # noqa: PLR0912, PLR0915
        """Render the initial plot from the sample's data."""
        sample = self._state.data.experiment.samples.get(self._sample_id)
        if sample is None or sample.fcs_data is None:
            logger.warning(
                f"GraphWindow._render_initial: Sample {self._sample_id} not found or has no FCS data"
            )
            return

        sample_events = sample.fcs_data.events
        if sample_events is None:
            logger.warning(f"GraphWindow._render_initial: Sample {self._sample_id} has no events")
            return

        # Use PopulationService to get the actual subset (respects negations, etc)
        assert self._population_service is not None
        gated_events = self._population_service.get_gated_events(self._sample_id, self._node_id)
        if gated_events is None:
            logger.warning(
                f"GraphWindow._render_initial: PopulationService returned None for node {self._node_id}"
            )
            return

        logger.info(f"GraphWindow._render_initial: Gated events size = {len(gated_events)}")

        # Guard against empty gate result
        if len(gated_events) == 0:
            self._canvas.set_data(gated_events)
            return

        x_ch = self._axis_panel.get_current_x()
        y_ch = self._axis_panel.get_current_y()

        fcs = sample.fcs_data
        x_label = get_channel_marker_label(fcs, x_ch)
        y_label = get_channel_marker_label(fcs, y_ch)

        logger.info(
            "[W-DIAG] _render_initial: node=%s  x=%s  y=%s  "
            "_x_scale.transform=%s  _x_scale.min_val=%s  _x_scale.w=%.4f  "
            "_y_scale.transform=%s  _y_scale.min_val=%s  _y_scale.w=%.4f",
            self._node_id,
            x_ch,
            y_ch,
            self._x_scale.transform_type,
            self._x_scale.min_val,
            self._x_scale.logicle_w,
            self._y_scale.transform_type,
            self._y_scale.min_val,
            self._y_scale.logicle_w,
        )

        # Clone scales so we don't corrupt the global channel_scales store
        x_scale_active = self._x_scale.copy()
        y_scale_active = self._y_scale.copy()

        # ── PARENT POPULATION for W/A estimation ────────────────────────────
        # W and A must be estimated from the *parent* population — the events the
        # gate was drawn against — not the current node's subset.  FlowJo does the
        # same: when you view the B220/CD3 gate, FlowJo computes W from leukocytes
        # (the parent population), not from B+T cells (the child subset).
        #
        # For a node with a parent, the parent population is the events that passed
        # all gates *above* this one, i.e. apply_hierarchy on the parent node.
        # For a root-level or ungated node, fall back to the full sample.
        _node = sample.gate_tree.find_node_by_id(self._node_id) if self._node_id else None
        _parent_node = _node.parents[0] if (_node and _node.parents) else None
        if _parent_node is not None:
            parent_events = _parent_node.apply_hierarchy(sample_events)
            if len(parent_events) == 0:
                logger.warning(
                    "[W-DIAG] parent_events empty after apply_hierarchy — falling back to full sample"
                )
                parent_events = sample_events  # safety fallback
        else:
            parent_events = sample_events  # root or ungated: full sample is the parent

        logger.info(
            "[W-DIAG] parent resolution: node=%s  parent_node=%s  "
            "full_sample_n=%d  parent_n=%d  gated_n=%d",
            _node.node_id if _node else None,
            _parent_node.node_id if _parent_node else None,
            len(sample_events),
            len(parent_events),
            len(gated_events),
        )

        # ── LOGICLE SHAPE PARAMETERS (always recomputed from parent population) ─
        # T, W, and A are re-estimated on every render, even when min_val is already
        # set (e.g. restored from creation_view or group.channel_scales).
        #
        # Why parent population:  The axis range (min/max) is locked first-time-only
        # so the view doesn't jump, but W determines the *shape* of the transform —
        # how wide the linear region is around zero.  A W stored from an earlier
        # render (full sample, or a different gate depth) is too small for a narrow
        # gated subset, splitting one population into two apparent clusters — exactly
        # the CD3 bug on spleen B/T gates.
        #
        # T is still taken from the full sample so it always reflects the
        # instrument's true dynamic range regardless of gate depth.
        _x_biexp_cond = (
            x_scale_active.transform_type == TransformType.BIEXPONENTIAL
            and x_ch in sample_events.columns
            and x_ch in parent_events.columns
        )
        logger.info(
            "[W-DIAG] X biexp condition: transform=%s  x_ch_in_sample=%s  x_ch_in_parent=%s  → will_estimate=%s",
            x_scale_active.transform_type,
            x_ch in sample_events.columns,
            x_ch in parent_events.columns,
            _x_biexp_cond,
        )
        if _x_biexp_cond:
            x_scale_active.logicle_t = detect_logicle_top(sample_events[x_ch].values)
            w_val, a_val = estimate_logicle_params(
                parent_events[x_ch].values, t=x_scale_active.logicle_t
            )
            logger.info(
                "[W-DIAG] X W/A estimated: channel=%s  w_before=%.4f  w_after=%.4f  a_after=%.4f  t=%.0f",
                x_ch,
                self._x_scale.logicle_w,
                w_val,
                a_val,
                x_scale_active.logicle_t,
            )
            x_scale_active.logicle_w = w_val
            x_scale_active.logicle_a = a_val

        _y_biexp_cond = (
            y_scale_active.transform_type == TransformType.BIEXPONENTIAL
            and y_ch in sample_events.columns
            and y_ch in parent_events.columns
        )
        logger.info(
            "[W-DIAG] Y biexp condition: transform=%s  y_ch_in_sample=%s  y_ch_in_parent=%s  → will_estimate=%s",
            y_scale_active.transform_type,
            y_ch in sample_events.columns,
            y_ch in parent_events.columns,
            _y_biexp_cond,
        )
        if _y_biexp_cond:
            # T from full sample; W and A from parent population (see above).
            y_scale_active.logicle_t = detect_logicle_top(sample_events[y_ch].values)
            w_val, a_val = estimate_logicle_params(
                parent_events[y_ch].values, t=y_scale_active.logicle_t
            )
            logger.info(
                "[W-DIAG] Y W/A estimated: channel=%s  w_before=%.4f  w_after=%.4f  a_after=%.4f  t=%.0f",
                y_ch,
                self._y_scale.logicle_w,
                w_val,
                a_val,
                y_scale_active.logicle_t,
            )
            y_scale_active.logicle_w = w_val
            y_scale_active.logicle_a = a_val

        # ── AUTO-RANGE (first-time only) ──────────────────────────────────
        # Only compute min/max when the channel has never been ranged before
        # (min_val is None). If the user has manually set limits, or a previous
        # render already established them, we preserve those values entirely.
        # This is the single gate that prevents the view from jumping whenever
        # the user switches channels, enters a gate, or changes transform type.
        # ── AUTO-RANGE (first-time only) ──────────────────────────────────
        if x_ch in sample_events.columns and x_scale_active.min_val is None:
            vmin, vmax = calculate_auto_range(
                sample_events[x_ch].values,
                x_scale_active.transform_type,
                x_scale_active.outlier_percentile,
            )
            x_scale_active.min_val = vmin
            x_scale_active.max_val = vmax

            # Also update the global state so it persists
            assert self._axis_manager is not None
            self._axis_manager.set_scale(
                x_ch, x_scale_active, notify=False, sample_id=self._sample_id
            )
            # Update our reference
            self._x_scale = x_scale_active.copy()

        if y_ch in sample_events.columns and y_scale_active.min_val is None:
            vmin, vmax = calculate_auto_range(
                sample_events[y_ch].values,
                y_scale_active.transform_type,
                y_scale_active.outlier_percentile,
            )
            y_scale_active.min_val = vmin
            y_scale_active.max_val = vmax

            # Also update the global state so it persists
            assert self._axis_manager is not None
            self._axis_manager.set_scale(
                y_ch, y_scale_active, notify=False, sample_id=self._sample_id
            )
            # Update our reference
            self._y_scale = y_scale_active.copy()

        # ── PERSIST THE ESTIMATED SCALES ──
        # This ensures the global state (and thus the Group Preview)
        # uses the same "Optimized" parameters as this window.
        self._x_scale = x_scale_active.copy()
        self._y_scale = y_scale_active.copy()
        if self._axis_manager is not None:
            self._axis_manager.set_scale(
                x_ch, self._x_scale.copy(), sample_id=self._sample_id, notify=False
            )
            self._axis_manager.set_scale(
                y_ch, self._y_scale.copy(), sample_id=self._sample_id, notify=False
            )

        self._canvas.begin_update()
        self._canvas.set_sample_id(self._sample_id)
        self._canvas.set_axes(x_ch, y_ch, x_label, y_label)
        self._canvas.set_scales(x_scale_active, y_scale_active)
        self._canvas.end_update()  # single redraw with correct axes+scales
        self._canvas.set_data(gated_events)  # final redraw with gated data

        # Notify the system (and Group Preview) that the scale has been finalized
        CentralEventBus.publish(
            events.AXIS_RANGE_CHANGED,
            {
                "sample_id": self._sample_id,
                "x_param": x_ch,
                "y_param": y_ch,
                "x_scale": self._x_scale,
                "y_scale": self._y_scale,
            },
        )

    def apply_axis_scale(self, channel_name: str, scale: AxisScale) -> None:
        """Apply an external scale setting if this graph uses that channel."""
        x_ch = self._axis_panel.get_current_x()
        y_ch = self._axis_panel.get_current_y()

        needs_redraw = False
        if x_ch == channel_name:
            self._x_scale = scale.copy()
            needs_redraw = True
        if y_ch == channel_name:
            self._y_scale = scale.copy()
            needs_redraw = True

        if needs_redraw:
            self._canvas.set_scales(self._x_scale, self._y_scale)

    def _on_axis_changed(self) -> None:
        """Handle axis dropdown changes — debounced to avoid redundant renders."""
        # Update internal scale objects immediately so they match the selection,
        # even if the actual render is delayed by the debounce timer.
        x_ch = self._axis_panel.get_current_x()
        y_ch = self._axis_panel.get_current_y()

        self._state.view.active_x_param = x_ch
        self._state.view.active_y_param = y_ch

        # Sync X scale
        if self._axis_manager is not None:
            self._x_scale = self._axis_manager.get_scale(x_ch, self._sample_id).copy()
            self._y_scale = self._axis_manager.get_scale(y_ch, self._sample_id).copy()

        # Save to memory
        sample = self._state.data.experiment.samples.get(self._sample_id)
        if sample:
            key = self._node_id or "root"
            sample.last_viewed_axes[key] = {"x_param": x_ch, "y_param": y_ch}

        # Show spinner immediately so the user knows a change was registered
        self._axis_panel.set_spinner_visible(True)
        # Restart the debounce timer; actual render fires after 100ms of quiet
        self._axis_debounce.start()

    def _do_axis_render(self) -> None:
        """Perform the actual render after axis debounce fires."""
        self._render_initial()
        self._axis_panel.set_spinner_visible(False)
        self.axis_changed.emit()

        x_ch = self._axis_panel.get_current_x()
        y_ch = self._axis_panel.get_current_y()

        # Publish to event bus for Group Preview sync
        CentralEventBus.publish(
            events.AXIS_PARAMS_CHANGED,
            {"sample_id": self._sample_id, "x_param": x_ch, "y_param": y_ch},
        )

    def _on_mode_changed(self, mode) -> None:
        """Handle display mode changes."""
        if mode:
            self._canvas.set_display_mode(mode)
            # Update global state and notify subscribers (e.g. thumbnails)
            self._state.view.active_plot_type = mode.value
            CentralEventBus.publish(events.DISPLAY_MODE_CHANGED, {"mode": mode.value})

    def _on_fmo_changed(self, sample_id: str) -> None:
        """Handle FMO overlay selection change."""
        self._canvas.set_fmo_overlay(sample_id)
        self._state.view.active_fmo_sample_id = sample_id or None
        CentralEventBus.publish(
            events.FMO_CHANGED, {"fmo_sample_id": self._state.view.active_fmo_sample_id}
        )
        if sample_id:
            # When an FMO is selected, it's almost always to draw a Range Gate
            self.tool_change_requested.emit("range")

    def _open_render_settings_dialog(self) -> None:
        """Open the popup dialog to customize density rendering."""
        from .render_settings_dialog import RenderSettingsDialog

        dlg = RenderSettingsDialog(self._state, self)
        dlg.settings_applied.connect(self._on_render_settings_applied)
        dlg.show()

    def _on_render_settings_applied(self, new_config) -> None:
        """Apply new settings and re-render."""
        self._state.view.render_config = new_config
        self._canvas.redraw()

    def _on_gate_created(self, gate: Gate) -> None:
        """Handle gate_created from canvas — forward to controller."""
        self.gate_drawn.emit(gate, self._sample_id, self._node_id)

    def _on_gate_selected(self, gate_id: str | None) -> None:
        """Handle gate selection on the canvas."""
        self.gate_selection_changed.emit(gate_id)

    def _on_render_full_quality(self) -> None:
        """Launch the high-quality render window."""
        # Clean up closed windows from the reference list
        self._render_windows = [w for w in self._render_windows if w.isVisible()]

        x_ch = self._axis_panel.get_current_x()
        y_ch = self._axis_panel.get_current_y()
        mode = self._axis_panel.get_current_display_mode()

        # Get current gate overlays
        gates = self._canvas._active_gates
        nodes = self._canvas._gate_nodes

        win = RenderWindow(
            state=self._state,
            sample_id=self._sample_id,
            node_id=self._node_id,
            x_param=x_ch,
            y_param=y_ch,
            display_mode=mode,  # type: ignore
            x_scale=self._x_scale,
            y_scale=self._y_scale,
            gates=gates,
            gate_nodes=nodes,
            parent=self.window(),  # Keep it associated with the main window
        )
        win.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        win.show()
        self._render_windows.append(win)

    def _open_transform_dialog(self) -> None:
        """Open the unified Transform & Scaling dialog."""
        x_name = self._axis_panel.get_current_x_text()
        y_name = self._axis_panel.get_current_y_text()
        x_ch = self._axis_panel.get_current_x()
        y_ch = self._axis_panel.get_current_y()

        def do_auto_range_x(outlier_p: float = 0.1) -> tuple[float, float]:
            return self._calculate_auto_range("x", outlier_p)

        def do_auto_range_y(outlier_p: float = 0.1) -> tuple[float, float]:
            return self._calculate_auto_range("y", outlier_p)

        dlg = TransformDialog(
            x_name=x_name,
            y_name=y_name,
            x_scale=self._x_scale,
            y_scale=self._y_scale,
            auto_range_x_callback=do_auto_range_x,
            auto_range_y_callback=do_auto_range_y,
            parent=self,
        )

        # When values change, update local, redraw, and implicitly sync globally
        def on_change(axis_id: str, new_scale: AxisScale):
            old_scale = self._x_scale if axis_id == "x" else self._y_scale
            transform_changed = old_scale.transform_type != new_scale.transform_type

            if axis_id == "x":
                self._x_scale = new_scale.copy()
                if self._axis_manager is not None:
                    self._axis_manager.set_scale(
                        x_ch, self._x_scale.copy(), sample_id=self._sample_id
                    )
                self.axis_scale_sync_requested.emit(x_ch, self._x_scale)
                self._notify_axis_change()
            else:
                self._y_scale = new_scale.copy()
                if self._axis_manager is not None:
                    self._axis_manager.set_scale(
                        y_ch, self._y_scale.copy(), sample_id=self._sample_id
                    )
                self.axis_scale_sync_requested.emit(y_ch, self._y_scale)
                self._notify_axis_change()

            if transform_changed:
                self._canvas._on_transform_changed()
                CentralEventBus.publish(
                    events.TRANSFORM_CHANGED,
                    {
                        "sample_id": self._sample_id,
                        "axis": axis_id,
                        "channel": x_ch if axis_id == "x" else y_ch,
                        "old_type": old_scale.transform_type,
                        "new_type": new_scale.transform_type,
                    },
                )

            self._render_initial()

        dlg.scale_changed.connect(on_change)

        dlg.show()

    def _notify_axis_change(self) -> None:
        """Publish the current axis state to the global event bus."""
        x_ch = self._axis_panel.get_current_x()
        y_ch = self._axis_panel.get_current_y()
        CentralEventBus.publish(
            events.AXIS_RANGE_CHANGED,
            {
                "sample_id": self._sample_id,
                "x_param": x_ch,
                "y_param": y_ch,
                "x_scale": self._x_scale,
                "y_scale": self._y_scale,
            },
        )

    def _calculate_auto_range(
        self, axis: str, outlier_p: float | None = None
    ) -> tuple[float, float]:
        """Compute the robust min/max for the given axis, using gated data.

        Args:
            axis: "x" or "y".
            outlier_p: Percentile to clip at each end. If None, uses the
                       value stored in the current axis scale.
        """
        sample = self._state.data.experiment.samples.get(self._sample_id)
        if not sample or not sample.fcs_data or sample.fcs_data.events is None:
            return (0.0, 1.0)

        events = sample.fcs_data.events

        col = self._axis_panel.get_current_x() if axis == "x" else self._axis_panel.get_current_y()
        if not col or col not in events:
            return (0.0, 1.0)

        scale = self._x_scale if axis == "x" else self._y_scale
        pct = outlier_p if outlier_p is not None else scale.outlier_percentile
        return calculate_auto_range(
            events[col].values, scale.transform_type, outlier_percentile=pct
        )

    def _update_breadcrumb(self) -> None:
        """Update the breadcrumb navigation bar showing gating path."""
        sample = self._state.data.experiment.samples.get(self._sample_id)
        if sample is None:
            self._toolbar.set_breadcrumb_text("⊘ No sample selected")
            return

        parts = [f"🧪 {sample.display_name}"]

        if self._node_id:
            # Build full path from root to this population node
            node = sample.gate_tree.find_node_by_id(self._node_id)
            if node:
                path: list[str] = []
                current = node
                while current and not current.is_root:
                    path.append(current.name)
                    current = current.parents[0] if current.parents else None  # type: ignore
                path.reverse()
                for p in path:
                    parts.append(f"⊳ {p}")

        self._toolbar.set_breadcrumb_text("  ›  ".join(parts))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        logger.info(f"GraphWindow resized: {self.width()}x{self.height()}")
