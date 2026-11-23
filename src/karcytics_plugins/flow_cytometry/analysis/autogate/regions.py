"""Density regions: populations as the areas their density covers, outlined as polygons.

The view's smoothed 2-D density is split into one basin per peak (a
watershed: every spot belongs to the peak it is reached from along the highest path). Two basins are one
population unless the highest pass between them is a clear valley, the same
valley depth every other method uses. Each population is outlined where its
density falls to OUTLINE of its peak, basin by basin (the level a single Gaussian has at
RADIUS standard deviations), so a gate follows the shape the cells make
rather than a box or an ellipse.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
from matplotlib.path import Path as MplPath

from .density import Grid, peaks_2d, smoothed_grid
from .mixture import RADIUS

if TYPE_CHECKING:
    from .views import View

BINS = 96
PAD = 0.15  # of each axis's robust range, so outlines aren't clipped at its ends
OUTLINE = float(np.exp(-0.5 * RADIUS**2))  # of a population's own peak
PEAK_SPACING = 6  # bins between two peaks
SMOOTH = 2.0  # bins; light, so a tight cluster (debris, dead cells) keeps its own peak
PEAK_SHARE = 0.01  # of the tallest: small populations get a basin; merging drops noise peaks
MOST_PEAKS = 16
MIN_SHARE = 0.01  # of the density: smaller regions are stray events
GAP_BINS = 3  # gaps this narrow between joined regions are closed
OWN_LEVEL_SHARE = 0.05  # of the tallest: a peak this tall is outlined at its own level
MAX_POINTS = 120  # an outline is thinned to at most this many vertices


@dataclass(frozen=True, eq=False)
class DensityRegion:
    """One density region: a set of grid bins around a peak."""

    mask: np.ndarray  # (BINS, BINS) bins in this population
    peak: tuple[float, float]  # display units
    height: float  # of its tallest peak, 0-1
    weight: float  # its share of the density


@dataclass(frozen=True, eq=False)
class DensityRegions:
    """A view's density regions, on one grid."""

    grid: Grid
    regions: tuple[DensityRegion, ...]  # largest first
    peaks: int  # found before merging

    def outline(self, mask: np.ndarray) -> np.ndarray | None:
        """The outer boundary of bins ``mask``, (n, 2) in display units; None if empty."""
        from contourpy import contour_generator  # karcytics: allow KS360 - only when gating

        if not mask.any():
            return None
        z = np.pad(mask.astype(np.float64).T, 1)  # rows: y bins; padded so it closes
        lines: list[np.ndarray] = [np.asarray(c) for c in contour_generator(z=z).lines(0.5)]
        if not lines:
            return None
        line = max(lines, key=len)
        line = line[:: max(1, len(line) // MAX_POINTS)]
        return self.grid.to_display(line[:, 0] - 1, line[:, 1] - 1)

    def joined(self, regions: list[DensityRegion]) -> np.ndarray | None:
        """One outline around ``regions`` together: small gaps between them closed, and
        only the part joined to the largest kept (a gate is a single shape).
        """
        from scipy.ndimage import binary_closing, label  # karcytics: allow KS360 - only when gating

        if not regions:
            return None
        mask = binary_closing(
            np.logical_or.reduce([r.mask for r in regions]), iterations=GAP_BINS, border_value=0
        )
        parts, _n = label(mask)
        anchor = parts[regions[0].mask]
        anchor = anchor[anchor > 0]
        if anchor.size == 0:
            return self.outline(regions[0].mask)
        return self.outline(parts == np.bincount(anchor).argmax())


def density_regions(x: np.ndarray, y: np.ndarray, min_valley: float) -> DensityRegions | None:
    """The view's populations as density regions; None with too few events."""
    grid = smoothed_grid(x, y, BINS, PAD, SMOOTH)
    if grid is None:
        return None
    h = grid.heights
    peaks = peaks_2d(h, PEAK_SPACING, PEAK_SHARE, MOST_PEAKS)
    basins = _flood(h, peaks)
    groups = _merge(h, basins, [float(h[p]) for p in peaks], min_valley)
    regions = []
    for members in groups:
        tallest = max(members, key=lambda m: h[peaks[m - 1]])
        top = float(h[peaks[tallest - 1]])
        # A clear peak is outlined against its own height, so a lower peak joined to a
        # taller one keeps its spread; a speck it absorbed uses the population's height.
        levels = {
            m: OUTLINE * (float(h[peaks[m - 1]]) if h[peaks[m - 1]] >= OWN_LEVEL_SHARE else top)
            for m in members
        }
        mask = np.logical_or.reduce([(basins == m) & (h >= levels[m]) for m in members])
        if not mask.any():
            continue
        i, j = peaks[tallest - 1]
        peak = grid.to_display(np.array([i]), np.array([j]))[0]
        regions.append(
            DensityRegion(mask, (float(peak[0]), float(peak[1])), top, float(h[mask].sum()))
        )
    total = sum(r.weight for r in regions) or 1.0
    ordered = sorted(
        (
            DensityRegion(r.mask, r.peak, r.height, r.weight / total)
            for r in regions
            if r.weight / total >= MIN_SHARE  # a few stray events are not a population
        ),
        key=lambda r: -r.weight,
    )
    return DensityRegions(grid, tuple(ordered), len(peaks))


def inside(outline: np.ndarray, view: View) -> np.ndarray:
    """Which of the view's events fall inside ``outline``."""
    return MplPath(outline).contains_points(np.column_stack((view.x.values, view.y.values)))


def _flood(h: np.ndarray, peaks: list[tuple[int, int]]) -> np.ndarray:
    """Each bin's peak: every peak grows downhill at once, the highest bins first.

    A bin goes to whichever peak reaches it along the highest path, so basins meet
    at the passes between peaks (a watershed on the density).
    """
    labels = np.zeros(h.shape, dtype=np.int32)
    queue: list[tuple[float, int, int]] = []
    for label, (i, j) in enumerate(peaks, start=1):
        labels[i, j] = label
        heapq.heappush(queue, (-float(h[i, j]), i, j))
    rows, cols = h.shape
    while queue:
        _level, i, j = heapq.heappop(queue)
        for ni, nj in ((i - 1, j), (i + 1, j), (i, j - 1), (i, j + 1)):
            if 0 <= ni < rows and 0 <= nj < cols and labels[ni, nj] == 0:
                labels[ni, nj] = labels[i, j]
                heapq.heappush(queue, (-float(h[ni, nj]), ni, nj))
    return labels


def _merge(
    h: np.ndarray, basins: np.ndarray, heights: list[float], min_valley: float
) -> list[list[int]]:
    """Basin labels grouped into populations, persistence style (as in ToMATo clustering).

    Passes are taken from the highest down, so a small basin joins the population it
    climbs into first, through its highest pass. Two basins already holding a
    population each join only if the pass between them is no clear valley for the
    lower one; otherwise a speck of noise between two populations would chain them.
    """
    passes: dict[tuple[int, int], float] = {}
    for a, b, level in (
        (basins[:-1, :], basins[1:, :], np.minimum(h[:-1, :], h[1:, :])),
        (basins[:, :-1], basins[:, 1:], np.minimum(h[:, :-1], h[:, 1:])),
    ):
        differ = a != b
        for la, lb, lv in zip(
            a[differ].tolist(), b[differ].tolist(), level[differ].tolist(), strict=True
        ):
            key = (min(la, lb), max(la, lb))
            passes[key] = max(passes.get(key, 0.0), lv)
    group = list(range(len(heights) + 1))
    top = [0.0, *heights]  # each population's tallest peak, kept at its root

    def root(i: int) -> int:
        while group[i] != i:
            i = group[i]
        return i

    for (first, second), saddle in sorted(passes.items(), key=lambda kv: -kv[1]):
        ra, rb = root(first), root(second)
        if ra == rb:
            continue
        low, high = (ra, rb) if top[ra] < top[rb] else (rb, ra)
        if 1.0 - saddle / top[low] < min_valley:
            group[low] = high
    members: dict[int, list[int]] = {}
    for label in range(1, len(heights) + 1):
        members.setdefault(root(label), []).append(label)
    return list(members.values())
