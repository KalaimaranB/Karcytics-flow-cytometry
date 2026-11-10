"""Gaussian mixtures on a 2-D view: how many groups, and an ellipse around each.

The number of groups is the one BIC prefers among 1 to MAX_GROUPS, counting
only fits whose groups are distinct: a fit that splits one population into
two overlapping halves is passed over. Each group's gate is the ellipse at
RADIUS standard deviations (Mahalanobis distance) of its Gaussian, so it
holds roughly the central 86% of a well-shaped population.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

MAX_GROUPS = 4
MAX_OVERLAP = 0.3  # two groups sharing more of the smaller one's events are one population
RADIUS = 2.0
FIT_EVENTS = 8_000
SEED = 0


@dataclass(frozen=True, eq=False)
class Component:
    mean: np.ndarray  # (2,)
    cov: np.ndarray  # (2, 2)
    weight: float


@dataclass(frozen=True, eq=False)
class Mixture:
    components: tuple[Component, ...]  # the chosen fit, largest first (seeded: in the seeds' order)
    bic: tuple[float, ...]  # for 1..MAX_GROUPS groups (only the fitted count when seeded)
    bic_best: int = 0  # the count BIC prefers before overlapping fits are passed over


def fit_mixture(xy: np.ndarray, means_init: np.ndarray | None = None) -> Mixture:
    """Fit 1..MAX_GROUPS groups and keep the BIC's choice, or exactly as many as ``means_init``."""
    from sklearn.mixture import GaussianMixture  # karcytics: allow KS360 - heavy library

    rows = xy[np.all(np.isfinite(xy), axis=1)]
    if len(rows) > FIT_EVENTS:
        rows = rows[np.random.default_rng(SEED).choice(len(rows), FIT_EVENTS, replace=False)]
    counts = [len(means_init)] if means_init is not None else list(range(1, MAX_GROUPS + 1))
    fits: list[tuple[Component, ...]] = []
    bics: list[float] = []
    for k in counts:
        model = GaussianMixture(
            n_components=k,
            covariance_type="full",
            random_state=SEED,
            n_init=1 if means_init is not None else 2,
            means_init=means_init,
        ).fit(rows)
        # Seeded fits keep the seeds' order, so each group lines up with the one it started from.
        order = np.arange(k) if means_init is not None else np.argsort(-model.weights_)
        fits.append(
            tuple(
                Component(
                    model.means_[i].copy(), model.covariances_[i].copy(), float(model.weights_[i])
                )
                for i in order
            )
        )
        bics.append(float(model.bic(rows)))
    ranked = list(np.argsort(bics))
    chosen = next((i for i in ranked if distinct(rows, fits[i])), ranked[0])
    return Mixture(fits[chosen], tuple(bics), len(fits[ranked[0]]))


def distinct(xy: np.ndarray, components: tuple[Component, ...]) -> bool:
    """No two groups share more than MAX_OVERLAP of the smaller one's events."""
    masks = [inside(xy, c) for c in components]
    for i, a in enumerate(masks):
        for b in masks[i + 1 :]:
            smaller = min(a.sum(), b.sum())
            if smaller and (a & b).sum() / smaller > MAX_OVERLAP:
                return False
    return True


def inside(xy: np.ndarray, component: Component, radius: float = RADIUS) -> np.ndarray:
    """Events within ``radius`` standard deviations of the component's centre."""
    diff = xy - component.mean
    inv = np.linalg.inv(component.cov)
    d2 = np.einsum("ni,ij,nj->n", diff, inv, diff)
    return np.isfinite(d2) & (d2 <= radius**2)


def axes(component: Component, radius: float = RADIUS) -> tuple[float, float, float]:
    """The ellipse's semi-axes along its own axes and its angle in degrees (major axis first)."""
    values, vectors = np.linalg.eigh(component.cov)
    major = int(np.argmax(values))
    minor = 1 - major
    angle = float(np.degrees(np.arctan2(vectors[1, major], vectors[0, major])))
    a = radius * float(np.sqrt(max(values[major], 0.0)))
    b = radius * float(np.sqrt(max(values[minor], 0.0)))
    return a, b, angle


def outline(component: Component, radius: float = RADIUS, points: int = 48) -> np.ndarray:
    """The ellipse as a closed polygon, (points, 2), in the view's units."""
    a, b, angle = axes(component, radius)
    t = np.linspace(0, 2 * np.pi, points, endpoint=False)
    theta = np.radians(angle)
    x = a * np.cos(t) * np.cos(theta) - b * np.sin(t) * np.sin(theta)
    y = a * np.cos(t) * np.sin(theta) + b * np.sin(t) * np.cos(theta)
    return np.column_stack((x + component.mean[0], y + component.mean[1]))
