"""Course 1's handling of the Properties Panel's Properties | Histogram switch.

Role assignment needs the Properties view (the Role dropdown lives there);
the first gate is drawn with the Histogram view open and spotlit, then the
panel is switched back for the steps that read gate statistics.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from karcytics_plugins.flow_cytometry.analysis.constants import (
    PROPERTIES_VIEW_HISTOGRAM,
    PROPERTIES_VIEW_PROPERTIES,
)
from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.tutorials.course1 import (
    course_1_fundamentals,
    route_by_properties_view,
)
from karcytics_plugins.flow_cytometry.tutorials.validators import PropertiesViewValidator

pytestmark = pytest.mark.unit

STEPS = {step.id: step for step in course_1_fundamentals.steps}


def _state(view: str) -> FlowState:
    state = FlowState()
    state.view.properties_view = view
    return state


def test_validator_passes_only_on_the_expected_view():
    validator = PropertiesViewValidator(PROPERTIES_VIEW_HISTOGRAM)

    assert validator.validate(_state(PROPERTIES_VIEW_HISTOGRAM)) is True
    assert validator.validate(_state(PROPERTIES_VIEW_PROPERTIES)) is False


def test_properties_is_the_default_view():
    assert FlowState().view.properties_view == PROPERTIES_VIEW_PROPERTIES


@pytest.mark.parametrize(
    "view, expected_next",
    [
        (PROPERTIES_VIEW_PROPERTIES, "c1_s5_blank_role"),
        (PROPERTIES_VIEW_HISTOGRAM, "c1_s5_switch_to_properties"),
        # Routing rewrites the step in place, so it must also route back.
        (PROPERTIES_VIEW_PROPERTIES, "c1_s5_blank_role"),
    ],
)
def test_role_assignment_asks_for_a_switch_only_when_on_histogram(view, expected_next):
    check = STEPS["c1_s5_check_properties_view"]

    check.action(SimpleNamespace(state=_state(view)))

    assert check.next_step_id == expected_next


def test_router_ignores_an_unknown_step():
    before = {step.id: step.next_step_id for step in course_1_fundamentals.steps}

    route_by_properties_view(
        SimpleNamespace(state=_state(PROPERTIES_VIEW_HISTOGRAM)), "nope", "a", "b"
    )

    assert {step.id: step.next_step_id for step in course_1_fundamentals.steps} == before


def test_switch_step_leads_into_role_assignment():
    switch = STEPS["c1_s5_switch_to_properties"]

    assert switch.validator.expected == PROPERTIES_VIEW_PROPERTIES
    assert switch.on_success_step_id == "c1_s5_blank_role"
    assert switch.target_widget_names == ["PropertiesViewToggle"]


def test_first_gate_is_drawn_with_the_histogram_open_and_spotlit():
    open_histogram = STEPS["c1_s23b_open_histogram"]
    draw = STEPS["c1_s24_cells_gate"]

    assert STEPS["c1_s23_cells_intro"].next_step_id == open_histogram.id
    assert open_histogram.validator.expected == PROPERTIES_VIEW_HISTOGRAM
    assert open_histogram.on_success_step_id == draw.id
    assert "GateHistogramPanel" in draw.target_widget_names


@pytest.mark.parametrize("step_id", ["c1_s24_cells_gate_verify", "c1_s24_cells_gate_misnamed"])
def test_panel_is_switched_back_after_the_first_gate(step_id):
    step = STEPS[step_id]
    back = STEPS["c1_s24a_back_to_properties"]

    assert back.id in (step.next_step_id, getattr(step, "on_success_step_id", None))
    assert back.validator.expected == PROPERTIES_VIEW_PROPERTIES
    assert back.on_success_step_id == "c1_s24b_cells_hierarchy_intro"


def test_only_the_first_gate_uses_the_histogram_view():
    spotlit = [
        s.id for s in course_1_fundamentals.steps if "GateHistogramPanel" in s.target_widget_names
    ]

    assert spotlit == ["c1_s24_cells_gate"]


def _gate_drawing_steps():
    from karcytics_plugins.flow_cytometry.tutorials.courses import (
        course_2_compensation,
        course_3_gating,
    )

    return [
        step
        for course in (course_1_fundamentals, course_2_compensation, course_3_gating)
        for step in course.steps
        if getattr(step, "event_trigger", "") == "gate_added_to_tree"
    ]


def test_every_gate_drawing_step_keeps_the_right_panel_usable():
    """A spotlit widget stays clickable and scrollable; anything else is dimmed
    and locked. Every gate is drawn with the right panel in the spotlight, so
    the user can switch it to Histogram or scroll the Group Preview meanwhile.
    """
    steps = _gate_drawing_steps()
    assert len(steps) == 6  # Cells; Live Cells and Leukocytes; three in Course 3

    for step in steps:
        if step.id == "c1_s24_cells_gate":
            continue  # the first gate spotlights the histogram itself
        assert "PropertiesPanel" in step.target_widget_names, step.id
        assert "Group Preview" in step.text and "Histogram" in step.text, step.id
