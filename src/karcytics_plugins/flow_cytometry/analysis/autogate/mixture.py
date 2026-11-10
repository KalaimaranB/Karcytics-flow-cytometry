"""Gaussian mixtures on a 2-D view: which populations it holds, and a shape around each.

Real populations are rarely Gaussian, so a mixture often spends two or three
components on one skewed population. The number of components is the one BIC
prefers among 1 to MAX_COMPONENTS; then any two components with no clear valley
between them (along the line joining their centres, in the pair's fitted density) are
one population and merge (the ridgeline criterion, Hennig 2010). Each
population's gate is the ellipse at RADIUS standard deviations of its
Gaussian (one component), or for several the contour of their summed density at
the same level, so a lopsided population isn't squeezed into one ellipse.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .density import on_scale

MAX_COMPONENTS = 6
RADIUS = 2.5  # standard deviations: one Gaussian holds about 96% of its events
FIT_EVENTS = 8_000
RIDGE_POINTS = 64  # densities sampled along the line between two components
RAY_STEPS = 200  # points along each ray when tracing a population's outline
SEED = 0


@dataclass(frozen=True, eq=False)
class Component:
    mean: np.ndarray  # (2,)
    cov: np.ndarray  # (2, 2)
    weight: float


@dataclass(frozen=True, eq=False)
class Mixture:
    components: tuple[Component, ...]  # populations, largest first (seeded: in the seeds' order)
    parts: tuple[tuple[Component, ...], ...]  # each population's fitted components
    bic: tuple[float, ...]  # for 1..MAX_COMPONENTS components (only the fitted count when seeded)
    fitted: int = 0  # components BIC chose, before those with no valley between them merged


def fit_mixture(
    xy: np.ndarray, min_valley: float = 0.0, means_init: np.ndarray | None = None
) -> Mixture:
    """The populations in ``xy``, or exactly as many as ``means_init`` (unmerged)."""
    from sklearn.mixture import GaussianMixture  # karcytics: allow KS360 - heavy library

    rows = xy[on_scale(xy[:, 0]) & on_scale(xy[:, 1])]
    if len(rows) > FIT_EVENTS:
        rows = rows[np.random.default_rng(SEED).choice(len(rows), FIT_EVENTS, replace=False)]
    counts = [len(means_init)] if means_init is not None else list(range(1, MAX_COMPONENTS + 1))
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
        fits.append(
            tuple(
                Component(m.copy(), c.copy(), float(w))
                for m, c, w in zip(model.means_, model.covariances_, model.weights_, strict=True)
            )
        )
        bics.append(float(model.bic(rows)))
    if means_init is not None:  # seeded fits keep the seeds' order, one group per seed
        return Mixture(fits[0], tuple((c,) for c in fits[0]), tuple(bics), len(fits[0]))
    best = fits[int(np.argmin(bics))]
    groups = sorted(merge(best, min_valley), key=lambda parts: -sum(p.weight for p in parts))
    return Mixture(
        tuple(_moments(parts) for parts in groups), tuple(groups), tuple(bics), len(best)
    )


def ridge_valley(a: Component, b: Component) -> float:
    """How empty ``a`` and ``b``'s density gets between their centres (0: no dip, 1: empty).

    Only the pair's own density: a third component sitting between them would
    otherwise fill the gap. A chain (a~b, b~c) still joins through union.
    """
    t = np.linspace(0.0, 1.0, RIDGE_POINTS)[:, None]
    line = a.mean + t * (b.mean - a.mean)
    density = a.weight * _pdf(line, a) + b.weight * _pdf(line, b)
    ends = min(density[0], density[-1])
    return float(1.0 - density.min() / ends) if ends > 0 else 0.0


def merge(components: tuple[Component, ...], min_valley: float) -> list[tuple[Component, ...]]:
    """Components grouped wherever there is no valley of ``min_valley`` between them."""
    group = list(range(len(components)))

    def root(i: int) -> int:
        while group[i] != i:
            i = group[i]
        return i

    for i, a in enumerate(components):
        for j in range(i + 1, len(components)):
            if ridge_valley(a, components[j]) < min_valley:
                group[root(j)] = root(i)
    members: dict[int, list[Component]] = {}
    for i, c in enumerate(components):
        members.setdefault(root(i), []).append(c)
    return [tuple(parts) for parts in members.values()]


def _moments(parts: tuple[Component, ...]) -> Component:
    """One Gaussian with the same weight, mean and spread as ``parts`` together."""
    if len(parts) == 1:
        return parts[0]
    weight = sum(p.weight for p in parts)
    mean = sum(p.weight * p.mean for p in parts) / weight
    cov = sum(p.weight * (p.cov + np.outer(p.mean - mean, p.mean - mean)) for p in parts) / weight
    return Component(np.asarray(mean), np.asarray(cov), float(weight))


def _pdf(xy: np.ndarray, c: Component) -> np.ndarray:
    diff = xy - c.mean
    inv = np.linalg.inv(c.cov)
    d2 = np.einsum("ni,ij,nj->n", diff, inv, diff)
    return np.exp(-0.5 * d2) / (2 * np.pi * np.sqrt(max(np.linalg.det(c.cov), 1e-300)))


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


def envelope(parts: tuple[Component, ...], radius: float = RADIUS, rays: int = 96) -> np.ndarray:
    """The population's outline, (rays, 2): where its own density falls to the level a
    single Gaussian has at ``radius`` standard deviations (exp(-radius²/2) of the peak).

    For one component that is exactly its ellipse. For several it follows a
    lopsided or L-shaped population without bridging gaps, and a broad, faint
    component (a mixture's catch-all for scattered events) adds little to it.
    Traced along rays from the population's centre, keeping the farthest point
    above the level on each.
    """
    weight = sum(p.weight for p in parts)
    centre = sum(p.weight * p.mean for p in parts) / weight
    peak = max(float(_density(p.mean[None, :], parts)[0]) for p in parts)
    level = peak * float(np.exp(-0.5 * radius**2))
    reach = 1.05 * max(
        float(np.max(np.linalg.norm(outline(p, radius) - centre, axis=1))) for p in parts
    )
    steps = np.linspace(0.0, reach, RAY_STEPS)
    angles = np.linspace(0.0, 2 * np.pi, rays, endpoint=False)
    directions = np.column_stack((np.cos(angles), np.sin(angles)))
    points = centre + (directions[:, None, :] * steps[None, :, None]).reshape(-1, 2)
    hit = (_density(points, parts) >= level).reshape(rays, RAY_STEPS)
    last = np.where(hit.any(axis=1), RAY_STEPS - 1 - np.argmax(hit[:, ::-1], axis=1), 0)
    return centre + directions * steps[last][:, None]


def _density(xy: np.ndarray, parts: tuple[Component, ...]) -> np.ndarray:
    return np.sum([p.weight * _pdf(xy, p) for p in parts], axis=0)
