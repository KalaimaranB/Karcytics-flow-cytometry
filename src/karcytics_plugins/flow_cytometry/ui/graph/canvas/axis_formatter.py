"""Axis formatting for FlowCanvas."""

import numpy as np
from matplotlib.ticker import FixedFormatter, FixedLocator

from karcytics_plugins.flow_cytometry.analysis.transforms import (
    TransformType,
    biological_tick_values,
)


class AxisFormatter:
    def __init__(self, canvas):
        self.canvas = canvas

    def apply_formatting(self):
        """Apply biological decade formatting to axes if transformed."""
        ax = self.canvas._ax
        x_scale = self.canvas._x_scale
        y_scale = self.canvas._y_scale
        mapper = self.canvas._coordinate_mapper
        display_mode = self.canvas._display_mode
        from ..flow_canvas import DisplayMode

        if x_scale.transform_type != TransformType.LINEAR:
            raw_ticks, labels = self._build_bio_ticks(
                x_scale, x_scale.transform_type == TransformType.BIEXPONENTIAL
            )
            disp_ticks = mapper.transform_x(raw_ticks)
            ax.xaxis.set_major_locator(FixedLocator(disp_ticks))
            ax.xaxis.set_major_formatter(FixedFormatter(labels))
            if x_scale.transform_type == TransformType.BIEXPONENTIAL:
                self._add_linear_region_shading(ax, mapper, "x")

        if display_mode not in (DisplayMode.HISTOGRAM, DisplayMode.CDF):
            if y_scale.transform_type != TransformType.LINEAR:
                raw_ticks, labels = self._build_bio_ticks(
                    y_scale, y_scale.transform_type == TransformType.BIEXPONENTIAL
                )
                disp_ticks = mapper.transform_y(raw_ticks)
                ax.yaxis.set_major_locator(FixedLocator(disp_ticks))
                ax.yaxis.set_major_formatter(FixedFormatter(labels))
                if y_scale.transform_type == TransformType.BIEXPONENTIAL:
                    self._add_linear_region_shading(ax, mapper, "y")

    def _add_linear_region_shading(self, ax, mapper, axis: str) -> None:
        raw_bounds = np.array([-1000.0, 1000.0])
        if axis == "x":
            disp_bounds = mapper.transform_x(raw_bounds)
            ax.axvspan(
                disp_bounds[0],
                disp_bounds[1],
                color="#000000",
                alpha=0.03,
                zorder=0,
                linewidth=0,
            )
        else:
            disp_bounds = mapper.transform_y(raw_bounds)
            ax.axhspan(
                disp_bounds[0],
                disp_bounds[1],
                color="#000000",
                alpha=0.03,
                zorder=0,
                linewidth=0,
            )

    def _build_bio_ticks(self, scale, is_biex):
        show_neg = False
        if is_biex:
            show_neg = scale.logicle_a > 0 or (scale.min_val is not None and scale.min_val < 0)
        return biological_tick_values(is_biex, show_neg)
