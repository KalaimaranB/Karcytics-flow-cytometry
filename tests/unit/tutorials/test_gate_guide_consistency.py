"""Regression test: the on-canvas guide box shown to the user for a gate-
drawing tutorial step must be something GateShapeValidator actually accepts.

Found via a real bug report: course1's Live Cells guide_range topped out at
10000, but its validator's target_bounds required the gate to reach ~50000
(within a 10%-of-axis-range tolerance) — so a gate drawn to exactly trace the
box the user was shown got rejected as "bad shape" even though it was
correct. The same mismatch existed for course2's B-cells gate. This test
walks every gate-drawing InteractionStep in course1/course2 that has guide
metadata, builds a gate matching that guide exactly, and asserts the paired
VerificationStep's validator accepts it — so this class of bug can't silently
come back in either course.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from karcytics_sdk.plugin.tutorial_models import InteractionStep, VerificationStep

from karcytics_plugins.flow_cytometry.analysis.gating.polygon import PolygonGate
from karcytics_plugins.flow_cytometry.analysis.gating.quadrant import QuadrantGate, QuadrantSubGate
from karcytics_plugins.flow_cytometry.analysis.gating.range import RangeGate
from karcytics_plugins.flow_cytometry.analysis.gating.rectangle import RectangleGate
from karcytics_plugins.flow_cytometry.tutorials import course1, course2
from karcytics_plugins.flow_cytometry.tutorials.validators import GateShapeValidator


def _gate_matching_guide(metadata: dict):
    if "guide_range" in metadata:
        low, high = metadata["guide_range"]
        return RangeGate(x_param="x", low=low, high=high)
    if "guide_rect" in metadata:
        x_min, x_max, y_min, y_max = metadata["guide_rect"]
        return RectangleGate(
            x_param="x", y_param="y", x_min=x_min, x_max=x_max, y_min=y_min, y_max=y_max
        )
    if "guide_quadrant" in metadata:
        x_mid, y_mid = metadata["guide_quadrant"]
        # Wrapped in a QuadrantSubGate, matching what's actually stored as
        # node.gate at runtime: QuadrantGate.create_nodes() only ever attaches
        # QuadrantSubGate leaves (see quadrant.py), never the parent
        # QuadrantGate directly, and GateMutationService.add_gate() selects
        # one of those leaves after creation. A bare QuadrantGate here would
        # miss GateShapeValidator's QuadrantSubGate->parent unwrap step
        # entirely (see validators.py), which is exactly how a typo'd
        # attribute name there (parent_gate vs parent) silently turned
        # quadrant shape checking into a no-op that accepted any position.
        parent = QuadrantGate(x_param="x", y_param="y", x_mid=x_mid, y_mid=y_mid)
        return QuadrantSubGate(parent, "Q1")
    if "guide_data_poly" in metadata:
        return PolygonGate(x_param="x", y_param="y", vertices=list(metadata["guide_data_poly"]))
    return None


def _gate_drawing_cases():
    """Yields (case_id, metadata, validator) for every InteractionStep with
    guide metadata whose next_step_id points at a VerificationStep using a
    GateShapeValidator.
    """
    for course in (course1.course_1_fundamentals, course2.course_2_gating):
        steps_by_id = {s.id: s for s in course.steps}
        for step in course.steps:
            if not isinstance(step, InteractionStep):
                continue
            guide_keys = {
                "guide_range",
                "guide_rect",
                "guide_quadrant",
                "guide_data_poly",
            } & step.metadata.keys()
            if not guide_keys or not step.next_step_id:
                continue
            next_step = steps_by_id.get(step.next_step_id)
            if not isinstance(next_step, VerificationStep) or not isinstance(
                next_step.validator, GateShapeValidator
            ):
                continue
            yield f"{course.id}/{step.id}", step.metadata, next_step.validator


def _fake_app_state(gate) -> SimpleNamespace:
    node = SimpleNamespace(gate=gate)
    sample = SimpleNamespace(gate_tree=SimpleNamespace(find_node_by_id=lambda _nid: node))
    return SimpleNamespace(data=SimpleNamespace(experiment=SimpleNamespace(samples={"s1": sample})))


_CASES = list(_gate_drawing_cases())


class TestNoGateDrawingStepsAreSilentlyOrphaned:
    def test_at_least_one_gate_drawing_step_was_found_per_course(self):
        """Guards the test itself: if course step wiring changes shape and
        this stops matching anything, we'd otherwise pass vacuously."""
        found_courses = {case_id.split("/")[0] for case_id, _metadata, _validator in _CASES}
        assert found_courses == {course1.course_1_fundamentals.id, course2.course_2_gating.id}
        assert len(_CASES) >= 6, "expected at least the 3 gates in each of course1/course2"


@pytest.mark.parametrize("case_id, metadata, validator", _CASES, ids=[c[0] for c in _CASES])
def test_gate_matching_the_shown_guide_box_is_accepted(case_id, metadata, validator):  # noqa: ARG001
    gate = _gate_matching_guide(metadata)
    assert gate is not None, f"unrecognized guide metadata keys: {metadata.keys()}"

    app_state = _fake_app_state(gate)

    # Plain truthy check, not `is True` — the polygon path returns a numpy
    # bool_ (iou >= 0.90), and numpy.bool_(True) is not the `is`-identical
    # to Python's True singleton.
    assert validator.validate_shape(app_state, node_id="node_1", sample_id="s1")


_QUADRANT_CASES = [
    (case_id, metadata, validator)
    for case_id, metadata, validator in _CASES
    if "guide_quadrant" in metadata
]


@pytest.mark.parametrize(
    "case_id, metadata, validator", _QUADRANT_CASES, ids=[c[0] for c in _QUADRANT_CASES]
)
def test_quadrant_gate_far_from_the_guide_is_rejected(case_id, metadata, validator):  # noqa: ARG001
    """A gate drawn to match the guide box is asserted accepted above, but that
    alone can pass vacuously if shape checking is silently a no-op for this
    gate type (exactly what happened when GateShapeValidator's
    QuadrantSubGate->parent unwrap read the wrong attribute name and always
    fell through to "skip unknown gate types" — see validators.py). This
    checks the other direction: a quadrant crosshair placed nowhere near the
    guide must be rejected.
    """
    x_mid, y_mid = metadata["guide_quadrant"]
    far_parent = QuadrantGate(
        x_param="x", y_param="y", x_mid=x_mid + 100000.0, y_mid=y_mid + 100000.0
    )
    far_gate = QuadrantSubGate(far_parent, "Q1")

    app_state = _fake_app_state(far_gate)

    assert not validator.validate_shape(app_state, node_id="node_1", sample_id="s1")
