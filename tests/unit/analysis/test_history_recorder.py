"""HistoryRecorder: which events become undo steps, and how they coalesce."""

from __future__ import annotations

import pytest

from karcytics_plugins.flow_cytometry.analysis import events
from karcytics_plugins.flow_cytometry.analysis.gating import RectangleGate
from karcytics_plugins.flow_cytometry.analysis.history_recorder import (
    CONNECTION_ADDED,
    HistoryRecorder,
)
from karcytics_plugins.flow_cytometry.analysis.store import FlowStore
from tests.fixtures.workspace import FakeBus, ManualDefer, build_rich_state


@pytest.fixture
def env():
    state = build_rich_state()
    bus = FakeBus()
    store = FlowStore(state, bus.publish)
    store.reset()
    defer = ManualDefer()
    recorder = HistoryRecorder(store, bus.subscribe, bus.unsubscribe, defer)
    recorder.start()
    return state, bus, store, defer, recorder


def _edit(state, name="G"):
    state.data.experiment.samples["s0"].gate_tree.add_child(
        RectangleGate("FSC-A", "SSC-A", x_min=0.0, x_max=1.0, y_min=0.0, y_max=1.0), name=name
    )


@pytest.mark.parametrize(
    ("topic", "payload", "label"),
    [
        (events.GATE_CREATED, {"name": "CD4+"}, "Add Gate 'CD4+'"),
        (events.GATE_CREATED, {"is_split": True}, "Split Population"),
        (events.GATES_CREATED, {}, "Add Gates"),
        (events.LOGIC_NODE_CREATED, {}, "Add Logic Gate"),
        (events.GATE_DELETED, {}, "Delete Gate"),
        (events.GATE_RENAMED, {"new_name": "T"}, "Rename Gate to 'T'"),
        (events.GATE_MODIFIED, {}, "Edit Gate"),
        (CONNECTION_ADDED, {}, "Connect Gates"),
        (events.SAMPLE_LOADED, {}, "Add Samples"),
        (events.COMPENSATION_APPLIED, {}, "Change Compensation"),
        (events.DERIVED_PARAMS_CHANGED, {"action": "created"}, "Add Derived Parameter"),
        (events.DERIVED_PARAMS_CHANGED, {"action": "deleted"}, "Delete Derived Parameter"),
        (events.UMAP_COMPLETED, {}, "Run UMAP"),
        (events.MODEL_EDITED, {"label": "Rename Sample"}, "Rename Sample"),
    ],
)
def test_step_events_record_a_labelled_step(env, topic, payload, label):
    state, bus, store, defer, _ = env
    _edit(state)
    bus.publish(topic, payload)
    assert not store.history.can_undo()  # deferred to the end of the turn
    defer.run()
    assert store.history.undo_label() == label


def test_derived_resync_is_not_a_user_edit(env):
    state, bus, store, defer, _ = env
    _edit(state)
    bus.publish(events.DERIVED_PARAMS_CHANGED, {"action": "synced"})
    defer.run()
    assert not store.history.can_undo()


def test_one_action_publishing_many_events_is_one_step(env):
    state, bus, store, defer, _ = env
    for sid in ("s0", "s1", "s2"):  # e.g. a rename applied across samples
        state.data.experiment.samples[sid].gate_tree.children[0].name = "Lymphs"
        bus.publish(events.GATE_RENAMED, {"sample_id": sid, "new_name": "Lymphs"})
    defer.run()
    assert store.history.undo_label() == "Rename Gate to 'Lymphs'"
    store.restore(store.history.undo())
    names = {s.gate_tree.children[0].name for s in state.data.experiment.samples.values()}
    assert names == {"Lymphocytes"}


def test_separate_turns_are_separate_steps(env):
    state, bus, store, defer, _ = env
    _edit(state, "A")
    bus.publish(events.GATE_CREATED, {"name": "A"})
    defer.run()
    _edit(state, "B")
    bus.publish(events.GATE_CREATED, {"name": "B"})
    defer.run()
    assert store.history.undo_label() == "Add Gate 'B'"
    store.history.undo()
    assert store.history.undo_label() == "Add Gate 'A'"


def test_flush_commits_a_pending_step_immediately(env):
    state, bus, store, defer, recorder = env
    _edit(state)
    bus.publish(events.GATE_CREATED, {"name": "A"})
    assert recorder.has_pending
    recorder.flush()
    assert store.history.undo_label() == "Add Gate 'A'"
    defer.run()  # the scheduled flush is now a no-op
    assert store.history.undo_label() == "Add Gate 'A'"


def test_propagation_results_are_absorbed_into_the_triggering_step(env):
    state, bus, store, defer, _ = env
    _edit(state, "Source")
    bus.publish(events.GATE_CREATED, {"name": "Source"})
    state.data.experiment.samples["s1"].display_name = "propagated"
    bus.publish(events.PROPAGATION_COMPLETE, {})  # before the turn ended
    assert store.history.undo_label() == "Add Gate 'Source'"
    assert store.record_unannounced_changes() is False
    defer.run()
    assert store.history.undo_label() == "Add Gate 'Source'"


def test_display_settings_only_mark_dirty(env):
    _, bus, store, defer, _ = env
    bus.publish(events.DISPLAY_SETTINGS_CHANGED, {})
    defer.run()
    assert store.is_dirty
    assert not store.history.can_undo()


def test_events_while_not_recording_are_ignored(env):
    state, bus, store, defer, recorder = env
    with store.suspended():
        _edit(state)
        bus.publish(events.GATE_CREATED, {"name": "during load"})
    assert not recorder.has_pending
    defer.run()
    assert not store.history.can_undo()


def test_stop_unsubscribes_everything(env):
    state, bus, store, defer, recorder = env
    recorder.stop()
    assert all(not subs for subs in bus.subscribers.values())
    _edit(state)
    bus.publish(events.GATE_CREATED, {})
    defer.run()
    assert not store.history.can_undo()


def test_start_is_idempotent(env):
    _, bus, _, _, recorder = env
    counts = {t: len(s) for t, s in bus.subscribers.items()}
    recorder.start()
    assert {t: len(s) for t, s in bus.subscribers.items()} == counts
