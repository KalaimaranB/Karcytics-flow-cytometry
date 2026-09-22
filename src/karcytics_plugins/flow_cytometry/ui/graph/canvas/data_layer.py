"""Data layer compute/rasterize split for FlowCanvas.

Splits the old synchronous ``DataLayerRenderer.render()`` into a pure
numpy/pandas ``FlowDataComputeStage.compute()`` (runs off the Qt main
thread, via ``FlowCanvas.request_data_redraw()``) and a matplotlib-only
``FlowDataRasterizeStage.rasterize()`` (runs under ``MPL_RASTER_LOCK`` on
the thread that owns the Figure — see ``karcytics_sdk.plugin.rendering``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np
from karcytics_sdk.plugin import get_logger
from karcytics_sdk.plugin.rendering.pipeline import RasterizeStage, RenderComputeStage, RenderData

from karcytics_plugins.flow_cytometry.analysis.scaling import (
    compute_axis_limits as _compute_limits,
)
from karcytics_plugins.flow_cytometry.analysis.scaling import (
    get_transform_kwargs as _get_transform_kwargs,
)
from karcytics_plugins.flow_cytometry.analysis.transforms import apply_transform

from ..renderers.factory import RenderStrategyFactory

if TYPE_CHECKING:
    import pandas as pd

    from karcytics_plugins.flow_cytometry.analysis.scaling import AxisScale
    from karcytics_plugins.flow_cytometry.analysis.state import FlowState
    from karcytics_plugins.flow_cytometry.ui.graph.renderers.base import DisplayStrategy

    from ..flow_canvas import DisplayMode, FlowCanvas

logger = get_logger(__name__, "flow_cytometry")


@dataclass
class FlowRenderState:
    """Immutable-in-spirit snapshot of what a data-layer render needs.

    Captured on the Qt main thread (see ``FlowCanvas._snapshot_render_state``)
    before being handed to a background thread's ``compute()`` call. Holds
    references rather than deep copies of ``x_scale``/``y_scale``/``flow_state``
    — the same tradeoff ``RenderTask`` already makes for its own thumbnail
    path — so a scale object mutated in place *after* this snapshot was taken
    (rather than replaced wholesale, which is how ``FlowCanvas.set_scales()``
    normally does it) could race with an in-flight compute(). Narrow,
    pre-existing exposure, not introduced by this split.
    """

    current_data: pd.DataFrame | None
    x_param: str
    y_param: str
    x_scale: AxisScale
    y_scale: AxisScale
    display_mode: DisplayMode
    x_label: str
    y_label: str
    fmo_sample_id: str | None
    flow_state: FlowState | None
    quality_multiplier: float
    max_events: int | None
    render_config: Any | None


@dataclass
class FlowRenderData(RenderData):
    """What a compute() call hands to rasterize(): everything needed to draw."""

    mode: str = "empty"  # "empty" | "error" | "1d" | "2d"
    error_message: str = ""
    x_label: str = ""
    y_label: str = ""
    xlim: tuple[float, float] | None = None
    ylim: tuple[float, float] | None = None
    strategy: DisplayStrategy | None = None
    strategy_data: Any = None
    strategy_kwargs: dict = field(default_factory=dict)
    event_count: int = 0


class FlowDataComputeStage(RenderComputeStage):
    """Pure numpy/pandas half of the data-layer render — never touches a Figure/Axes."""

    def __init__(self, plugin_id: str = "flow_cytometry") -> None:
        super().__init__(plugin_id)

    def compute(self, state: Any | None) -> FlowRenderData:  # noqa: PLR0912
        """`raw_state` must be a `FlowRenderState`; typed `Any` to satisfy
        `RenderComputeStage`'s `PluginState | None` signature — this stage is
        only ever paired with `FlowCanvas.request_data_redraw()`, which
        always passes one.
        """
        flow_state: FlowRenderState | None = state
        if flow_state is None or flow_state.current_data is None or flow_state.current_data.empty:
            return FlowRenderData(mode="empty")

        df = flow_state.current_data
        if flow_state.x_param not in df.columns:
            return FlowRenderData(
                mode="error", error_message=f"Channel '{flow_state.x_param}' not found"
            )

        x_raw = df[flow_state.x_param].values.astype(np.float64)

        from ..flow_canvas import DisplayMode

        if flow_state.display_mode in (DisplayMode.HISTOGRAM, DisplayMode.CDF):
            result = self._compute_1d(flow_state, x_raw)
            if result is not None:
                return result
            # 1D compute failed — fall through to the 2D fallback path below,
            # matching the old DataLayerRenderer._render_1d()'s "return False" behavior.

        return self._compute_2d(flow_state, df, x_raw)

    def _compute_1d(self, state: FlowRenderState, x_raw: np.ndarray) -> FlowRenderData | None:
        try:
            strategy = RenderStrategyFactory.get_strategy(state.display_mode.value)
            x_kwargs = _get_transform_kwargs(state.x_scale)
            x_transformed = apply_transform(x_raw, state.x_scale.transform_type, **x_kwargs)
            xlim = _compute_limits(x_raw, state.x_scale, x_kwargs)

            fmo_data_x = None
            if state.fmo_sample_id and state.flow_state is not None:
                samples = state.flow_state.data.experiment.samples  # type: ignore[union-attr]
                fmo_sample = samples.get(state.fmo_sample_id) if samples else None
                if (
                    fmo_sample
                    and fmo_sample.fcs_data is not None
                    and state.x_param in fmo_sample.fcs_data.events  # type: ignore[operator]
                ):
                    fmo_raw_x = fmo_sample.fcs_data.events[  # type: ignore[index]
                        state.x_param
                    ].values.astype(np.float64)
                    fmo_data_x = apply_transform(
                        fmo_raw_x, state.x_scale.transform_type, **x_kwargs
                    )

            render_kwargs_1d: dict[str, Any] = {}
            if state.render_config:
                from ..flow_canvas import DisplayMode

                if state.display_mode == DisplayMode.HISTOGRAM:
                    h = state.render_config.histogram
                    render_kwargs_1d.update(
                        {
                            "bar_color": h.bar_color,
                            "color": h.bar_color,
                            "bins": h.bins,
                            "auto_bins": h.auto_bins,
                            "y_axis_mode": h.y_axis_mode,
                            "density": (h.y_axis_mode == "frequency"),
                            "filled": h.filled,
                            "smooth_kde": h.smooth_kde,
                            "fmo_color": getattr(h, "fmo_color", "#888888"),
                            "show_fmo_threshold": getattr(h, "show_fmo_threshold", True),
                            "fmo_threshold_percentile": getattr(
                                h, "fmo_threshold_percentile", 99.0
                            ),
                            "fmo_threshold_color": getattr(h, "fmo_threshold_color", "#ff4444"),
                        }
                    )

            kwargs_1d = {**render_kwargs_1d, "fmo_data_x": fmo_data_x}
            strategy_data = strategy.compute(x_transformed, None, **kwargs_1d)

            return FlowRenderData(
                mode="1d",
                x_label=state.x_label,
                xlim=xlim,
                strategy=strategy,
                strategy_data=strategy_data,
                strategy_kwargs=kwargs_1d,
            )
        except Exception as e:
            logger.error(f"1D Strategy compute failed: {e}", exc_info=True)
            return None

    def _compute_2d(
        self, state: FlowRenderState, df: pd.DataFrame, x_raw: np.ndarray
    ) -> FlowRenderData:  # noqa: PLR0912
        if state.y_param not in df.columns:
            return FlowRenderData(
                mode="error", error_message=f"Channel '{state.y_param}' not found"
            )

        y_raw = df[state.y_param].values.astype(np.float64)

        x_kwargs = _get_transform_kwargs(state.x_scale)
        y_kwargs = _get_transform_kwargs(state.y_scale)

        x_data = apply_transform(x_raw, state.x_scale.transform_type, **x_kwargs)
        y_data = apply_transform(y_raw, state.y_scale.transform_type, **y_kwargs)

        xlim = _compute_limits(x_raw, state.x_scale, x_kwargs)
        ylim = _compute_limits(y_raw, state.y_scale, y_kwargs)

        strategy = RenderStrategyFactory.get_strategy(state.display_mode.value)

        render_kwargs: dict[str, Any] = {
            "quality_multiplier": state.quality_multiplier,
            "grid_size": int(512 * state.quality_multiplier),
            "alpha": 1.0 if state.quality_multiplier >= 2.0 else 0.8,  # noqa: PLR2004
        }

        if state.render_config:
            from ..flow_canvas import DisplayMode

            mode = state.display_mode

            if mode == DisplayMode.PSEUDOCOLOR:
                pc = state.render_config.pseudocolor
                render_kwargs.update(
                    {
                        "max_events": pc.max_events,
                        "nbins_scaling": pc.population_detail,
                        "sigma_scaling": pc.population_smoothing,
                        "density_threshold": pc.background_suppression,
                        "vibrancy_min": pc.vibrancy_min,
                        "vibrancy_range": pc.vibrancy_range,
                        "colormap": pc.colormap,
                        "cmap": pc.colormap,
                        "point_size": pc.point_size,
                        "s": pc.point_size,
                        "opacity": pc.opacity,
                        "alpha": pc.opacity,
                    }
                )
            elif mode == DisplayMode.DOT_PLOT:
                dp = state.render_config.dot_plot
                render_kwargs.update(
                    {
                        "max_events": dp.max_events,
                        "dot_color": dp.dot_color,
                        "c": dp.dot_color,
                        "dot_size": dp.dot_size,
                        "s": dp.dot_size,
                        "opacity": dp.opacity,
                        "alpha": dp.opacity,
                    }
                )
            elif mode == DisplayMode.HISTOGRAM:
                h = state.render_config.histogram
                render_kwargs.update(
                    {
                        "bar_color": h.bar_color,
                        "color": h.bar_color,
                        "bins": h.bins,
                        "auto_bins": h.auto_bins,
                        "y_axis_mode": h.y_axis_mode,
                        "density": (h.y_axis_mode == "frequency"),
                        "filled": h.filled,
                        "smooth_kde": h.smooth_kde,
                    }
                )
            elif mode == DisplayMode.CONTOUR:
                c = state.render_config.contour
                render_kwargs.update(
                    {
                        "num_levels": c.num_levels,
                        "levels": c.num_levels,
                        "smoothing": c.smoothing,
                        "sigma": c.smoothing,
                        "color_mode": c.color_mode,
                        "colormap": c.colormap,
                        "show_filled": c.show_filled,
                        "show_dot_underlay": c.show_dot_underlay,
                    }
                )
        else:
            render_kwargs["max_events"] = state.max_events

        try:
            strategy_data = strategy.compute(x_data, y_data, xlim=xlim, ylim=ylim, **render_kwargs)
            used_strategy = strategy
            used_kwargs = render_kwargs
        except Exception as e:
            logger.error(f"Strategy compute failed: {e}", exc_info=True)
            fallback = RenderStrategyFactory.get_strategy("Dot Plot")
            strategy_data = fallback.compute(x_data, y_data)
            used_strategy = fallback
            used_kwargs = {}

        return FlowRenderData(
            mode="2d",
            x_label=state.x_label,
            y_label=state.y_label,
            xlim=xlim,
            ylim=ylim,
            strategy=used_strategy,
            strategy_data=strategy_data,
            strategy_kwargs=used_kwargs,
            event_count=len(x_data),
        )


class FlowDataRasterizeStage(RasterizeStage):
    """Matplotlib-only half of the data-layer render — must run under MPL_RASTER_LOCK.

    Holds a reference to the owning ``FlowCanvas`` because it must reset
    gate/guide tracking state that ``ax.clear()`` (already run by the caller,
    ``LayeredMatplotlibCanvas._apply_data_layer``, before this) just
    invalidated — the same responsibility the old ``DataLayerRenderer.render()``
    had at the top of its lock-held block.
    """

    def __init__(self, canvas: FlowCanvas) -> None:
        self.canvas = canvas

    def rasterize(self, target: Any, data: Any) -> None:
        """`data` must be a `FlowRenderData`; typed `Any` to satisfy
        `RasterizeStage`'s `RenderData` signature — this stage is only ever
        paired with `FlowDataComputeStage`, which always produces one.
        """
        ax = target
        render_data: FlowRenderData = data
        canvas = self.canvas

        ax.set_axis_on()
        ax.set_facecolor(getattr(canvas, "_PLOT_BG", "#FFFFFF"))
        canvas._gate_patches.clear()
        canvas._gate_artists.clear()
        canvas._gate_overlay_artists.clear()
        # These artists were just invalidated by the caller's ax.clear() —
        # drop the stale references so nothing later tries to .remove() them.
        canvas._guide_poly_patch = None
        if hasattr(canvas, "_guide_patches"):
            canvas._guide_patches.clear()
        canvas._overlay_manager._instruction_text = None

        if render_data.mode == "empty":
            canvas._show_empty()
            return
        if render_data.mode == "error":
            canvas._show_error(render_data.error_message)
            return

        try:
            self._draw_strategy(ax, render_data)
        except Exception as exc:
            logger.error(f"FlowDataRasterizeStage: strategy draw failed: {exc}", exc_info=True)
            canvas._show_error(f"Render error: {exc}")
            if canvas._crash_reporter is not None:
                canvas._crash_reporter.report_error(
                    "FlowCanvas render failed",
                    exception=exc,
                    plugin_id=canvas._plugin_id,
                    fatal=False,
                )

    def _draw_strategy(self, ax: Any, data: FlowRenderData) -> None:
        assert data.strategy is not None
        from .axis_formatter import AxisFormatter

        if data.mode == "1d":
            if data.xlim is not None:
                ax.set_xlim(data.xlim)
            data.strategy.draw(ax, data.strategy_data, **data.strategy_kwargs)
            ax.set_xlabel(data.x_label, fontsize=9, color="#333333")
            AxisFormatter(self.canvas).apply_formatting()
            return

        if data.xlim is not None:
            ax.set_xlim(data.xlim)
        if data.ylim is not None:
            ax.set_ylim(data.ylim)

        data.strategy.draw(ax, data.strategy_data, **data.strategy_kwargs)

        # Re-apply the pre-render limits to prevent autoscale from shifting the
        # view — scatter()/contour()/hist() calls autoscale_view() internally.
        if data.xlim is not None:
            ax.set_xlim(data.xlim)
        if data.ylim is not None:
            ax.set_ylim(data.ylim)

        ax.set_xlabel(data.x_label, fontsize=9, color="#333333")
        ax.set_ylabel(data.y_label, fontsize=9, color="#333333")
        AxisFormatter(self.canvas).apply_formatting()

        for spine in ax.spines.values():
            spine.set_color("#333333")
            spine.set_linewidth(1.0)
        ax.tick_params(colors="#333333", labelsize=8)

        ax.annotate(
            f"{data.event_count:,} events",
            xy=(0.98, 0.98),
            xycoords="axes fraction",
            ha="right",
            va="top",
            fontsize=8,
            color="#333333",
            alpha=0.8,
        )

        ax.grid(True, color="#B0B0B0", alpha=0.35, linewidth=0.5)
        self.canvas._fig.subplots_adjust(left=0.12, bottom=0.12, right=0.95, top=0.95)
