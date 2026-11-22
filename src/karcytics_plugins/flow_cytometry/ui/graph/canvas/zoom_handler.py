"""ZoomHandler — handles scroll zoom events for the canvas."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from ....analysis.scaling import AxisScale
    from ..flow_canvas import FlowCanvas


_MIN_VALUE, _MAX_VALUE = -1e6, 1e7


class ZoomHandler:
    """Turns the scroll wheel into a request for zoomed scales (the owner applies them)."""

    def __init__(self, canvas: FlowCanvas) -> None:
        self.canvas = canvas

    def handle_scroll(self, event) -> None:
        """Handle scroll wheel to zoom in and out."""
        if not event.inaxes:
            return

        base_scale = 1.2
        if event.button == "up":
            scale_factor = 1 / base_scale
        elif event.button == "down":
            scale_factor = base_scale
        else:
            return

        mapper = self.canvas.coordinate_mapper
        x_scale = self.canvas.x_scale
        y_scale = self.canvas.y_scale

        # Calculate new ranges in visual space
        x_min_vis = mapper.transform_x(np.array([x_scale.min_val]))[0]
        x_max_vis = mapper.transform_x(np.array([x_scale.max_val]))[0]
        y_min_vis = mapper.transform_y(np.array([y_scale.min_val]))[0]
        y_max_vis = mapper.transform_y(np.array([y_scale.max_val]))[0]

        # Zoom in visual space, about the pointer
        new_width = (x_max_vis - x_min_vis) * scale_factor
        new_height = (y_max_vis - y_min_vis) * scale_factor
        relx = (
            (x_max_vis - event.xdata) / (x_max_vis - x_min_vis) if x_max_vis != x_min_vis else 0.5
        )
        rely = (
            (y_max_vis - event.ydata) / (y_max_vis - y_min_vis) if y_max_vis != y_min_vis else 0.5
        )
        new_x = (event.xdata - new_width * (1 - relx), event.xdata + new_width * relx)
        new_y = (event.ydata - new_height * (1 - rely), event.ydata + new_height * rely)

        # Back to real values, within sanity limits (no zooming out forever).
        real_x = mapper.inverse_transform_x(np.array(new_x))
        real_y = mapper.inverse_transform_y(np.array(new_y))
        self.canvas.scale_edit_requested.emit(
            _with_range(x_scale, *real_x), _with_range(y_scale, *real_y)
        )


def _with_range(scale: AxisScale, low: float, high: float) -> AxisScale:
    """A copy of ``scale`` showing ``low``..``high``, clamped and never empty."""
    zoomed = scale.copy()
    zoomed.min_val = max(_MIN_VALUE, float(low))
    zoomed.max_val = min(_MAX_VALUE, float(high))
    if zoomed.max_val <= zoomed.min_val:  # an extreme zoom: avoid dividing by zero
        zoomed.max_val = zoomed.min_val + 1.0
    return zoomed
