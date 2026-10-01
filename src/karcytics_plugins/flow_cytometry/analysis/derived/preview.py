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
        reference_counts: The reference events binned on the same edges
            (e.g. the whole sample behind one population), or None.
        ticks:    ``(fraction along the axis, label)`` pairs for axis labels.
    """

    n_events: int
    n_valid: int
    n_plotted: int
    median: float | None
    counts: np.ndarray
    edges: np.ndarray
    log_scale: bool
    reference_counts: np.ndarray | None = None
    ticks: tuple[tuple[float, str], ...] = ()

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
    reference: pd.DataFrame | None = None,
    max_events: int = PREVIEW_MAX_EVENTS,
    bins: int = PREVIEW_BINS,
) -> PreviewSummary:
    """Evaluate ``expr`` on (a subsample of) ``events`` and histogram it.

    With ``reference`` (e.g. the whole sample when ``events`` is one
    population), the axis range comes from the reference and its counts are
    returned too, so switching population keeps the axis still and shows
    where the population sits within the sample.

    Raises:
        KeyError: If a referenced channel is missing from ``events``.
    """
    values = _evaluate(expr, events, positive_denominators, max_events)
    valid = values[np.isfinite(values)]
    median = float(np.median(valid)) if len(valid) else None
    plotted = _plottable(valid, log_scale)

    ref_plotted = None
    if reference is not None:
        ref_values = _evaluate(expr, reference, positive_denominators, max_events)
        ref_plotted = _plottable(ref_values[np.isfinite(ref_values)], log_scale)
    edges = _edges(
        ref_plotted if ref_plotted is not None and len(ref_plotted) else plotted, bins, log_scale
    )
    return PreviewSummary(
        n_events=len(values),
        n_valid=len(valid),
        n_plotted=len(plotted),
        median=median,
        counts=_counts(plotted, edges),
        edges=edges,
        log_scale=log_scale,
        reference_counts=None if ref_plotted is None else _counts(ref_plotted, edges),
        ticks=_ticks(edges, log_scale),
    )


def _evaluate(
    expr: DerivedExpression, events: pd.DataFrame, positive_denominators: bool, max_events: int
) -> np.ndarray:
    if len(events) > max_events:
        events = events.loc[stable_subsample_mask(len(events), max_events)]
    return expr.evaluate(events, positive_denominators=positive_denominators)


def _plottable(valid: np.ndarray, log_scale: bool) -> np.ndarray:
    return valid[valid > 0] if log_scale else valid


def _counts(values: np.ndarray, edges: np.ndarray) -> np.ndarray:
    if len(edges) == 0:
        return np.zeros(0, dtype=int)
    counts, _ = np.histogram(np.clip(values, edges[0], edges[-1]), bins=edges)
    return counts


def _ticks(edges: np.ndarray, log_scale: bool) -> tuple[tuple[float, str], ...]:
    """Axis labels: each decade on a log axis, ~4 round numbers on a linear one."""
    if len(edges) < 2:  # noqa: PLR2004
        return ()
    lo, hi = float(edges[0]), float(edges[-1])
    if log_scale:
        exps = range(int(np.ceil(np.log10(lo) - 1e-9)), int(np.floor(np.log10(hi) + 1e-9)) + 1)
        span = np.log10(hi) - np.log10(lo)
        return tuple(((k - np.log10(lo)) / span, f"{10.0**k:g}") for k in exps)
    values = _round_ticks(lo, hi)
    return tuple(((v - lo) / (hi - lo), f"{v:.4g}") for v in values)


_MAX_LINEAR_TICKS = 6


def _round_ticks(lo: float, hi: float) -> np.ndarray:
    """Multiples of the smallest 1/2/5×10^k step giving at most 6 ticks."""
    magnitude = 10.0 ** np.floor(np.log10((hi - lo) / _MAX_LINEAR_TICKS))
    for mult in (1, 2, 5, 10, 20):
        step = mult * magnitude
        values = np.arange(np.ceil(lo / step) * step, hi + step * 1e-9, step)
        if len(values) <= _MAX_LINEAR_TICKS:
            return np.round(values / step) * step
    return np.array([lo, hi])


def _edges(values: np.ndarray, bins: int, log_scale: bool) -> np.ndarray:
    if len(values) == 0:
        return np.zeros(0)
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
    return edges
