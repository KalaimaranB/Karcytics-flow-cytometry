"""Why an auto gate is where it is, read back from the record saved on the gate.

The record (``Gate.provenance``) is written once, when the split is accepted;
this only turns it into what the Why panel shows and a methods paragraph.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from .models import PCA, Bar, BarSection, GateStory, method


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
    tried = record.get("groups_tried")
    if not tried:
        return None
    bics = [b for _k, b in tried]
    lo, hi = min(bics), max(bics)
    span = (hi - lo) or 1.0
    chosen = int(record.get("groups", 0))
    return BarSection(
        "Groups tried (BIC, lower fits better)",
        tuple(
            Bar(f"{k} group{'s' if k > 1 else ''}", 0.15 + 0.85 * (b - lo) / span, f"{b:,.0f}")
            for k, b in tried
        ),
        highlight=tuple(i for i, (k, _b) in enumerate(tried) if k == chosen),
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
    elif record.get("cuts"):
        cuts = ", ".join(record["cuts"])
        text += f"Cuts were placed at the lowest point of the density between two peaks on {cuts}. "
    else:
        text += f"The population was split on {record.get('view')}, the marker pair with the clearest valley. "
    if record.get("groups"):
        text += (
            f"A Gaussian mixture with {record['groups']} components was fitted (the number chosen by "
            f"BIC over 1-{len(record.get('groups_tried', []))}, among fits whose components overlapped "
            f"by less than {100 * float(record.get('max_overlap', 0.3)):.0f}%), and gates were placed at "
            f"{record.get('radius', 2):g} standard deviations (Mahalanobis distance) around each component. "
        )
    return text + "The same gates were applied unchanged to every sample in the group."


def story_of(gate: str, record: dict[str, Any]) -> GateStory:
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
