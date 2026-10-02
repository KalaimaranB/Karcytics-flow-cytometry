"""Structural checks on every Academy course's step graph.

A dangling step id silently ends a course (the engine treats a missing
next step as completion and awards the badge); an unreachable step is dead
content. Both are easy to introduce when inserting a block of steps.
"""

from __future__ import annotations

import pytest

from karcytics_plugins.flow_cytometry.tutorials.courses import (
    course_1_fundamentals,
    course_2_gating,
    course_3_analysis,
    course_4_reporting,
)

COURSES = [course_1_fundamentals, course_2_gating, course_3_analysis, course_4_reporting]
SPECIAL_TARGETS = {"__abandon__"}
# Reached only from Python callbacks (ActionStep lambdas), which a static
# walk can't see — e.g. Course 1's route_import_failure(...).
DYNAMICALLY_ROUTED = {"c1_s3_fail_incorrect", "c1_s3_fail_too_few"}
_LINK_FIELDS = (
    "next_step_id",
    "on_success_step_id",
    "on_fail_step_id",
    "on_accept_step_id",
    "on_decline_step_id",
)


def _links(step) -> list[str]:
    links = [getattr(step, f) for f in _LINK_FIELDS if getattr(step, f, None)]
    links += list(getattr(step, "options", {}).values())
    # Validators can route too, via ValidationFailure.retry_step_id
    # (e.g. GateShapeValidator's misnamed_retry_step_id).
    validator = getattr(step, "validator", None)
    links += (
        [
            value
            for name, value in vars(validator).items()
            if name.endswith("_step_id") and isinstance(value, str)
        ]
        if validator is not None
        else []
    )
    return links


@pytest.mark.parametrize("course", COURSES, ids=[c.id for c in COURSES])
def test_step_ids_unique(course):
    ids = [s.id for s in course.steps]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("course", COURSES, ids=[c.id for c in COURSES])
def test_every_link_points_at_a_step(course):
    ids = {s.id for s in course.steps}
    dangling = [
        (s.id, target)
        for s in course.steps
        for target in _links(s)
        if target not in ids and target not in SPECIAL_TARGETS
    ]
    assert dangling == []


@pytest.mark.parametrize("course", COURSES, ids=[c.id for c in COURSES])
def test_every_step_reachable_from_the_first(course):
    by_id = {s.id: s for s in course.steps}
    seen: set[str] = set()
    stack = [course.steps[0].id]
    while stack:
        sid = stack.pop()
        if sid in seen or sid not in by_id:
            continue
        seen.add(sid)
        stack.extend(_links(by_id[sid]))
    unreachable = [s.id for s in course.steps if s.id not in seen]
    assert [sid for sid in unreachable if sid not in DYNAMICALLY_ROUTED] == []


def test_course4_derived_block_sits_between_course3_check_and_statistics():
    by_id = {s.id: s for s in course_4_reporting.steps}
    assert by_id["c4_s01_validate_analysis"].on_success_step_id == "c4_d01_intro"
    assert by_id["c4_d13_pitfalls"].next_step_id == "c4_d14_invalid_question"
    assert by_id["c4_d14_invalid_question"].next_step_id == "c4_s02_switch_statistics"
    assert by_id["c4_s06_select_stats"].on_success_step_id == "c4_s06a_ratio_channel"
    assert by_id["c4_s06a_ratio_channel"].on_success_step_id == "c4_s06b_compute"
