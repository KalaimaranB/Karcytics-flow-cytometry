"""The events a split looks at: one population, subsampled, on its display scales.

Splits are found in display space (where gates are drawn and populations look
compact), and every gate carries the same scales, so it draws where it was found.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np

from .._utils import project_to_display
from ..derived.sync import sync_sample
from ..fcs_io import get_channel_marker_label, get_scatter_channels
from ..population_matching import label_path_index, populations
from .density import robust_range

if TYPE_CHECKING:
    import pandas as pd

    from ..axis_manager import AxisManager
    from ..experiment import Sample
    from ..fcs_io import FCSData
    from ..scaling import AxisScale
    from ..state import FlowState

MAX_EVENTS = 20_000  # a split looks at no more than this many events of its population
PLOT_POINTS = 3_000
SEED = 0


@dataclass(eq=False)
class PopulationData:
    sample: Sample
    parent_id: str | None
    parent_name: str
    events: pd.DataFrame  # raw values, subsampled
    parent_total: int  # events in the population before subsampling
    scales: dict[str, AxisScale]
    labels: dict[str, str]  # channel -> "CD4 (PE-A)"
    display: dict[str, np.ndarray] = field(default_factory=dict)

    def on_display(self, channel: str) -> np.ndarray:
        if channel not in self.display:
            self.display[channel] = project_to_display(
                self.events[channel].to_numpy(dtype=np.float64), self.scales[channel]
            )
        return self.display[channel]

    def plot_rows(self) -> np.ndarray:
        return plot_rows(len(self.events))


def plot_rows(n: int) -> np.ndarray:
    """The rows drawn on a plot: all of them, up to PLOT_POINTS."""
    if n <= PLOT_POINTS:
        return np.arange(n)
    return np.sort(np.random.default_rng(SEED).choice(n, PLOT_POINTS, replace=False))


def population_events(sample: Sample, node_id: str | None) -> tuple[pd.DataFrame | None, str]:
    """All events of the population ``node_id`` (the sample's when None), and its name."""
    fcs = sample.fcs_data
    if fcs is None or fcs.events is None:
        return None, ""
    node = sample.gate_tree.find_node_by_id(node_id) if node_id else None
    if node is None:
        return fcs.events, "All Events"
    return node.apply_hierarchy(fcs.events), node.name


def same_population(
    reference: Sample, node_id: str | None, other: Sample
) -> tuple[bool, str | None]:
    """(found, node id) of the population in ``other`` with the reference one's path of names.

    Matched by path ("Lymphocytes / T cells"), as Statistics does, not by id. A node
    id of None is All Events, found everywhere.
    """
    if node_id is None:
        return True, None
    path = next((p for p, n in populations(reference) if n.node_id == node_id), None)
    found = label_path_index(other).get(path) if path is not None else None
    return found is not None, found


def subsample(events: pd.DataFrame, max_events: int = MAX_EVENTS) -> pd.DataFrame:
    if len(events) <= max_events:
        return events
    rows = np.sort(np.random.default_rng(SEED).choice(len(events), max_events, replace=False))
    return events.iloc[rows]


def load_population(  # noqa: PLR0913 - the request, unpacked
    state: FlowState,
    axis_manager: AxisManager,
    sample_id: str,
    node_id: str | None,
    channels: tuple[str, ...],
    min_events: int,
) -> PopulationData | str:
    """The population's data, or why it can't be split."""
    experiment = state.data.experiment
    sample = experiment.samples.get(sample_id)
    if sample is None:
        return "Pick a reference sample."
    sync_sample(experiment, sample)
    events, name = population_events(sample, node_id)
    if events is None:
        return f"{sample.display_name} has no events loaded."
    if len(events) < min_events:
        return f"{name} has {len(events):,} events, fewer than the smallest population ({min_events:,})."
    missing = [ch for ch in channels if ch not in events.columns]
    if missing:
        return f"{sample.display_name} has no channel {missing[0]}."
    scales = {ch: axis_manager.get_scale(ch, sample_id) for ch in channels}
    fcs = sample.fcs_data
    assert fcs is not None  # it has events
    labels = {ch: get_channel_marker_label(fcs, ch) for ch in channels}
    return PopulationData(sample, node_id, name, subsample(events), len(events), scales, labels)


@dataclass(frozen=True)
class Frame:
    """Maps a view's display values to plot units (0-1) by each axis's robust range."""

    x_lo: float
    x_hi: float
    y_lo: float
    y_hi: float

    @classmethod
    def around(cls, x: np.ndarray, y: np.ndarray) -> Frame:
        return cls(*robust_range(x), *robust_range(y))

    def unit(self, xy: np.ndarray) -> np.ndarray:
        return np.column_stack(
            (
                (xy[:, 0] - self.x_lo) / (self.x_hi - self.x_lo),
                (xy[:, 1] - self.y_lo) / (self.y_hi - self.y_lo),
            )
        )

    def span(self, axis: str) -> float:
        return (self.x_hi - self.x_lo) if axis == "x" else (self.y_hi - self.y_lo)


def scatter_pair(data: FCSData) -> tuple[str | None, str | None]:
    """The forward and side scatter channels to plot cells on, area (``-A``) preferred."""
    scatter = get_scatter_channels(data)

    def pick(prefix: str) -> str | None:
        named = [ch for ch in scatter if ch.startswith(prefix)]
        return next((ch for ch in named if ch.endswith("-A")), named[0] if named else None)

    return pick("FSC"), pick("SSC")


def singlet_pair(data: FCSData) -> tuple[str, str] | None:
    """Forward-scatter area and height, the axes doublets show on; None without both."""
    channels = set(data.channels)
    for area, height in (("FSC-A", "FSC-H"), ("SSC-A", "SSC-H")):
        if area in channels and height in channels:
            return area, height
    return None
