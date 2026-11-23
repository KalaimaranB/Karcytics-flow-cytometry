"""The numbers the Learning Compensation slides plot (no Qt, no matplotlib).

Spillover values are real: measured from the emission spectra of the dyes the
learner loaded (``analysis.spectral_math``), so a slide's numbers are evidence,
not a script. The cell clouds around them are seeded, so a slide looks the same
each time it is drawn.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Any

import numpy as np

from ....analysis.spectral_math import spectral_overlap_pct

MIN_RUN = 1e-6  # a ruler whose two points share an x has no slope


@dataclass(frozen=True)
class TeachingPair:
    """The two loaded dyes that overlap most, which every slide teaches with."""

    dye_a: str
    dye_b: str
    pct: float  # how much of dye_a's light lands in dye_b's detector
    label_a: str
    label_b: str


def spectral_dyes(fluors: dict[str, dict[str, Any]]) -> list[str]:
    """The loaded dyes that have an emission spectrum, in load order."""
    return [name for name, data in fluors.items() if "em_data" in data]


def dye_label(fluors: dict[str, dict[str, Any]], name: str) -> str:
    return str(fluors[name].get("display_label", name))


def best_overlap_pairs(fluors: dict[str, dict[str, Any]]) -> list[tuple[str, str, float]]:
    """Real overlap % (highest first) for every pair of loaded dyes with EM data."""
    pairs = [(a, b, _overlap(fluors, a, b)) for a, b in combinations(spectral_dyes(fluors), 2)]
    pairs.sort(key=lambda p: p[2], reverse=True)
    return pairs


def teaching_pair(fluors: dict[str, dict[str, Any]]) -> TeachingPair | None:
    """The most-overlapping pair; None with fewer than two dyes that have spectra."""
    pairs = best_overlap_pairs(fluors)
    if not pairs:
        return None
    dye_a, dye_b, pct = pairs[0]
    return TeachingPair(dye_a, dye_b, pct, dye_label(fluors, dye_a), dye_label(fluors, dye_b))


def overlap_matrix(fluors: dict[str, dict[str, Any]], names: list[str]) -> np.ndarray:
    """Pairwise overlap % between ``names`` (100 on the diagonal)."""
    matrix = np.eye(len(names)) * 100.0
    for i, j in combinations(range(len(names)), 2):
        matrix[i, j] = matrix[j, i] = _overlap(fluors, names[i], names[j])
    return matrix


def _overlap(fluors: dict[str, dict[str, Any]], a: str, b: str) -> float:
    return spectral_overlap_pct(
        np.asarray(fluors[a]["em_data"], dtype=float),
        np.asarray(fluors[b]["em_data"], dtype=float),
    )


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
