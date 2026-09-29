"""PolygonGate class."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from matplotlib.path import Path

from .._utils import ScaleFactory, ScaleSerializer, project_to_display
from ..scaling import AxisScale
from .base import Gate


class PolygonGate(Gate):
    """Polygonal gate defined by an ordered list of vertices.

    Vertices are stored in **raw data space**.  ``contains()`` projects vertices
    into display space before the point-in-polygon test.

    Attributes:
        vertices: Ordered ``[(x, y), ...]`` pairs in raw data space.
        x_scale:  Axis scale for the X parameter.
        y_scale:  Axis scale for the Y parameter.
    """

    def __init__(  # noqa: PLR0913, PLR0917
        self,
        x_param: str,
        y_param: str,
        vertices: list[tuple[float, float]],
        x_scale: AxisScale | None = None,
        y_scale: AxisScale | None = None,
        name: str = "Polygon Gate",
        adaptive: bool = False,
        gate_id: str | None = None,
        **_kwargs: Any,
    ) -> None:
        super().__init__(x_param, y_param, adaptive=adaptive, gate_id=gate_id)
        self.name = name
        self.vertices = vertices
        self.x_scale = ScaleFactory.parse(x_scale)
        self.y_scale = ScaleFactory.parse(y_scale)

    def copy(self) -> PolygonGate:
        if self.y_param is None:
            raise ValueError(f"{self.__class__.__name__} requires a y_param")
        return PolygonGate(
            self.x_param,
            self.y_param,
            vertices=list(self.vertices),
            x_scale=self.x_scale.copy() if self.x_scale else None,
            y_scale=self.y_scale.copy() if self.y_scale else None,
            name=self.name,
            adaptive=self.adaptive,
            gate_id=self.gate_id,
        )

    def contains(self, events: pd.DataFrame) -> np.ndarray:
        """Test which events fall inside this polygon gate."""
        if self.y_param is None:
            raise ValueError(f"{self.__class__.__name__} requires a y_param")
        if self.x_param not in events.columns:
            raise KeyError(self.x_param)
        if self.y_param not in events.columns:
            raise KeyError(self.y_param)

        x_raw = events[self.x_param].values
        y_raw = events[self.y_param].values
        vx_raw = np.array([v[0] for v in self.vertices])
        vy_raw = np.array([v[1] for v in self.vertices])

        # Project events into display space
        x_disp = project_to_display(x_raw, self.x_scale)
        y_disp = project_to_display(y_raw, self.y_scale)

        # Project raw-space vertices into the same display space
        vx_disp = project_to_display(vx_raw, self.x_scale)
        vy_disp = project_to_display(vy_raw, self.y_scale)

        points = np.column_stack((x_disp, y_disp))
        poly_path = Path(np.column_stack((vx_disp, vy_disp)))
        return poly_path.contains_points(points)

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["vertices"] = [list(v) for v in self.vertices]
        d["x_scale"] = ScaleSerializer.to_dict(self.x_scale)
        d["y_scale"] = ScaleSerializer.to_dict(self.y_scale)
        return d

    @classmethod
    def from_dict(cls, data: dict) -> PolygonGate:
        return cls(
            x_param=data["x_param"],
            y_param=data["y_param"],
            vertices=[tuple(v) for v in data.get("vertices", [])],
            x_scale=data.get("x_scale"),
            y_scale=data.get("y_scale"),
            adaptive=data.get("adaptive", False),
            gate_id=data.get("gate_id"),
        )
