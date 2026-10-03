"""Gate histogram panel — the displayed population as X and Y histograms.

A second view of the gate being drawn on the main plot: each histogram shows
the population in grey with the events inside the gate drawn over it, and
updates as the gate is drawn or dragged.

Renders through the main canvas's own pipeline (``FlowDataComputeStage`` →
``HistogramStrategy`` on a ``LayeredMatplotlibCanvas``), so bins, transforms
and render settings match the main plot's Histogram mode.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pandas as pd
from karcytics_sdk.plugin import CentralEventBus, get_logger
from karcytics_sdk.plugin.rendering.mpl_canvas import LayeredMatplotlibCanvas
from karcytics_sdk.plugin.rendering.pipeline import RasterizeStage
from matplotlib.figure import Figure
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget

from karcytics_plugins.flow_cytometry.analysis import events
from karcytics_plugins.flow_cytometry.analysis.constants import (
    GATE_DRAWING_COLOR,
    GATE_SELECTED_COLOR,
)
from karcytics_plugins.flow_cytometry.analysis.fcs_io import derived_labels_of
from karcytics_plugins.flow_cytometry.analysis.gating import Gate, QuadrantGate, RangeGate
from karcytics_plugins.flow_cytometry.analysis.gating.projection import axis_interval
from karcytics_plugins.flow_cytometry.analysis.scaling import AxisScale
from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.analysis.transforms import TransformType
from karcytics_plugins.flow_cytometry.ui.graph.canvas.axis_formatter import AxisFormatter
from karcytics_plugins.flow_cytometry.ui.graph.canvas.data_layer import (
    FlowDataComputeStage,
    FlowRenderData,
    FlowRenderState,
)
from karcytics_plugins.flow_cytometry.ui.graph.flow_canvas import DisplayMode
from karcytics_plugins.flow_cytometry.ui.graph.flow_services import (
    CoordinateMapper,
    GateOverlayRenderer,
)

logger = get_logger(__name__, "flow_cytometry")

_PLOT_BG = "#FFFFFF"
_TEXT_COLOR = "#333333"
# One render per interval however fast previews and model events arrive.
_REFRESH_INTERVAL_MS = 100

# Model changes that can alter the population, its axes or how it is drawn.
# Selection is not here: the owning panel pushes it through ``set_context``.
_REFRESH_TOPICS = (
    events.GATE_CREATED,
    events.GATES_CREATED,
    events.GATE_MODIFIED,
    events.GATE_DELETED,
    events.AXIS_PARAMS_CHANGED,
    events.AXIS_RANGE_CHANGED,
    events.TRANSFORM_CHANGED,
    events.RENDER_CONFIG_CHANGED,
    events.SAMPLE_UPDATED,
    events.EXPERIMENT_DATA_CHANGED,
    events.STATE_RESTORED,
)

# (low, high, color) of a gate's edges along one axis, in raw data space.
Boundary = tuple[float, float, str]


class _HistogramRasterizeStage(RasterizeStage):
    """Draws one computed histogram, plus the gate's edges, onto the canvas axes."""

    def __init__(self, canvas: GateHistogramCanvas) -> None:
        self._canvas = canvas

    def rasterize(self, target: Any, data: Any) -> None:
        ax = target
        render_data: FlowRenderData = data
        ax.set_facecolor(_PLOT_BG)

        if render_data.mode != "1d" or render_data.strategy_data is None:
            self._show_message(ax, render_data.error_message or "No events to show")
            return

        assert render_data.strategy is not None
        ax.set_xlim(render_data.xlim)
        render_data.strategy.draw(ax, render_data.strategy_data, **render_data.strategy_kwargs)
        ax.set_xlim(render_data.xlim)  # hist() autoscales the view

        ax.set_xlabel(render_data.x_label, fontsize=8, color=_TEXT_COLOR)
        ax.yaxis.label.set_fontsize(8)
        ax.tick_params(colors=_TEXT_COLOR, labelsize=7)
        ax.locator_params(nbins=5)  # the plot is narrow; default ticks crowd
        AxisFormatter(self._canvas).apply_formatting()
        self._draw_boundary(ax)

    def _draw_boundary(self, ax: Any) -> None:
        boundary = self._canvas.boundary
        if boundary is None:
            return
        low, high, color = boundary
        xlim, ylim = ax.get_xlim(), ax.get_ylim()
        renderer = GateOverlayRenderer(
            self._canvas._coordinate_mapper, linewidth=1.0, show_labels=False
        )
        renderer.render_range(ax, RangeGate("", low=low, high=high), color=color)
        ax.set_xlim(xlim)
        ax.set_ylim(ylim)

    @staticmethod
    def _show_message(ax: Any, message: str) -> None:
        ax.set_axis_off()
        ax.text(
            0.5,
            0.5,
            message,
            transform=ax.transAxes,
            ha="center",
            va="center",
            fontsize=8,
            color="#777777",
        )


class GateHistogramCanvas(LayeredMatplotlibCanvas):
    """A small histogram canvas on the main plot's async render pipeline."""

    def __init__(self, parent: QWidget | None = None, task_scheduler: Any | None = None) -> None:
        # Constrained layout sizes the margins from the labels' real extents on
        # every draw; fixed fractions clip the x label once the plot gets short.
        self._fig = Figure(figsize=(3, 2), dpi=100, layout="constrained")
        self._fig.set_facecolor(_PLOT_BG)
        super().__init__(
            self._fig, task_scheduler=task_scheduler, parent=parent, plugin_id="flow_cytometry"
        )
        self.setObjectName("GateHistogramCanvas")
        self.setMinimumHeight(110)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._ax = self._fig.add_subplot(111)

        # What AxisFormatter reads off a canvas. A histogram has one data
        # axis, so the same scale stands in for both.
        self._x_scale = self._y_scale = AxisScale(TransformType.LINEAR)
        self._coordinate_mapper = CoordinateMapper(self._x_scale, self._y_scale)
        self._display_mode = DisplayMode.HISTOGRAM

        self.boundary: Boundary | None = None

        self.set_compute_stage(FlowDataComputeStage())
        self.set_rasterize_stage(_HistogramRasterizeStage(self))

    def show_histogram(self, render_state: FlowRenderState, boundary: Boundary | None) -> None:
        """Render ``render_state`` (async); ``boundary`` marks the gate's edges."""
        self._x_scale = self._y_scale = render_state.x_scale
        self._coordinate_mapper.update_scales(self._x_scale, self._y_scale)
        self.boundary = boundary
        self.request_data_redraw(render_state)  # type: ignore[arg-type]


class GateHistogramPanel(QWidget):
    """X and Y histograms of the displayed population, with one gate highlighted.

    The highlighted gate is the one being drawn or dragged on the main plot,
    else the selected gate if it is drawn on the displayed population, else
    none (a plain histogram).
    """

    def __init__(
        self,
        state: FlowState,
        axis_manager: Any,
        population_service: Any,
        parent: QWidget | None = None,
        task_scheduler: Any | None = None,
    ) -> None:
        super().__init__(parent)
        self._state = state
        self._axis_manager = axis_manager
        self._population_service = population_service

        self._sample_id: str | None = None
        self._node_id: str | None = None  # displayed population (None = root)
        self._selected_node_id: str | None = None
        self._preview_gate: Gate | None = None

        # The displayed population's two axis columns, capped — reused across
        # preview frames, so a drag only costs the gate's own mask.
        self._frame: pd.DataFrame | None = None
        self._frame_key: tuple | None = None

        self._is_alive = True
        self._stale = True  # nothing rendered yet

        self.setObjectName("GateHistogramPanel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        self._x_canvas = GateHistogramCanvas(self, task_scheduler)
        self._y_canvas = GateHistogramCanvas(self, task_scheduler)
        layout.addWidget(self._x_canvas, stretch=1)
        layout.addWidget(self._y_canvas, stretch=1)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(_REFRESH_INTERVAL_MS)
        self._refresh_timer.timeout.connect(self._render)

        # Kept as one list so cleanup() unsubscribes the exact callables that
        # were subscribed — CentralEventBus matches subscribers by identity.
        self._subscriptions: list[tuple[str, Callable[..., None]]] = [
            (events.GATE_PREVIEW, self._on_gate_preview)
        ]
        self._subscriptions += [(topic, self._on_model_changed) for topic in _REFRESH_TOPICS]
        for topic, callback in self._subscriptions:
            CentralEventBus.subscribe(topic, callback)
        self.destroyed.connect(self.cleanup)

    # ── Public API ────────────────────────────────────────────────────

    def set_context(
        self, sample_id: str | None, node_id: str | None, selected_node_id: str | None
    ) -> None:
        """Set the displayed population and the currently selected node."""
        if (sample_id, node_id, selected_node_id) == (
            self._sample_id,
            self._node_id,
            self._selected_node_id,
        ):
            return
        self._sample_id = sample_id
        self._node_id = node_id
        self._selected_node_id = selected_node_id
        self.refresh()

    def refresh(self) -> None:
        """Re-read the population and re-render (throttled)."""
        self._frame_key = None
        self._schedule_render()

    def cleanup(self) -> None:
        """Unsubscribe from the event bus; safe to call more than once."""
        if not self._is_alive:
            return
        self._is_alive = False
        try:
            self._refresh_timer.stop()
        except RuntimeError:
            pass  # the C++ timer is already gone
        for topic, callback in self._subscriptions:
            CentralEventBus.unsubscribe(topic, callback)

    # ── Events ────────────────────────────────────────────────────────

    def _on_gate_preview(self, data: dict) -> None:
        self._preview_gate = data.get("gate")
        self._schedule_render()

    def _on_model_changed(self, _data: dict | None = None) -> None:
        self.refresh()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if self._stale:
            self._schedule_render()

    def _schedule_render(self) -> None:
        if not self._is_alive:
            return
        try:
            if not self._refresh_timer.isActive():
                self._refresh_timer.start()
        except RuntimeError:
            self.cleanup()  # the C++ timer was deleted under us

    # ── Rendering ─────────────────────────────────────────────────────

    def _render(self) -> None:
        if not self._is_alive:
            return
        if not self.isVisible():
            self._stale = True  # showEvent picks it up
            return
        self._stale = False

        x_param = self._state.view.active_x_param
        y_param = self._state.view.active_y_param
        frame = self._population_frame(x_param, y_param)
        gate, color = self._highlight(x_param, y_param)
        # A quadrant gate contains every event; only its divider is worth showing.
        overlay = None if isinstance(gate, QuadrantGate) else gate

        for canvas, param in ((self._x_canvas, x_param), (self._y_canvas, y_param)):
            interval = axis_interval(gate, param) if gate is not None else None
            canvas.show_histogram(
                self._render_state(frame, param, overlay),
                (*interval, color) if interval else None,
            )

    def _render_state(
        self, frame: pd.DataFrame | None, param: str, highlight_gate: Gate | None
    ) -> FlowRenderState:
        scale = self._axis_manager.get_scale(param, self._sample_id).copy()
        return FlowRenderState(
            current_data=frame,
            x_param=param,
            y_param=param,
            x_scale=scale,
            y_scale=scale,
            display_mode=DisplayMode.HISTOGRAM,
            x_label=self._label(param),
            y_label="",
            fmo_sample_id=None,
            flow_state=None,
            quality_multiplier=1.0,
            max_events=None,
            render_config=self._state.view.render_config,
            highlight_gate=highlight_gate,
        )

    def _label(self, param: str) -> str:
        sample = self._state.data.experiment.samples.get(self._sample_id or "")
        return derived_labels_of(sample.fcs_data).get(param, param) if sample else param

    def _population_frame(self, x_param: str, y_param: str) -> pd.DataFrame | None:
        key = (self._sample_id, self._node_id, x_param, y_param)
        if key != self._frame_key:
            self._frame_key = key
            self._frame = self._load_frame(x_param, y_param)
        return self._frame

    def _load_frame(self, x_param: str, y_param: str) -> pd.DataFrame | None:
        if not self._sample_id:
            return None
        population = self._population_service.get_gated_events(self._sample_id, self._node_id)
        if population is None:
            return None
        columns = [c for c in dict.fromkeys((x_param, y_param)) if c in population.columns]
        frame = population[columns]
        # Same cap, same seed, as the scatter these histograms sit beside.
        cap = self._state.view.render_config.max_events
        if cap and len(frame) > cap:
            frame = frame.sample(n=cap, random_state=42)
        return frame

    def _highlight(self, x_param: str, y_param: str) -> tuple[Gate | None, str]:
        """The gate to highlight (a private copy) and the colour of its edges."""
        previewing = self._preview_gate is not None
        gate = self._preview_gate if previewing else self._selected_gate()
        color = GATE_DRAWING_COLOR if previewing else GATE_SELECTED_COLOR
        if gate is None:
            return None, color
        gate_params = {p for p in (gate.x_param, gate.y_param) if p}
        if not gate_params <= {x_param, y_param}:
            return None, color  # drawn on axes that aren't on screen
        # Copied: the live gate is mutated on this thread while it is being
        # dragged, and this one is read on the compute thread.
        return gate.copy(), color

    def _selected_gate(self) -> Gate | None:
        """The selected node's gate, if it gates the displayed population."""
        if not (self._sample_id and self._selected_node_id):
            return None
        node = self._population_service.find_node(self._sample_id, self._selected_node_id)
        if node is None or node.gate is None or not node.parents:
            return None
        parent = node.parents[0]
        displayed = parent.is_root if self._node_id is None else parent.node_id == self._node_id
        return node.gate if displayed else None
