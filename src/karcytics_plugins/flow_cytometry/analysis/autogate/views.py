"""How each method picks the 2-D view to split. The only part the methods don't share.

* Density valleys: the user's two axes.
* Marker-pair search: every pair of the chosen channels, ranked by separation.
* PCA: planes of the first principal components, ranked by separation. Each
  component is written out as a formula over the channels (arcsinh, cofactor
  150), the formula a derived parameter gets when the split is accepted, so the
  axis is reproducible and readable.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import TYPE_CHECKING

import numpy as np

from ..clustering.describe import short_marker
from ..derived.expression import MAX_FORMULA_LENGTH, parse_formula
from ..scaling import AxisScale
from ..transforms import TransformType
from .density import find_valley, separation
from .models import DENSITY_VALLEYS, MARKER_PAIRS, Bar, BarSection, PendingAxis

if TYPE_CHECKING:
    from .population import PopulationData

COFACTOR = 150.0  # arcsinh cofactor for flow cytometry
MAX_COMPONENTS = 5
PLANE_COMPONENTS = 4  # planes are formed from the first this-many components
SHOWN_PAIRS = 8
SHOWN_LOADINGS = 6
TINY = 1e-9  # a channel varying less than this carries no information


@dataclass(frozen=True, eq=False)
class Axis:
    """One axis of a view: a channel (or a pending derived axis) in display units."""

    key: str  # channel, or a pending axis's key
    label: str
    values: np.ndarray  # display units, one per event
    scale: AxisScale
    pending: PendingAxis | None = None


@dataclass(frozen=True, eq=False)
class View:
    """Two axes to split a population on, and how well they separate it."""

    x: Axis
    y: Axis
    score: float  # separation, 0-1

    @property
    def name(self) -> str:
        """The view's markers (``CD4 × CD8``)."""
        return f"{short_marker(self.x.label)} × {short_marker(self.y.label)}"


@dataclass(frozen=True, eq=False)
class ViewChoice:
    """The views a method found, best first, and how it ranked them."""

    views: tuple[View, ...]  # best first
    sections: tuple[BarSection, ...]  # how they were ranked (highlighting the best)
    notes: dict[str, object]  # for the gate's record

    def ranked(self, rank: int) -> tuple[View, tuple[BarSection, ...]]:
        """The view at ``rank`` (wrapping), with the sections highlighting it."""
        i = rank % len(self.views)
        sections = tuple(
            BarSection(s.title, s.bars, s.signed, (i,), s.note) if s.title.startswith(RANKED) else s
            for s in self.sections
        )
        return self.views[i], sections


RANKED = "Ranked"  # a section whose rows are the views, in rank order


def channel_axis(data: PopulationData, channel: str) -> Axis:
    """``channel`` as an axis of ``data``."""
    return Axis(channel, data.labels[channel], data.on_display(channel), data.scales[channel])


def chosen_axes(data: PopulationData, x: str, y: str) -> ViewChoice:
    """The user's two axes, scored by the deeper of their density valleys."""
    vx, vy = (find_valley(data.on_display(ch)) for ch in (x, y))
    view = View(channel_axis(data, x), channel_axis(data, y), max(_depth(vx), _depth(vy)))
    bars = tuple(
        Bar(short_marker(data.labels[ch]), _depth(v), f"{_depth(v):.2f}" if v else "none")
        for ch, v in ((x, vx), (y, vy))
    )
    note = "How empty the gap between the two peaks is (1 = no events between them)."
    return ViewChoice((view,), (BarSection("Valleys found", bars, note=note),), {})


def marker_pairs(data: PopulationData, channels: tuple[str, ...]) -> ViewChoice:
    """Every pair of ``channels``, ranked by how well they separate the events."""
    views = sorted(
        (
            View(
                channel_axis(data, a),
                channel_axis(data, b),
                separation(data.on_display(a), data.on_display(b)),
            )
            for a, b in combinations(channels, 2)
        ),
        key=lambda v: -v.score,
    )
    shown = views[:SHOWN_PAIRS]
    section = BarSection(
        f"{RANKED}: marker pairs",
        tuple(Bar(v.name, v.score, f"{v.score:.2f}") for v in shown),
        note=f"All {len(views)} pairs tried. Score: how empty the deepest valley across the pair is.",
    )
    return ViewChoice(tuple(views), (section,), {"pairs_tried": len(views)})


def principal_components(data: PopulationData, channels: tuple[str, ...]) -> ViewChoice | str:
    """The first two principal components of ``channels``; a reason if fewer than two vary."""
    raw = data.events[list(channels)].to_numpy(dtype=np.float64)
    t = np.arcsinh(raw / COFACTOR)
    mean, sd = np.nanmean(t, axis=0), np.nanstd(t, axis=0)
    keep = sd > TINY
    if keep.sum() < 2:  # noqa: PLR2004 - a plane needs two axes
        return "PCA needs at least two channels that vary."
    channels = tuple(ch for ch, k in zip(channels, keep, strict=True) if k)
    mean, sd = mean[keep], sd[keep]
    z = np.nan_to_num((t[:, keep] - mean) / sd)
    _u, s, vt = np.linalg.svd(z, full_matrices=False)
    variance = s**2 / np.sum(s**2)
    n = min(MAX_COMPONENTS, len(channels))
    axes: list[Axis] = []
    loadings: list[list[tuple[str, float]]] = []
    for k in range(n):
        weights = vt[k] * (1 if vt[k][np.argmax(np.abs(vt[k]))] > 0 else -1)
        formula = _formula(channels, weights, mean, sd)
        values = parse_formula(formula).evaluate(data.events, positive_denominators=False)
        label = f"PC{k + 1}"
        pending = PendingAxis(f"pending:pc{k + 1}", f"{label} · {data.parent_name}", formula)
        axes.append(
            Axis(
                pending.key, label, values, AxisScale(transform_type=TransformType.LINEAR), pending
            )
        )
        loadings.append(
            [
                (short_marker(data.labels[ch]), float(w))
                for ch, w in zip(channels, weights, strict=True)
            ]
        )
    planes = sorted(
        (
            View(axes[i], axes[j], separation(axes[i].values, axes[j].values))
            for i, j in combinations(range(min(PLANE_COMPONENTS, n)), 2)
        ),
        key=lambda v: -v.score,
    )
    sections = (
        BarSection(
            "Variance explained",
            tuple(
                Bar(f"PC{k + 1}", float(variance[k]) / max(variance[0], TINY), f"{variance[k]:.0%}")
                for k in range(n)
            ),
        ),
        BarSection(
            f"{RANKED}: planes to split",
            tuple(Bar(v.name, v.score, f"{v.score:.2f}") for v in planes),
            note="How empty the deepest valley across each plane is.",
        ),
    )
    notes: dict[str, object] = {
        "variance": [round(float(v), 4) for v in variance[:n]],
        "loadings": {f"PC{k + 1}": [[m, round(w, 3)] for m, w in loadings[k]] for k in range(n)},
    }
    return ViewChoice(tuple(planes), sections, notes)


def loadings_section(notes: dict[str, object], axis: str) -> BarSection | None:
    """What a principal component is made of, largest weights first."""
    table = notes.get("loadings")
    if not isinstance(table, dict) or axis not in table:
        return None
    rows = sorted(table[axis], key=lambda r: -abs(r[1]))[:SHOWN_LOADINGS]
    bars = tuple(Bar(m, float(w), f"{'+' if w > 0 else '−'}{abs(w):.2f}") for m, w in rows)
    pos = [m for m, w in rows if w > 0]
    neg = [m for m, w in rows if w < 0]
    note = f"High {axis} reads as {', '.join(pos[:2]) or '—'} high"
    note += f" and {', '.join(neg[:2])} low." if neg else "."
    return BarSection(f"What {axis} is made of", bars, signed=True, note=note)


def choose(
    data: PopulationData, method_key: str, channels: tuple[str, ...], x: str, y: str
) -> ViewChoice | str:
    """The views ``method_key`` offers; a reason if it can't run on these axes."""
    if method_key == DENSITY_VALLEYS.key:
        if not x or not y or x == y:
            return "Pick two different axes for density valleys."
        return chosen_axes(data, x, y)
    if len(channels) < 2:  # noqa: PLR2004 - a view needs two axes
        return "Tick at least two channels."
    if method_key == MARKER_PAIRS.key:
        return marker_pairs(data, channels)
    return principal_components(data, channels)


def _depth(valley: object) -> float:
    return float(getattr(valley, "depth", 0.0))


def _formula(
    channels: tuple[str, ...], weights: np.ndarray, mean: np.ndarray, sd: np.ndarray
) -> str:
    """PC = Σ w/sd · asinh(ch/150) − Σ w·mean/sd, dropping the smallest terms if it's too long."""
    coefs = weights / sd
    order = np.argsort(-np.abs(weights))
    text = ""
    for n in range(len(channels), 1, -1):
        kept = sorted(order[:n])
        offset = -float(np.sum(weights[kept] * mean[kept] / sd[kept]))
        parts = []
        for i in kept:
            c = float(coefs[i])
            term = f"{abs(c):.4g} * asinh([{channels[i]}] / {COFACTOR:g})"
            parts.append(("- " if c < 0 else "+ ") + term)
        parts.append(("- " if offset < 0 else "+ ") + f"{abs(offset):.4g}")
        text = " ".join(parts)
        text = text[2:] if text.startswith("+ ") else "-" + text[2:]
        if len(text) <= MAX_FORMULA_LENGTH:
            return text
    return text
