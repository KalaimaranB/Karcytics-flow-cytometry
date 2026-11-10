"""Turning a split into what a proposal shows: exact masks, named regions and a plot.

Shared by every way a split is found (the search methods and templates), so a
proposal always shows exactly what its gates will hold.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import numpy as np

from ..derived.expression import parse_formula
from .models import PlotData, Region
from .population import Frame

if TYPE_CHECKING:
    import pandas as pd

    from .population import PopulationData
    from .split import Split
    from .views import View


def with_pending(events: pd.DataFrame, view: View) -> pd.DataFrame:
    """``events`` plus a column for each combined axis, so proposed gates can be tested on them."""
    out = events
    for axis in (view.x, view.y):
        if axis.pending is not None:
            out = out.assign(
                **{
                    axis.key: parse_formula(axis.pending.formula).evaluate(
                        events, positive_denominators=False
                    )
                }
            )
    return out


def exact(split: Split, data: PopulationData, view: View) -> Split:
    """``split`` with each piece's mask what its gate holds, empty pieces dropped.

    The gate, not the shape it was fitted as, is what goes in the tree, so its
    numbers are the ones shown.
    """
    on_axes = with_pending(data.events, view)
    pieces = [
        replace(p, mask=np.asarray(p.gate.contains(on_axes), dtype=bool)) for p in split.pieces
    ]
    return replace(split, pieces=[p for p in pieces if p.mask.any()])


def regions_of(
    names: list[str], split: Split, frame: Frame, data: PopulationData, min_events: int
) -> list[Region]:
    """One region per piece, largest first; big enough ones (``min_events``) are to gate."""
    regions = []
    for name, piece in zip(names, split.pieces, strict=True):
        fraction = float(piece.mask.mean())
        regions.append(
            Region(
                name,
                fraction,
                tuple(float(v) for v in frame.unit(piece.outline).ravel()),
                piece.gate,
                piece.mask,
                is_main=fraction * data.parent_total >= min_events,
            )
        )
    return sorted(regions, key=lambda r: -r.fraction)


def plot_of(
    view: View, frame: Frame, data: PopulationData, regions: list[Region], split: Split
) -> PlotData:
    rows = data.plot_rows()
    points = frame.unit(np.column_stack((view.x.values[rows], view.y.values[rows])))
    cuts = tuple(
        (axis, float(frame.unit(np.array([[pos, pos]]))[0, 0 if axis == "x" else 1]))
        for axis, pos in split.cuts
    )
    return PlotData(view.x.label, view.y.label, points, tuple(regions), cuts=cuts)


def frame_of(view: View) -> Frame:
    return Frame.around(view.x.values, view.y.values)
