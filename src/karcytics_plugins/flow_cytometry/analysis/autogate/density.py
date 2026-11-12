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
CLEAR_PEAK = 0.1  # of the tallest: lower bumps on a population's tail are noise
MIN_PEAK_SHARE_2D = 0.05
GRID = 64  # bins per side of the 2-D density
GRID_SMOOTH_SD = 3.0  # bins, at FULL_DETAIL_EVENTS or more
FULL_DETAIL_EVENTS = 2_000  # fewer events: smoothed wider (by sqrt), so noise isn't read as peaks
MIN_PEAK_DISTANCE = 6  # bins between two 2-D peaks
MAX_PEAKS = 8  # the tallest 2-D peaks compared pairwise
PILE_SHARE = 0.001  # this many events on exactly a channel's top or bottom value: off scale


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


def on_scale(values: np.ndarray) -> np.ndarray:
    """False for off-scale events: those piled on exactly the lowest or highest value.

    A detector clips what it can't measure to its limit, so saturated events
    stack up there and look like a population. Searches leave them out; gates
    still hold them.
    """
    keep = np.isfinite(values)
    if not keep.any():
        return keep
    finite = values[keep]
    for edge in (finite.min(), finite.max()):
        at_edge = values == edge
        if at_edge.sum() >= max(2, PILE_SHARE * len(values)):
            keep &= ~at_edge
    return keep


def robust_range(values: np.ndarray) -> tuple[float, float]:
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return 0.0, 1.0
    lo, hi = np.quantile(finite, [EDGE_QUANTILE, 1 - EDGE_QUANTILE])
    if hi <= lo:
        hi = lo + 1.0
    return float(lo), float(hi)


def density(values: np.ndarray) -> Density:
    values = values[on_scale(values)]
    lo, hi = robust_range(values)
    counts, _ = np.histogram(values, bins=BINS, range=(lo, hi))
    radius = int(3 * SMOOTH_SD)
    kernel = np.exp(-0.5 * (np.arange(-radius, radius + 1) / SMOOTH_SD) ** 2)
    smooth = np.convolve(counts.astype(np.float64), kernel / kernel.sum(), mode="same")
    peak = smooth.max()
    return Density(lo, hi, smooth / peak if peak > 0 else smooth)


def find_valley(values: np.ndarray, side: str = "") -> Valley | None:
    """The deepest valley between two well-separated peaks; None if unimodal.

    ``side``: "below" or "above" keeps only valleys on that side of the tallest
    peak (debris sits below the cells on forward scatter, doublets above
    singlets on area/height).
    """
    d = density(values)
    h = d.heights
    peaks = [
        i
        for i in range(1, BINS - 1)
        if h[i] >= h[i - 1] and h[i] > h[i + 1] and h[i] >= MIN_PEAK_SHARE
    ]
    tallest = int(np.argmax(h))
    best: tuple[float, int] | None = None
    for a_i, a in enumerate(peaks):
        for b in peaks[a_i + 1 :]:
            if b - a < MIN_PEAK_GAP or (side == "below" and b > tallest):
                continue
            if side == "above" and a < tallest:
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


def peak_beyond(values: np.ndarray, position: float, above: bool) -> bool:
    """Whether a clear peak of ``values`` lies above (or below) ``position``: a
    population there, not just the tail of one on the other side.
    """
    d = density(values)
    h = d.heights
    centers = d.lo + (np.arange(BINS) + 0.5) * (d.hi - d.lo) / BINS
    return any(
        h[i] >= CLEAR_PEAK
        and h[i] >= h[i - 1]
        and h[i] > h[i + 1]
        and (centers[i] > position if above else centers[i] < position)
        for i in range(1, BINS - 1)
    )


def separation(x: np.ndarray, y: np.ndarray) -> float:
    """How clearly a 2-D view splits: the deepest valley along its axes or diagonals, or
    between two peaks of its 2-D density (which catches groups no single direction parts).
    """
    best = valley_2d(x, y)
    zx, zy = _standardize(x), _standardize(y)
    for line in (zx, zy, zx + zy, zx - zy):
        valley = find_valley(line)
        if valley is not None:
            best = max(best, valley.depth)
    return best


@dataclass(frozen=True)
class Grid:
    """A smoothed 2-D histogram: ``heights[i, j]`` at x bin i, y bin j; the tallest is 1."""

    heights: np.ndarray
    x_lo: float
    x_hi: float
    y_lo: float
    y_hi: float

    def to_display(self, ix: np.ndarray, iy: np.ndarray) -> np.ndarray:
        """Bin coordinates (fractional allowed) to display units, (n, 2)."""
        n = self.heights.shape[0]
        return np.column_stack(
            (
                self.x_lo + (ix + 0.5) * (self.x_hi - self.x_lo) / n,
                self.y_lo + (iy + 0.5) * (self.y_hi - self.y_lo) / n,
            )
        )


def smoothed_grid(
    x: np.ndarray, y: np.ndarray, bins: int = GRID, pad: float = 0.0, smooth: float = GRID_SMOOTH_SD
) -> Grid | None:
    """The view's density on a ``bins`` grid over its robust range (widened by ``pad`` of it
    on each side); None with too few on-scale events. Smoothing widens below
    FULL_DETAIL_EVENTS events, so noise isn't read as peaks.
    """
    keep = on_scale(x) & on_scale(y)
    if keep.sum() < bins:
        return None
    (xlo, xhi), (ylo, yhi) = robust_range(x[keep]), robust_range(y[keep])
    xlo, xhi = xlo - pad * (xhi - xlo), xhi + pad * (xhi - xlo)
    ylo, yhi = ylo - pad * (yhi - ylo), yhi + pad * (yhi - ylo)
    counts, _, _ = np.histogram2d(x[keep], y[keep], bins=bins, range=((xlo, xhi), (ylo, yhi)))
    sd = smooth * max(1.0, float(np.sqrt(FULL_DETAIL_EVENTS / keep.sum())))
    h = _smooth_2d(counts, sd)
    if h.max() <= 0:
        return None
    return Grid(h / h.max(), xlo, xhi, ylo, yhi)


def valley_2d(x: np.ndarray, y: np.ndarray) -> float:
    """The deepest valley on the straight line between two peaks of the smoothed 2-D density."""
    grid = smoothed_grid(x, y)
    if grid is None:
        return 0.0
    h = grid.heights
    peaks = peaks_2d(h)
    best = 0.0
    for i, a in enumerate(peaks):
        for b in peaks[i + 1 :]:
            n = int(max(abs(b[0] - a[0]), abs(b[1] - a[1]))) + 1
            rows = np.rint(np.linspace(a[0], b[0], n)).astype(int)
            cols = np.rint(np.linspace(a[1], b[1], n)).astype(int)
            floor = h[rows, cols].min()
            best = max(best, 1.0 - floor / min(h[a], h[b]))
    return float(best)


def _smooth_2d(counts: np.ndarray, sd: float) -> np.ndarray:
    radius = min(int(3 * sd), counts.shape[0] - 1)
    kernel = np.exp(-0.5 * (np.arange(-radius, radius + 1) / sd) ** 2)
    kernel /= kernel.sum()
    rows = np.apply_along_axis(np.convolve, 0, counts, kernel, mode="same")
    return np.apply_along_axis(np.convolve, 1, rows, kernel, mode="same")


def peaks_2d(
    h: np.ndarray,
    min_distance: int = MIN_PEAK_DISTANCE,
    min_share: float = MIN_PEAK_SHARE_2D,
    most: int = MAX_PEAKS,
) -> list[tuple[int, int]]:
    """Local maxima at least ``min_share`` tall and ``min_distance`` apart, tallest first."""
    padded = np.pad(h, 1, constant_values=-1.0)
    centre = padded[1:-1, 1:-1]
    is_max = centre >= min_share
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if dr or dc:
                is_max &= (
                    centre >= padded[1 + dr : h.shape[0] + 1 + dr, 1 + dc : h.shape[1] + 1 + dc]
                )
    peaks: list[tuple[int, int]] = []
    for r, c in sorted(zip(*np.nonzero(is_max), strict=True), key=lambda p: -h[p]):
        if all(max(abs(r - pr), abs(c - pc)) >= min_distance for pr, pc in peaks):
            peaks.append((int(r), int(c)))
        if len(peaks) == most:
            break
    return peaks


def _standardize(values: np.ndarray) -> np.ndarray:
    lo, hi = robust_range(values)
    return (values - lo) / (hi - lo)
