"""Course 3's "edit a gate, then undo it" pair of steps."""

from __future__ import annotations

from karcytics_plugins.flow_cytometry.analysis.experiment import Sample
from karcytics_plugins.flow_cytometry.analysis.gating import RectangleGate
from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.analysis.store import FlowStore
from karcytics_plugins.flow_cytometry.tutorials.validators import GateEditTracker


def _state() -> tuple[FlowState, RectangleGate]:
    state = FlowState()
    gate = RectangleGate("FITC-A", "PE-A", x_min=0, x_max=100, y_min=0, y_max=100)
    for sample_id in ("a", "b"):
        sample = Sample(sample_id=sample_id, display_name=sample_id)
        sample.gate_tree.add_child(gate if sample_id == "a" else gate.copy(), "T-cells")
        state.data.experiment.samples[sample_id] = sample
    state.view.current_sample_id = "a"
    return state, gate


def test_the_edit_step_passes_once_the_gate_changes_and_the_undo_step_once_it_is_back():
    state, gate = _state()
    tracker = GateEditTracker("t-cells")
    edited, undone = tracker.edited(), tracker.undone()
    store = FlowStore(state, lambda *_: None)
    store.reset()

    assert not undone.validate(state)  # nothing to undo yet
    assert not edited.validate(state)  # first look: remembers the shape

    gate.x_max = 60
    store.commit("Edit Gate")
    assert edited.validate(state)
    assert not undone.validate(state)

    store.restore(store.history.undo())  # what Ctrl+Z does
    assert undone.validate(state)

    # A replay of the course starts from whatever the gate looks like then.
    assert not edited.validate(state)


def test_a_missing_gate_fails_rather_than_raising():
    state, _gate = _state()
    assert not GateEditTracker("B-cells").edited().validate(state)
