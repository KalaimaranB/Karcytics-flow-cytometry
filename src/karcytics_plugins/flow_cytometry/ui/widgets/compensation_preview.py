"""Before/after preview for the spillover matrix editor.

Draws the same events before and after compensation: as a scatter pair, as
overlaid histograms, or both. Rendering goes through the main plot's own
engine (``FlowDataComputeStage`` → display strategy → ``AxisFormatter``),
so the transforms, tick labels and render settings match the workspace plots.

Two steps, so many previews can be produced off the UI thread:
``plan_preview`` does the number work, ``draw_preview`` the matplotlib work.
``CompensationPreview`` runs both on a live canvas for one sample;
``render_preview_image`` runs both into an image, for a worker thread.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
from karcytics_sdk.plugin.rendering.lock import MPL_RASTER_LOCK
from karcytics_sdk.plugin.theme_fallback import Colors
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.patches import Patch

from karcytics_plugins.flow_cytometry.analysis.scaling import AxisScale, calculate_auto_range
from karcytics_plugins.flow_cytometry.ui.graph._mpl_compat import (
    LockedFigureCanvas,  # thread-safe vs RenderTask's Agg rasterization
)
from karcytics_plugins.flow_cytometry.ui.graph.canvas.axis_formatter import AxisFormatter
from karcytics_plugins.flow_cytometry.ui.graph.canvas.data_layer import (
    FlowDataComputeStage,
    FlowRenderData,
    FlowRenderState,
)
from karcytics_plugins.flow_cytometry.ui.graph.flow_canvas import DisplayMode
from karcytics_plugins.flow_cytometry.ui.graph.flow_services import CoordinateMapper

VIEW_SCATTER = "scatter"
VIEW_HISTOGRAM = "histogram"
VIEW_BOTH = "both"

_PLOT_BG = "#FFFFFF"
_BEFORE_COLOR = "#888888"
_IMAGE_DPI = 100


@dataclass
class PreviewRequest:
    """One preview: the same events before and after compensation."""

    before: pd.DataFrame
    after: pd.DataFrame
    x_param: str
    y_param: str
    x_scale: AxisScale
    y_scale: AxisScale
    view: str  # VIEW_SCATTER | VIEW_HISTOGRAM | VIEW_BOTH
    caption: str  # which sample and how many events
    render_config: Any | None = None


@dataclass
class PreviewPlan:
    """A request with everything computed, ready to draw."""

    request: PreviewRequest
    x_scale: AxisScale
    y_scale: AxisScale
    scatter: tuple[FlowRenderData, FlowRenderData] | None  # before, after
    histograms: list[tuple[str, AxisScale, FlowRenderData, FlowRenderData]]  # per channel

    @property
    def plot_count(self) -> int:
        return (2 if self.scatter else 0) + len(self.histograms)


# ── Number work (no matplotlib; safe on any thread) ───────────────────


def plan_preview(request: PreviewRequest) -> PreviewPlan:
    compute = FlowDataComputeStage()
    # One range per channel, covering both versions, so the two sides
    # can be compared by eye.
    x_scale = _shared_scale(request, request.x_param, request.x_scale)
    y_scale = _shared_scale(request, request.y_param, request.y_scale)

    def _computed(events: pd.DataFrame, mode: DisplayMode, x: str, y: str, xs, ys):
        return compute.compute(
            FlowRenderState(
                current_data=events,
                x_param=x,
                y_param=y,
                x_scale=xs,
                y_scale=ys,
                display_mode=mode,
                x_label=x,
                y_label=y,
                fmo_sample_id=None,
                flow_state=None,
                quality_multiplier=1.0,
                max_events=None,
                render_config=request.render_config,
            )
        )

    scatter = None
    if request.view in (VIEW_SCATTER, VIEW_BOTH):
        before, after = (
            _computed(
                events, DisplayMode.PSEUDOCOLOR, request.x_param, request.y_param, x_scale, y_scale
            )
            for events in (request.before, request.after)
        )
        scatter = (before, after)

    histograms = []
    if request.view in (VIEW_HISTOGRAM, VIEW_BOTH):
        for param, scale in ((request.x_param, x_scale), (request.y_param, y_scale)):
            before, after = (
                _computed(events, DisplayMode.HISTOGRAM, param, param, scale, scale)
                for events in (request.before, request.after)
            )
            histograms.append((param, scale, before, after))
    return PreviewPlan(request, x_scale, y_scale, scatter, histograms)


def _shared_scale(request: PreviewRequest, param: str, scale: AxisScale) -> AxisScale:
    """``scale`` with one explicit range covering ``param`` before and after."""
    shared = scale.copy()
    if shared.min_val is None or shared.max_val is None:
        values = np.concatenate(
            [
                frame[param].to_numpy(dtype=np.float64)
                for frame in (request.before, request.after)
                if param in frame.columns
            ]
            or [np.zeros(0)]
        )
        shared.min_val, shared.max_val = calculate_auto_range(values, shared.transform_type)
    return shared


# ── Matplotlib work ───────────────────────────────────────────────────


def draw_preview(fig: Figure, plan: PreviewPlan, single_row: bool = False) -> list[Any]:
    """Lay the plan's plots out on ``fig`` and draw them; returns the axes.

    Scatter pair first, then one histogram per channel. With both views they
    stack as two rows, unless ``single_row`` (a row in the all-samples list).
    """
    fig.clear()
    count = plan.plot_count
    rows = 1 if single_row or count <= 2 else 2  # noqa: PLR2004
    axes = [fig.add_subplot(rows, count // rows, index + 1) for index in range(count)]
    for ax in axes:
        ax.set_facecolor(_PLOT_BG)

    remaining = iter(axes)
    request = plan.request
    if plan.scatter is not None:
        before, after = plan.scatter
        # The biexponential transform isn't bit-for-bit repeatable, so the
        # two sides' own limits differ in the fourth decimal; pin both to
        # one pair so they are exactly comparable.
        limits = (before.xlim, before.ylim)
        for data, title in ((before, "Before — raw signal"), (after, "After — with this matrix")):
            ax = next(remaining)
            if _draw(ax, data):
                ax.set_ylim(limits[1])
                ax.set_title(title)
            ax.set_ylabel(request.y_param)
            _style(ax, DisplayMode.PSEUDOCOLOR, plan.x_scale, plan.y_scale, limits)
    for param, scale, before, after in plan.histograms:
        _draw_histogram(next(remaining), param, scale, before, after)

    fig.suptitle(request.caption, color=Colors.FG_SECONDARY, fontsize=9)
    return axes


def _draw_histogram(
    ax: Any, param: str, scale: AxisScale, before: FlowRenderData, after: FlowRenderData
) -> None:
    """``param`` before (grey) and after (the histogram colour), on shared bins."""
    after_color = after.strategy_kwargs.get("color", Colors.ACCENT_PRIMARY)
    before.strategy_kwargs = {
        **before.strategy_kwargs,
        "color": _BEFORE_COLOR,
        "bar_color": _BEFORE_COLOR,
    }
    # Both layers must draw for the comparison to mean anything.
    if not (_draw(ax, before) and _draw(ax, after)):
        return
    ax.set_title(f"{param} — before vs after")
    ax.legend(
        handles=[
            Patch(color=_BEFORE_COLOR, alpha=0.7, label="Before (raw)"),
            Patch(color=after_color, alpha=0.7, label="After (this matrix)"),
        ],
        fontsize=8,
        loc="upper right",
    )
    _style(ax, DisplayMode.HISTOGRAM, scale, scale, (after.xlim, None))


def _draw(ax: Any, data: FlowRenderData) -> bool:
    """Draw one computed layer; False (with the reason on the axes) if it can't be."""
    if data.strategy is None or data.strategy_data is None:
        ax.text(
            0.5,
            0.5,
            data.error_message or "No events to show",
            transform=ax.transAxes,
            ha="center",
            va="center",
            color="#777777",
        )
        return False
    ax.set_xlim(data.xlim)
    data.strategy.draw(ax, data.strategy_data, **data.strategy_kwargs)
    ax.set_xlim(data.xlim)  # the strategies autoscale the view
    ax.set_xlabel(data.x_label)
    return True


def _style(
    ax: Any, mode: DisplayMode, x_scale: AxisScale, y_scale: AxisScale, limits: tuple
) -> None:
    """Tick labels and theme colours; ``limits`` (xlim, ylim) are re-applied
    last because drawing and tick formatting both nudge the view.
    """
    # The attributes AxisFormatter reads off a canvas.
    AxisFormatter(
        SimpleNamespace(
            _ax=ax,
            _x_scale=x_scale,
            _y_scale=y_scale,
            _coordinate_mapper=CoordinateMapper(x_scale, y_scale),
            _display_mode=mode,
        )
    ).apply_formatting()
    ax.tick_params(colors=Colors.FG_PRIMARY, labelsize=8)
    for label in (ax.xaxis.label, ax.yaxis.label, ax.title):
        label.set_color(Colors.FG_PRIMARY)
    ax.xaxis.label.set_fontsize(9)
    ax.yaxis.label.set_fontsize(9)
    ax.title.set_fontsize(10)
    for spine in ax.spines.values():
        spine.set_color(Colors.BORDER)
    xlim, ylim = limits
    if xlim is not None:
        ax.set_xlim(xlim)
    if ylim is not None:
        ax.set_ylim(ylim)


def render_preview_image(
    request: PreviewRequest, width: int, height: int, pixel_ratio: float = 1.0
) -> dict:
    """Render ``request`` as one row of plots into an RGBA buffer.

    For worker threads: nothing here touches a widget. Returns
    ``{"image_data", "width", "height"}`` in device pixels.
    """
    plan = plan_preview(request)
    fig = Figure(
        figsize=(width / _IMAGE_DPI, height / _IMAGE_DPI),
        dpi=_IMAGE_DPI * pixel_ratio,
        facecolor=Colors.BG_DARKEST,
        layout="constrained",
    )
    canvas = FigureCanvasAgg(fig)
    # Matplotlib isn't thread-safe: every draw in the app shares this lock.
    with MPL_RASTER_LOCK:
        draw_preview(fig, plan, single_row=True)
        canvas.draw()
        buffer = bytes(canvas.buffer_rgba())
    pixel_width, pixel_height = canvas.get_width_height()
    return {"image_data": buffer, "width": pixel_width, "height": pixel_height}


class CompensationPreview:
    """Owns the live preview figure for one sample, redrawn from a ``PreviewRequest``."""

    def __init__(self) -> None:
        self._fig = Figure(figsize=(8, 4), facecolor=Colors.BG_DARKEST, layout="constrained")
        self.canvas = LockedFigureCanvas(self._fig)
        self.axes: list[Any] = []
        self.show_message("Select a sample to preview the matrix.")

    # The first two plots: the scatter pair, or the two histograms.
    @property
    def _left(self) -> Any:
        return self.axes[0]

    @property
    def _right(self) -> Any:
        return self.axes[1]

    def render(self, request: PreviewRequest) -> None:
        self.axes = draw_preview(self._fig, plan_preview(request))
        self.canvas.draw_idle()

    def show_message(self, message: str) -> None:
        self._fig.clear()
        self.axes = []
        self._fig.text(
            0.5, 0.5, message, ha="center", va="center", color=Colors.FG_SECONDARY, fontsize=10
        )
        self.canvas.draw_idle()
