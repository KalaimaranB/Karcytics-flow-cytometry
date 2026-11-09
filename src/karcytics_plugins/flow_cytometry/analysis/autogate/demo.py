"""Example output for the Auto Gating tab while the analysis is being built.

Nothing here looks at events: every proposal is the same made-up split
(two main populations and two small ones), labelled with the markers the
user picked so the screens read like the real thing. Replaced by the real
engine in ``composition_root`` once it exists; the tab does not change.
"""

from __future__ import annotations

import zlib
from dataclasses import replace
from itertools import combinations

import numpy as np

from ..clustering.describe import short_marker
from .models import (
    DENSITY_VALLEYS,
    MARKER_PAIRS,
    PCA,
    Bar,
    BarSection,
    GateStory,
    GroupPreview,
    MethodOutcome,
    PlotData,
    Proposal,
    Region,
    SampleOutcome,
    Shape,
    StepRequest,
    method,
)

N_POINTS = 3000
N_EVENTS = 19_884
FLAG_SHIFT = 0.05  # a gate that moved more than this share of its axis needs a look
DRIFTED_SAMPLE = 2  # the third sample that is not a control drifts, so the flag shows
SHOWN_TERMS = 3  # loadings written out in an axis label
DEMO_SAMPLES = tuple((f"Specimen_00{i}", False) for i in range(1, 7))

# The made-up populations: (centre x, centre y, sd x, sd y, share of events).
_BLOBS = (
    (0.70, 0.30, 0.070, 0.055, 0.61),  # a+ b-
    (0.28, 0.72, 0.060, 0.050, 0.33),  # a- b+
    (0.22, 0.22, 0.035, 0.035, 0.05),  # a- b-
    (0.76, 0.78, 0.030, 0.030, 0.01),  # a+ b+
)


def _seed(*parts: str) -> int:
    return zlib.crc32("|".join(parts).encode())


def _points(seed: int, dx: float = 0.0, dy: float = 0.0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    parts = []
    for cx, cy, sx, sy, share in _BLOBS:
        n = int(N_POINTS * share)
        parts.append(rng.normal((cx + dx, cy + dy), (sx, sy), size=(n, 2)))
    parts.append(rng.uniform(0.05, 0.95, size=(60, 2)))  # debris between them
    return np.clip(np.vstack(parts), 0.0, 1.0)


def _markers(request: StepRequest) -> tuple[str, str]:
    """The two markers the example split is about, from what the user picked."""
    if request.x_channel and request.y_channel:
        return short_marker(request.x_channel), short_marker(request.y_channel)
    shorts = [short_marker(c) for c in request.channels] or ["CD4", "CD8"]
    preferred = [m for m in ("CD4", "CD8") if m in shorts]
    rest = [m for m in shorts if m not in preferred]
    picked = (preferred + rest + ["CD4", "CD8"])[:2]
    return picked[0], picked[1]


def _names(a: str, b: str) -> tuple[str, str, str, str]:
    return f"{a}+ {b}−", f"{a}− {b}+", f"{a}− {b}−", f"{a}+ {b}+"


def _regions(method_key: str, a: str, b: str) -> tuple[Region, ...]:
    pos, neg, dn, dp = _names(a, b)
    if method_key == DENSITY_VALLEYS.key:
        cut = (0.48, 0.50)
        return tuple(
            Region(name, share, Shape.QUADRANT, (*cut, float(q)))
            for q, (name, share) in enumerate(((neg, 0.32), (dp, 0.02), (dn, 0.05), (pos, 0.61)))
        )
    if method_key == MARKER_PAIRS.key:
        return (
            Region(
                pos,
                0.60,
                Shape.POLYGON,
                (0.50, 0.46, 0.86, 0.48, 0.92, 0.20, 0.80, 0.10, 0.52, 0.12, 0.46, 0.28),
            ),
            Region(
                neg,
                0.33,
                Shape.POLYGON,
                (0.12, 0.62, 0.15, 0.86, 0.42, 0.88, 0.44, 0.60, 0.30, 0.54),
            ),
        )
    return (
        Region(pos, 0.61, Shape.ELLIPSE, (0.70, 0.30, 0.17, 0.13, -12.0)),
        Region(neg, 0.33, Shape.ELLIPSE, (0.28, 0.72, 0.14, 0.11, 8.0)),
    )


def _moved(region: Region, dx: float, dy: float) -> Region:
    p = list(region.params)
    if region.shape is Shape.ELLIPSE:
        p[0], p[1] = p[0] + dx, p[1] + dy
    elif region.shape is Shape.POLYGON:
        p = [v + (dx if i % 2 == 0 else dy) for i, v in enumerate(p)]
    elif region.shape is Shape.QUADRANT:
        p[0], p[1] = p[0] + dx, p[1] + dy
    else:
        p = [v + dx for v in p]
    return replace(region, params=tuple(p))


def _pc_formula(n: int, terms: list[tuple[str, float]]) -> str:
    body = "  ".join(f"{'+' if w > 0 else '−'}{abs(w):.2f} {m}" for m, w in terms[:SHOWN_TERMS])
    return f"PC{n} = {body}" + ("  …" if len(terms) > SHOWN_TERMS else "")


class DemoEngine:
    """Example output in the shape the real engine will return."""

    is_demo = True

    # ── Build ─────────────────────────────────────────────────────────

    def propose(self, request: StepRequest) -> Proposal:
        a, b = _markers(request)
        info = method(request.method_key)
        rank = max(request.view_rank, 0)
        if info.key == PCA.key:
            x_label, y_label, sections, why = self._pca_view(request, a, b, rank)
        elif info.key == MARKER_PAIRS.key:
            x_label, y_label, sections, why = self._pairs_view(request, a, b, rank)
        else:
            x_label = request.x_channel or a
            y_label = request.y_channel or b
            sections = (
                BarSection(
                    "Valleys found",
                    (Bar(a, 0.78, "0.78"), Bar(b, 0.83, "0.83")),
                    note="How deep the low point between the two peaks is (1 = empty between them).",
                ),
            )
            why = (
                f"On the axes you chose: {a} has two peaks with a clear low point between them "
                f"(valley 0.78), and so does {b} (0.83). The quadrant is placed at both low points."
            )
        regions = _regions(info.key, a, b)
        named = ", ".join(f"{r.name} ({r.fraction:.0%})" for r in regions if r.is_main)
        reason = f"{why} Named from each group's medians: {named}."
        plot = PlotData(x_label, y_label, _points(_seed(request.population)), regions)
        return Proposal(info.key, request.population, N_EVENTS, plot, sections, reason)

    def _pca_view(
        self, request: StepRequest, a: str, b: str, rank: int
    ) -> tuple[str, str, tuple[BarSection, ...], str]:
        others = [short_marker(c) for c in request.channels if short_marker(c) not in (a, b)]
        pc1 = [(a, 0.68), (b, -0.66)] + [
            (m, w) for m, w in zip(others, (0.21, -0.08, 0.05), strict=False)
        ]
        pc2 = [(others[0] if others else a, 0.72), (b, 0.41), (a, 0.38)]
        planes = (("PC1 × PC2", 0.84), ("PC1 × PC3", 0.61), ("PC2 × PC3", 0.22))
        chosen = rank % len(planes)
        sections = (
            BarSection(
                "Variance explained",
                tuple(Bar(f"PC{i + 1}", v / 50, f"{v}%") for i, v in enumerate((46, 21, 12, 9, 6))),
                highlight=(0, 1),
            ),
            BarSection(
                "Best plane to split",
                tuple(Bar(name, s, f"{s:.2f}") for name, s in planes),
                highlight=(chosen,),
                note="How cleanly the best split on each plane separates the cells.",
            ),
            BarSection(
                "What PC1 is made of",
                tuple(Bar(m, w, f"{'+' if w > 0 else '−'}{abs(w):.2f}") for m, w in pc1),
                signed=True,
                note=f"Mostly {a} against {b}: high PC1 reads as {a}+, low as {b}+.",
            ),
        )
        name, score = planes[chosen]
        lead = "Next-best plane. " if rank else ""
        why = (
            f"{lead}{name} separates {request.population} best (score {score:.2f}). Along PC1 "
            "there are two clear peaks (valley 0.81), and a 2-group Gaussian mixture fits better "
            "than 1, 3 or 4 groups (BIC)."
        )
        return _pc_formula(1, pc1), _pc_formula(2, pc2), sections, why

    def _pairs_view(
        self, request: StepRequest, a: str, b: str, rank: int
    ) -> tuple[str, str, tuple[BarSection, ...], str]:
        shorts = [short_marker(c) for c in request.channels] or [a, b]
        pairs = [(x, y) for x, y in combinations(shorts, 2) if {x, y} != {a, b}]
        scores = np.linspace(0.64, 0.07, max(len(pairs), 1))
        ranked = [((a, b), 0.91)] + [(p, float(s)) for p, s in zip(pairs, scores, strict=True)]
        chosen = rank % len(ranked)
        sections = (
            BarSection(
                "Marker pairs, ranked",
                tuple(Bar(f"{x} × {y}", s, f"{s:.2f}") for (x, y), s in ranked),
                highlight=(chosen,),
                note=f"All {len(ranked)} pairs of the chosen channels were tried.",
            ),
        )
        (x, y), score = ranked[chosen]
        lead = "Next-best pair. " if rank else ""
        why = (
            f"{lead}{x} × {y} is the clearest of the {len(ranked)} pairs (score {score:.2f}). "
            "Two groups, each drawn as a polygon along its density contour."
        )
        label = {short_marker(c): c for c in request.channels}
        return label.get(x, x), label.get(y, y), sections, why

    # ── Apply to group ────────────────────────────────────────────────

    def preview_group(self, request: StepRequest, adaptive: bool) -> GroupPreview:
        proposal = self.propose(request)
        regions = proposal.plot.regions
        names = proposal.plot.main_names
        rows = []
        panels = 0
        for sample, is_control in request.samples or DEMO_SAMPLES:
            if is_control:
                rows.append(SampleOutcome(sample, {}, 0.0, "Skipped: control sample", False, None))
                continue
            rng = np.random.default_rng(_seed(sample))
            dx, dy = rng.normal(0, 0.02, size=2)
            panels += 1
            if panels == DRIFTED_SAMPLE + 1:
                dx, dy = 0.07, -0.02
            percents = {
                r.name: max(0.0, r.fraction * 100 + float(rng.normal(0, 3)))
                for r in regions
                if r.name in names
            }
            shift = float(max(abs(dx), abs(dy))) if adaptive else 0.0
            moved = tuple(_moved(r, dx, dy) for r in regions) if adaptive else regions
            flagged = shift > FLAG_SHIFT
            if not adaptive:
                status = "Same gates as the reference"
            elif flagged:
                status = f"Review: moved {shift:.0%} of the axis"
            else:
                status = f"Moved {shift:.0%}"
            plot = PlotData(
                proposal.plot.x_label,
                proposal.plot.y_label,
                _points(_seed(request.population, sample), dx, dy),
                moved,
                regions if adaptive else (),
            )
            rows.append(SampleOutcome(sample, percents, shift, status, flagged, plot))
        return GroupPreview(names, tuple(rows))

    # ── Compare methods ───────────────────────────────────────────────

    def compare(self, request: StepRequest) -> tuple[MethodOutcome, ...]:
        a, b = _markers(request)
        pos, neg, _dn, _dp = _names(a, b)
        points = _points(_seed(request.population))
        own = (
            Region(pos, 0.62, Shape.POLYGON, (0.48, 0.48, 0.90, 0.50, 0.94, 0.12, 0.50, 0.10)),
            Region(neg, 0.32, Shape.POLYGON, (0.10, 0.58, 0.10, 0.90, 0.46, 0.90, 0.46, 0.58)),
        )
        rows = [
            MethodOutcome(
                "Your gates",
                "",
                {pos: 62.0, neg: 32.1},
                {},
                1,
                f"{a} × {b}",
                PlotData(a, b, points, own),
            )
        ]
        results = {
            DENSITY_VALLEYS.key: (
                {pos: 61.2, neg: 32.4},
                {pos: 0.97, neg: 0.96},
                1,
                f"{a} × {b} (yours)",
            ),
            MARKER_PAIRS.key: ({pos: 60.4, neg: 33.0}, {pos: 0.96, neg: 0.95}, 1, f"{a} × {b}"),
            PCA.key: ({pos: 61.0, neg: 33.2}, {pos: 0.94, neg: 0.93}, 1, "PC1 × PC2"),
        }
        for info in (DENSITY_VALLEYS, MARKER_PAIRS, PCA):
            percents, agreement, steps, axes = results[info.key]
            x, y = ("PC1", "PC2") if info.key == PCA.key else (a, b)
            plot = PlotData(x, y, points, _regions(info.key, a, b))
            rows.append(MethodOutcome(info.name, info.key, percents, agreement, steps, axes, plot))
        return tuple(rows)

    # ── Why this gate ─────────────────────────────────────────────────

    def story(self, gate: str, parent: str, request: StepRequest) -> GateStory:
        parent = parent or "All Events"
        a, b = _markers(request)
        info = method(request.method_key)
        xs = np.linspace(0, 1, 120)
        density = 0.62 * np.exp(-((xs - 0.28) ** 2) / 0.006) + np.exp(-((xs - 0.70) ** 2) / 0.009)
        density = density / density.max()
        bic = (("1 group", 0.95), ("2 groups", 0.42), ("3 groups", 0.47), ("4 groups", 0.55))
        sections: tuple[BarSection, ...] = (
            BarSection(
                "Groups tried (BIC, lower fits better)",
                tuple(Bar(k, v, f"{v * 1000:.0f}") for k, v in bic),
                highlight=(1,),
            ),
        )
        if info.key == PCA.key:
            sections = (
                BarSection(
                    "PC1 loadings",
                    (Bar(a, 0.68, "+0.68"), Bar(b, -0.66, "−0.66")),
                    signed=True,
                    note="Fixed when the gate was made: every sample uses these same weights.",
                ),
                *sections,
            )
        axes = "PC1 × PC2" if info.key == PCA.key else f"{a} × {b}"
        split_axis = "PC1" if info.key == PCA.key else a
        facts = (
            ("Method", info.name),
            ("Split", f"{parent} → {gate}"),
            ("Reference sample", request.reference or "Specimen_001"),
            ("Events used", f"{N_EVENTS:,} (all of {parent})"),
            ("Channels", ", ".join(short_marker(c) for c in request.channels) or f"{a}, {b}"),
            ("View", axes),
            ("Valley depth", "0.81 (clear)"),
            ("Share of parent", "61.0%"),
        )
        transform = (
            "logicle-transformed and standardised" if info.key == PCA.key else "logicle-transformed"
        )
        text = (
            f"The {gate} population was identified within {parent} by automated gating in "
            f"Karcytics ({info.name}). Channels ({facts[4][1]}) were {transform}; the population was "
            f"split on {axes} with a two-component Gaussian mixture (chosen by BIC over 1-4 "
            "components), and gates were placed at a Mahalanobis radius of 2. The same gates were "
            "applied unchanged to every sample in the group."
        )
        return GateStory(
            gate,
            info.key,
            facts,
            sections,
            density,
            0.48,
            split_axis,
            text,
            edits=("No edits since it was made.",),
        )
