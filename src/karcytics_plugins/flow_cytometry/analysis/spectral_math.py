"""Real emission-spectrum overlap math.

Shared between the Spectral Viewer's overlap-highlighting (`spectral_viewer.py`)
and the interactive "Learning Compensation" teaching widget
(`ui/widgets/spectral_learning/`), so both surfaces report the same number for the
same pair of dyes.

The overlap % is a Bhattacharyya-style normalized integral of two dyes'
*emission curves* — a theoretical estimate of how much one dye's light could
leak into another's detector based on published spectra alone. This is
distinct from `compensation.calculate_spillover_matrix`, which measures
spillover empirically from real single-stain event data (detector gain,
laser power, and filter bandpass all shift the real value away from this
theoretical one).
"""

from __future__ import annotations

import numpy as np
from scipy.integrate import trapezoid

DEFAULT_X_GRID = np.linspace(300, 800, 1001)
_OVERLAP_THRESHOLD = 0.05


def normalise_em_to_grid(em_data: np.ndarray, x_grid: np.ndarray = DEFAULT_X_GRID) -> np.ndarray:
    """Peak-normalizes a raw ``[[wavelength_nm, intensity], ...]`` emission curve
    and resamples it onto a shared wavelength grid.
    """
    arr = np.asarray(em_data, dtype=float)
    x, y = arr[:, 0], arr[:, 1]
    peak = np.max(y)
    if peak > 0:
        y = y / peak
    return np.interp(x_grid, x, y, left=0.0, right=0.0)


def overlap_pct_from_grid(
    y1: np.ndarray, y2: np.ndarray, x_grid: np.ndarray = DEFAULT_X_GRID
) -> float:
    """Overlap-integral spillover estimate between two grid-aligned, peak-normalized curves."""
    overlap = np.minimum(y1, y2)
    mask = (y1 > _OVERLAP_THRESHOLD) & (y2 > _OVERLAP_THRESHOLD)
    if not mask.any():
        return 0.0
    denom = max(float(trapezoid(y1, x=x_grid)), float(trapezoid(y2, x=x_grid)))
    if denom <= 0:
        return 0.0
    return float(trapezoid(overlap[mask], x=x_grid[mask])) / denom * 100


def spectral_overlap_pct(
    em_a: np.ndarray, em_b: np.ndarray, x_grid: np.ndarray = DEFAULT_X_GRID
) -> float:
    """Overlap-integral spillover estimate directly from two raw ``em_data`` arrays."""
    return overlap_pct_from_grid(
        normalise_em_to_grid(em_a, x_grid), normalise_em_to_grid(em_b, x_grid), x_grid
    )
