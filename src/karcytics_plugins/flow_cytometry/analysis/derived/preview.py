"""Quick preview statistics for a formula being edited.

Runs synchronously on a stable subsample so the editor can update as the
user types without a background task.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..rendering import stable_subsample_mask
from .expression import DerivedExpression

PREVIEW_MAX_EVENTS = 20_000
PREVIEW_BINS = 64


@dataclass(frozen=True)
class PreviewSummary:
    """What the editor shows under the formula.

    Attributes:
        n_events: Events evaluated (after subsampling).
        n_valid:  Of those, events with a finite result.
        n_plotted: Valid events inside the histogram (log scale drops ≤ 0).
        median:   Median of valid results, or None if there are none.
        counts:   Histogram bin counts (length ``PREVIEW_BINS`` or 0).
        edges:    Bin edges in data units (length ``len(counts) + 1``).
        log_scale: Whether bins are log-spaced.
    """

    n_events: int
    n_valid: int
    n_plotted: int
    median: float | None
    counts: np.ndarray
    edges: np.ndarray
    log_scale: bool

    @property
    def pct_invalid(self) -> float:
        if self.n_events == 0:
            return 0.0
        return 100.0 * (self.n_events - self.n_valid) / self.n_events


def compute_preview(
    expr: DerivedExpression,
    events: pd.DataFrame,
    *,
    positive_denominators: bool,
    log_scale: bool,
    max_events: int = PREVIEW_MAX_EVENTS,
    bins: int = PREVIEW_BINS,
) -> PreviewSummary:
    """Evaluate ``expr`` on (a subsample of) ``events`` and histogram it.

    Raises:
        KeyError: If a referenced channel is missing from ``events``.
    """
    if len(events) > max_events:
        events = events.loc[stable_subsample_mask(len(events), max_events)]
    values = expr.evaluate(events, positive_denominators=positive_denominators)
    valid = values[np.isfinite(values)]
    median = float(np.median(valid)) if len(valid) else None

    plotted = valid[valid > 0] if log_scale else valid
    counts, edges = _histogram(plotted, bins, log_scale)
    return PreviewSummary(
        n_events=len(values),
        n_valid=len(valid),
        n_plotted=len(plotted),
        median=median,
        counts=counts,
        edges=edges,
        log_scale=log_scale,
    )


def _histogram(values: np.ndarray, bins: int, log_scale: bool) -> tuple[np.ndarray, np.ndarray]:
    if len(values) == 0:
        return np.zeros(0, dtype=int), np.zeros(0)
    lo, hi = np.percentile(values, [0.5, 99.5])
    if log_scale:
        lo_e, hi_e = np.log10(lo), np.log10(hi)
        if hi_e <= lo_e:
            hi_e = lo_e + 1.0
        edges = np.logspace(lo_e, hi_e, bins + 1)
    else:
        if hi <= lo:
            hi = lo + 1.0
        edges = np.linspace(lo, hi, bins + 1)
    counts, _ = np.histogram(np.clip(values, edges[0], edges[-1]), bins=edges)
    return counts, edges
