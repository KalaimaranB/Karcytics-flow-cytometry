"""EllipseGate class."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .._utils import ScaleFactory, ScaleSerializer, project_to_display
from .base import Gate


class EllipseGate(Gate):
    """Elliptical gate defined by center, semi-axes, and rotation.

    Attributes:
        center:   (cx, cy) center of the ellipse in raw data space.
        width:    Semi-axis length along X (before rotation) in raw data space.
        height:   Semi-axis length along Y (before rotation) in raw data space.
        angle:    Rotation angle in degrees (counter-clockwise).
        x_scale:  Axis scale for X parameter.
        y_scale:  Axis scale for Y parameter.
    """

    def __init__(  # noqa: PLR0913
        self,
        x_param: str,
        y_param: str,
        *,
        center: tuple[float, float] = (0.0, 0.0),
        width: float = 1.0,
        height: float = 1.0,
        angle: float = 0.0,
        adaptive: bool = False,
        gate_id: str | None = None,
        x_scale=None,
        y_scale=None,
    ) -> None:
        super().__init__(x_param, y_param, adaptive=adaptive, gate_id=gate_id)
        self.center = center
        self.width = width
        self.height = height
        self.angle = angle
        self.x_scale = ScaleFactory.parse(x_scale)
        self.y_scale = ScaleFactory.parse(y_scale)

    def copy(self) -> EllipseGate:
        if self.y_param is None:
            raise ValueError(f"{self.__class__.__name__} requires a y_param")
        return EllipseGate(
            self.x_param,
            self.y_param,
            center=self.center,
            width=self.width,
            height=self.height,
            angle=self.angle,
            adaptive=self.adaptive,
            gate_id=self.gate_id,
            x_scale=self.x_scale.copy() if self.x_scale else None,
            y_scale=self.y_scale.copy() if self.y_scale else None,
        )

    def contains(self, events: pd.DataFrame) -> np.ndarray:
        """Test which events fall inside this ellipse."""
        if self.y_param is None:
            raise ValueError(f"{self.__class__.__name__} requires a y_param")
        if self.x_param not in events.columns:
            raise KeyError(self.x_param)
        if self.y_param not in events.columns:
            raise KeyError(self.y_param)

        x_raw = events[self.x_param].values
        y_raw = events[self.y_param].values
        cx_raw = self.center[0]
        cy_raw = self.center[1]

        # Project events and center to display space
        x_disp = project_to_display(x_raw, self.x_scale)
        y_disp = project_to_display(y_raw, self.y_scale)
        cx_disp = project_to_display(np.array([cx_raw]), self.x_scale)[0]
        cy_disp = project_to_display(np.array([cy_raw]), self.y_scale)[0]

        # Project axis endpoints to get semi-axes lengths in display space
        x_plus_w_disp = project_to_display(np.array([cx_raw + self.width]), self.x_scale)[0]
        y_plus_h_disp = project_to_display(np.array([cy_raw + self.height]), self.y_scale)[0]
        width_disp = abs(x_plus_w_disp - cx_disp)
        height_disp = abs(y_plus_h_disp - cy_disp)

        # Translate to center
        x_centered = x_disp - cx_disp
        y_centered = y_disp - cy_disp

        # Rotate
        theta = np.radians(self.angle)
        cos_t, sin_t = np.cos(theta), np.sin(theta)
        x_rot = cos_t * x_centered + sin_t * y_centered
        y_rot = -sin_t * x_centered + cos_t * y_centered

        # Ellipse containment test
        # Avoid division by zero
        if width_disp == 0 or height_disp == 0:
            return np.zeros(len(events), dtype=bool)

        return (x_rot / width_disp) ** 2 + (y_rot / height_disp) ** 2 <= 1.0

    def to_dict(self) -> dict:
        d = super().to_dict()
        d.update(
            center=list(self.center),
            width=self.width,
            height=self.height,
            angle=self.angle,
        )
        d["x_scale"] = ScaleSerializer.to_dict(self.x_scale)
        d["y_scale"] = ScaleSerializer.to_dict(self.y_scale)
        return d

    @classmethod
    def from_dict(cls, data: dict) -> EllipseGate:
        return cls(
            x_param=data["x_param"],
            y_param=data["y_param"],
            center=tuple(data.get("center", (0.0, 0.0))),
            width=data.get("width", 1.0),
            height=data.get("height", 1.0),
            angle=data.get("angle", 0.0),
            adaptive=data.get("adaptive", False),
            gate_id=data.get("gate_id"),
            x_scale=data.get("x_scale"),
            y_scale=data.get("y_scale"),
        )
