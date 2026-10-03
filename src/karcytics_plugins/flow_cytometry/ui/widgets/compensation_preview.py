"""Before/after preview for the spillover matrix editor.

Draws the same events before and after compensation, as a scatter pair or as
overlaid histograms. Rendering goes through the main plot's own engine
(``FlowDataComputeStage`` → display strategy → ``AxisFormatter``), so the
transforms, tick labels and render settings match the workspace plots.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
from karcytics_sdk.plugin.theme_fallback import Colors
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

_PLOT_BG = "#FFFFFF"
_BEFORE_COLOR = "#888888"


@dataclass
class PreviewRequest:
    """One preview: the same events before and after compensation."""

    before: pd.DataFrame
    after: pd.DataFrame
    x_param: str
    y_param: str
    x_scale: AxisScale
    y_scale: AxisScale
    view: str  # VIEW_SCATTER | VIEW_HISTOGRAM
    caption: str  # which sample and how many events
    render_config: Any | None = None


class CompensationPreview:
    """Owns the preview figure: two axes, redrawn from a ``PreviewRequest``."""

    def __init__(self) -> None:
        self._fig = Figure(figsize=(8, 4), facecolor=Colors.BG_DARKEST, layout="constrained")
        self.canvas = LockedFigureCanvas(self._fig)
        self._left = self._fig.add_subplot(121)
        self._right = self._fig.add_subplot(122)
        self._compute = FlowDataComputeStage()
        self.show_message("Select a sample to preview the matrix.")

    # ── Public API ────────────────────────────────────────────────────

    def render(self, request: PreviewRequest) -> None:
        self._clear()
        # One range per channel, covering both versions, so the two sides
        # can be compared by eye.
        x_scale = self._shared_scale(request, request.x_param, request.x_scale)
        y_scale = self._shared_scale(request, request.y_param, request.y_scale)

        if request.view == VIEW_HISTOGRAM:
            self._draw_histogram(self._left, request, request.x_param, x_scale)
            self._draw_histogram(self._right, request, request.y_param, y_scale)
        else:
            before, after = (
                self._computed(
                    request,
                    events,
                    DisplayMode.PSEUDOCOLOR,
                    request.x_param,
                    request.y_param,
                    x_scale,
                    y_scale,
                )
                for events in (request.before, request.after)
            )
            # The biexponential transform isn't bit-for-bit repeatable, so the
            # two sides' own limits differ in the fourth decimal; pin both to
            # one pair so they are exactly comparable.
            limits = (before.xlim, before.ylim)
            for ax, data, title in (
                (self._left, before, "Before — raw signal"),
                (self._right, after, "After — with this matrix"),
            ):
                self._draw_scatter(ax, data, limits, title)
                ax.set_ylabel(request.y_param)
                self._style(ax, DisplayMode.PSEUDOCOLOR, x_scale, y_scale, limits)

        self._fig.suptitle(request.caption, color=Colors.FG_SECONDARY, fontsize=9)
        self.canvas.draw_idle()

    def show_message(self, message: str) -> None:
        self._clear()
        self._right.set_axis_off()
        self._left.set_axis_off()
        self._fig.suptitle("")
        self._fig.text(
            0.5, 0.5, message, ha="center", va="center", color=Colors.FG_SECONDARY, fontsize=10
        )
        self.canvas.draw_idle()

    # ── Drawing ───────────────────────────────────────────────────────

    def _clear(self) -> None:
        for text in list(self._fig.texts):
            text.remove()
        for ax in (self._left, self._right):
            ax.clear()
            ax.set_axis_on()
            ax.set_facecolor(_PLOT_BG)

    def _draw_scatter(self, ax: Any, data: FlowRenderData, limits: tuple, title: str) -> None:
        if self._draw(ax, data):
            ax.set_ylim(limits[1])
            ax.set_title(title)

    def _draw_histogram(
        self, ax: Any, request: PreviewRequest, param: str, scale: AxisScale
    ) -> None:
        """``param`` before (grey) and after (the histogram colour), on shared bins."""
        before, after = (
            self._computed(request, events, DisplayMode.HISTOGRAM, param, param, scale, scale)
            for events in (request.before, request.after)
        )
        after_color = after.strategy_kwargs.get("color", Colors.ACCENT_PRIMARY)
        before.strategy_kwargs = {
            **before.strategy_kwargs,
            "color": _BEFORE_COLOR,
            "bar_color": _BEFORE_COLOR,
        }
        # Both layers must draw for the comparison to mean anything.
        if not (self._draw(ax, before) and self._draw(ax, after)):
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
        self._style(ax, DisplayMode.HISTOGRAM, scale, scale, (after.xlim, None))

    def _computed(  # noqa: PLR0913
        self,
        request: PreviewRequest,
        events: pd.DataFrame,
        mode: DisplayMode,
        x_param: str,
        y_param: str,
        x_scale: AxisScale,
        y_scale: AxisScale,
    ) -> FlowRenderData:
        return self._compute.compute(
            FlowRenderState(
                current_data=events,
                x_param=x_param,
                y_param=y_param,
                x_scale=x_scale,
                y_scale=y_scale,
                display_mode=mode,
                x_label=x_param,
                y_label=y_param,
                fmo_sample_id=None,
                flow_state=None,
                quality_multiplier=1.0,
                max_events=None,
                render_config=request.render_config,
            )
        )

    @staticmethod
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

    @staticmethod
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

    @staticmethod
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
