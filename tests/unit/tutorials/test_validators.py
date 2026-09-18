"""Unit tests for GateShapeValidator.describe_failure().

`describe_failure()` is what lets AcademyStepDriver (SDK) auto-correct a
misnamed or badly-shaped tutorial gate and explain why, instead of a course
routing an ActionStep through the old `_TUTORIAL_STATE` global. These tests
drive it directly against the instance state `validate_flow()` leaves behind
(`last_misnamed_node_id`/`last_failed_node_id`/`last_misnamed_sample_id`)
rather than re-deriving that state from a full FlowState/gate-tree fixture —
`validate_flow()`'s own shape/name-matching search is unchanged by this work
and isn't what's under test here.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from karcytics_plugins.flow_cytometry.analysis.gating.quadrant import QuadrantGate
from karcytics_plugins.flow_cytometry.tutorials.validators import GateShapeValidator


def make_panel() -> SimpleNamespace:
    return SimpleNamespace(
        state=SimpleNamespace(
            view=SimpleNamespace(current_sample_id="sample_a", current_gate_id=None)
        ),
        _gate_coordinator=MagicMock(),
        _on_delete_selected_gate=MagicMock(),
    )


class TestNoFailureDiagnosed:
    def test_returns_none_when_nothing_recorded(self):
        validator = GateShapeValidator(target_name="Live Cells")
        assert validator.describe_failure(app_state=None) is None


class TestMisnamedGate:
    def test_reason_mentions_the_correct_name(self):
        validator = GateShapeValidator(
            target_name="Live Cells",
            misnamed_retry_step_id="misnamed_step",
            shape_retry_step_id="retry_step",
        )
        validator.last_misnamed_node_id = "node_42"
        validator.last_misnamed_sample_id = "sample_b"

        failure = validator.describe_failure(app_state=None)

        assert failure is not None
        assert "Live Cells" in failure.reason
        assert failure.retry_step_id == "misnamed_step"

    def test_corrective_renames_on_the_sample_the_gate_was_found_on(self):
        validator = GateShapeValidator(target_name="Live Cells")
        validator.last_misnamed_node_id = "node_42"
        validator.last_misnamed_sample_id = "sample_b"  # differs from panel's current_sample_id
        panel = make_panel()

        failure = validator.describe_failure(app_state=None)
        assert failure and failure.corrective
        failure.corrective(panel)

        assert panel.state.view.current_gate_id == "node_42"
        panel._gate_coordinator.rename_population.assert_called_once_with(
            "sample_b", "node_42", "Live Cells"
        )
        panel._gate_coordinator.request_propagation.assert_called_once_with("node_42", "sample_b")

    def test_corrective_falls_back_to_current_sample_when_no_sample_recorded(self):
        validator = GateShapeValidator(target_name="Live Cells")
        validator.last_misnamed_node_id = "node_42"
        validator.last_misnamed_sample_id = None
        panel = make_panel()  # current_sample_id == "sample_a"

        validator.describe_failure(app_state=None).corrective(panel)

        panel._gate_coordinator.rename_population.assert_called_once_with(
            "sample_a", "node_42", "Live Cells"
        )

    def test_misnamed_takes_priority_over_a_stale_shape_failure(self):
        """validate_flow() only ever sets one of the two per run, but
        describe_failure() should still prefer the naming fix if somehow
        both are set — a misnamed gate is real & present; don't delete it."""
        validator = GateShapeValidator(target_name="Live Cells")
        validator.last_misnamed_node_id = "node_42"
        validator.last_failed_node_id = "node_99"

        failure = validator.describe_failure(app_state=None)

        assert "renamed" in failure.reason.lower()


class TestBadlyShapedGate:
    def test_reason_explains_the_gate_was_deleted(self):
        validator = GateShapeValidator(
            target_name="Live Cells",
            shape_retry_step_id="retry_step",
        )
        validator.last_failed_node_id = "node_99"

        failure = validator.describe_failure(app_state=None)

        assert failure is not None
        assert "deleted" in failure.reason.lower()
        assert failure.retry_step_id == "retry_step"

    def test_corrective_selects_and_deletes_the_bad_gate(self):
        validator = GateShapeValidator(target_name="Live Cells")
        validator.last_failed_node_id = "node_99"
        panel = make_panel()

        validator.describe_failure(app_state=None).corrective(panel)

        assert panel.state.view.current_gate_id == "node_99"
        panel._on_delete_selected_gate.assert_called_once_with(force_silent=True)


def _app_state_with_gate(gate) -> SimpleNamespace:
    node = SimpleNamespace(gate=gate)
    sample = SimpleNamespace(gate_tree=SimpleNamespace(find_node_by_id=lambda _nid: node))
    return SimpleNamespace(data=SimpleNamespace(experiment=SimpleNamespace(samples={"s1": sample})))


class TestQuadrantGateShape:
    """QuadrantGate has one click point (x_mid, y_mid), not two independent
    edges — reusing RangeGate/RectangleGate's ±10%-of-axis-range edge
    tolerance here previously worked out to accepting almost anywhere within
    roughly 26,000 units of either target edge (over 12x wider than a 4,000-
    unit target window), because it checked "close to either target edge
    independently" instead of "contained within the target window". These
    lock in the fix: containment against target_bounds, no bonus tolerance.
    """

    def test_crosshair_inside_the_target_window_is_accepted(self):
        validator = GateShapeValidator(target_bounds=(3000.0, 7000.0, 3000.0, 7000.0))
        gate = QuadrantGate(x_param="x", y_param="y", x_mid=5000.0, y_mid=5000.0)

        assert validator.validate_shape(_app_state_with_gate(gate), node_id="n", sample_id="s1")

    def test_crosshair_far_from_the_target_window_is_rejected(self):
        validator = GateShapeValidator(target_bounds=(3000.0, 7000.0, 3000.0, 7000.0))
        # Well outside [3000, 7000] on both axes, but well within the old
        # (buggy) ~26,000-unit tolerance band that used to let this through.
        gate = QuadrantGate(x_param="x", y_param="y", x_mid=20000.0, y_mid=20000.0)

        assert not validator.validate_shape(_app_state_with_gate(gate), node_id="n", sample_id="s1")

    def test_crosshair_just_outside_the_window_on_one_axis_is_rejected(self):
        validator = GateShapeValidator(target_bounds=(3000.0, 7000.0, 3000.0, 7000.0))
        gate = QuadrantGate(x_param="x", y_param="y", x_mid=5000.0, y_mid=7500.0)

        assert not validator.validate_shape(_app_state_with_gate(gate), node_id="n", sample_id="s1")
