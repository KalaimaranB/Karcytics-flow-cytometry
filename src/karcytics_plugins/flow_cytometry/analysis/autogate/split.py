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

from .._utils import project_to_display
from ..clustering.describe import short_marker
from ..gating.from_display import (
    ellipse_from_display,
    polygon_from_display,
    rectangle_from_display,
)
from ..gating.polygon import PolygonGate
from .density import Valley, find_valley, on_scale
from .mixture import RADIUS, Component, axes, envelope, fit_mixture, inside, outline
from .regions import OUTLINE, density_regions
from .regions import inside as in_outline

if TYPE_CHECKING:
    from collections.abc import Callable

    from ..gating.base import Gate
    from .views import View

DENSITY_POINTS = 64  # the density curve kept on each gate's record


CELLS, DEBRIS = "Cells", "Debris"
SINGLETS, DOUBLETS = "Singlets", "Doublets"


@dataclass(frozen=True, eq=False)
class Piece:
    mask: np.ndarray
    outline: np.ndarray  # (k, 2) display units
    gate: Gate
    name: str = ""  # set when convention names it (Singlets), else named from its markers


@dataclass(frozen=True, eq=False)
class Split:
    pieces: list[Piece]
    cuts: list[tuple[str, float]]  # ("x"/"y", display position)
    reason: str
    record: dict[str, object] = field(default_factory=dict)
    components: tuple[Component, ...] = ()  # mixtures: to redo the fit on another sample
    # density regions: one piece around several of them (identified by their outlines)
    join: Callable[[list[Piece]], Piece | None] | None = None


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


def by_valleys(view: View, min_valley: float, x_only: bool = False) -> Split | str:
    """Rectangles between the valleys on each axis (only x when ``x_only``)."""
    axes = (("x", view.x),) if x_only else (("x", view.x), ("y", view.y))
    valleys = {name: find_valley(axis.values) for name, axis in axes}
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


SPREAD_CUT = 3.0  # robust standard deviations from the main ratio peak, when there is no valley
OUTLINE_POINTS = 32  # per boundary line, so the gate follows it on any axis scale


def by_singlets(view: View, area: np.ndarray, height: np.ndarray, min_valley: float) -> Split | str:
    """Singlets on forward-scatter area × height: the main peak of log(area / height).

    A doublet is two cells passing together: about twice the area for the same
    height. The cut above the peak is the valley there, or SPREAD_CUT robust
    standard deviations when there is none; the same spread bounds it below.
    """
    ok = on_scale(area) & on_scale(height) & (area > 0) & (height > 0)
    if ok.sum() < 2:  # noqa: PLR2004 - a median needs two
        return "Too few events with forward-scatter area and height for a singlets gate."
    ratio = np.full(len(area), np.nan)
    ratio[ok] = np.log(area[ok] / height[ok])
    centre = float(np.median(ratio[ok]))
    spread = 1.4826 * float(np.median(np.abs(ratio[ok] - centre)))
    valley = find_valley(ratio[ok], side="above")
    if valley is not None and valley.depth >= min_valley:
        hi, how = valley.position, f"at the valley above the main peak (depth {valley.depth:.2f})"
    else:
        hi, how = (
            centre + SPREAD_CUT * spread,
            f"{SPREAD_CUT:g} robust SDs above the main peak (no valley)",
        )
    lo = centre - SPREAD_CUT * spread
    a_hi = float(np.max(area[ok])) * 1.05
    a_lo = max(float(np.quantile(area[ok], 0.001)) * 0.5, 1.0)
    a = np.linspace(a_lo, a_hi, OUTLINE_POINTS)
    upper_edge = np.column_stack((a, a / np.exp(lo)))  # the smallest area/height kept
    lower_edge = np.column_stack((a, a / np.exp(hi)))  # the largest: doublets fall below it
    keep = np.vstack((lower_edge, upper_edge[::-1]))
    below = np.vstack((lower_edge, [[a_hi, 0.0], [a_lo, 0.0]]))
    pieces = []
    for name, raw, mask in (
        (SINGLETS, keep, ok & (ratio >= lo) & (ratio <= hi)),
        (DOUBLETS, below, ok & (ratio > hi)),
    ):
        gate = PolygonGate(
            view.x.key,
            view.y.key,
            vertices=[(float(x), float(y)) for x, y in raw],
            x_scale=view.x.scale.copy(),
            y_scale=view.y.scale.copy(),
        )
        outline = np.column_stack(
            (
                project_to_display(raw[:, 0], view.x.scale),
                project_to_display(raw[:, 1], view.y.scale),
            )
        )
        pieces.append(Piece(mask, outline, gate, name))
    reason = (
        f"On {view.name}: a doublet has about twice the area for the same height, so events are "
        f"kept by their area/height ratio around its main peak; doublets are cut {how}."
    )
    record: dict[str, object] = {
        "ratio_kept": [round(float(np.exp(lo)), 4), round(float(np.exp(hi)), 4)],
        "doublet_cut": "valley" if valley is not None and valley.depth >= min_valley else "spread",
    }
    return Split(pieces, [], reason, record)


def whole(view: View, why: str) -> Split:
    """One piece holding the whole population: a rectangle open on every side."""
    extremes = _extremes(view)
    corners = np.array(
        [
            [extremes[0], extremes[2]],
            [extremes[1], extremes[2]],
            [extremes[1], extremes[3]],
            [extremes[0], extremes[3]],
        ]
    )
    gate = rectangle_from_display(
        view.x.key,
        view.y.key,
        (-np.inf, np.inf, -np.inf, np.inf),
        view.x.scale,
        view.y.scale,
        extremes,
    )
    mask = np.ones(len(view.x.values), dtype=bool)
    return Split([Piece(mask, corners, gate)], [], why, {"whole_population": True})


def by_density(view: View, min_valley: float) -> Split | str:
    """One polygon per density region: gates that follow the populations' own shapes."""
    found = density_regions(view.x.values, view.y.values, min_valley)
    if found is None:
        return f"Too few events on {view.name} to map its density."
    pieces, regions = [], []
    for region in found.regions:
        shape = found.outline(region.mask)
        if shape is not None:
            pieces.append(Piece(in_outline(shape, view), shape, _polygon(view, shape)))
            regions.append(region)

    def join(chosen: list[Piece]) -> Piece | None:
        picked = [
            r
            for p, r in zip(pieces, regions, strict=True)
            if any(p.outline is c.outline for c in chosen)
        ]
        shape = found.joined(picked)
        if shape is None:
            return None
        return Piece(in_outline(shape, view), shape, _polygon(view, shape))

    reason = (
        f"On {view.name}: its density has {found.peaks} peak{'s' if found.peaks != 1 else ''}; "
        f"peaks with no valley of {min_valley:.2f} between them are one population, leaving "
        f"{len(pieces)}. Each gate follows its population's outline, where the density falls "
        f"to {OUTLINE:.0%} of that population's peak."
    )
    record: dict[str, object] = {
        "density_peaks": found.peaks,
        "populations": len(pieces),
        "outline_level": round(OUTLINE, 4),
    }
    return Split(pieces, [], reason, record, join=join)


def cells_by_density(view: View, min_valley: float) -> Split | str:
    """Cells on forward × side scatter: the outline of where the cells are.

    Debris sits near the origin, below and left of the cells; scattered and
    saturated events lie outside the cells' density. So the gate is the outline
    of every density region except any lying below-left of the main one.
    """
    found = density_regions(view.x.values, view.y.values, min_valley)
    if found is None or not found.regions:
        return f"Too few events on {view.name} to map its density."
    main = found.regions[0]
    debris = [
        r for r in found.regions[1:] if r.peak[0] < main.peak[0] and r.peak[1] <= main.peak[1]
    ]
    kept = [r for r in found.regions if r not in debris]
    shape = found.joined(kept)
    if shape is None:
        return f"No cells region found on {view.name}."
    pieces = [Piece(in_outline(shape, view), shape, _polygon(view, shape), CELLS)]
    if debris:
        junk = found.joined(debris)
        if junk is not None:
            pieces.append(Piece(in_outline(junk, view), junk, _polygon(view, junk), DEBRIS))
    reason = (
        f"On {view.name}: the gate follows the cells' density, leaving out the debris near the "
        "origin and scattered or saturated events"
        + (", and a separate debris population below and left of the cells" if debris else "")
        + f" (outlined where the density falls to {OUTLINE:.0%} of its peak)."
    )
    return Split(pieces, [], reason, {"density_peaks": found.peaks, "debris_regions": len(debris)})


def _polygon(view: View, shape: np.ndarray) -> Gate:
    return polygon_from_display(view.x.key, view.y.key, shape, view.x.scale, view.y.scale)
