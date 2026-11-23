"""A gating template: the tree of populations you expect, and each one's markers.

You write "Cells → Singlets → Live (PI−) → T cells (CD3+) → CD4 T (CD4+ CD8−)";
the template runner finds where each gate goes. Markers are kept by name, not
channel, so one template serves every panel that measures them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

CELLS, SINGLETS, MARKERS = "cells", "singlets", "markers"  # step kinds
LEVELS = ("+", "lo", "−")
MAX_CALLS = 2  # a gate is drawn on two axes
_CALL = re.compile(r"^(?P<marker>.+?)\s*(?P<level>\+|−|-|lo|dim|hi|bright|neg|pos)$", re.IGNORECASE)
_LEVEL = {"+": "+", "pos": "+", "hi": "+", "bright": "+", "lo": "lo", "dim": "lo"}
KIND_WORDS = {"scatter": CELLS, "cells": CELLS, "singlets": SINGLETS}


@dataclass(frozen=True)
class Call:
    """One marker level a template step asks for (``CD3+``)."""

    marker: str  # a marker name ("CD3") or a channel ("PE-A")
    level: str  # "+", "lo" or "−"

    @property
    def text(self) -> str:
        """The call as written (``CD3+``)."""
        return f"{self.marker}{self.level}"


@dataclass(frozen=True)
class TemplateStep:
    """One population a template finds, under its parent step."""

    step_id: str
    name: str
    parent_id: str | None  # None: straight under the start population
    kind: str = MARKERS
    calls: tuple[Call, ...] = ()

    @property
    def calls_text(self) -> str:
        """The step's markers as written (``CD3+ CD4lo``), or its scatter kind."""
        if self.kind != MARKERS:
            return "scatter" if self.kind == CELLS else SINGLETS
        return " ".join(c.text for c in self.calls)


@dataclass(frozen=True)
class GatingTemplate:
    """A named gating hierarchy written as marker calls."""

    name: str
    steps: tuple[TemplateStep, ...] = field(default=())

    def ordered(self) -> list[TemplateStep]:
        """Every step after its parent (depth first, in the order written)."""
        out: list[TemplateStep] = []

        def walk(parent: str | None) -> None:
            for step in self.steps:
                if step.parent_id == parent:
                    out.append(step)
                    walk(step.step_id)

        walk(None)
        return out

    def to_dict(self) -> dict[str, Any]:
        """The template as saved: each step's markers as text."""
        return {
            "name": self.name,
            "steps": [
                {"id": s.step_id, "name": s.name, "parent": s.parent_id, "markers": s.calls_text}
                for s in self.steps
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GatingTemplate:
        """A saved template; ``ValueError`` names a step whose markers don't parse."""
        steps = []
        for raw in data.get("steps", []):
            parsed = parse_calls(str(raw.get("markers", "")))
            if isinstance(parsed, str):
                raise ValueError(f"{raw.get('name', 'A step')}: {parsed}")
            kind, calls = parsed
            steps.append(
                TemplateStep(str(raw["id"]), str(raw["name"]), raw.get("parent"), kind, calls)
            )
        return cls(str(data.get("name", "Template")), tuple(steps))


def parse_calls(text: str) -> tuple[str, tuple[Call, ...]] | str:
    """("markers", calls) from e.g. "CD4+ CD8−", or a convention ("scatter", "singlets"),
    or why the text can't be read.
    """
    words = text.replace(",", " ").split()
    if len(words) == 1 and words[0].lower() in KIND_WORDS:
        return KIND_WORDS[words[0].lower()], ()
    if not words:
        return "Give one or two markers with + / lo / −, e.g. “CD3+” or “CD4+ CD8−”."
    calls = []
    for word in words:
        match = _CALL.match(word)
        if match is None:
            return f"“{word}” needs + / lo / − after the marker (e.g. “{word}+”)."
        level = _LEVEL.get(match["level"].lower(), "−")
        calls.append(Call(match["marker"], level))
    if len(calls) > MAX_CALLS:
        return f"At most {MAX_CALLS} markers per population: a gate is drawn on two axes."
    return MARKERS, tuple(calls)


STARTER = GatingTemplate(
    "Starter",
    (
        TemplateStep("cells", "Cells", None, CELLS),
        TemplateStep("singlets", "Singlets", "cells", SINGLETS),
    ),
)
