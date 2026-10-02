"""QuadrantGate class."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from .gate_node import GateNode

from .._utils import ScaleFactory, ScaleSerializer, project_to_display
from ..scaling import AxisScale
from .base import Gate


class QuadrantGate(Gate):
    """Quadrant gate — divides the plot into 4 regions at (x_mid, y_mid)."""

    def __init__(  # noqa: PLR0913
        self,
        x_param: str,
        y_param: str,
        *,
        x_mid: float = 0.0,
        y_mid: float = 0.0,
        adaptive: bool = False,
        gate_id: str | None = None,
        x_scale: AxisScale | None = None,
        y_scale: AxisScale | None = None,
    ) -> None:
        super().__init__(x_param, y_param, adaptive=adaptive, gate_id=gate_id)
        self.x_mid = x_mid
        self.y_mid = y_mid
        self.x_scale: AxisScale = ScaleFactory.parse(x_scale)
        self.y_scale: AxisScale = ScaleFactory.parse(y_scale)

    def copy(self) -> QuadrantGate:
        if self.y_param is None:
            raise ValueError(f"{self.__class__.__name__} requires a y_param")
        return QuadrantGate(
            self.x_param,
            self.y_param,
            x_mid=self.x_mid,
            y_mid=self.y_mid,
            adaptive=self.adaptive,
            gate_id=self.gate_id,
            x_scale=self.x_scale.copy() if self.x_scale else None,
            y_scale=self.y_scale.copy() if self.y_scale else None,
        )

    def contains(self, events: pd.DataFrame) -> np.ndarray:
        """Returns True for all events (the quadrant gate itself holds all)."""
        return np.ones(len(events), dtype=bool)

    def get_quadrant(self, events: pd.DataFrame, quadrant: str) -> np.ndarray:
        """Return a boolean mask for a specific quadrant."""
        if self.y_param is None:
            raise ValueError(f"{self.__class__.__name__} requires a y_param")
        if self.x_param not in events.columns or self.y_param not in events.columns:
            return np.zeros(len(events), dtype=bool)

        q = quadrant.split()[0].upper() if quadrant else quadrant

        x_raw = events[self.x_param].values
        y_raw = events[self.y_param].values
        mid_x_raw = np.array([self.x_mid])
        mid_y_raw = np.array([self.y_mid])

        x_disp = project_to_display(x_raw, self.x_scale)
        y_disp = project_to_display(y_raw, self.y_scale)
        mid_x_disp = project_to_display(mid_x_raw, self.x_scale)[0]
        mid_y_disp = project_to_display(mid_y_raw, self.y_scale)[0]

        if q == "Q1":  # Upper Left
            return (x_disp < mid_x_disp) & (y_disp >= mid_y_disp)
        if q == "Q2":  # Upper Right
            return (x_disp >= mid_x_disp) & (y_disp >= mid_y_disp)
        if q == "Q3":  # Lower Left
            return (x_disp < mid_x_disp) & (y_disp < mid_y_disp)
        if q == "Q4":  # Lower Right
            return (x_disp >= mid_x_disp) & (y_disp < mid_y_disp)
        raise ValueError(f"Invalid quadrant: {quadrant!r}")

    def create_nodes(self, parent_node: GateNode, _name: str | None = None) -> list[GateNode]:
        """Create and attach 4 GateNodes for the four quadrants to a parent node."""
        from .gate_node import GateNode

        q_names = ["Q1", "Q2", "Q3", "Q4"]
        nodes = []
        for q_name in q_names:
            child_gate = QuadrantSubGate(self, q_name)
            child_gate.derived_formulas = dict(self.derived_formulas)
            node = GateNode(gate=child_gate, name=q_name, parents=[parent_node])
            parent_node.children.append(node)
            nodes.append(node)
        return nodes

    def to_dict(self) -> dict:
        d = super().to_dict()
        d.update(x_mid=self.x_mid, y_mid=self.y_mid)
        d["x_scale"] = ScaleSerializer.to_dict(self.x_scale)
        d["y_scale"] = ScaleSerializer.to_dict(self.y_scale)
        return d

    @classmethod
    def from_dict(cls, data: dict) -> QuadrantGate:
        return cls(
            x_param=data["x_param"],
            y_param=data["y_param"],
            x_mid=data.get("x_mid", 0.0),
            y_mid=data.get("y_mid", 0.0),
            adaptive=data.get("adaptive", False),
            gate_id=data.get("gate_id"),
            x_scale=data.get("x_scale"),
            y_scale=data.get("y_scale"),
        )


class QuadrantSubGate(Gate):
    """Internal gate representing a single quadrant region.

    This class satisfies the Liskov Substitution Principle (LSP) by
    implementing .contains() correctly for a specific quadrant region,
    allowing generic analysis tools to compute statistics for individual
    quadrants without specialized logic.
    """

    def __init__(self, parent: QuadrantGate, quadrant: str, gate_id: str | None = None):
        # The sub-gate ID is derived from the parent for consistency
        gid = gate_id or f"{parent.gate_id}_{quadrant}"
        super().__init__(parent.x_param, parent.y_param, gate_id=gid)
        self.parent = parent
        self.quadrant = quadrant

    def contains(self, events: pd.DataFrame) -> np.ndarray:
        """Filter events for this specific quadrant."""
        return self.parent.get_quadrant(events, self.quadrant)

    def copy(self) -> QuadrantSubGate:
        return QuadrantSubGate(self.parent.copy(), self.quadrant, gate_id=self.gate_id)

    def to_dict(self) -> dict:
        d = super().to_dict()
        d.update({"parent_gate": self.parent.to_dict(), "quadrant": self.quadrant})
        return d

    @classmethod
    def from_dict(cls, data: dict) -> QuadrantSubGate:
        parent = QuadrantGate.from_dict(data["parent_gate"])
        return cls(parent, data["quadrant"], gate_id=data.get("gate_id"))
