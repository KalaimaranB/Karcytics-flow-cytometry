"""RectangleGate class."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .._utils import ScaleFactory, ScaleSerializer, project_to_display
from ..scaling import AxisScale
from .base import Gate


class RectangleGate(Gate):
    """Rectangular (2-D) or range (1-D) gate defined by min/max bounds.

    Bounds are stored in **raw data space**. The ``contains()`` method
    projects both events and bounds into display space using the axis
    scales before comparison.

    Attributes:
        x_min, x_max: X-axis bounds in raw data space.
        y_min, y_max: Y-axis bounds in raw data space (ignored if ``y_param`` is None).
        x_scale:      Axis scale for X parameter.
        y_scale:      Axis scale for Y parameter.
    """

    def __init__(  # noqa: PLR0913
        self,
        x_param: str,
        y_param: str | None = None,
        *,
        x_min: float = -np.inf,
        x_max: float = np.inf,
        y_min: float = -np.inf,
        y_max: float = np.inf,
        adaptive: bool = False,
        gate_id: str | None = None,
        x_scale: AxisScale | None = None,
        y_scale: AxisScale | None = None,
    ) -> None:
        super().__init__(x_param, y_param, adaptive=adaptive, gate_id=gate_id)
        self.x_min = x_min
        self.x_max = x_max
        self.y_min = y_min
        self.y_max = y_max
        self.x_scale: AxisScale = ScaleFactory.parse(x_scale)
        self.y_scale: AxisScale = ScaleFactory.parse(y_scale)

    def contains(self, events: pd.DataFrame) -> np.ndarray:
        """Test which events fall inside this rectangle."""
        if self.x_param not in events.columns:
            raise KeyError(self.x_param)

        x_raw = events[self.x_param].values
        bounds_x_raw = np.array([self.x_min, self.x_max])

        # Project X to display space
        x_disp = project_to_display(x_raw, self.x_scale)
        bounds_x_disp = project_to_display(bounds_x_raw, self.x_scale)
        x_min_disp, x_max_disp = bounds_x_disp[0], bounds_x_disp[1]

        mask = (x_disp >= x_min_disp) & (x_disp <= x_max_disp)

        # Apply Y constraint if present
        if self.y_param:
            if self.y_param not in events.columns:
                raise KeyError(self.y_param)
            y_raw = events[self.y_param].values
            bounds_y_raw = np.array([self.y_min, self.y_max])

            y_disp = project_to_display(y_raw, self.y_scale)
            bounds_y_disp = project_to_display(bounds_y_raw, self.y_scale)
            y_min_disp, y_max_disp = bounds_y_disp[0], bounds_y_disp[1]

            mask &= (y_disp >= y_min_disp) & (y_disp <= y_max_disp)

        return mask

    def copy(self) -> RectangleGate:
        return RectangleGate(
            self.x_param,
            self.y_param,
            x_min=self.x_min,
            x_max=self.x_max,
            y_min=self.y_min,
            y_max=self.y_max,
            adaptive=self.adaptive,
            gate_id=self.gate_id,
            x_scale=self.x_scale.copy() if self.x_scale else None,
            y_scale=self.y_scale.copy() if self.y_scale else None,
        )

    def to_dict(self) -> dict:
        d = super().to_dict()
        d.update(x_min=self.x_min, x_max=self.x_max, y_min=self.y_min, y_max=self.y_max)
        d["x_scale"] = ScaleSerializer.to_dict(self.x_scale)
        d["y_scale"] = ScaleSerializer.to_dict(self.y_scale)
        return d

    @classmethod
    def from_dict(cls, data: dict) -> RectangleGate:
        return cls(
            x_param=data["x_param"],
            y_param=data.get("y_param"),
            x_min=data.get("x_min", -np.inf),
            x_max=data.get("x_max", np.inf),
            y_min=data.get("y_min", -np.inf),
            y_max=data.get("y_max", np.inf),
            adaptive=data.get("adaptive", False),
            gate_id=data.get("gate_id"),
            x_scale=data.get("x_scale"),
            y_scale=data.get("y_scale"),
        )
