"""What auto gating proposes, as plain data the Auto Gating tab renders.

The tab never computes anything itself: it builds a :class:`StepRequest`
from what the user picked, hands it to the engine (``engine.py``), and draws
what comes back. Outlines are in plot units, 0-1 on each axis of the view
they were found in, so a plot can draw them without knowing any scale.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import numpy as np

    from ..gating.base import Gate


@dataclass(frozen=True)
class MethodInfo:
    """One way of choosing the view to split. The only thing the methods differ in."""

    key: str
    name: str
    blurb: str  # one line under the name in the method picker
    user_picks_axes: bool  # True: the user chooses the axes; the engine only places the cuts


DENSITY_VALLEYS = MethodInfo(
    "valleys",
    "Density valleys",
    "You pick the axes; each cut goes at the low point between two peaks.",
    user_picks_axes=True,
)
MARKER_PAIRS = MethodInfo(
    "pairs",
    "Marker-pair search",
    "Tries every pair of real markers and splits on the clearest one.",
    user_picks_axes=False,
)
PCA = MethodInfo(
    "pca",
    "PCA",
    "Splits on combined axes (principal components), shown with what each is made of.",
    user_picks_axes=False,
)
METHODS: tuple[MethodInfo, ...] = (DENSITY_VALLEYS, MARKER_PAIRS, PCA)  # the searches
TEMPLATE = MethodInfo(
    "template",
    "From a template",
    "You write the gating tree and each population's markers; it finds where each gate goes.",
    user_picks_axes=False,
)
PICKABLE: tuple[MethodInfo, ...] = (*METHODS, TEMPLATE)


def method(key: str) -> MethodInfo:
    """The method with ``key`` (PCA for an unknown one)."""
    return next((m for m in PICKABLE if m.key == key), PCA)


@dataclass(frozen=True)
class StepRequest:
    """Split the population ``node_id`` of sample ``sample_id``."""

    method_key: str
    sample_id: str
    node_id: str | None  # None: All Events
    channels: tuple[str, ...]  # channel keys the split may use
    group: tuple[str, ...] = ()  # sample ids the gates go to
    x_channel: str = ""  # density valleys: the axes the user picked
    y_channel: str = ""
    view_rank: int = 0  # 0: the best view, 1: the next best, ...
    min_events: int = 500
    min_valley: float = 0.3  # real populations rarely part more cleanly; noise stays under 0.2
    cells_first: bool = True  # from All Events, cut debris off on FSC before anything else


@dataclass(frozen=True)
class Bar:
    """One bar of a ranking chart."""

    label: str
    value: float  # 0-1, or -1..1 for a signed list
    text: str  # the number as shown, "46%", "+0.68"


@dataclass(frozen=True)
class BarSection:
    """A titled list of bars: variance explained, loadings, pair scores."""

    title: str
    bars: tuple[Bar, ...]
    signed: bool = False  # bars grow both ways from the middle (loadings)
    highlight: tuple[int, ...] = ()  # rows drawn as chosen
    note: str = ""


@dataclass(frozen=True, eq=False)
class Region:
    """One population a split would create."""

    name: str
    fraction: float  # of the parent
    outline: tuple[float, ...]  # polygon in plot units: x0, y0, x1, y1, ...
    gate: Gate | None = None  # what accepting adds (None: shown only)
    mask: np.ndarray | None = None  # its events among the ones the split looked at
    is_main: bool = False  # big enough to gate: at least the smallest population's events


@dataclass(frozen=True, eq=False)
class PlotData:
    """Events and regions on one 2-D view, in plot units (0-1)."""

    x_label: str
    y_label: str
    points: np.ndarray  # (n, 2)
    regions: tuple[Region, ...] = ()
    ghosts: tuple[Region, ...] = ()  # drawn dashed and grey, for comparison
    cuts: tuple[tuple[str, float], ...] = ()  # ("x" or "y", position): density-valley cut lines

    @property
    def main_names(self) -> tuple[str, ...]:
        """The populations accepting would gate."""
        return tuple(r.name for r in self.regions if r.is_main)


@dataclass(frozen=True)
class PendingAxis:
    """A combined axis (a principal component) that accepting creates as a derived parameter."""

    key: str  # stands in for the parameter's id in the proposal's gates
    name: str
    formula: str


@dataclass(frozen=True, eq=False)
class Proposal:
    """One proposed split, and why."""

    method_key: str
    sample_id: str
    parent_id: str | None
    parent: str  # its name
    n_events: int
    plot: PlotData
    view_sections: tuple[BarSection, ...]  # how the view was chosen
    reason: str  # the plain-language case for this split
    pending_axes: tuple[PendingAxis, ...] = ()
    provenance: dict[str, Any] = field(default_factory=dict)  # stored on every accepted gate
    context: Any = None  # the engine's own: how to redo this split on another sample
    view_rank: int = 0  # the view it is on; the next best starts after it

    @property
    def gated(self) -> tuple[Region, ...]:
        """The main regions that became gates."""
        return tuple(r for r in self.plot.regions if r.is_main and r.gate is not None)


@dataclass(frozen=True, eq=False)
class SampleOutcome:
    """The proposed gates on one sample of the group."""

    sample: str
    percents: dict[str, float]  # population -> % of parent
    drift: float  # how far this sample's own split sits from the gates, share of the axis
    status: str
    flagged: bool
    plot: PlotData | None  # None: the sample is skipped


@dataclass(frozen=True, eq=False)
class GroupPreview:
    """A proposal's gates on every sample of the group, one row each."""

    populations: tuple[str, ...]
    rows: tuple[SampleOutcome, ...]


@dataclass(frozen=True, eq=False)
class MethodOutcome:
    """One method's split of the same population, or the user's own gates under it."""

    label: str  # "Your gates", or a method name
    method_key: str  # "" for the user's own gates
    percents: dict[str, float]
    agreement: dict[str, float]  # population -> F1 against the best-matching gate of yours
    summary: str  # the view, e.g. "CD4 × CD8"
    plot: PlotData | None
    error: str = ""  # why there is no split


@dataclass(frozen=True, eq=False)
class GateStory:
    """Everything recorded about why an auto gate is where it is."""

    gate: str
    method_key: str
    facts: tuple[tuple[str, str], ...]  # (label, value)
    sections: tuple[BarSection, ...]
    density: np.ndarray  # along the split axis, 0-1 heights
    valley_at: float  # 0-1 along that axis
    split_axis: str
    methods_text: str  # a paragraph for a paper's methods section
    edits: tuple[str, ...] = ()
