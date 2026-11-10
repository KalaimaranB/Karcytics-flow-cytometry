"""Turning a split into what a proposal shows: exact masks, named regions and a plot.

Shared by every way a split is found (the search methods and templates), so a
proposal always shows exactly what its gates will hold.
"""

from __future__ import annotations

import datetime
from dataclasses import replace
from typing import TYPE_CHECKING

import numpy as np

from ..clustering.describe import short_marker
from ..derived.expression import parse_formula
from .models import PCA, PlotData, Region
from .population import Frame
from .split import split_axis_record

if TYPE_CHECKING:
    import pandas as pd

    from .models import StepRequest
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


def record_of(  # noqa: PLR0913 - everything the record keeps
    key: str,
    data: PopulationData,
    view: View,
    notes: dict[str, object],
    split: Split,
    request: StepRequest,
) -> dict[str, object]:
    """What is stored on every accepted gate: the single source for its story."""
    record: dict[str, object] = {
        "method": key,
        "created": datetime.date.today().isoformat(),
        "reference_sample": data.sample.display_name,
        "parent": data.parent_name,
        "events_used": len(data.events),
        "parent_events": data.parent_total,
        "channels": [short_marker(data.labels[ch]) for ch in request.channels if ch in data.labels],
        "view": view.name,
        "view_score": round(view.score, 3),
        "x_axis": view.x.label,
        "y_axis": view.y.label,
        "axis_formulas": {
            a.label: a.pending.formula for a in (view.x, view.y) if a.pending is not None
        },
        "min_valley": request.min_valley,
    }
    record.update(split_axis_record(view))
    record.update(split.record)
    if key == PCA.key:
        record["loadings"] = notes.get("loadings")
        record["variance"] = notes.get("variance")
    return record
