"""One-dimensional densities and the valley between two peaks.

A valley's depth says how empty the gap between two populations is: 1 means
no events between the peaks, 0 means no dip at all. It is the one number
every method uses to judge a view, so they can be compared.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

BINS = 128
SMOOTH_SD = 2.0  # bins
EDGE_QUANTILE = 0.005  # the axis runs from this quantile to 1 minus it
MIN_PEAK_GAP = 8  # bins between two peaks
MIN_PEAK_SHARE = 0.03  # a peak must be at least this high relative to the tallest


@dataclass(frozen=True)
class Density:
    """A smoothed histogram over the values' robust range."""

    lo: float
    hi: float
    heights: np.ndarray  # BINS values, the tallest is 1

    def at(self, position: float) -> float:
        """Where ``position`` falls along the axis, 0-1."""
        return float((position - self.lo) / (self.hi - self.lo)) if self.hi > self.lo else 0.5


@dataclass(frozen=True)
class Valley:
    position: float  # in the values' units
    depth: float  # 0 (no dip) to 1 (empty between the peaks)
    density: Density


def robust_range(values: np.ndarray) -> tuple[float, float]:
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return 0.0, 1.0
    lo, hi = np.quantile(finite, [EDGE_QUANTILE, 1 - EDGE_QUANTILE])
    if hi <= lo:
        hi = lo + 1.0
    return float(lo), float(hi)


def density(values: np.ndarray) -> Density:
    lo, hi = robust_range(values)
    counts, _ = np.histogram(values[np.isfinite(values)], bins=BINS, range=(lo, hi))
    radius = int(3 * SMOOTH_SD)
    kernel = np.exp(-0.5 * (np.arange(-radius, radius + 1) / SMOOTH_SD) ** 2)
    smooth = np.convolve(counts.astype(np.float64), kernel / kernel.sum(), mode="same")
    peak = smooth.max()
    return Density(lo, hi, smooth / peak if peak > 0 else smooth)


def find_valley(values: np.ndarray) -> Valley | None:
    """The deepest valley between the two tallest well-separated peaks; None if unimodal."""
    d = density(values)
    h = d.heights
    peaks = [
        i
        for i in range(1, BINS - 1)
        if h[i] >= h[i - 1] and h[i] > h[i + 1] and h[i] >= MIN_PEAK_SHARE
    ]
    best: tuple[float, int] | None = None
    for a_i, a in enumerate(peaks):
        for b in peaks[a_i + 1 :]:
            if b - a < MIN_PEAK_GAP:
                continue
            between = h[a : b + 1]
            floor = between.min()
            # The middle of the lowest stretch: an empty gap has no single lowest bin.
            flat = np.flatnonzero(between <= floor + 1e-3 * min(h[a], h[b]))
            low = a + int(flat[len(flat) // 2])
            depth = 1.0 - floor / min(h[a], h[b])
            if best is None or depth > best[0]:
                best = (depth, low)
    if best is None:
        return None
    depth, low = best
    position = d.lo + (low + 0.5) * (d.hi - d.lo) / BINS
    return Valley(float(position), float(depth), d)


def separation(x: np.ndarray, y: np.ndarray) -> float:
    """How clearly a 2-D view splits: the deepest valley along its axes or diagonals."""
    best = 0.0
    zx, zy = _standardize(x), _standardize(y)
    for line in (zx, zy, zx + zy, zx - zy):
        valley = find_valley(line)
        if valley is not None:
            best = max(best, valley.depth)
    return best


def _standardize(values: np.ndarray) -> np.ndarray:
    lo, hi = robust_range(values)
    return (values - lo) / (hi - lo)
