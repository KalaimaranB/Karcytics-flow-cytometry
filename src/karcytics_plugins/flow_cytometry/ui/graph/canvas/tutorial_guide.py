"""The Academy's dashed guide shapes on a gating plot ("draw your gate about here").

A tutorial step describes its guide in raw data units (``guide_poly`` on the
step, or ``guide_data_poly`` / ``guide_rect`` / ``guide_range`` /
``guide_quadrant`` in its metadata); this transforms it to the plot's current
axis scales and draws it over the data. The data layer clears the axes on
every render, so the canvas calls ``redraw()`` after each one.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from ....analysis.constants import TUTORIAL_GUIDE_COLOR as _COLOR
from ....analysis.scaling import AxisScale, get_transform_kwargs
from ....analysis.transforms import apply_transform

_ZORDER = 100  # above the data and gates
_LINE: dict[str, Any] = {"color": _COLOR, "linestyle": "--", "linewidth": 2, "zorder": _ZORDER}
_OUTLINE: dict[str, Any] = {
    "fill": False,
    "edgecolor": _COLOR,
    "linestyle": "--",
    "linewidth": 2,
    "alpha": 0.8,
    "zorder": _ZORDER,
}


def _scaled(values: Any, scale: AxisScale) -> np.ndarray:
    return apply_transform(
        np.asarray(values, dtype=float), scale.transform_type, **get_transform_kwargs(scale)
    )


class TutorialGuide:
    """The current step's guide shapes on one canvas's axes."""

    def __init__(self, canvas: Any) -> None:
        self._canvas = canvas
        self._step: Any | None = None
        self.artists: list[Any] = []  # what is on the axes now

    def set_step(self, step: Any | None) -> None:
        """Show ``step``'s guide (None: none) and redraw the canvas."""
        self._step = step
        self.redraw()
        self._canvas.draw_idle()

    def redraw(self) -> None:
        """Re-add the guide to the axes (after a render cleared them)."""
        self.remove()
        if self._step is not None and self._applies_to_plot():
            self._draw(self._step)

    def remove(self) -> None:
        for artist in self.artists:
            try:
                artist.remove()
            except (ValueError, AttributeError, NotImplementedError):
                pass  # already gone with an ax.clear()
        self.artists.clear()

    def forget(self) -> None:
        """Drop references to artists an ``ax.clear()`` already removed."""
        self.artists.clear()

    def _applies_to_plot(self) -> bool:
        """A guide naming its channels shows only on plots of them (the Sample Lens has several)."""
        axes = (getattr(self._step, "metadata", None) or {}).get("guide_axes")
        return not axes or tuple(axes) == (self._canvas.x_param, self._canvas.y_param)

    def _draw(self, step: Any) -> None:
        from matplotlib.patches import Polygon, Rectangle  # karcytics: allow KS360 - heavy library

        ax = self._canvas.ax
        x_scale, y_scale = self._canvas.x_scale, self._canvas.y_scale
        metadata = getattr(step, "metadata", None) or {}

        if poly := getattr(step, "guide_poly", None):  # already in plot coordinates
            self.artists.append(ax.add_patch(Polygon(poly, closed=True, **_OUTLINE)))
        if poly := metadata.get("guide_data_poly"):
            xs, ys = _scaled([p[0] for p in poly], x_scale), _scaled([p[1] for p in poly], y_scale)
            vertices = list(zip(xs, ys, strict=True))
            self.artists.append(ax.add_patch(Polygon(vertices, closed=True, **_OUTLINE)))
        if rect := metadata.get("guide_rect"):
            min_x, max_x, min_y, max_y = rect
            # Clipped to the plot: an edge past the axis would otherwise not show at all.
            (x0, x1), (y0, y1) = sorted(ax.get_xlim()), sorted(ax.get_ylim())
            xs = np.clip(_scaled([min_x, max_x], x_scale), x0, x1)
            ys = np.clip(_scaled([min_y, max_y], y_scale), y0, y1)
            box = Rectangle((xs[0], ys[0]), xs[1] - xs[0], ys[1] - ys[0], **_OUTLINE)
            self.artists.append(ax.add_patch(box))
        if span := metadata.get("guide_range"):
            low, high = _scaled(span, x_scale)
            self.artists += [
                ax.axvspan(low, high, color=_COLOR, alpha=0.08, zorder=_ZORDER - 1),
                ax.axvline(low, **_LINE),
                ax.axvline(high, **_LINE),
            ]
        if cross := metadata.get("guide_quadrant"):
            x = _scaled([cross[0]], x_scale)[0]
            y = _scaled([cross[1]], y_scale)[0]
            self.artists += [ax.axvline(x, **_LINE), ax.axhline(y, **_LINE)]
