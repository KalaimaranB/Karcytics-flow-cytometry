"""Per-sample bookkeeping for derived columns (owned by derived/sync.py)."""

from __future__ import annotations

import weakref
from dataclasses import dataclass, field

import pandas as pd


@dataclass
class DerivedColumnsState:
    """What sync last wrote into one FCSData.

    Attributes:
        labels:     ``derived:<id>`` key -> display label. The only field
                    meant for readers outside sync (via ``derived_labels_of``).
        signatures: key -> definition signature the column was computed with.
        frame_ref:  Weak reference to the event frame sync last produced; any
                    other frame means the events were replaced underneath us.
    """

    labels: dict[str, str] = field(default_factory=dict)
    signatures: dict[str, str] = field(default_factory=dict)
    frame_ref: weakref.ref[pd.DataFrame] | None = field(default=None, compare=False)
