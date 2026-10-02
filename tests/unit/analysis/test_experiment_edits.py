"""Non-gate model edits: each is one labelled undo step that undoes exactly.

Runs every edit through the real chain — experiment_edits → FakeBus →
HistoryRecorder → FlowStore — the same path the widgets now use.
"""

from __future__ import annotations

import numpy as np
import pytest

from karcytics_plugins.flow_cytometry.analysis import events
from karcytics_plugins.flow_cytometry.analysis.compensation import CompensationMatrix
from karcytics_plugins.flow_cytometry.analysis.experiment import SampleRole, WorkflowTemplate
from karcytics_plugins.flow_cytometry.analysis.history_recorder import HistoryRecorder
from karcytics_plugins.flow_cytometry.analysis.services import experiment_edits as edits
from karcytics_plugins.flow_cytometry.analysis.store import FlowStore
from tests.fixtures.workspace import CHANNELS, FakeBus, ManualDefer, build_rich_state, fake_umap_run


class Env:
    def __init__(self) -> None:
        self.state = build_rich_state()
        self.bus = FakeBus()
        self.store = FlowStore(self.state, self.bus.publish)
        self.store.reset()
        self.defer = ManualDefer()
        HistoryRecorder(self.store, self.bus.subscribe, self.bus.unsubscribe, self.defer).start()

    def end_turn(self) -> None:
        self.defer.run()

    def undo(self) -> None:
        self.store.restore(self.store.history.undo())

    def redo(self) -> None:
        self.store.restore(self.store.history.redo())


@pytest.fixture
def env():
    return Env()


def _assert_one_exact_step(env: Env, edit, label: str):
    before = env.store.capture()
    assert edit()
    env.end_turn()
    after = env.store.capture()
    assert after != before
    assert env.store.history.undo_label() == label
    env.undo()
    assert env.store.capture() == before
    assert not env.store.history.can_undo()
    assert not env.store.is_dirty
    env.redo()
    assert env.store.capture() == after
    assert env.store.record_unannounced_changes() is False


# ── One step each, exact undo/redo ────────────────────────────────────


@pytest.mark.parametrize(
    ("label", "edit"),
    [
        ("Rename Sample", lambda s, p: edits.rename_sample(s, "s1", "  Renamed ", p)),
        ("Remove Sample", lambda s, p: edits.remove_samples(s, ["s1"], p)),
        ("Remove Samples", lambda s, p: edits.remove_samples(s, ["s0", "s2", "nope"], p)),
        ("Change Sample Role", lambda s, p: edits.set_sample_roles(s, ["s1"], SampleRole.OTHER, p)),
        (
            "Assign Sample Roles",
            lambda s, p: edits.set_sample_roles(s, ["s0", "s1", "s2"], SampleRole.SINGLE_STAIN, p),
        ),
        ("Create Group", lambda s, p: edits.create_group(s, "New", p)),
        ("Rename Group", lambda s, p: edits.rename_group(s, "g1", "Renamed", p)),
        ("Delete Group", lambda s, p: edits.delete_group(s, "g1", p)),
        ("Add to Group 'Tests'", lambda s, p: edits.add_samples_to_group(s, "g1", ["s2"], p)),
        (
            "Remove from Group 'Tests'",
            lambda s, p: edits.remove_samples_from_group(s, "g1", ["s0"], p),
        ),
        (
            "Edit Compensation Matrix",
            lambda s, p: (
                edits.set_compensation(
                    s,
                    CompensationMatrix(np.eye(2), ["FITC-A", "APC-A"]),
                    "Edit Compensation Matrix",
                    p,
                )
                or True
            ),
        ),
        (
            "Apply Template 'T'",
            lambda s, p: (
                edits.apply_template(s, WorkflowTemplate(name="T", markers=["X"]), p) or True
            ),
        ),
    ],
)
def test_each_edit_is_one_exact_undo_step(env, label, edit):
    _assert_one_exact_step(env, lambda: edit(env.state, env.bus.publish), label)


def test_no_op_edits_record_nothing(env):
    publish = env.bus.publish
    assert not edits.rename_sample(env.state, "s0", "Sample 0", publish)
    assert not edits.rename_sample(env.state, "missing", "x", publish)
    assert not edits.rename_group(env.state, "g1", "  ", publish)
    assert not edits.set_sample_roles(
        env.state, ["s0"], env.state.data.experiment.samples["s0"].role, publish
    )
    assert not edits.add_samples_to_group(env.state, "g1", ["s0"], publish)
    assert edits.create_group(env.state, "   ", publish) is None
    env.end_turn()
    assert not env.store.history.can_undo()
    assert events.MODEL_EDITED not in env.bus.topics()


def test_edits_keep_publishing_the_ui_refresh_events(env):
    edits.rename_sample(env.state, "s0", "X", env.bus.publish)
    edits.remove_samples(env.state, ["s1"], env.bus.publish)
    edits.set_sample_roles(env.state, ["s2"], SampleRole.OTHER, env.bus.publish)
    topics = env.bus.topics()
    assert topics.count(events.MODEL_EDITED) == 3
    assert events.SAMPLE_UPDATED in topics
    assert events.EXPERIMENT_DATA_CHANGED in topics


def test_one_turn_of_edits_is_one_step_named_by_the_first(env):
    """E.g. the compensation editor: set matrix, then re-apply, same turn."""
    edits.set_compensation(
        env.state, CompensationMatrix(np.eye(2), ["FITC-A", "APC-A"]), "Edit Compensation Matrix",
        env.bus.publish,
    )  # fmt: skip
    edits.apply_compensation_to_all(env.state, env.bus.publish)
    env.end_turn()
    assert env.store.history.undo_label() == "Edit Compensation Matrix"
    env.undo()
    assert not env.store.history.can_undo()


def test_delete_group_clears_a_filter_pointing_at_it(env):
    env.state.view.active_group_filter = "g1"
    edits.delete_group(env.state, "g1", env.bus.publish)
    assert env.state.view.active_group_filter == "__all__"


def test_role_edit_after_undo_lands_on_the_live_sample(env):
    """Widgets address samples by id — a held object is detached by undo."""
    edits.rename_sample(env.state, "s0", "first", env.bus.publish)
    env.end_turn()
    env.undo()
    edits.set_sample_roles(env.state, ["s0"], SampleRole.ISOTYPE_CONTROL, env.bus.publish)
    assert env.state.data.experiment.samples["s0"].role == SampleRole.ISOTYPE_CONTROL


# ── Compensation rewrites event data — undo must put it back ──────────


def _events_equal(a, b) -> bool:
    """Compare measured channels only — derived columns are re-synced."""
    return np.allclose(a[CHANNELS].to_numpy(), b[CHANNELS].to_numpy())


def test_undoing_apply_compensation_restores_raw_events(env):
    sample = env.state.data.experiment.samples["s0"]
    raw = sample.fcs_data.events.copy()
    result = edits.apply_compensation_to_all(env.state, env.bus.publish)
    assert result.changed == 3
    env.end_turn()
    assert not _events_equal(sample.fcs_data.events, raw)

    env.undo()
    restored = env.state.data.experiment.samples["s0"]
    assert restored.is_compensated is False
    assert restored.fcs_data.is_compensated is False
    assert _events_equal(restored.fcs_data.events, raw)

    env.redo()
    again = env.state.data.experiment.samples["s0"]
    assert again.fcs_data.is_compensated is True
    assert not _events_equal(again.fcs_data.events, raw)


def test_undoing_a_toggle_off_recompensates(env):
    edits.apply_compensation_to_all(env.state, env.bus.publish)
    env.end_turn()
    compensated = env.state.data.experiment.samples["s0"].fcs_data.events.copy()

    toggled, target = edits.toggle_compensation(env.state, env.bus.publish)
    env.end_turn()
    assert (toggled, target) == (3, False)
    assert env.store.history.undo_label() == "Turn Compensation Off"

    env.undo()
    sample = env.state.data.experiment.samples["s0"]
    assert sample.fcs_data.is_compensated
    assert _events_equal(sample.fcs_data.events, compensated)


def test_undoing_a_matrix_change_recompensates_with_the_old_matrix(env):
    edits.apply_compensation_to_all(env.state, env.bus.publish)
    env.end_turn()
    with_old = env.state.data.experiment.samples["s0"].fcs_data.events.copy()

    new = CompensationMatrix(np.array([[1.0, 0.5], [0.4, 1.0]]), ["FITC-A", "APC-A"])
    edits.set_compensation(env.state, new, "Edit Compensation Matrix", env.bus.publish)
    for sample in env.state.data.experiment.samples.values():  # what the editor's re-apply does
        sample.is_compensated = False
    edits.apply_compensation_to_all(env.state, env.bus.publish)
    env.end_turn()
    assert not _events_equal(env.state.data.experiment.samples["s0"].fcs_data.events, with_old)

    env.undo()
    assert _events_equal(env.state.data.experiment.samples["s0"].fcs_data.events, with_old)


# ── UMAP runs ─────────────────────────────────────────────────────────


def test_umap_run_add_and_delete_are_undoable(env):
    run = fake_umap_run("s0")
    key = edits.add_umap_run(env.state, run, env.bus.publish)
    env.end_turn()
    assert env.store.history.undo_label() == "Run UMAP"

    assert edits.delete_umap_run(env.state, key, 0, env.bus.publish)
    env.end_turn()
    assert env.state.data.umap_results[key] == []
    assert env.store.history.undo_label() == "Delete UMAP Run"

    env.undo()
    assert env.state.data.umap_results[key][0] is run
    env.undo()
    assert env.state.data.umap_results.get(key, []) == []


def test_deleting_a_missing_run_is_a_no_op(env):
    assert not edits.delete_umap_run(env.state, "nope::root", 0, env.bus.publish)
    edits.add_umap_run(env.state, fake_umap_run(), env.bus.publish)
    assert not edits.delete_umap_run(env.state, "s0::root", 5, env.bus.publish)


def test_annotation_edits_mark_unsaved_without_a_step(env):
    edits.announce_unsaved_change(env.bus.publish)
    env.end_turn()
    assert env.store.is_dirty
    assert not env.store.history.can_undo()
