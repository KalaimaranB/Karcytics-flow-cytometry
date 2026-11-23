"""Why an auto gate is where it is, read back from the record saved on the gate.

The record (``Gate.provenance``) is written once, when the split is accepted;
this only turns it into what the Why panel shows and a methods paragraph.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from .models import PCA, TEMPLATE, Bar, BarSection, GateStory, method


def _loadings(record: dict[str, Any], axis: str) -> BarSection | None:
    table = record.get("loadings") or {}
    if axis not in table:
        return None
    rows = sorted(table[axis], key=lambda r: -abs(r[1]))[:6]
    return BarSection(
        f"{axis} loadings",
        tuple(Bar(m, float(w), f"{'+' if w > 0 else '−'}{abs(w):.2f}") for m, w in rows),
        signed=True,
        note="Fixed when the gate was made: every sample uses these same weights.",
    )


def _groups(record: dict[str, Any]) -> BarSection | None:
    tried = record.get("components_tried")
    if not tried:
        return None
    bics = [b for _k, b in tried]
    lo, hi = min(bics), max(bics)
    span = (hi - lo) or 1.0
    chosen = int(record.get("components", 0))
    return BarSection(
        "Components tried (BIC, lower fits better)",
        tuple(
            Bar(f"{k} component{'s' if k > 1 else ''}", 0.15 + 0.85 * (b - lo) / span, f"{b:,.0f}")
            for k, b in tried
        ),
        highlight=tuple(i for i, (k, _b) in enumerate(tried) if k == chosen),
        note=(
            f"Components with no valley of {float(record.get('min_valley', 0)):.2f} between them "
            f"are one population: {chosen} components gave {record.get('groups', chosen)}."
        ),
    )


def _methods_text(gate: str, record: dict[str, Any]) -> str:
    info = method(str(record.get("method", "")))
    channels = ", ".join(record.get("channels", []))
    parent = record.get("parent", "its parent population")
    text = (
        f"The {gate} population was identified within {parent} by automated gating in Karcytics "
        f"({info.name}) on {record.get('reference_sample', 'the reference sample')}, using "
        f"{record.get('events_used', 0):,} events and the channels {channels}. "
    )
    if info.key == PCA.key:
        text += (
            "Channels were arcsinh-transformed (cofactor 150) and standardised, and principal components "
            f"were computed; the population was split on {record.get('view')}, the plane whose density "
            "showed the clearest valley. "
        )
    elif info.key == TEMPLATE.key:
        text += (
            f"It was gated from the template “{record.get('template', '')}”, which asked for "
            f"{record.get('asked', '')} within {parent}, on {record.get('view')}. "
        )
        if record.get("whole_population"):
            text += f"Nothing split {parent} on these markers, so the gate holds all of it. "
        elif record.get("control_lines"):
            text += _controls_text(record["control_lines"])
        elif record.get("cuts"):
            cuts = ", ".join(record["cuts"])
            text += (
                f"Cuts were placed at the lowest point of the density between two peaks on {cuts}. "
            )
    elif record.get("cuts"):
        cuts = ", ".join(record["cuts"])
        text += f"Cuts were placed at the lowest point of the density between two peaks on {cuts}. "
    else:
        text += f"The population was split on {record.get('view')}, the marker pair with the clearest valley. "
    if record.get("groups"):
        text += (
            f"A Gaussian mixture was fitted with {record.get('components', record['groups'])} "
            f"components (the number chosen by BIC over 1-{len(record.get('components_tried', []))}); "
            "components whose joint density showed no valley of "
            f"{float(record.get('min_valley', 0)):.2f} along the line between their centres were "
            f"merged (ridgeline criterion), giving {record['groups']} populations. Gates were placed "
            f"at {record.get('radius', 2):g} standard deviations (Mahalanobis distance) around each "
            "population's merged Gaussian. "
        )
    if record.get("convention") == "cells":
        text += (
            "Following convention, this first split kept the cells' density region on forward and "
            "side scatter, leaving out debris in the low corner and off-scale events. "
        )
    elif record.get("convention") == "singlets":
        text += (
            "Following convention, doublets were removed by the ratio of forward-scatter area to height "
            f"(kept between {record.get('ratio_kept', ['?', '?'])[0]} and {record.get('ratio_kept', ['?', '?'])[1]}). "
        )
    return text + "The same gates were applied unchanged to every sample in the group."


def _controls_text(lines: dict[str, dict[str, Any]]) -> str:
    """How control tubes placed the positive boundaries, e.g. for an FMO."""
    each = "; ".join(
        f"{marker}+ at the {line.get('percentile', 99.5):g}th percentile of the {line.get('kind')} "
        f"control {line.get('control')} ({int(line.get('events', 0)):,} events)"
        for marker, line in lines.items()
    )
    return f"Positive boundaries were set from control tubes put through the same gates: {each}. "


def story_of(gate: str, record: dict[str, Any]) -> GateStory:
    """The gate's story, told from its record."""
    info = method(str(record.get("method", "")))
    share = record.get("share")
    facts = [
        ("Method", info.name),
        ("Made on", f"{record.get('created', '')} · {record.get('reference_sample', '')}"),
        ("Split", f"{record.get('parent', '')} → {gate}"),
        ("Events used", f"{record.get('events_used', 0):,} of {record.get('parent_events', 0):,}"),
        ("Channels", ", ".join(record.get("channels", []))),
        ("View", f"{record.get('view', '')} (score {record.get('view_score', 0):.2f})"),
        (
            "Valley depth",
            f"{record.get('valley_depth', 0):.2f} (needs {record.get('min_valley', 0):.2f})",
        ),
    ]
    if share is not None:
        facts.append(("Share of parent", f"{100 * float(share):.1f}% when made"))
    for label, formula in (record.get("axis_formulas") or {}).items():
        facts.append((f"{label} formula", formula))
    sections = [
        s
        for s in (_loadings(record, "PC1"), _loadings(record, "PC2"), _groups(record))
        if s is not None
    ]
    if info.key == PCA.key:
        x, y = str(record.get("x_axis", "")), str(record.get("y_axis", ""))
        sections = [
            s
            for s in (_loadings(record, x), _loadings(record, y), _groups(record))
            if s is not None
        ]
    density = np.asarray(record.get("density") or [], dtype=np.float64)
    return GateStory(
        gate,
        info.key,
        tuple(facts),
        tuple(sections),
        density,
        float(record.get("valley_at", 0.5)),
        str(record.get("split_axis", "")),
        _methods_text(gate, record),
    )
