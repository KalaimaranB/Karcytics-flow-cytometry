"""FlowCanvas — embedded matplotlib widget for flow cytometry plots.

This is the core rendering engine for the graph window.  It creates
a ``FigureCanvasQTAgg`` embedded in PyQt6 and handles:
- Scatter (dot) plots
- Pseudocolor (hexbin density) plots
- Contour plots
- Histograms (1-D)
- Density plots (KDE)
- CDF plots
- Interactive gate drawing (Rectangle, Polygon, Ellipse, Quadrant, Range)
- Gate overlay rendering with named, color-coded patches
- Gate selection and editing via drag handles

Mouse events are handled via matplotlib's ``mpl_connect`` system with a
state machine that manages drawing, selection, and editing modes.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

import numpy as np
import pandas as pd
from karcytics_sdk.interfaces.i_crash_reporter import ICrashReporter
from karcytics_sdk.plugin import CentralEventBus, get_logger
from karcytics_sdk.plugin.rendering.lock import MPL_RASTER_LOCK
from karcytics_sdk.plugin.rendering.mpl_canvas import LayeredMatplotlibCanvas
from matplotlib.figure import Figure
from PyQt6 import sip
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QSizePolicy

from karcytics_plugins.flow_cytometry.analysis import events
from karcytics_plugins.flow_cytometry.analysis.gating import (
    Gate,
    GateNode,
    QuadrantSubGate,
    RangeGate,
)
from karcytics_plugins.flow_cytometry.analysis.protocols import IGateCoordinator
from karcytics_plugins.flow_cytometry.analysis.scaling import AxisScale
from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.analysis.transforms import TransformType

from .canvas.axis_formatter import AxisFormatter

# Decomposed components
from .canvas.data_layer import FlowDataComputeStage, FlowDataRasterizeStage, FlowRenderState
from .canvas.event_handler import CanvasEventHandler, artist_contains_point
from .canvas.gate_layer import GateLayerRenderer
from .flow_services import (
    CoordinateMapper,
    GateFactory,
    GateOverlayRenderer,
    OverlayArtists,
)
from .gate_editor import RECTANGLE_HANDLE_ORDER, GateEditor

logger = get_logger(__name__, "flow_cytometry")


class DisplayMode(Enum):
    """Available plot display modes."""

    PSEUDOCOLOR = "Pseudocolor"
    DOT_PLOT = "Dot Plot"
    CONTOUR = "Contour"
    HISTOGRAM = "Histogram"
    CDF = "CDF"


class GateDrawingMode(Enum):
    """Active gate drawing tool."""

    NONE = "none"  # Default — pointer / selection mode
    RECTANGLE = "rectangle"
    POLYGON = "polygon"
    ELLIPSE = "ellipse"
    QUADRANT = "quadrant"
    RANGE = "range"


# ── Visual constants ─────────────────────────────────────────────────────────

# Plot area uses a pure white background inside the axes
# so all populations and density hexbins are perfectly visible.
_PLOT_BG = "#FFFFFF"

_MPL_STYLE = {
    "figure.facecolor": "#FFFFFF",
    "axes.facecolor": _PLOT_BG,
    "axes.edgecolor": "#333333",
    "axes.labelcolor": "#333333",
    "xtick.color": "#333333",
    "ytick.color": "#333333",
    "text.color": "#333333",
    "grid.color": "#E0E0E0",  # Light grey for visibility on white background
    "grid.alpha": 0.5,
    "font.size": 9,
    "axes.titlesize": 10,
    "axes.labelsize": 9,
    "xtick.labelsize": 8,
    "ytick.labelsize": 8,
}


class FlowCanvas(LayeredMatplotlibCanvas):
    """Interactive matplotlib canvas for flow cytometry plots.

    Signals:
        point_clicked(x, y):     Emitted on left-click with data coords.
        region_selected(dict):   Emitted when a rectangular selection is made.
        gate_created(Gate):      Emitted when a gate drawing is completed.
        gate_modified(str):      Emitted when a gate is edited (gate_id).
        gate_selected(str):      Emitted when a gate overlay is clicked (gate_id).
    """

    point_clicked = pyqtSignal(float, float)
    region_selected = pyqtSignal(dict)
    gate_created = pyqtSignal(object)  # Gate instance
    gate_modified = pyqtSignal(str)  # gate_id
    gate_selected = pyqtSignal(object)  # gate_id or None
    render_requested = pyqtSignal()  # Emitted on context menu "Render"
    quality_mode_changed = pyqtSignal(str)  # "optimized" or "transparent"
    gate_preview_emitted = pyqtSignal(object)  # Temporary gate object
    drawing_cancelled = pyqtSignal()  # Emitted when user cancels drawing via Esc

    def __init__(  # noqa: PLR0913, PLR0915
        self,
        state: FlowState | None = None,
        controller: IGateCoordinator | None = None,
        parent=None,
        crash_reporter: ICrashReporter | None = None,
    ) -> None:
        # Apply Karcytics theme
        import matplotlib

        for key, val in _MPL_STYLE.items():
            matplotlib.rcParams[key] = val  # type: ignore

        self._fig = Figure(figsize=(6, 5), dpi=100)
        self._fig.set_facecolor(_PLOT_BG)
        super().__init__(self._fig, crash_reporter=crash_reporter, plugin_id="flow_cytometry")
        self.setObjectName("FlowCanvas")
        self.setStyleSheet(f"background-color: {_PLOT_BG};")

        logger.info(f"FlowCanvas.__init__: state={state}, controller={controller}, parent={parent}")
        self._state = state
        self._controller = controller
        self.setParent(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._ax = self._fig.add_subplot(111)
        self._ax.set_facecolor(_PLOT_BG)
        self._ax.grid(True, color="#B0B0B0", alpha=0.35, linewidth=0.5)

        # Set fixed subplot margins once — avoids calling tight_layout()
        # which inspects every artist and crashes with non-standard ones.
        self._fig.subplots_adjust(left=0.12, bottom=0.12, right=0.95, top=0.95)

        # ── Data state ────────────────────────────────────────────────
        self._sample_id: str | None = None
        self._current_data: pd.DataFrame | None = None
        self._x_param: str = "FSC-A"
        self._y_param: str = "SSC-A"
        self._x_scale = AxisScale(TransformType.LINEAR)
        self._y_scale = AxisScale(TransformType.LINEAR)
        self._display_mode = DisplayMode.PSEUDOCOLOR
        self._x_label: str = "FSC-A"
        self._y_label: str = "SSC-A"
        self._fmo_sample_id: str | None = None

        self._guide_poly_patch: Any | None = None

        # ── Service instances (SOLID: Separation of concerns) ────────────
        # These services decouple rendering, drawing, and gate creation logic
        self._coordinate_mapper = CoordinateMapper(self._x_scale, self._y_scale)
        self._gate_factory = GateFactory(
            self._x_param,
            self._y_param,
            self._x_scale,
            self._y_scale,
            self._coordinate_mapper,
        )
        self._gate_overlay_renderer = GateOverlayRenderer(self._coordinate_mapper)
        self._gate_editor = GateEditor(self._coordinate_mapper)

        # ── Cached background bitmap ──────────────────────────────────
        # The expensive scatter data is rendered once and cached.
        # Gate overlays are drawn on top without re-rendering scatter.
        self._canvas_bitmap_cache = None  # Matplotlib canvas background bitmap for fast redraw
        self._gate_overlay_artists: dict = {}  # gate_id → OverlayArtists
        self._gate_artists: list = []  # matplotlib patches/lines for all gates

        # ── Gate drawing state machine ────────────────────────────────
        self._drawing_mode = GateDrawingMode.NONE

        # Gate Drawing FSM (Manages state, previews, and instructions)
        from .gate_drawing_fsm import GateDrawingFSM

        self._fsm = GateDrawingFSM(self)

        # ── Gate overlays ─────────────────────────────────────────────
        self._gate_patches: dict[str, dict] = {}  # gate_id → patch info
        self._active_gates: list[Gate] = []
        self._gate_nodes: list[GateNode] = []  # for stat labels
        self._selected_gate_id: str | None = None
        self._instruction_text = None  # on-canvas drawing hint

        # ── Setup ──────────────────────────────────────────────────────
        self._max_events: int | None = 100_000  # Default subsampling limit
        self._quality_multiplier: float = 1.0  # Grid resolution scaler
        self._use_cache: bool = True  # ENABLED for blitting

        # ── Signals ───────────────────────────────────────────────────
        from karcytics_sdk.plugin import CentralEventBus

        from ...analysis import events

        # Stored as bound attributes (not inline lambdas) so _cleanup_events
        # can unsubscribe the exact same callable later — CentralEventBus
        # matches subscribers by identity, so an anonymous lambda passed
        # straight to subscribe() can never be removed again.
        self._cb_gate_modified = lambda p: self._on_controller_geometry_changed(
            p.get("sample_id", ""), p.get("gate_id", "")
        )
        self._cb_gate_created = lambda p: self._on_controller_geometry_changed(
            p.get("sample_id", ""), p.get("gate_id", "")
        )
        self._cb_gates_created = lambda p: self._on_controller_geometry_changed(
            p.get("sample_id", ""), p.get("gate_id", "")
        )
        self._cb_gate_selected = lambda p: self._on_controller_selected(
            p.get("sample_id", ""), p.get("node_id", "")
        )
        self._cb_gate_deleted = lambda p: self._on_controller_gate_removed(
            p.get("sample_id", ""), p.get("node_id", "")
        )
        self._cb_gate_renamed = lambda p: self._on_controller_gate_renamed(
            p.get("sample_id", ""), p.get("node_id", "")
        )

        CentralEventBus.subscribe(events.GATE_MODIFIED, self._cb_gate_modified)
        CentralEventBus.subscribe(events.GATE_CREATED, self._cb_gate_created)
        CentralEventBus.subscribe(events.GATES_CREATED, self._cb_gates_created)
        CentralEventBus.subscribe(events.GATE_SELECTED, self._cb_gate_selected)
        CentralEventBus.subscribe(events.GATE_DELETED, self._cb_gate_deleted)
        CentralEventBus.subscribe(events.GATE_RENAMED, self._cb_gate_renamed)
        self.destroyed.connect(self._cleanup_events)

        # Mouse event connections
        self._mpl_conn_press = self.mpl_connect("button_press_event", self._on_press)
        self._mpl_conn_release = self.mpl_connect("button_release_event", self._on_release)
        self._cid_motion = self.mpl_connect("motion_notify_event", self._on_motion)
        self._mpl_conn_dblclick = self.mpl_connect("button_press_event", self._on_dblclick)
        self._cid_scroll = self.mpl_connect("scroll_event", self._on_scroll)
        self._cid_key = self.mpl_connect("key_press_event", self._on_key_press)
        self._cid_draw = self.mpl_connect("draw_event", self._on_draw)

        # ── Decomposed components ─────────────────────────────────────
        from .canvas.overlay_manager import OverlayManager
        from .canvas.zoom_handler import ZoomHandler

        self._overlay_manager = OverlayManager(self)
        self._zoom_handler = ZoomHandler(self)

        # ── Decomposed components ─────────────────────────────────────
        self.set_compute_stage(FlowDataComputeStage())
        self.set_rasterize_stage(FlowDataRasterizeStage(self))
        self.data_layer_finished.connect(self._on_data_layer_finished)
        self.data_layer_failed.connect(self._on_data_layer_failed)

        self._gate_renderer = GateLayerRenderer(self)
        self._event_handler = CanvasEventHandler(self)

        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        # Show empty state
        self._show_empty()

    def _apply_theme_styles(self) -> None:
        """Dynamically refresh canvas when theme changes."""
        if hasattr(self, "draw_idle"):
            self.draw_idle()

    def mouseDoubleClickEvent(self, event) -> None:
        """Intercept double clicks to prevent macOS fullscreen tearing.

        On macOS, QMainWindow interprets unhandled double-clicks as a
        title-bar toggle, dropping the app out of full screen. By explicitly
        accepting the event after Matplotlib processes it, we stop the
        bubbling.
        """
        super().mouseDoubleClickEvent(event)
        event.accept()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if getattr(self, "_dirty", False):
            self.redraw()

    def set_guide_polygon(self, vertices: list[tuple[float, float]] | None) -> None:
        """Draws a faint dark purple dotted polygon to guide tutorial users."""
        if self._guide_poly_patch:
            try:
                self._guide_poly_patch.remove()
            except (ValueError, AttributeError, NotImplementedError):
                pass
            self._guide_poly_patch = None

        if vertices:
            from matplotlib.patches import Polygon

            self._guide_poly_patch = Polygon(
                vertices,
                closed=True,
                fill=False,
                edgecolor="#800080",  # Dark purple
                linestyle="--",
                linewidth=2,
                alpha=0.8,
                zorder=100,  # Ensure it renders on top
            )
            self._ax.add_patch(self._guide_poly_patch)

        self.draw_idle()

    def set_tutorial_guide(self, step: Any | None) -> None:
        """Sets the active tutorial step, applies transforms to data bounds, and draws guides."""
        self._current_tutorial_step = step

        if not hasattr(self, "_guide_patches"):
            self._guide_patches: list[Any] = []

        # Clean up old patches
        for patch in self._guide_patches:
            try:
                patch.remove()
            except Exception:
                pass
        self._guide_patches.clear()

        # Backward compatibility for old `guide_poly` via the existing method
        old_poly = getattr(step, "guide_poly", None) if step else None
        self.set_guide_polygon(old_poly)

        if not step:
            self.draw_idle()
            return

        from karcytics_plugins.flow_cytometry.analysis.transforms import TransformType

        def _get_kwargs(scale):
            if scale.transform_type == TransformType.BIEXPONENTIAL:
                return {
                    "top": scale.logicle_t,
                    "width": scale.logicle_w,
                    "positive": scale.logicle_m,
                    "negative": scale.logicle_a,
                }
            return {}

        x_kwargs = _get_kwargs(self._x_scale)
        y_kwargs = _get_kwargs(self._y_scale)

        # Common style
        style: dict[str, Any] = {
            "fill": False,
            "edgecolor": "#800080",  # Dark purple
            "linestyle": "--",
            "linewidth": 2,
            "alpha": 0.8,
            "zorder": 100,
        }

        self._draw_tutorial_shapes(step, x_kwargs, y_kwargs, style)

        self.draw_idle()

    def _draw_tutorial_shapes(
        self, step: Any, x_kwargs: dict[str, Any], y_kwargs: dict[str, Any], style: dict[str, Any]
    ) -> None:
        """Draw metadata-driven tutorial shapes."""
        import numpy as np
        from matplotlib.patches import Polygon, Rectangle

        from karcytics_plugins.flow_cytometry.analysis.transforms import apply_transform

        # 1. guide_data_poly
        guide_data_poly = getattr(step, "metadata", {}).get("guide_data_poly")
        if guide_data_poly:
            xs = np.array([p[0] for p in guide_data_poly])
            ys = np.array([p[1] for p in guide_data_poly])
            txs = apply_transform(xs, self._x_scale.transform_type, **x_kwargs)
            tys = apply_transform(ys, self._y_scale.transform_type, **y_kwargs)
            vertices = list(zip(txs, tys, strict=True))
            patch = Polygon(vertices, closed=True, **style)
            self._ax.add_patch(patch)
            self._guide_patches.append(patch)

        # 2. guide_rect
        guide_rect = getattr(step, "metadata", {}).get("guide_rect")
        if guide_rect:
            min_x, max_x, min_y, max_y = guide_rect
            txs = apply_transform(
                np.array([min_x, max_x]), self._x_scale.transform_type, **x_kwargs
            )
            tys = apply_transform(
                np.array([min_y, max_y]), self._y_scale.transform_type, **y_kwargs
            )
            rect_patch = Rectangle((txs[0], tys[0]), txs[1] - txs[0], tys[1] - tys[0], **style)
            self._ax.add_patch(rect_patch)
            self._guide_patches.append(rect_patch)

        # 3. guide_range
        guide_range = getattr(step, "metadata", {}).get("guide_range")
        if guide_range:
            min_x, max_x = guide_range
            txs = apply_transform(
                np.array([min_x, max_x]), self._x_scale.transform_type, **x_kwargs
            )
            # Use axvspan instead of a patch so it spans the entire Y axis
            span = self._ax.axvspan(txs[0], txs[1], color="#800080", alpha=0.08, zorder=99)
            line1 = self._ax.axvline(
                txs[0], color="#800080", linestyle="--", linewidth=2, zorder=100
            )
            line2 = self._ax.axvline(
                txs[1], color="#800080", linestyle="--", linewidth=2, zorder=100
            )
            self._guide_patches.extend([span, line1, line2])

        # 4. guide_quadrant
        guide_quadrant = getattr(step, "metadata", {}).get("guide_quadrant")
        if guide_quadrant:
            x_thresh, y_thresh = guide_quadrant
            tx = apply_transform(np.array([x_thresh]), self._x_scale.transform_type, **x_kwargs)[0]
            ty = apply_transform(np.array([y_thresh]), self._y_scale.transform_type, **y_kwargs)[0]
            line_x = self._ax.axvline(tx, color="#800080", linestyle="--", linewidth=2, zorder=100)
            line_y = self._ax.axhline(ty, color="#800080", linestyle="--", linewidth=2, zorder=100)
            self._guide_patches.extend([line_x, line_y])

    def paintEvent(self, event) -> None:
        """Paint under a non-blocking RasterLock acquire, retrying if a background render task holds it.

        Overrides LayeredMatplotlibCanvas.paintEvent() only to retry via a
        sip.isdeleted()-guarded `_retry_update()` instead of `self.update`
        directly: a queued QTimer retry firing after this widget is
        destroyed crashes natively (not a catchable RuntimeError) since it
        runs from a QTimer callback rather than a normal Python call. Not
        wired to crash_reporter — deliberately, see LayeredMatplotlibCanvas's
        own paintEvent()/draw() docstrings (Qt lifecycle noise vs render bugs).
        """
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg

        self.raster_lock.try_run(
            lambda: FigureCanvasQTAgg.paintEvent(self, event), self._retry_update
        )

    def _retry_update(self) -> None:
        # This canvas is normally long-lived, but guard anyway: a queued
        # retry firing after the widget was destroyed would crash natively
        # (QTimer callback, not a normal Python call PyQt can intercept).
        if sip.isdeleted(self):
            return
        self.update()

    def draw(self) -> None:
        """Draw under a non-blocking RasterLock acquire. See paintEvent() for why this
        overrides LayeredMatplotlibCanvas.draw() rather than just inheriting it.
        """
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg

        self.raster_lock.try_run(lambda: FigureCanvasQTAgg.draw(self), self._retry_draw)

    def _retry_draw(self) -> None:
        if sip.isdeleted(self):
            return
        self.draw()

    def resizeEvent(self, event) -> None:
        """Keep the loading overlay centered over the canvas."""
        super().resizeEvent(event)
        logger.info(f"FlowCanvas resized: {self.width()}x{self.height()}")
        if hasattr(self, "_overlay_manager"):
            self._overlay_manager.resize_loading(self.width(), self.height())

    # ── coordinate mapping ────────────────────────────────────────────

    def set_sample_id(self, sample_id: str) -> None:
        """Set the sample ID for event publication context."""
        self._sample_id = sample_id

    # ── Public API ────────────────────────────────────────────────────

    def set_data(self, events: pd.DataFrame) -> None:
        """Set the event data for this canvas.

        Args:
            events: DataFrame with columns matching axis parameters.
        """
        self._current_data = events
        self.redraw()

    def set_axes(
        self,
        x_param: str,
        y_param: str,
        x_label: str = "",
        y_label: str = "",
    ) -> None:
        """Update axis parameters and labels.

        Args:
            x_param: Column name for X axis.
            y_param: Column name for Y axis.
            x_label: Display label for X axis.
            y_label: Display label for Y axis.
        """
        self._x_param = x_param
        self._y_param = y_param
        self._x_label = x_label or x_param
        self._y_label = y_label or y_param
        # Update services with new parameters
        self._gate_factory.update_params(x_param, y_param)
        self.redraw()

    def set_scales(
        self,
        x_scale: AxisScale,
        y_scale: AxisScale,
    ) -> None:
        """Update the axis scaling configurations.

        Args:
            x_scale: Scale configuration for X axis.
            y_scale: Scale configuration for Y axis.
        """
        self._x_scale = x_scale
        self._y_scale = y_scale
        # Update services with new scales
        self._coordinate_mapper.update_scales(x_scale, y_scale)
        self._gate_factory.update_scales(x_scale, y_scale)
        self.redraw()

    def set_display_mode(self, mode: DisplayMode) -> None:
        """Change the plot display mode.

        Args:
            mode: One of the :class:`DisplayMode` values.
        """
        self._display_mode = mode
        self.redraw()

    def set_fmo_overlay(self, sample_id: str) -> None:
        """Set the FMO overlay sample ID and trigger a redraw."""
        self._fmo_sample_id = sample_id or None
        self.redraw()

    def set_drawing_mode(self, mode: GateDrawingMode) -> None:
        """Set the active gate drawing tool.

        Args:
            mode: The drawing mode to activate.
        """
        self._cancel_drawing()
        self._drawing_mode = mode

        from PyQt6.QtCore import Qt as _Qt

        if mode == GateDrawingMode.NONE:
            self.setCursor(_Qt.CursorShape.ArrowCursor)
            self._hide_instruction()
        else:
            self.setCursor(_Qt.CursorShape.CrossCursor)
            self._show_instruction(mode)
            # Grab keyboard focus so Escape reaches keyPressEvent right away.
            # Every other tool's first "cancelable" moment is a click/drag,
            # which transfers focus to the canvas as a side effect. Quadrant
            # has no such moment — it finalizes on mouse *press* with no
            # drag — so its only in-progress phase is the crosshair preview
            # *before* any click, when focus would otherwise still be on
            # whichever ribbon button the user just clicked.
            self.setFocus()

    def set_gates(self, gates: list[Gate], gate_nodes: list[GateNode] | None = None) -> None:
        """Set the gates to render as overlays.

        Args:
            gates:      List of Gate objects to render.
            gate_nodes: Optional matching GateNode list for stat labels.
        """
        self._active_gates = gates
        self._gate_nodes = gate_nodes or []
        # Only redraw the gate layer — never re-render the scatter data
        self._gate_renderer.render()

    def select_gate(self, gate_id: str | None) -> None:
        """Programmatically select a gate overlay."""
        self._selected_gate_id = gate_id
        self._gate_renderer.render()

    def _on_transform_changed(self) -> None:
        """Called when a transform is modified (e.g. logicle params).

        Invalidates the bitmap cache so the plot is fully re-rendered
        in the next frame with new scales applied to the data.
        """
        logger.info("FlowCanvas: Transform changed, invalidating cache.")
        self._canvas_bitmap_cache = None
        self.redraw()

    def _auto_range_axes(self) -> None:
        """Request parent window to re-calculate auto-range for active axes."""
        # This is typically called when switching to Full quality
        # to ensure the plot is centered on the real data boundaries.
        parent = self.parent()
        while parent and not hasattr(parent, "_calculate_auto_range"):
            parent = parent.parent()

        if parent:
            # We use the parent's logic to compute and apply new scales
            x_min, x_max = parent._calculate_auto_range("x")
            y_min, y_max = parent._calculate_auto_range("y")

            # Update local scales (parent will also sync globally)
            parent._x_scale.min_val = x_min
            parent._x_scale.max_val = x_max
            parent._y_scale.min_val = y_min
            parent._y_scale.max_val = y_max

            self.set_scales(parent._x_scale, parent._y_scale)
            # Notify the system to refresh thumbnails and sidebar
            parent._notify_axis_change()

    # ── Batch update ───────────────────────────────────────────────

    def begin_update(self) -> None:
        """Start a batch update — suppress intermediate redraws."""
        self._batch_update = True

    def end_update(self) -> None:
        """End batch — perform a single redraw with final state."""
        self._batch_update = False
        self.redraw()

    def redraw(self) -> None:
        """Full redraw: render data layer (expensive) + gate layer (cheap)."""
        if getattr(self, "_batch_update", False):
            return

        # If the canvas is 0x0, defer the redraw until it has a size.
        if self.width() <= 0 or self.height() <= 0:
            logger.warning("Canvas redraw deferred: size is 0x0. Setting timer for retry.")
            from PyQt6.QtCore import QTimer

            QTimer.singleShot(200, self.redraw)
            return

        # Removed isVisible guard to ensure rendering even if Qt state is delayed
        self._dirty = False
        logger.info(
            "Canvas redraw triggered: data_size=%s, x=%s, y=%s, size=(%d, %d)",
            len(self._current_data) if self._current_data is not None else "None",
            self._x_param,
            self._y_param,
            self.width(),
            self.height(),
        )
        self._canvas_bitmap_cache = None  # Invalidate cached bitmap

        self._show_loading()

        # request_data_redraw() debounces internally (LayeredMatplotlibCanvas's
        # own _redraw_timer) — rapid successive redraw() calls (e.g. dragging
        # a slider) collapse into a single compute submission, same as before.
        self.request_data_redraw(self._snapshot_render_state(), debounce_ms=50)  # type: ignore[arg-type]

    def _snapshot_render_state(self) -> FlowRenderState:
        """Capture what FlowDataComputeStage.compute() needs, off the live canvas state.

        Called on the Qt main thread right before request_data_redraw();
        see FlowRenderState's own docstring for the reference-vs-copy tradeoff.
        """
        return FlowRenderState(
            current_data=self._current_data,
            x_param=self._x_param,
            y_param=self._y_param,
            x_scale=self._x_scale,
            y_scale=self._y_scale,
            display_mode=self._display_mode,
            x_label=self._x_label,
            y_label=self._y_label,
            fmo_sample_id=self._fmo_sample_id,
            flow_state=self._state,
            quality_multiplier=self._quality_multiplier,
            max_events=self._max_events,
            render_config=self._state.view.render_config if self._state else None,
        )

    def _on_data_layer_finished(self) -> None:
        """The data layer finished computing+rasterizing — redraw gate overlays on top of it."""
        self._hide_loading()
        self._gate_renderer.render()
        # Re-apply tutorial guides if they exist, because ax.clear() wiped them out
        step = getattr(self, "_current_tutorial_step", None)
        if step is not None:
            # Re-draw the shapes without calling set_tutorial_guide again to avoid infinite recursion
            # or we can just call self._draw_tutorial_shapes but we need the kwargs.
            # Instead, we just re-invoke set_tutorial_guide
            self.set_tutorial_guide(step)

        self.draw()  # Forced immediate draw instead of idle

    def _on_data_layer_failed(self, message: str) -> None:
        """FlowDataComputeStage.compute() itself raised — show the error and stop.

        Strategy-level and rasterize-level failures never reach here — they're
        already caught and shown via canvas._show_error() inside
        FlowDataRasterizeStage.rasterize() (a compute() failure is the only
        way to reach LayeredMatplotlibCanvas's data_layer_failed signal at all).
        """
        logger.error("Canvas render failed: %s", message)
        self._hide_loading()
        self._show_error(f"Render error: {message}")

    def _show_loading(self) -> None:
        """Show the loading overlay, keeping it on top."""
        if hasattr(self, "_overlay_manager"):
            self._overlay_manager.show_loading()

    def _hide_loading(self) -> None:
        """Hide the loading overlay."""
        if hasattr(self, "_overlay_manager"):
            self._overlay_manager.hide_loading()

    def _render_data_layer(self) -> None:
        """Trigger an (async) render of the expensive scatter/histogram data.

        Delegated to request_data_redraw() / FlowDataComputeStage+FlowDataRasterizeStage.
        """
        self.request_data_redraw(self._snapshot_render_state(), debounce_ms=0)  # type: ignore[arg-type]

    def _render_gate_layer(self) -> None:
        """Draw gate overlays on top of the cached data layer.

        Delegated to GateLayerRenderer.
        """
        self._gate_renderer.render()

    # ── Mouse event handlers — gate drawing state machine ─────────────

    def keyPressEvent(self, event) -> None:
        """Handle keyboard — Escape cancels drawing."""
        self._event_handler.handle_key_press(event)
        super().keyPressEvent(event)

    def _on_key_press(self, event) -> None:
        """Handle keyboard shortcuts for the canvas."""
        if getattr(event, "key", None) in ("f", "F"):
            self._auto_range_axes()

    def _on_draw(self, event) -> None:
        """Called by Matplotlib when a full draw is completed."""
        if getattr(self, "_use_cache", False):
            # Only cache if there are no gate artists on the axes. Otherwise, gates get baked in
            # and drawn repeatedly during fast UI updates (stacked rendering).
            if not getattr(self, "_gate_artists", []):
                self._canvas_bitmap_cache = self._fig.canvas.copy_from_bbox(self._ax.bbox)  # type: ignore

    def _on_scroll(self, event) -> None:
        """Handle scroll wheel to zoom in and out."""
        self._zoom_handler.handle_scroll(event)

    def _on_press(self, event) -> None:
        """Handle mouse press — start drawing or select gate."""
        self._event_handler.handle_press(event)

    def _on_motion(self, event) -> None:
        """Handle mouse movement — rubber-band preview during drawing."""
        self._event_handler.handle_motion(event)

    def _on_release(self, event) -> None:
        """Handle mouse release — finalize gate drawing."""
        self._event_handler.handle_release(event)

    def _on_dblclick(self, event) -> None:
        """Handle double-click — close polygon."""
        self._event_handler.handle_dblclick(event)

    def _finalize_drag_gate(self, x0: float, y0: float, x1: float, y1: float, mode: str) -> None:
        self._event_handler.finalize_drag_gate(x0, y0, x1, y1, mode)

    def _finalize_rectangle(self, x0, y0, x1, y1):
        # Kept for backward compatibility if needed, but FSM calls _finalize_drag_gate
        self._event_handler.finalize_drag_gate(x0, y0, x1, y1, "rectangle")

    def _finalize_polygon(self, vertices: list[tuple[float, float]]) -> None:
        self._event_handler.finalize_polygon(vertices)

    def _finalize_ellipse(self, x0: float, y0: float, x1: float, y1: float) -> None:
        self._event_handler.finalize_drag_gate(x0, y0, x1, y1, "ellipse")

    def _finalize_quadrant(self, x: float, y: float) -> None:
        self._event_handler.finalize_quadrant(x, y)

    def _finalize_range(self, x0: float, x1: float) -> None:
        self._event_handler.finalize_drag_gate(x0, 0, x1, 0, "range")

    def _try_select_gate(self, x: float, y: float, alt_cycle: bool = False) -> bool:
        return self._event_handler.try_select_gate(x, y, alt_cycle=alt_cycle)

    def _find_node_id_for_gate(self, gate_id: str) -> str | None:
        """Look up which node_id corresponds to this gate_id in active nodes."""
        for node in self._gate_nodes:
            if node.gate and node.gate.gate_id == gate_id:
                return node.node_id
        return None

    # ── Gate editing (drag handles) ────────────────────────────────────
    #
    # Only the *selected* gate ever exposes handles/body-move — this is
    # what keeps overlapping gates unambiguous: a gate must be explicitly
    # selected (top-most-wins click, or Alt+click cycling) before it can be
    # edited, so a drag never accidentally grabs whichever gate happens to
    # be underneath.

    def _find_selected_gate(self) -> Gate | None:
        """The Gate object behind `_selected_gate_id` (a GateNode.node_id)."""
        if not self._selected_gate_id:
            return None
        for node in self._gate_nodes:
            if node.node_id == self._selected_gate_id and node.gate is not None:
                return node.gate
        return None

    def _try_hit_edit_handle(self, x: float, y: float) -> tuple[Gate, str] | None:
        """Hit-test the selected gate's edit handles only.

        Uses a fixed pixel-space radius (via ax.transData) so the click
        target stays a constant screen size regardless of zoom/axis scale —
        GateEditor.get_handles() returns positions in transformed-data
        space, which has no fixed relationship to pixels.
        """
        gate = self._find_selected_gate()
        if gate is None:
            return None

        handles = self._gate_editor.get_handles(gate)
        if not handles:
            return None

        target = gate.parent if isinstance(gate, QuadrantSubGate) else gate
        x_only = isinstance(target, RangeGate)
        order = RECTANGLE_HANDLE_ORDER if hasattr(target, "x_min") else list(handles)

        mouse_px = self._ax.transData.transform((x, y))
        radius_px = 8.0
        best_key: str | None = None
        best_dist = radius_px
        for key in order:
            if key not in handles:
                continue
            hx, hy = handles[key]
            hx_px, hy_px = self._ax.transData.transform((hx, hy))
            dist = (
                abs(hx_px - mouse_px[0])
                if x_only
                else float(np.hypot(hx_px - mouse_px[0], hy_px - mouse_px[1]))
            )
            if dist <= best_dist:
                best_dist = dist
                best_key = key

        return (gate, best_key) if best_key is not None else None

    def _find_overlay_key_for_gate(self, gate: Gate) -> str | None:
        """Resolve which key in `_gate_overlay_artists` renders `gate`'s geometry.

        Quadrant crosshairs are drawn once per parent geometry — deduplicated
        in GateLayerRenderer._redraw_gate_overlays — keyed by whichever of the
        4 QuadrantSubGates happened to be encountered first while walking
        `_active_gates`, not necessarily the exact subgate instance that is
        currently selected/being edited. A direct `gate.gate_id` lookup can
        therefore miss the real entry for a quadrant even though its crosshair
        is on screen; resolve by parent identity in that case.
        """
        if gate.gate_id in self._gate_overlay_artists:
            return gate.gate_id
        if isinstance(gate, QuadrantSubGate):
            for key, info in self._gate_overlay_artists.items():
                candidate = info.get("gate")
                if isinstance(candidate, QuadrantSubGate) and candidate.parent is gate.parent:
                    return key
        return None

    def _try_hit_selected_gate_body(self, x: float, y: float) -> Gate | None:
        """Hit-test the selected gate's body (patch) for a whole-gate move drag.

        Range/Quadrant overlays use a Line2D as their `patch`, which has no
        enclosed area to represent a "body" — those types have no move
        affordance distinct from their handles (matches the plan: Quadrant's
        single center handle already *is* the move; Range's body-move is
        exposed via MOVE_HANDLE from its dedicated shaded span instead, see
        below).
        """
        gate = self._find_selected_gate()
        if gate is None:
            return None

        key = self._find_overlay_key_for_gate(gate)
        info = self._gate_overlay_artists.get(key) if key else None
        if not info:
            return None
        patch = info.get("patch")
        if patch is None:
            return None

        px, py = self._ax.transData.transform((x, y))

        target = gate.parent if isinstance(gate, QuadrantSubGate) else gate
        if isinstance(target, RangeGate):
            # The visible "body" is the shaded axvspan, tracked separately
            # from `patch` (which is the left boundary Line2D) — approximate
            # its hit test directly from the gate's own bounds instead.
            x_raw = self._coordinate_mapper.inverse_transform_x(np.array([x]))[0]
            return gate if target.low <= x_raw <= target.high else None

        if not hasattr(patch, "contains_point"):
            return None
        return gate if artist_contains_point(patch, px, py) else None

    def _iter_overlay_artists(self, artists: OverlayArtists | None):
        """Yield every real matplotlib artist inside an OverlayArtists bundle."""
        if artists is None:
            return
        if artists.patch is not None:
            yield artists.patch
        if hasattr(artists, "extra_artists") and artists.extra_artists:
            yield from artists.extra_artists
        if artists.label_text is not None:
            yield artists.label_text
        if artists.handles:
            yield from artists.handles.values()

    def _begin_gate_edit_preview(self, gate: Gate) -> None:
        """Remove `gate`'s current overlay artists and recapture the bitmap
        cache without them baked in.

        The blit fast-path used during the drag (restore_region + draw_artist
        + blit) only avoids ghosting for shapes that were never part of the
        cached bitmap in the first place — true for rubber-band creation
        previews, not true for editing an *existing* gate, whose old outline
        is already baked into `_canvas_bitmap_cache`. Removing it once here
        (a single full draw, at press time — not per motion frame) keeps the
        per-frame drag path exactly as cheap as rubber-band's.
        """
        key = self._find_overlay_key_for_gate(gate)
        info = self._gate_overlay_artists.pop(key, None) if key else None
        if info:
            for artist in self._iter_overlay_artists(info.get("artists")):
                try:
                    artist.remove()
                except (ValueError, AttributeError, NotImplementedError):
                    pass
                if artist in self._gate_artists:
                    self._gate_artists.remove(artist)
        self.draw()

    def _commit_gate_edit(self, gate: Gate, anchor: dict) -> None:
        """Apply one completed drag gesture — the single point per gesture
        where the real backend mutation (recompute stats, GATE_MODIFIED,
        debounced propagation) fires. Never called from motion handling.
        """
        kwargs = self._gate_editor.diff_kwargs(gate, anchor)
        if not kwargs or not self._controller or not self._sample_id:
            return

        success = self._controller.modify_gate(gate.gate_id, self._sample_id, **kwargs)
        if not success:
            # Validation rejected the edit (or gate/sample vanished mid-drag).
            # The live-drag preview already mutated `gate` in place with no
            # GATE_MODIFIED event to trigger a refresh, so without this the
            # visual would stay stuck at the rejected geometry.
            self._gate_editor.restore(gate, anchor)
            self.refresh_gates()

    # ── Controller Event Handlers ─────────────────────────────────────

    def _cleanup_events(self) -> None:
        """Unsubscribe from CentralEventBus when this canvas is destroyed.

        FlowCanvas instances are created and torn down on every graph tab
        open/close. Without this, a gate event published after a canvas is
        gone still reaches these callbacks (CentralEventBus.publish is
        queued, so delivery can happen after destruction) and touches a
        deleted Qt C++ object, crashing with "wrapped C/C++ object ... has
        been deleted".
        """
        try:
            from karcytics_sdk.plugin import CentralEventBus

            from ...analysis import events

            CentralEventBus.unsubscribe(events.GATE_MODIFIED, self._cb_gate_modified)
            CentralEventBus.unsubscribe(events.GATE_CREATED, self._cb_gate_created)
            CentralEventBus.unsubscribe(events.GATES_CREATED, self._cb_gates_created)
            CentralEventBus.unsubscribe(events.GATE_SELECTED, self._cb_gate_selected)
            CentralEventBus.unsubscribe(events.GATE_DELETED, self._cb_gate_deleted)
            CentralEventBus.unsubscribe(events.GATE_RENAMED, self._cb_gate_renamed)
        except Exception:
            pass

    def _on_controller_geometry_changed(self, sample_id: str, gate_id: str) -> None:
        """Update a specific gate overlay when its geometry changes elsewhere."""
        if sip.isdeleted(self):
            # CentralEventBus.publish is queued, so an event published just
            # before this canvas was torn down can still be delivered after
            # _cleanup_events already unsubscribed it — see that method's
            # docstring. Guard against the leftover delivery here too.
            return
        if sample_id != self._sample_id:
            return

        logger.debug(f"FlowCanvas: Handling geometry change for {gate_id}")
        self.update_gate_overlays()

    def _on_controller_selected(self, sample_id: str, node_id: str) -> None:
        """Update selection highlight when changed globally."""
        if sip.isdeleted(self):
            return
        if sample_id != self._sample_id:
            return

        self._selected_gate_id = node_id if node_id else None
        self.gate_selected.emit(self._selected_gate_id)
        self._gate_renderer.render()

    def _on_controller_gate_removed(self, sample_id: str, node_id: str) -> None:
        if sip.isdeleted(self):
            return
        if sample_id == self._sample_id:
            self.refresh_gates()

    def _on_controller_gate_renamed(self, sample_id: str, node_id: str) -> None:
        if sip.isdeleted(self):
            return
        if sample_id == self._sample_id:
            self._gate_renderer.render()

    def refresh_gates(self) -> None:
        """Fetch the latest gates from the controller and re-render."""
        if self._controller and self._sample_id:
            # Note: parent_node_id could be passed if we want to support nested gating view
            # For now, we assume root-level display or that the controller knows the context.
            gates, nodes = self._controller.get_gates_for_display(self._sample_id)
            self.set_gates(gates, nodes)
        else:
            self._gate_renderer.render()

    def update_gate_overlays(self) -> None:
        """Backward-compatible alias for refreshing and re-rendering gates."""
        self.refresh_gates()

    def _cancel_drawing(self) -> None:
        """Cancel the active drawing operation."""
        self._fsm.cancel()
        self._hide_instruction()
        self._clear_previews()

    def _clear_drawing_state(self) -> None:
        """Backward-compatible alias for clearing the drawing state."""
        self._cancel_drawing()
        self._drawing_mode = GateDrawingMode.NONE

    def _setup_axis_ticks(self) -> None:
        """Backward-compatible alias for axis tick setup."""
        AxisFormatter(self).apply_formatting()

    def _show_instruction(self, mode: GateDrawingMode) -> None:
        if hasattr(self, "_overlay_manager"):
            self._overlay_manager.show_instruction(mode)

    def _update_instruction(self, text: str) -> None:
        if hasattr(self, "_overlay_manager"):
            self._overlay_manager.update_instruction(text)

    def _hide_instruction(self) -> None:
        if hasattr(self, "_overlay_manager"):
            self._overlay_manager.hide_instruction()

    # ── Internal helpers ──────────────────────────────────────────────

    def _show_empty(self) -> None:
        if hasattr(self, "_overlay_manager"):
            self._overlay_manager.show_empty()

    def _show_error(self, msg: str) -> None:
        if hasattr(self, "_overlay_manager"):
            self._overlay_manager.show_error(msg)

    # ── Context Menu ──────────────────────────────────────────────────

    def _on_context_menu(self, pos) -> None:
        """Show context menu on right click."""
        from PyQt6.QtGui import QAction
        from PyQt6.QtWidgets import QMenu

        menu = QMenu(self)

        # Copy to clipboard
        copy_act = QAction("📋  Copy to Clipboard (PNG)", self)
        copy_act.triggered.connect(self._copy_to_clipboard)
        menu.addAction(copy_act)

        menu.addSeparator()

        # Download submenu
        download_menu = menu.addMenu("💾  Download")
        if download_menu:
            for fmt, suffix in [("PNG", "png"), ("PDF", "pdf"), ("SVG", "svg")]:
                action = QAction(fmt, self)
                action.triggered.connect(lambda checked=False, f=suffix: self._on_download_plot(f))
                download_menu.addAction(action)

        menu.exec(self.mapToGlobal(pos))

    def _copy_to_clipboard(self) -> None:
        """Render figure to PNG in memory and copy to system clipboard."""
        import io

        from PyQt6.QtGui import QImage
        from PyQt6.QtWidgets import QApplication

        try:
            buf = io.BytesIO()
            # savefig() triggers a full Agg rasterization pass — must hold
            # MPL_RASTER_LOCK the same as paintEvent()/draw() do, or this can race
            # a background RenderTask drawing this same Figure.
            with MPL_RASTER_LOCK:
                self._fig.savefig(buf, format="png", dpi=96, bbox_inches="tight")
            buf.seek(0)
            image = QImage()
            image.loadFromData(buf.read())

            clipboard = QApplication.clipboard()
            if clipboard:
                clipboard.setImage(image)
            logger.info("Plot copied to clipboard")
        except Exception as e:
            logger.error(f"Failed to copy plot: {e}")

    def _on_download_plot(self, fmt: str) -> None:
        """Download plot in specified format (png, pdf, or svg)."""
        from datetime import datetime

        from PyQt6.QtWidgets import QFileDialog

        # Generate default filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"flow_plot_{timestamp}.{fmt}"

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            f"Save plot as {fmt.upper()}",
            default_name,
            f"{fmt.upper()} (*.{fmt})",
        )

        if not file_path:
            return

        try:
            # DPI settings for different formats
            dpi = 300 if fmt == "pdf" else 150
            # See _copy_to_clipboard: savefig() needs MPL_RASTER_LOCK too.
            with MPL_RASTER_LOCK:
                self._fig.savefig(file_path, format=fmt, dpi=dpi, bbox_inches="tight")
            logger.info(f"Plot saved to {file_path}")
        except Exception as e:
            logger.error(f"Failed to save plot: {e}")

    def _clear_previews(self) -> None:
        """Clear temporary gate previews across all views."""
        CentralEventBus.publish(events.GATE_PREVIEW, {"gate": None})
