"""2-D layouts shared by the methods that have no per-event map (FlowSOM, PhenoGraph).

Both draw a small graph (FlowSOM's node tree, PhenoGraph's cluster graph) and
put each event inside its node's circle, so event scatter plots still work.
"""

from __future__ import annotations

import numpy as np
from scipy.spatial.distance import cdist

LAYOUT_ITERATIONS = 300
NODE_SPREAD = 0.4  # the biggest node's radius, in layout units


def stress_layout(target: np.ndarray) -> np.ndarray:
    """2-D positions whose distances follow ``target`` (SMACOF stress majorization).

    Starts from classical MDS, so the result is deterministic and untangled.
    ``target`` must be finite and symmetric with a zero diagonal.
    """
    n = len(target)
    if n == 1:
        return np.zeros((1, 2))
    centring = np.eye(n) - 1.0 / n
    values, vectors = np.linalg.eigh(-0.5 * centring @ (target**2) @ centring)
    top = np.argsort(values)[::-1][:2]
    pos = vectors[:, top] * np.sqrt(np.maximum(values[top], 1e-9))
    if pos.shape[1] < 2:  # noqa: PLR2004 - two nodes: MDS gives one axis
        pos = np.column_stack([pos, np.zeros(n)])

    weights = np.where(target > 0, 1.0 / np.maximum(target, 1e-9) ** 2, 0.0)
    v = -weights
    np.fill_diagonal(v, weights.sum(axis=1))
    v_inv = np.linalg.pinv(v)
    for _ in range(LAYOUT_ITERATIONS):
        dist = cdist(pos, pos)
        b = np.where(dist > 0, -weights * target / np.maximum(dist, 1e-9), 0.0)
        np.fill_diagonal(b, -b.sum(axis=1))
        pos = v_inv @ b @ pos
    return pos - pos.mean(axis=0)


def jitter_around(
    layout: np.ndarray, groups: np.ndarray, seed: int = 0, spread: float = NODE_SPREAD
) -> np.ndarray:
    """A 2-D point per event, inside its group's circle (bigger groups, wider circles)."""
    counts = np.bincount(groups, minlength=len(layout))
    radius = spread * np.sqrt(counts / max(counts.max(), 1))
    rng = np.random.default_rng(seed)
    angle = rng.uniform(0, 2 * np.pi, len(groups))
    r = radius[groups] * np.sqrt(rng.uniform(0, 1, len(groups)))
    return layout[groups] + np.column_stack([r * np.cos(angle), r * np.sin(angle)])
