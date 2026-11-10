"""Gates from shapes found in display space.

Searches (Sample Lens synthesis, auto gating) look for populations where plots
show them, in display space. Gates store raw values plus the scales they were
drawn on; these turn one into the other, so a gate draws where it was found.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from .._utils import project_to_raw
from .ellipse import EllipseGate
from .polygon import PolygonGate
from .rectangle import RectangleGate

if TYPE_CHECKING:
    from ..scaling import AxisScale


def rectangle_from_display(  # noqa: PLR0913 - a gate is two axes, their scales and a shape
    x: str,
    y: str,
    bounds: tuple[float, float, float, float],
    x_scale: AxisScale,
    y_scale: AxisScale,
    extremes: tuple[float, float, float, float],
) -> RectangleGate:
    """A rectangle from display ``bounds`` (x_lo, x_hi, y_lo, y_hi).

    An infinite (open) edge goes just past the data's own extreme in ``extremes``
    (x_min, x_max, y_min, y_max, display units), so nothing beyond it is cut off.
    """
    corners = []
    for scale, lo, hi, lo_end, hi_end in (
        (x_scale, bounds[0], bounds[1], extremes[0], extremes[1]),
        (y_scale, bounds[2], bounds[3], extremes[2], extremes[3]),
    ):
        lo = lo_end - 1.0 if np.isinf(lo) else lo
        hi = hi_end + 1.0 if np.isinf(hi) else hi
        corners.append(project_to_raw(np.array([lo, hi]), scale))
    (x_min, x_max), (y_min, y_max) = corners
    return RectangleGate(
        x,
        y,
        x_min=float(x_min),
        x_max=float(x_max),
        y_min=float(y_min),
        y_max=float(y_max),
        x_scale=x_scale.copy(),
        y_scale=y_scale.copy(),
    )


def ellipse_from_display(  # noqa: PLR0913 - a gate is two axes, their scales and a shape
    x: str,
    y: str,
    center: tuple[float, float],
    semi_axes: tuple[float, float],
    angle: float,
    x_scale: AxisScale,
    y_scale: AxisScale,
) -> EllipseGate:
    """An ellipse whose centre, semi-axes and angle (degrees) are in display units.

    ``EllipseGate`` stores its centre in raw values and each semi-axis as the raw
    step that spans it in display space, so both are converted back here.
    """
    cx = float(project_to_raw(np.array([center[0]]), x_scale)[0])
    cy = float(project_to_raw(np.array([center[1]]), y_scale)[0])
    x_end = float(project_to_raw(np.array([center[0] + semi_axes[0]]), x_scale)[0])
    y_end = float(project_to_raw(np.array([center[1] + semi_axes[1]]), y_scale)[0])
    return EllipseGate(
        x,
        y,
        center=(cx, cy),
        width=x_end - cx,
        height=y_end - cy,
        angle=angle,
        x_scale=x_scale.copy(),
        y_scale=y_scale.copy(),
    )


def polygon_from_display(
    x: str, y: str, vertices: np.ndarray, x_scale: AxisScale, y_scale: AxisScale
) -> PolygonGate:
    """A polygon whose ``vertices`` ((n, 2), in order) are in display units."""
    vx = project_to_raw(vertices[:, 0], x_scale)
    vy = project_to_raw(vertices[:, 1], y_scale)
    return PolygonGate(
        x,
        y,
        vertices=[(float(a), float(b)) for a, b in zip(vx, vy, strict=True)],
        x_scale=x_scale.copy(),
        y_scale=y_scale.copy(),
    )
