"""Turn a cluster into ordinary gates (a Hypergate-style greedy search).

A cluster is just a list of events: it can't be read, edited, or applied to
another sample. This finds a short chain of rectangle gates on real channels
that recovers it. Each step tries every channel pair, fits a box around the
target events still in play (1st-99th percentile, padded), and keeps the pair
that raises F1 the most; it stops when a step stops helping.

The search runs in display space (where gates are drawn and where population
shapes are compact); the winning boxes are converted back to raw values for
``RectangleGate``, carrying the same scales so they draw where they were found.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import TYPE_CHECKING

import numpy as np

from .._utils import project_to_display, project_to_raw
from ..gating import RectangleGate

if TYPE_CHECKING:
    import pandas as pd

    from ..scaling import AxisScale

MAX_STEPS = 3
MIN_GAIN = 0.01  # a step must raise F1 at least this much
PAD = 0.03  # padding around a box, as a share of the channel's display range
OPEN_EDGE = 0.995  # a box edge past this quantile of the data is left open


@dataclass(frozen=True)
class ProposedGate:
    gate: RectangleGate
    f1: float
    precision: float
    recall: float


def _scores(selected: np.ndarray, target: np.ndarray) -> tuple[float, float, float]:
    tp = float((selected & target).sum())
    if tp == 0:
        return 0.0, 0.0, 0.0
    precision = tp / float(selected.sum())
    recall = tp / float(target.sum())
    return 2 * precision * recall / (precision + recall), precision, recall


@dataclass(frozen=True)
class _Box:
    x: str
    y: str
    bounds: tuple[float, float, float, float]  # display space: x_lo, x_hi, y_lo, y_hi


class _DisplayData:
    """Each channel of the events in display space, with its range."""

    def __init__(self, events: pd.DataFrame, scales: dict[str, AxisScale]) -> None:
        self.scales = scales
        self.values = {
            ch: project_to_display(events[ch].to_numpy(dtype=np.float64), scale)
            for ch, scale in scales.items()
        }
        self.limits = {
            ch: tuple(np.nanquantile(v, [1 - OPEN_EDGE, OPEN_EDGE]))
            for ch, v in self.values.items()
        }

    def fit(self, x: str, y: str, rows: np.ndarray) -> _Box:
        bounds = []
        for ch in (x, y):
            lo_lim, hi_lim = self.limits[ch]
            lo, hi = np.nanpercentile(self.values[ch][rows], [1, 99])
            pad = PAD * (hi_lim - lo_lim)
            # Past the data's own extremes, leave the edge open (out to the axis end).
            lo = -np.inf if lo - pad <= lo_lim else lo - pad
            hi = np.inf if hi + pad >= hi_lim else hi + pad
            bounds += [lo, hi]
        return _Box(x, y, (bounds[0], bounds[1], bounds[2], bounds[3]))

    def inside(self, box: _Box) -> np.ndarray:
        x_lo, x_hi, y_lo, y_hi = box.bounds
        xs, ys = self.values[box.x], self.values[box.y]
        return (xs >= x_lo) & (xs <= x_hi) & (ys >= y_lo) & (ys <= y_hi)

    def to_gate(self, box: _Box) -> RectangleGate:
        """``box`` as a gate in raw values; an open edge goes to the data's extreme."""
        corners = []
        for ch, lo, hi in ((box.x, *box.bounds[:2]), (box.y, *box.bounds[2:])):
            values = self.values[ch]
            lo = float(np.nanmin(values)) - 1.0 if np.isinf(lo) else lo
            hi = float(np.nanmax(values)) + 1.0 if np.isinf(hi) else hi
            corners.append(project_to_raw(np.array([lo, hi]), self.scales[ch]))
        (x_min, x_max), (y_min, y_max) = corners
        return RectangleGate(
            box.x,
            box.y,
            x_min=float(x_min),
            x_max=float(x_max),
            y_min=float(y_min),
            y_max=float(y_max),
            x_scale=self.scales[box.x].copy(),
            y_scale=self.scales[box.y].copy(),
        )


def propose_gates(
    events: pd.DataFrame, target: np.ndarray, scales: dict[str, AxisScale]
) -> list[ProposedGate]:
    """Gates on ``scales``' channels that best recover ``target`` among ``events``.

    The gates form a chain: each one is meant to be a child of the previous.
    """
    data = _DisplayData(events, scales)
    current = np.ones(len(events), dtype=bool)
    best_f1 = _scores(current, target)[0]
    boxes: list[tuple[_Box, float, float, float]] = []
    for _ in range(MAX_STEPS):
        best: tuple[float, float, float, _Box, np.ndarray] | None = None
        pool = current & target
        for x, y in combinations(scales, 2):
            box = data.fit(x, y, pool)
            selected = current & data.inside(box)
            f1, precision, recall = _scores(selected, target)
            if best is None or f1 > best[0]:
                best = (f1, precision, recall, box, selected)
        if best is None or best[0] < best_f1 + MIN_GAIN:
            break
        f1, precision, recall, box, current = best
        best_f1 = f1
        boxes.append((box, f1, precision, recall))
    return [ProposedGate(data.to_gate(box), f1, p, r) for box, f1, p, r in boxes]
