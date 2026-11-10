"""Names for the populations a split creates, read from their markers ("CD4+ CD8−").

The same +/lo/− calls the clustering views use (``clustering.describe``),
limited to the few markers that differ most between the new populations. Each
marker's scale runs at least across the whole sample's spread (SPAN quantiles),
so "+" means bright by the sample's standards, not just brighter than a sibling:
a dim group split off inside "PI−" is not called "PI+".
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from .._utils import project_to_display
from ..clustering.describe import MIN_SPREAD, MarkerScale, call
from .density import robust_range
from .population import population_events, subsample

if TYPE_CHECKING:
    from .population import PopulationData

MIN_MARKERS, MAX_MARKERS = 2, 4
SCATTER_CALLS = {"+": "hi", "lo": "mid", "−": "lo"}  # FSC/SSC are read as size and granularity
SPAN = (0.05, 0.95)  # the whole sample's quantiles every marker's scale covers


def _called(marker: str, level: float) -> str:
    c = call(level)
    return f"{marker}{SCATTER_CALLS[c]}" if marker.startswith(("FSC", "SSC")) else f"{marker}{c}"


def name_regions(
    data: PopulationData, channels: tuple[str, ...], masks: list[np.ndarray]
) -> list[str]:
    """One name per mask; masks that share a phenotype are numbered."""
    if not masks or not channels:
        return [f"Population {i + 1}" for i in range(len(masks))]
    whole = _whole_sample(data, channels)
    columns = []
    for ch in channels:
        lo, hi = robust_range(whole[ch])
        columns.append((data.on_display(ch) - lo) / (hi - lo))
        whole[ch] = (whole[ch] - lo) / (hi - lo)
    x = np.nan_to_num(np.column_stack(columns))
    groups = np.full(len(x), -1)
    for i, mask in enumerate(masks):
        groups[mask & (groups == -1)] = i
    present = [i for i in range(len(masks)) if (groups == i).any()]
    labels = [data.labels[ch] for ch in channels]
    between = MarkerScale.from_clusters(x, groups, labels)  # how far apart the groups are
    scale = _widened(between, whole, channels)
    ranked = [int(i) for i in np.argsort(-between.spread) if between.spread[i] >= MIN_SPREAD]
    levels = {i: scale.level(x[groups == i]) for i in present}
    names: list[str] = []
    # The fewest markers (most different first, at least two) that tell every population apart.
    for count in range(min(MIN_MARKERS, len(ranked)), min(MAX_MARKERS, len(ranked)) + 1):
        shown = sorted(ranked[:count])
        names = [
            " ".join(_called(scale.markers[m], levels[i][m]) for m in shown)
            if i in levels
            else f"Population {i + 1}"
            for i in range(len(masks))
        ]
        if len(set(names)) == len(names):
            break
    if not ranked:  # no marker differs between them: nothing to name them by
        names = [f"Population {i + 1}" for i in range(len(masks))]
    return _numbered(names)


def _whole_sample(data: PopulationData, channels: tuple[str, ...]) -> dict[str, np.ndarray]:
    """Each channel's display values over (a subsample of) the whole sample."""
    events, _name = population_events(data.sample, None)
    if events is None:
        return {ch: data.on_display(ch) for ch in channels}
    events = subsample(events)
    return {
        ch: project_to_display(events[ch].to_numpy(dtype=np.float64), data.scales[ch])
        if ch in events.columns
        else data.on_display(ch)
        for ch in channels
    }


def _widened(
    scale: MarkerScale, whole: dict[str, np.ndarray], channels: tuple[str, ...]
) -> MarkerScale:
    """``scale`` stretched to cover the whole sample's SPAN on every marker."""
    spans = np.array([np.nanquantile(whole[ch], SPAN) for ch in channels])
    low = np.minimum(scale.low, spans[:, 0])
    high = np.maximum(scale.low + scale.spread, spans[:, 1])
    return MarkerScale(scale.markers, low, high - low)


def _numbered(names: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    out = []
    for name in names:
        seen[name] = seen.get(name, 0) + 1
        out.append(name if seen[name] == 1 else f"{name} ({seen[name]})")
    return out
