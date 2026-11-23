"""Control tubes as reference points: where a marker's positive population starts.

An FMO control has every dye but one, so in that dye's channel it shows how far
negative events reach, spread from the other dyes included. Put through the
same gates as the population being split, its 99.5th percentile is where
"positive" starts: the standard way to place a positive gate, and the same
line for every sample in the group. With no FMO for a marker, an unstained
control stands in (autofluorescence only, so it is said to be weaker).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from .._utils import project_to_display
from ..clustering.describe import short_marker
from ..experiment import SampleRole
from .density import on_scale

if TYPE_CHECKING:
    import pandas as pd

    from ..experiment import Sample
    from ..scaling import AxisScale

PERCENTILE = 99.5
MIN_CONTROL_EVENTS = 200
FMO, UNSTAINED = "FMO", "unstained"


@dataclass(frozen=True)
class ControlLine:
    """Where a control says a marker's positives start, on one axis."""

    channel: str
    marker: str
    position: float  # display units
    control: str  # the control sample's name
    kind: str  # FMO or unstained
    events: int  # control events in the population, after the same gates

    @property
    def text(self) -> str:
        """The line's explanation for the gate's story."""
        weaker = (
            " (autofluorescence only: an FMO would also show the other dyes' spread)"
            if self.kind == UNSTAINED
            else ""
        )
        return (
            f"{self.marker}+ starts at {self.position:.2f}, above {PERCENTILE:g}% of the "
            f"{self.kind} control {self.control} ({self.events:,} events, same gates){weaker}"
        )

    def record(self) -> dict[str, object]:
        """The line, for the gate's record."""
        return {
            "control": self.control,
            "kind": self.kind,
            "at": round(self.position, 4),
            "percentile": PERCENTILE,
            "events": self.events,
        }


def control_for(samples: list[Sample], channel: str, label: str) -> tuple[Sample, str] | None:
    """The best control for ``channel``: an FMO lacking it, else an unstained tube."""
    names = {channel.lower(), label.lower(), short_marker(label).lower()}
    usable = [s for s in samples if s.fcs_data is not None]
    for s in usable:
        if s.role == SampleRole.FMO_CONTROL and (s.fmo_minus or "").strip().lower() in names:
            return s, FMO
    for s in usable:
        if s.role == SampleRole.UNSTAINED:
            return s, UNSTAINED
    return None


def control_line(
    control: Sample,
    kind: str,
    events: pd.DataFrame | None,
    channel: str,
    label: str,
    scale: AxisScale,
) -> ControlLine | None:
    """Where positive starts on ``channel`` by ``control``'s events in the same population."""
    if events is None or len(events) < MIN_CONTROL_EVENTS or channel not in events.columns:
        return None
    values = project_to_display(events[channel].to_numpy(dtype=np.float64), scale)
    values = values[on_scale(values)]
    if values.size < MIN_CONTROL_EVENTS:
        return None
    return ControlLine(
        channel,
        short_marker(label),
        float(np.percentile(values, PERCENTILE)),
        control.display_name,
        kind,
        len(events),
    )
