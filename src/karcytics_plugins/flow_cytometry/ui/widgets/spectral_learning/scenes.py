"""The numbers the Learning Compensation slides plot (no Qt, no matplotlib).

Spillover values are estimated from the real spectra of the dyes the learner
loaded: how much of a dye's emission reaches another dye's detector, scaled by
how well that detector's laser excites it. A dye the laser can't excite never
lights up there, however much its emission overlaps. The cell clouds around
the numbers are seeded, so a slide looks the same each time it is drawn.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import permutations
from typing import Any

import numpy as np

from ....analysis.spectral_math import normalise_em_to_grid

MIN_RUN = 1e-6  # a ruler whose two points share an x has no slope
LASERS_NM = (405.0, 488.0, 640.0)  # the common violet / blue / red three-laser cytometer
GRID = np.linspace(300, 850, 551)  # nm, 1 nm steps
MIN_EXCITATION = 0.1  # a laser exciting a dye less than this (vs its own laser) leaves it dark


@dataclass(frozen=True)
class TeachingPair:
    """The loaded dye that spills most into another dye's detector, which every slide teaches with."""

    dye_a: str  # the dye that leaks
    dye_b: str  # the dye whose detector it leaks into
    pct: float  # how much of dye_a's light lands in dye_b's detector
    label_a: str
    label_b: str


def spectral_dyes(fluors: dict[str, dict[str, Any]]) -> list[str]:
    """The loaded dyes that have an emission spectrum, in load order."""
    return [name for name, data in fluors.items() if "em_data" in data]


def dye_label(fluors: dict[str, dict[str, Any]], name: str) -> str:
    return str(fluors[name].get("display_label", name))


def emission_peak(fluors: dict[str, dict[str, Any]], name: str) -> float:
    """Where ``name`` emits most (nm): where its detector sits."""
    return float(GRID[np.argmax(_curve(fluors[name], "em_data"))])


def detector_laser(fluors: dict[str, dict[str, Any]], name: str) -> float | None:
    """The laser (nm) that excites ``name`` best; None without excitation data."""
    excitation = _excitation(fluors[name])
    if excitation is None:
        return None
    return max(LASERS_NM, key=lambda laser: float(np.interp(laser, GRID, excitation)))


def excitation_weight(fluors: dict[str, dict[str, Any]], dye: str, detector: str) -> float:
    """How strongly ``detector``'s laser excites ``dye``, against ``dye``'s own best laser.

    1 when it's the same laser; 0 when that laser can't excite ``dye`` at all.
    Without excitation data for either dye, 1: emission alone decides.
    """
    excitation = _excitation(fluors[dye])
    laser = detector_laser(fluors, detector)
    if excitation is None or laser is None:
        return 1.0
    own = max(float(np.interp(at, GRID, excitation)) for at in LASERS_NM)
    return float(np.interp(laser, GRID, excitation)) / own if own > 0 else 0.0


def spill_fraction(fluors: dict[str, dict[str, Any]], dye: str, detector: str) -> float:
    """Estimated fraction of ``dye``'s signal read in ``detector``'s detector."""
    if dye == detector:
        return 1.0
    height = float(np.interp(emission_peak(fluors, detector), GRID, _curve(fluors[dye], "em_data")))
    return height * excitation_weight(fluors, dye, detector)


def spill_matrix(fluors: dict[str, dict[str, Any]], names: list[str]) -> np.ndarray:
    """Spillover %: row = the dye, column = the detector it lands in (100 on the diagonal)."""
    return np.array([[spill_fraction(fluors, dye, det) * 100 for det in names] for dye in names])


def teaching_pair(fluors: dict[str, dict[str, Any]]) -> TeachingPair | None:
    """The largest spill between two loaded dyes; None with fewer than two that have spectra."""
    pairs = list(permutations(spectral_dyes(fluors), 2))
    if not pairs:
        return None
    dye_a, dye_b = max(pairs, key=lambda pair: spill_fraction(fluors, *pair))
    pct = spill_fraction(fluors, dye_a, dye_b) * 100
    return TeachingPair(dye_a, dye_b, pct, dye_label(fluors, dye_a), dye_label(fluors, dye_b))


def _curve(data: dict[str, Any], key: str) -> np.ndarray:
    return normalise_em_to_grid(data[key], GRID)


def _excitation(data: dict[str, Any]) -> np.ndarray | None:
    """The excitation spectrum, or absorbance where FPbase has no excitation one."""
    for key in ("ex_data", "ab_data"):
        if data.get(key):
            return _curve(data, key)
    return None


def unstained_cloud(seed: int = 42, n: int = 500) -> tuple[np.ndarray, np.ndarray]:
    """Unstained cells: autofluorescence only, low on both detectors."""
    rng = np.random.default_rng(seed)
    return rng.normal(100, 30, n), rng.normal(100, 30, n)


def leaked_single_stain(pct: float, seed: int, n: int = 200) -> tuple[np.ndarray, np.ndarray]:
    """A single-stain population slanting upward by the real spillover slope."""
    rng = np.random.default_rng(seed)
    slope = pct / 100.0
    x = rng.normal(800, 70, n)
    y = x * slope + rng.normal(0, 18, n)
    return x, y


def compensated_scene(seed: int) -> dict[str, np.ndarray]:
    """A background, two single-positives and a double-positive, already corrected."""
    rng = np.random.default_rng(seed)
    return {
        "bg_x": rng.normal(100, 30, 200),
        "bg_y": rng.normal(100, 30, 200),
        "p1_x": rng.normal(600, 80, 200),
        "p1_y": rng.normal(100, 30, 200),
        "p2_x": rng.normal(100, 30, 200),
        "p2_y": rng.normal(600, 80, 200),
        "dp_x": rng.normal(600, 80, 100),
        "dp_y": rng.normal(600, 80, 100),
    }


def uncompensated_scene(pct: float, seed: int) -> dict[str, np.ndarray]:
    """The same kind of scene as ``compensated_scene``, slanted by the real spillover."""
    rng = np.random.default_rng(seed)
    slope = pct / 100.0
    p1x = rng.normal(600, 80, 200)
    p2y = rng.normal(600, 80, 200)
    return {
        "bg_x": rng.normal(100, 30, 200),
        "bg_y": rng.normal(100, 30, 200),
        "p1_x": p1x,
        "p1_y": p1x * slope + rng.normal(0, 25, 200),
        "p2_x": p2y * slope + rng.normal(0, 25, 200),
        "p2_y": p2y,
        "dp_x": rng.normal(750, 80, 100),
        "dp_y": rng.normal(750, 80, 100),
    }


def rise_run_slope(x0: float, y0: float, x1: float, y1: float) -> tuple[float, float, float]:
    rise = y1 - y0
    run = x1 - x0
    slope = rise / run if abs(run) > MIN_RUN else float("inf")
    return rise, run, slope


def point_in_rect(px: float, py: float, x0: float, y0: float, x1: float, y1: float) -> bool:
    xmin, xmax = sorted((x0, x1))
    ymin, ymax = sorted((y0, y1))
    return xmin <= px <= xmax and ymin <= py <= ymax
