"""Every widget a course step points at is actually named somewhere.

The Academy finds targets by objectName at runtime and silently skips a
name that matches nothing — the step just loses its highlight (Course 1's
Outliers dropdown went unnamed this way). A static check is enough: the
name has to appear as a string literal in the plugin's own UI code, or come
from one of the few f-string patterns that build names dynamically.
"""

from __future__ import annotations

import re
from pathlib import Path

from karcytics_plugins.flow_cytometry.tutorials.courses import (
    course_1_fundamentals,
    course_2_gating,
    course_3_analysis,
    course_4_reporting,
)

COURSES = [course_1_fundamentals, course_2_gating, course_3_analysis, course_4_reporting]
PLUGIN_ROOT = Path(__file__).resolve().parents[3] / "src" / "karcytics_plugins" / "flow_cytometry"
# setObjectName(f"Tool_{tool_id}") in gating_ribbon.py,
# setObjectName(f"Add{op.capitalize()}GateButton") in pipeline_ribbon.py.
DYNAMIC = [re.compile(r"Tool_[a-z]+"), re.compile(r"Add(And|Or|Not)GateButton")]
# Named by the SDK widget the plugin uses (components.WorkspaceSaveButton).
SDK_NAMED = {"WorkspaceSaveButton"}


def _target_names() -> dict[str, str]:
    names: dict[str, str] = {}
    for course in COURSES:
        for step in course.steps:
            listed = list(getattr(step, "target_widget_names", None) or [])
            single = getattr(step, "target_widget_name", "") or ""
            for name in [*listed, single]:
                if name:
                    names.setdefault(name, step.id)
    return names


def test_every_course_target_name_exists_in_the_ui():
    source = "\n".join(
        p.read_text(encoding="utf-8")
        for p in PLUGIN_ROOT.rglob("*.py")
        if "tutorials" not in p.parts
    )
    missing = {
        name: step_id
        for name, step_id in _target_names().items()
        if f'"{name}"' not in source
        and f"'{name}'" not in source
        and name not in SDK_NAMED
        and not any(p.fullmatch(name) for p in DYNAMIC)
    }
    assert missing == {}
