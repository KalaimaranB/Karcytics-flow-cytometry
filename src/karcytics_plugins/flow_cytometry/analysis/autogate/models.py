"""What auto gating proposes, as plain data the Auto Gating tab renders.

The tab never computes anything itself: it builds a :class:`StepRequest`
from what the user picked, hands it to an engine (see ``engine.py``), and
draws what comes back. Shapes are in display units, 0-1 on each axis of the
view they were found in, so a plot can draw them without knowing any scale.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import numpy as np


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
METHODS: tuple[MethodInfo, ...] = (DENSITY_VALLEYS, MARKER_PAIRS, PCA)


def method(key: str) -> MethodInfo:
    return next((m for m in METHODS if m.key == key), PCA)


@dataclass(frozen=True)
class StepRequest:
    """What the user asked for: split ``population`` of the reference sample."""

    method_key: str
    population: str  # display name of the population to split
    channels: tuple[str, ...]  # channel labels, "CD4 (PE-A)"
    samples: tuple[tuple[str, bool], ...] = ()  # the group: (name, is_control)
    reference: str = ""
    x_channel: str = ""  # density valleys: the axes the user picked
    y_channel: str = ""
    view_rank: int = 0  # 0: the best view, 1: the next best, ...


@dataclass(frozen=True)
class Bar:
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


class Shape(Enum):
    ELLIPSE = "ellipse"  # params: cx, cy, rx, ry, angle in degrees
    POLYGON = "polygon"  # params: x0, y0, x1, y1, ...
    QUADRANT = "quadrant"  # params: x cut, y cut, quadrant 0-3 (TL, TR, BL, BR)
    RANGE = "range"  # params: low, high (x only)


MAIN_SHARE = 0.1  # a region holding less of its parent is a sliver, not a population to gate


@dataclass(frozen=True)
class Region:
    """One population a split would create."""

    name: str
    fraction: float  # of the parent
    shape: Shape
    params: tuple[float, ...]

    @property
    def is_main(self) -> bool:
        return self.fraction >= MAIN_SHARE


@dataclass(frozen=True, eq=False)
class PlotData:
    """Events and regions on one 2-D view, all in display units (0-1)."""

    x_label: str
    y_label: str
    points: np.ndarray  # (n, 2)
    regions: tuple[Region, ...] = ()
    ghosts: tuple[Region, ...] = ()  # where a region was before it moved

    @property
    def main_names(self) -> tuple[str, ...]:
        """The populations accepting would gate."""
        return tuple(r.name for r in self.regions if r.is_main)


@dataclass(frozen=True, eq=False)
class Proposal:
    """One proposed split, and why."""

    method_key: str
    parent: str
    n_events: int
    plot: PlotData
    view_sections: tuple[BarSection, ...]  # how the view was chosen
    reason: str  # the plain-language case for this split


@dataclass(frozen=True, eq=False)
class SampleOutcome:
    """The proposed gates on one sample of the group."""

    sample: str
    percents: dict[str, float]  # population -> % of parent
    shift: float  # largest gate move, as a share of the axis (0 when fixed)
    status: str
    flagged: bool
    plot: PlotData | None  # None: the sample is skipped


@dataclass(frozen=True, eq=False)
class GroupPreview:
    populations: tuple[str, ...]
    rows: tuple[SampleOutcome, ...]


@dataclass(frozen=True, eq=False)
class MethodOutcome:
    """One method's whole strategy from the same starting population."""

    label: str  # "Your gates", or a method name
    method_key: str  # "" for the user's own gates
    percents: dict[str, float]
    agreement: dict[str, float]  # population -> F1 against your gates
    steps: int
    axes: str
    plot: PlotData


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
    edits: tuple[str, ...] = field(default=())
