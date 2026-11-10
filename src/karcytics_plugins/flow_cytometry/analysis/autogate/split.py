"""Splitting a chosen view into populations.

* Valley cuts (density valleys): each axis with a clear valley is cut at its
  lowest point; the cells between cuts become rectangles.
* Mixtures (marker pairs, PCA): a Gaussian mixture picks the number of groups
  by BIC, and each group becomes an ellipse.

Either way a piece knows its events, the outline to draw, and the gate that
accepting would add, all from the same display-space numbers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np
from matplotlib.path import Path as MplPath

from ..clustering.describe import short_marker
from ..gating.from_display import (
    ellipse_from_display,
    polygon_from_display,
    rectangle_from_display,
)
from .density import Valley, find_valley
from .mixture import RADIUS, Component, axes, envelope, fit_mixture, inside, outline

if TYPE_CHECKING:
    from ..gating.base import Gate
    from .views import View

DENSITY_POINTS = 64  # the density curve kept on each gate's record


@dataclass(frozen=True, eq=False)
class Piece:
    mask: np.ndarray
    outline: np.ndarray  # (k, 2) display units
    gate: Gate


@dataclass(frozen=True, eq=False)
class Split:
    pieces: list[Piece]
    cuts: list[tuple[str, float]]  # ("x"/"y", display position)
    reason: str
    record: dict[str, object] = field(default_factory=dict)
    components: tuple[Component, ...] = ()  # mixtures: to redo the fit on another sample


def _extremes(view: View) -> tuple[float, float, float, float]:
    xs, ys = view.x.values, view.y.values
    return (float(np.nanmin(xs)), float(np.nanmax(xs)), float(np.nanmin(ys)), float(np.nanmax(ys)))


def split_axis_record(view: View) -> dict[str, object]:
    """The axis with the deepest valley: its density and where the valley is, for the record."""
    best: tuple[str, Valley] | None = None
    for axis in (view.x, view.y):
        valley = find_valley(axis.values)
        if valley is not None and (best is None or valley.depth > best[1].depth):
            best = (axis.label, valley)
    if best is None:
        return {"valley_depth": 0.0}
    label, valley = best
    heights = valley.density.heights.reshape(DENSITY_POINTS, -1).mean(axis=1)
    return {
        "split_axis": label,
        "valley_depth": round(valley.depth, 3),
        "valley_at": round(valley.density.at(valley.position), 4),
        "density": [round(float(h), 4) for h in heights / max(heights.max(), 1e-9)],
    }


def by_valleys(view: View, min_valley: float, cells: bool = False) -> Split | str:
    """Rectangles between the valleys on each axis.

    ``cells``: the cells split, cut only on x (forward scatter), and only below its
    tallest peak, where debris is.
    """
    axes = (("x", view.x),) if cells else (("x", view.x), ("y", view.y))
    valleys = {name: find_valley(axis.values, below_tallest=cells) for name, axis in axes}
    cuts = {
        name: v.position for name, v in valleys.items() if v is not None and v.depth >= min_valley
    }
    if not cuts:
        deepest = max((v.depth for v in valleys.values() if v is not None), default=0.0)
        cut_on = " or ".join(short_marker(a.label) for _n, a in axes)
        return (
            f"No clear valley on {cut_on} "
            f"(deepest {deepest:.2f}, needs {min_valley:.2f}). Try other axes, or lower "
            "“Clear valley at least”."
        )
    x_edges = [-np.inf, cuts["x"], np.inf] if "x" in cuts else [-np.inf, np.inf]
    y_edges = [-np.inf, cuts["y"], np.inf] if "y" in cuts else [-np.inf, np.inf]
    xs, ys = view.x.values, view.y.values
    extremes = _extremes(view)
    pieces = []
    for x_lo, x_hi in zip(x_edges, x_edges[1:], strict=False):
        for y_lo, y_hi in zip(y_edges, y_edges[1:], strict=False):
            mask = (xs >= x_lo) & (xs < x_hi) & (ys >= y_lo) & (ys < y_hi)
            corners = np.array(
                [
                    [max(x_lo, extremes[0]), max(y_lo, extremes[2])],
                    [min(x_hi, extremes[1]), max(y_lo, extremes[2])],
                    [min(x_hi, extremes[1]), min(y_hi, extremes[3])],
                    [max(x_lo, extremes[0]), min(y_hi, extremes[3])],
                ]
            )
            gate = rectangle_from_display(
                view.x.key,
                view.y.key,
                (x_lo, x_hi, y_lo, y_hi),
                view.x.scale,
                view.y.scale,
                extremes,
            )
            pieces.append(Piece(mask, corners, gate))
    said = []
    for name, axis in axes:
        v = valleys[name]
        marker = short_marker(axis.label)
        if name in cuts and v is not None:
            said.append(
                f"{marker} has two peaks with a clear gap (valley {v.depth:.2f}), cut at its lowest point"
            )
        else:
            said.append(f"{marker} has no clear valley, so it isn't cut")
    reason = f"On {view.name}: " + "; ".join(said) + "."
    record: dict[str, object] = {
        "cuts": {
            short_marker(a.label): round(float(cuts[n]), 4)
            for n, a in (("x", view.x), ("y", view.y))
            if n in cuts
        }
    }
    return Split(pieces, [(n, float(p)) for n, p in cuts.items()], reason, record)


def by_mixture(view: View, min_valley: float, means_init: np.ndarray | None = None) -> Split | str:
    xy = np.column_stack((view.x.values, view.y.values))
    mixture = fit_mixture(xy, min_valley, means_init)
    if len(mixture.components) < 2:  # noqa: PLR2004 - a split needs two groups
        return (
            f"One population on {view.name}: the mixture's {mixture.fitted} components have no "
            f"valley of {min_valley:.2f} between them. Try other channels, or lower "
            "“Clear valley at least”."
        )
    pieces = []
    for comp, parts in zip(mixture.components, mixture.parts, strict=True):
        if len(parts) > 1:
            shape = envelope(parts)
            mask = MplPath(shape).contains_points(xy)
            polygon = polygon_from_display(
                view.x.key, view.y.key, shape, view.x.scale, view.y.scale
            )
            pieces.append(Piece(mask, shape, polygon))
            continue
        a, b, angle = axes(comp)
        gate = ellipse_from_display(
            view.x.key,
            view.y.key,
            (float(comp.mean[0]), float(comp.mean[1])),
            (a, b),
            angle,
            view.x.scale,
            view.y.scale,
        )
        pieces.append(Piece(inside(xy, comp), outline(comp), gate))
    k = len(mixture.components)
    if mixture.fitted != k:
        reason = (
            f"A Gaussian mixture fits best with {mixture.fitted} components (BIC); those with no "
            f"valley of {min_valley:.2f} between them are one population, leaving {k}. "
        )
    else:
        reason = (
            f"A Gaussian mixture fits best with {k} components (BIC), each its own population. "
        )
    reason += f"Each gate is the ellipse {RADIUS:g} standard deviations around its population, or the matching contour of its components' density when it has several."
    record: dict[str, object] = {
        "groups": k,
        "components": mixture.fitted,
        "min_valley": min_valley,
        "components_tried": [[n + 1, round(b, 1)] for n, b in enumerate(mixture.bic)],
        "radius": RADIUS,
    }
    return Split(pieces, [], reason, record, mixture.components)
