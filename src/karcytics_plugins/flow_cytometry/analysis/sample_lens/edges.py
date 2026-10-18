"""How fragile a gate is on a sample, and how it compares across samples.

*Edge density*: the share of the parent's events that change sides when nudged
by a small step on either axis of the gate, in display space. A high share
means the edge runs through a dense part of the data, so a small move of the
gate (or a small staining shift) changes the result a lot. Using
``Gate.contains`` on nudged copies keeps this independent of the gate's shape.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np

from .._utils import project_to_display, project_to_raw
from ..gating import (
    EllipseGate,
    PolygonGate,
    QuadrantGate,
    QuadrantSubGate,
    RangeGate,
    RectangleGate,
    SubsetGate,
)
from ..population_matching import populations
from ..scaling import AxisScale

if TYPE_CHECKING:
    import pandas as pd

    from ..experiment import Sample
    from ..gating import Gate

EDGE_STEP = 0.02  # nudge: this share of the parent's display range on that axis
EDGE_SAMPLE = 20_000  # parent events used for the check; plenty for a share
FRAGILE_ABOVE = 0.05  # an edge share above this is flagged
OUTLIER_MIN_PTS = 5.0  # an outlier must also be this many % points off the median


def gate_axes(gate: Gate) -> list[tuple[str, AxisScale]]:
    """The (channel, display scale) pairs a gate's edges live on."""
    target = gate.parent if isinstance(gate, QuadrantSubGate) else gate
    if isinstance(target, SubsetGate):
        return []
    axes = [(target.x_param, getattr(target, "x_scale", None) or AxisScale())]
    if target.y_param:
        axes.append((target.y_param, getattr(target, "y_scale", None) or AxisScale()))
    return axes


def gate_extent(gate: Gate) -> dict[str, tuple[float, float]]:
    """The raw-value span a gate covers on each of its channels, to keep it in view.

    An ellipse gets its centre plus its longest semi-axis either way (rotation
    ignored); a quadrant its crosshair. Infinite (open) ends are left out.
    """
    target = gate.parent if isinstance(gate, QuadrantSubGate) else gate
    spans: list[tuple[str | None, float, float]] = []
    if isinstance(target, RangeGate):
        spans.append((target.x_param, target.low, target.high))
    elif isinstance(target, RectangleGate):
        spans += [
            (target.x_param, target.x_min, target.x_max),
            (target.y_param, target.y_min, target.y_max),
        ]
    elif isinstance(target, PolygonGate) and target.vertices:
        xs, ys = zip(*target.vertices, strict=True)
        spans += [(target.x_param, min(xs), max(xs)), (target.y_param, min(ys), max(ys))]
    elif isinstance(target, EllipseGate):
        (cx, cy), r = target.center, max(target.width, target.height)
        spans += [(target.x_param, cx - r, cx + r), (target.y_param, cy - r, cy + r)]
    elif isinstance(target, QuadrantGate):
        spans += [(target.x_param, target.x_mid, target.x_mid)]
        spans += [(target.y_param, target.y_mid, target.y_mid)]
    return {
        param: (lo if np.isfinite(lo) else hi, hi if np.isfinite(hi) else lo)
        for param, lo, hi in spans
        if param and (np.isfinite(lo) or np.isfinite(hi))
    }


def edge_fraction(gate: Gate, parent_events: pd.DataFrame, seed: int = 0) -> float:
    """Share of ``parent_events`` sitting on ``gate``'s edge (see the module docstring)."""
    axes = gate_axes(gate)
    if not axes or parent_events.empty:
        return 0.0
    if len(parent_events) > EDGE_SAMPLE:
        rng = np.random.default_rng(seed)
        parent_events = parent_events.iloc[rng.choice(len(parent_events), EDGE_SAMPLE, False)]
    events = parent_events[list(dict.fromkeys(param for param, _ in axes))]

    inside = gate.contains(events)
    on_edge = np.zeros(len(events), dtype=bool)
    for param, scale in axes:
        display = project_to_display(events[param].to_numpy(dtype=np.float64), scale)
        lo, hi = np.nanpercentile(display, [1, 99])
        step = EDGE_STEP * max(hi - lo, 1e-9)
        for sign in (1.0, -1.0):
            nudged = events.assign(**{param: project_to_raw(display + sign * step, scale)})
            on_edge |= gate.contains(nudged) != inside
    return float(on_edge.mean())


@dataclass
class SampleCheck:
    sample_id: str
    sample_name: str
    pct_parent: float
    count: int
    edge_fraction: float
    flags: list[str] = field(default_factory=list)


def check_across(samples: list[tuple[Sample, pd.DataFrame]], path: str) -> list[SampleCheck]:
    """``path``'s population in every sample that has it, with odd ones flagged.

    ``samples`` pairs each sample with its root events (derived columns synced).
    """
    checks = []
    for sample, events in samples:
        node = dict(populations(sample)).get(path)
        if node is None:
            continue
        parent = node.parent_mask(events)
        inside = node.mask(events)
        n_parent = int(parent.sum())
        edge = edge_fraction(node.gate, events.loc[parent]) if node.gate is not None else 0.0
        check = SampleCheck(
            sample.sample_id,
            sample.display_name,
            100.0 * int(inside.sum()) / n_parent if n_parent else 0.0,
            int(inside.sum()),
            edge,
        )
        if edge > FRAGILE_ABOVE:
            check.flags.append("edge in a dense region")
        checks.append(check)
    _flag_outliers(checks)
    return checks


def _flag_outliers(checks: list[SampleCheck]) -> None:
    if len(checks) < 3:  # noqa: PLR2004 - a median of two says nothing
        return
    pcts = np.array([c.pct_parent for c in checks])
    median = float(np.median(pcts))
    mad = 1.4826 * float(np.median(np.abs(pcts - median)))
    limit = max(3 * mad, OUTLIER_MIN_PTS)
    for check in checks:
        if abs(check.pct_parent - median) > limit:
            check.flags.append(f"outlier ({check.pct_parent - median:+.1f} pts vs median)")
