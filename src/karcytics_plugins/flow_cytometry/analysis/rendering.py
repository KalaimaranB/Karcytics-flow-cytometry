"""Functional rendering core for flow cytometry plots.

Contains the math and data processing logic for creating histograms,
pseudocolor density maps, and contour plots.
Decoupled from both PyQt and Matplotlib backend details where possible.
"""

from __future__ import annotations

import numpy as np
from fast_histogram import histogram2d as fast_hist2d
from karcytics_sdk.plugin import get_logger
from scipy.ndimage import gaussian_filter, map_coordinates
from scipy.stats import rankdata

from .constants import (
    DEFAULT_NBINS_MAX,
    DEFAULT_NBINS_MIN,
    DENSITY_THRESHOLD_MIN,
    NBINS_SCALING_FACTOR,
    SIGMA_MIN,
    SIGMA_SCALING_FACTOR,
    VIBRANCY_MIN,
    VIBRANCY_RANGE,
)

logger = get_logger(__name__, "flow_cytometry")


def stable_subsample_mask(n: int, k: int, seed: int = 42) -> np.ndarray:
    """Boolean mask selecting ~k of n events, stable under tiny changes in n.

    ``np.random.Generator.choice(n, k, replace=False)`` looks deterministic
    (fixed seed) but its *selected set* is a chaotic function of ``n``: two
    populations differing by only a handful of events out of hundreds of
    thousands — the kind of gap that legitimately arises from floating-point
    rounding at a gate boundary on different platforms/BLAS builds — can
    still end up with under 50% overlap in which events get kept. Since the
    downstream density/threshold computation is sensitive to exactly which
    events populate the low-density boundary between subpopulations, that
    near-total resampling was enough to visibly merge or split a population
    that should have rendered the same way.

    This avoids that by making each event's inclusion an independent
    Bernoulli draw from a fixed PRNG *stream*, keyed only by the event's own
    index. Extending or shrinking n by a few events shifts the stream by the
    same few positions — every other event's draw, and therefore its
    inclusion decision, is unaffected. Only ``|k/n|`` needs to hold
    approximately, so the actual kept count varies slightly around k; that's
    fine for a density-map subsample and far preferable to being a chaotic
    function of population size.
    """
    if n <= k:
        return np.ones(n, dtype=bool)
    frac = k / n
    rng = np.random.default_rng(seed)
    return rng.random(n) < frac


def compute_pseudocolor_base_density(  # noqa: PLR0913, PLR0917
    x: np.ndarray,
    y: np.ndarray,
    max_events: int,
    *,
    enabled: bool = True,
    nbins_scaling: float | None = None,
    sigma_scaling: float | None = None,
    density_threshold: float | None = None,
    vibrancy_min: float | None = None,
    vibrancy_range: float | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    """Subsample to `max_events` (via `stable_subsample_mask`) and compute
    pseudocolor density for a "base/context" layer, or return None if
    disabled or there's no data.

    Convenience wrapper around `compute_pseudocolor_points` for callers that
    just want "the whole array, density-shaded, capped at N points" — e.g.
    the Comparisons Pseudocolor Overlay plot type's base layer — without
    each caller re-deriving the axis range and subsample-then-compute steps
    themselves. The optional density-shaping kwargs forward straight through
    to `compute_pseudocolor_points` (falling back to its own defaults when
    omitted), letting a caller drive this with a `PseudocolorConfig`.
    """
    if not enabled or len(x) == 0 or len(y) == 0:
        return None
    x_sub, y_sub = x, y
    if len(x_sub) > max_events:
        mask = stable_subsample_mask(len(x_sub), max_events)
        x_sub, y_sub = x_sub[mask], y_sub[mask]
    return compute_pseudocolor_points(
        x_sub,
        y_sub,
        (float(np.nanmin(x)), float(np.nanmax(x))),
        (float(np.nanmin(y)), float(np.nanmax(y))),
        nbins_scaling=nbins_scaling,
        sigma_scaling=sigma_scaling,
        density_threshold=density_threshold,
        vibrancy_min=vibrancy_min,
        vibrancy_range=vibrancy_range,
    )


def compute_pseudocolor_points(  # noqa: PLR0913, PLR0917
    x: np.ndarray,
    y: np.ndarray,
    x_range: tuple[float, float],
    y_range: tuple[float, float],
    quality_multiplier: float = 1.0,
    nbins_scaling: float | None = None,
    sigma_scaling: float | None = None,
    density_threshold: float | None = None,
    vibrancy_min: float | None = None,
    vibrancy_range: float | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Compute robust, industry-standard pseudocolor density.

    Uses rank-based normalization to ensure visual parity between sparse
    thumbnails and dense main plots.
    """
    valid = np.isfinite(x) & np.isfinite(y)
    x_vis, y_vis = x[valid], y[valid]

    if len(x_vis) == 0:
        return np.array([]), np.array([]), np.array([])

    n_points = len(x_vis)
    x_lo, x_hi = x_range
    y_lo, y_hi = y_range

    # 1. 2D Histogram Computation
    # Calculates a 2D density grid over the given data range extremely fast using C bindings.
    # High resolution for both main and subplots ensures density peaks remain sharp.
    # We cap nbins at DEFAULT_NBINS_MAX to prevent grid undersampling lumpiness ("blocky chunks").
    nbins_scaling_val = nbins_scaling if nbins_scaling is not None else NBINS_SCALING_FACTOR
    raw_nbins = max(DEFAULT_NBINS_MIN, np.sqrt(n_points) * nbins_scaling_val)
    nbins = int(min(DEFAULT_NBINS_MAX, raw_nbins * quality_multiplier))

    # Handle potentially inverted axis limits from Matplotlib
    x_min, x_max = (min(x_lo, x_hi), max(x_lo, x_hi))
    y_min, y_max = (min(y_lo, y_hi), max(y_lo, y_hi))

    # Ensure non-zero span for fast_histogram (prevents divide-by-zero errors)
    if x_min == x_max:
        x_max += 1e-6
    if y_min == y_max:
        y_max += 1e-6

    # ── FILTER OUT-OF-BOUNDS POINTS ──
    # Points outside the visible range must not contribute to the density grid.
    # Otherwise, np.clip in fast_hist2d piles them into the edge bins (0 and nbins-1),
    # creating an artificial massive density spike (a "red wall") on the axis spines.
    valid_mask = (x_vis >= x_min) & (x_vis <= x_max) & (y_vis >= y_min) & (y_vis <= y_max)
    if not np.all(valid_mask):
        x_vis = x_vis[valid_mask]
        y_vis = y_vis[valid_mask]
        n_points = len(x_vis)
        if n_points == 0:
            return np.array([]), np.array([]), np.array([])

    h_mat = fast_hist2d(x_vis, y_vis, bins=[nbins, nbins], range=[[x_min, x_max], [y_min, y_max]])

    # 2. Robust Gaussian Smoothing
    # Smoothes the raw histogram to create continuous color transitions
    # instead of sharp rectangular bin outlines.
    # Sigma scales proportionally with nbins to maintain a consistent visual 'glow' regardless of resolution.
    sigma_scaling_val = sigma_scaling if sigma_scaling is not None else SIGMA_SCALING_FACTOR
    sigma = max(SIGMA_MIN, sigma_scaling_val * (nbins / DEFAULT_NBINS_MIN))
    smoothed = gaussian_filter(h_mat.astype(np.float64), sigma=sigma)

    # 3. Interpolated Density Lookup
    # map_coordinates extracts the exact smoothed density value for each individual event.
    # This dynamic point-lookup approach completely prevents blocky grid artifacts.
    x_span = max(x_max - x_min, 1e-12)
    y_span = max(y_max - y_min, 1e-12)

    # Map data coordinates to grid indices [0, nbins - 1]
    x_coords = np.clip((x_vis - x_min) / x_span * (nbins - 1), 0, nbins - 1)
    y_coords = np.clip((y_vis - y_min) / y_span * (nbins - 1), 0, nbins - 1)

    # We transpose the smoothed array and use [y_coords, x_coords] to ensure
    # the standard (row, col) -> (y, x) mapping aligns correctly with matplotlib backends.
    densities = map_coordinates(smoothed.T, [y_coords, x_coords], order=1, mode="nearest")

    # 4. Normalization and Scaling
    max_d = np.max(densities)
    c_plot = np.zeros_like(densities)

    if max_d > 0:
        # 4. Rank Percentile Normalization
        # Industry-standard "secret sauce": instead of log-scaling, we use the percentile rank
        # of each event's density. This ensures that the "blue cloud" of low-density
        # events is robustly represented regardless of the absolute density values.
        c_plot = rankdata(densities, method="average") / n_points

        # 5. Thresholding & Vibrancy
        # Background Suppression: Snaps the bottom X% of events strictly to 0.0 (blue).
        # This cleans up sparse background noise.
        density_thresh_val = (
            density_threshold if density_threshold is not None else DENSITY_THRESHOLD_MIN
        )
        c_plot[c_plot < density_thresh_val] = 0.0

        # Vibrancy: Mathematically amplifies the color range for the rest of the distribution.
        vib_min_val = vibrancy_min if vibrancy_min is not None else VIBRANCY_MIN
        vib_range_val = vibrancy_range if vibrancy_range is not None else VIBRANCY_RANGE

        mask = c_plot > 0
        if np.any(mask):
            # Scale the ranks [threshold, 1.0] -> [vib_min, vib_min + vib_range]
            # This makes the population core "pop" with vivid colors.
            c_plot[mask] = vib_min_val + vib_range_val * (c_plot[mask] - density_thresh_val) / (
                1.0 - density_thresh_val
            )
            c_plot = np.clip(c_plot, 0, 1)

    # 6. Z-Sorting
    # Sort events so that dense events are rendered on top, preventing sparse outliers
    # from hiding the dense core population.
    sort_idx = np.argsort(c_plot)
    return x_vis[sort_idx], y_vis[sort_idx], c_plot[sort_idx]


def compute_1d_histogram(
    x_vis: np.ndarray, x_range: tuple[float, float], bins: int = 256
) -> tuple[np.ndarray, np.ndarray]:
    """Compute 1D histogram counts and bin edges."""
    if len(x_vis) == 0:
        return np.zeros(bins), np.linspace(x_range[0], x_range[1], bins + 1)

    counts, edges = np.histogram(x_vis, bins=bins, range=x_range)
    return counts, edges
