"""RangeGate class."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .._utils import ScaleFactory, ScaleSerializer, project_to_display
from .base import Gate


class RangeGate(Gate):
    """1-D range gate for histograms."""

    def __init__(  # noqa: PLR0913
        self,
        x_param: str,
        *,
        low: float = -np.inf,
        high: float = np.inf,
        adaptive: bool = False,
        gate_id: str | None = None,
        x_scale=None,
    ) -> None:
        super().__init__(x_param, None, adaptive=adaptive, gate_id=gate_id)
        self.low = low
        self.high = high
        self.x_scale = ScaleFactory.parse(x_scale)

    def copy(self) -> RangeGate:
        return RangeGate(
            self.x_param,
            low=self.low,
            high=self.high,
            adaptive=self.adaptive,
            gate_id=self.gate_id,
            x_scale=self.x_scale.copy() if self.x_scale else None,
        )

    def contains(self, events: pd.DataFrame) -> np.ndarray:
        """Test which events fall inside this range."""
        if self.x_param not in events.columns:
            raise KeyError(self.x_param)

        x_raw = events[self.x_param].values
        bounds_raw = np.array([self.low, self.high])

        # Project to display space
        x_disp = project_to_display(x_raw, self.x_scale)
        bounds_disp = project_to_display(bounds_raw, self.x_scale)
        low_disp, high_disp = bounds_disp[0], bounds_disp[1]

        return (x_disp >= low_disp) & (x_disp <= high_disp)

    def to_dict(self) -> dict:
        d = super().to_dict()
        d.update(low=self.low, high=self.high)
        d["x_scale"] = ScaleSerializer.to_dict(self.x_scale)
        return d

    @classmethod
    def from_dict(cls, data: dict) -> RangeGate:
        return cls(
            x_param=data["x_param"],
            low=data.get("low", -np.inf),
            high=data.get("high", np.inf),
            adaptive=data.get("adaptive", False),
            gate_id=data.get("gate_id"),
            x_scale=data.get("x_scale"),
        )
