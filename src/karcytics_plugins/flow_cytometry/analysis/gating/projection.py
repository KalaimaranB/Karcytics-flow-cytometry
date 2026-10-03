"""Projection of a gate onto a single axis."""

from __future__ import annotations

import math

from .base import Gate
from .quadrant import QuadrantGate, QuadrantSubGate
from .range import RangeGate
from .rectangle import RectangleGate


def axis_interval(gate: Gate, param: str) -> tuple[float, float] | None:
    """The ``(low, high)`` raw-space interval ``gate`` covers on ``param``.

    Only gates whose edges are straight along the axis have one: a range, a
    rectangle, and a quadrant (its divider, as a zero-width interval). Returns
    None for any other shape, for a gate that isn't on ``param``, and for
    open-ended bounds.
    """
    target = gate.parent if isinstance(gate, QuadrantSubGate) else gate
    on_x = target.x_param == param
    if not on_x and target.y_param != param:
        return None

    if isinstance(target, RangeGate):
        interval = (target.low, target.high)
    elif isinstance(target, RectangleGate):
        interval = (target.x_min, target.x_max) if on_x else (target.y_min, target.y_max)
    elif isinstance(target, QuadrantGate):
        mid = target.x_mid if on_x else target.y_mid
        interval = (mid, mid)
    else:
        return None

    return interval if all(math.isfinite(v) for v in interval) else None
