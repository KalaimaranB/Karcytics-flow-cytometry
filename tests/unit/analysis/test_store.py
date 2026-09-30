"""FlowStore: undo/redo over one long-lived FlowState, and dirty tracking."""

from __future__ import annotations

import pytest

from karcytics_plugins.flow_cytometry.analysis import events
from karcytics_plugins.flow_cytometry.analysis.compensation import CompensationMatrix
from karcytics_plugins.flow_cytometry.analysis.experiment import Group, Sample, SampleRole
from karcytics_plugins.flow_cytometry.analysis.gating import RectangleGate
from karcytics_plugins.flow_cytometry.analysis.population_service import PopulationService
from karcytics_plugins.flow_cytometry.analysis.scaling import AxisScale
from karcytics_plugins.flow_cytometry.analysis.store import UNRECORDED_CHANGE_LABEL, FlowStore
from karcytics_plugins.flow_cytometry.analysis.transforms import TransformType
from tests.fixtures.workspace import FakeBus, build_rich_state, fake_umap_run, make_fcs


@pytest.fixture
def bus():
    return FakeBus()


@pytest.fixture
def state():
    return build_rich_state()


@pytest.fixture
def store(state, bus):
    s = FlowStore(state, bus.publish)
    s.reset()
    return s


def _undo(store: FlowStore) -> bool:
    snapshot = store.history.undo()
    if snapshot is None:
        return False
    store.restore(snapshot)
    return True


def _redo(store: FlowStore) -> bool:
    snapshot = store.history.redo()
    if snapshot is None:
        return False
    store.restore(snapshot)
    return True


def _add_gate(state, sid="s0", name="New Gate"):
    node = state.data.experiment.samples[sid].gate_tree.add_child(
        RectangleGate("FSC-A", "SSC-A", x_min=1.0, x_max=2.0, y_min=1.0, y_max=2.0), name=name
    )
    return node


def _names(state, sid="s0"):
    """Every population name in a sample's gate tree."""
    names, stack = [], [state.data.experiment.samples[sid].gate_tree]
    while stack:
        node = stack.pop()
        names.append(node.name)
        stack.extend(node.children)
    return names


# ── Basics ────────────────────────────────────────────────────────────


def test_reset_is_a_clean_baseline(store):
    assert not store.history.can_undo()
    assert not store.is_dirty


def test_commit_makes_an_undoable_step_and_dirties(store, state):
    _add_gate(state)
    assert store.commit("Add Gate") is True
    assert store.history.undo_label() == "Add Gate"
    assert store.is_dirty


def test_commit_without_changes_is_not_a_step(store):
    assert store.commit("Nothing") is False
    assert not store.history.can_undo()


def test_undo_restores_the_exact_previous_model(store, state):
    before = store.capture()
    _add_gate(state)
    store.commit("Add Gate")
    after = store.capture()

    assert _undo(store)
    assert store.capture() == before
    assert _redo(store)
    assert store.capture() == after


def test_undo_back_to_the_saved_step_is_clean(store, state):
    _add_gate(state)
    store.commit("Add Gate")
    assert store.is_dirty
    _undo(store)
    assert not store.is_dirty
    _redo(store)
    assert store.is_dirty


# ── Identity & reattachment ───────────────────────────────────────────


def test_restore_keeps_state_identity_but_replaces_the_experiment(store, state):
    data, view = state.data, state.view
    old_experiment = state.data.experiment
    _add_gate(state)
    store.commit("Add Gate")
    _undo(store)
    assert state.data is data
    assert state.view is view
    assert state.data.experiment is not old_experiment


def test_restore_reattaches_the_same_event_data_objects(store, state):
    fcs = {sid: s.fcs_data for sid, s in state.data.experiment.samples.items()}
    _add_gate(state)
    store.commit("Add Gate")
    _undo(store)
    for sid, sample in state.data.experiment.samples.items():
        assert sample.fcs_data is fcs[sid]


def test_undoing_a_sample_removal_brings_its_event_data_back(store, state):
    fcs = state.data.experiment.samples["s2"].fcs_data
    state.data.experiment.remove_sample("s2")
    store.commit("Remove Samples")
    assert "s2" not in state.data.experiment.samples

    _undo(store)
    assert state.data.experiment.samples["s2"].fcs_data is fcs
    _redo(store)
    assert "s2" not in state.data.experiment.samples


def test_undoing_a_group_deletion_restores_its_scales(store, state):
    scales = state.data.experiment.groups["g1"].channel_scales
    for sid in list(state.data.experiment.groups["g1"].sample_ids):
        state.data.experiment.samples[sid].group_ids.remove("g1")
    del state.data.experiment.groups["g1"]
    store.commit("Delete Group")

    _undo(store)
    assert state.data.experiment.groups["g1"].channel_scales is scales


def test_scales_and_axis_memory_are_not_undone(store, state):
    """Display settings / navigation are saved but never reverted by undo."""
    group = state.data.experiment.groups["g1"]
    sample = state.data.experiment.samples["s0"]
    _add_gate(state)
    store.commit("Add Gate")
    group.channel_scales["APC-A"] = AxisScale(TransformType.LOG)
    sample.last_viewed_axes["other"] = {"x_param": "APC-A"}

    _undo(store)
    restored_group = state.data.experiment.groups["g1"]
    restored_sample = state.data.experiment.samples["s0"]
    assert "APC-A" in restored_group.channel_scales
    assert "other" in restored_sample.last_viewed_axes


def test_live_containers_never_alias_history(store, state):
    """Mutating the restored model in place must not rewrite history."""
    state.data.experiment.samples["s0"].role = SampleRole.OTHER
    store.commit("Change Role")
    _undo(store)
    snapshot = store.history.current.snapshot
    before = repr(snapshot)
    state.data.experiment.samples["s0"].group_ids.append("zzz")
    state.data.experiment.groups["g1"].sample_ids.append("zzz")
    assert repr(snapshot) == before


# ── No phantom steps (exact round-trip under restore) ─────────────────


def _mutations(state):  # noqa: C901 - one closure per kind of edit
    """One of every kind of analysis-model edit."""
    exp = state.data.experiment

    def add_gate():
        _add_gate(state)

    def delete_gate():
        lymph = exp.samples["s1"].gate_tree.children[0]
        assert PopulationService(state).remove_population("s1", lymph.children[0].node_id)

    def rename_gate():
        exp.samples["s0"].gate_tree.children[0].name = "Lymphs"

    def move_gate():
        gate = exp.samples["s0"].gate_tree.children[0].children[0].gate
        gate.x_max = 777.0

    def role():
        exp.samples["s1"].role = SampleRole.SINGLE_STAIN

    def rename_sample():
        exp.samples["s1"].display_name = "Renamed"

    def group():
        exp.groups["g2"] = Group(group_id="g2", name="New", sample_ids=["s2"])
        exp.samples["s2"].group_ids.append("g2")

    def marker():
        exp.marker_mappings[0].color = "#ABCDEF"

    def compensation():
        import numpy as np

        state.data.compensation = CompensationMatrix(np.eye(2), ["FITC-A", "APC-A"], "imported")

    def derived():
        exp.derived_parameters[0].name = "Ratio 2"

    def umap():
        state.data.umap_results.setdefault("s0::root", []).append(fake_umap_run())

    return [add_gate, delete_gate, rename_gate, move_gate, role, rename_sample, group, marker,
            compensation, derived, umap]  # fmt: skip


def test_walking_the_whole_history_never_records_phantom_edits(store, state):
    mutations = _mutations(state)
    captures = [store.capture()]
    for i, mutate in enumerate(mutations):
        mutate()
        assert store.commit(f"step {i}") is True, f"mutation {mutate.__name__} not detected"
        captures.append(store.capture())

    for expected in reversed(captures[:-1]):
        assert _undo(store)
        assert store.record_unannounced_changes() is False
        assert store.capture() == expected
    for expected in captures[1:]:
        assert _redo(store)
        assert store.record_unannounced_changes() is False
        assert store.capture() == expected
    assert not store.history.can_redo()


def test_an_inconsistent_model_still_never_records_phantom_edits(store, state):
    """Low-level remove_child leaves a logic node pointing at a deleted
    parent; serialization drops that dangling link, so a restore of it
    doesn't reserialize identically — the store must normalize, not
    mistake that for an unannounced change.
    """
    lymph = state.data.experiment.samples["s0"].gate_tree.children[0]
    singlets = next(c for c in lymph.children if c.name == "Singlets")
    lymph.remove_child(singlets.node_id)  # FITC+ gone, logic node still lists it
    store.commit("Delete Gate")
    _add_gate(state)
    store.commit("Add Gate")

    assert _undo(store)
    assert store.record_unannounced_changes() is False
    assert _undo(store)
    assert store.record_unannounced_changes() is False
    assert _redo(store)
    assert _redo(store)
    assert store.record_unannounced_changes() is False
    assert not store.history.can_redo()


# ── View repair & notifications ───────────────────────────────────────


def test_restore_publishes_state_restored(store, state, bus):
    _add_gate(state)
    store.commit("Add Gate")
    _undo(store)
    assert events.STATE_RESTORED in bus.topics()


def test_restore_clears_a_selected_gate_that_no_longer_exists(store, state):
    node = _add_gate(state)
    store.commit("Add Gate")
    state.view.current_sample_id = "s0"
    state.view.current_gate_id = node.node_id
    _undo(store)
    assert state.view.current_gate_id is None
    assert state.view.current_sample_id == "s0"


def test_restore_moves_off_a_sample_that_no_longer_exists(store, state):
    state.data.experiment.add_sample(
        Sample(sample_id="s9", display_name="S9", fcs_data=make_fcs("s9"))
    )
    store.commit("Add Samples")
    state.view.current_sample_id = "s9"
    state.view.active_fmo_sample_id = "s9"
    _undo(store)
    assert state.view.current_sample_id == "s0"
    assert state.view.active_fmo_sample_id is None


def test_restore_resets_a_group_filter_for_a_vanished_group(store, state):
    state.data.experiment.groups["g2"] = Group(group_id="g2", name="G2")
    store.commit("Create Group")
    state.view.active_group_filter = "g2"
    _undo(store)
    assert state.view.active_group_filter == "__all__"


def test_commits_during_restore_are_ignored(state, bus):
    store = FlowStore(state, bus.publish)
    store.reset()
    bus.subscribe(events.STATE_RESTORED, lambda _d: store.commit("reaction"))
    _add_gate(state)
    store.commit("Add Gate")
    _undo(store)
    assert store.history.can_redo()  # the reaction didn't wipe redo


# ── Recording controls ────────────────────────────────────────────────


def test_batch_coalesces_into_one_step(store, state):
    with store.batch("Paste Gates"):
        _add_gate(state, name="A")
        store.commit("inner 1")
        _add_gate(state, name="B")
        store.commit("inner 2")
    assert store.history.undo_label() == "Paste Gates"
    _undo(store)
    assert "A" not in _names(state) and "B" not in _names(state)


def test_suspended_records_nothing(store, state):
    with store.suspended():
        _add_gate(state)
        assert store.commit("ignored") is False
    assert not store.history.can_undo()


def test_absorb_folds_follow_up_changes_into_the_current_step(store, state):
    _add_gate(state, "s0", name="Source")
    store.commit("Add Gate")
    _add_gate(state, "s1", name="Propagated")  # what propagation would do
    store.absorb()
    assert store.history.undo_label() == "Add Gate"
    assert store.record_unannounced_changes() is False

    _undo(store)
    assert "Source" not in _names(state, "s0")
    assert "Propagated" not in _names(state, "s1")
    _redo(store)
    assert "Propagated" in _names(state, "s1")


def test_absorb_on_a_clean_baseline_stays_clean(store, state):
    _add_gate(state, "s1")
    store.absorb()
    assert not store.is_dirty


def test_unannounced_changes_become_their_own_step(store, state):
    _add_gate(state, name="Announced")
    store.commit("Add Gate")
    state.data.experiment.samples["s0"].display_name = "Sneaky"
    assert store.record_unannounced_changes() is True
    assert store.history.undo_label() == UNRECORDED_CHANGE_LABEL

    _undo(store)  # reverts only the sneaky change
    assert state.data.experiment.samples["s0"].display_name == "Sample 0"
    assert "Announced" in _names(state)


def test_first_commit_before_reset_only_sets_a_baseline(state, bus):
    store = FlowStore(state, bus.publish)
    assert store.commit("x") is False
    assert store.history.is_initialized
    assert not store.history.can_undo()


# ── Heavy data lifetime ───────────────────────────────────────────────


def test_umap_runs_get_stable_ids_and_come_back_by_identity(store, state):
    run = fake_umap_run()
    state.data.umap_results["s0::root"] = [run]
    store.commit("Run UMAP")
    assert run["run_id"]

    _undo(store)
    assert state.data.umap_results.get("s0::root", []) == []
    _redo(store)
    assert state.data.umap_results["s0::root"][0] is run


def test_event_data_is_released_once_no_step_can_bring_it_back(state, bus):
    store = FlowStore(state, bus.publish, max_steps=2)
    store.reset()
    state.data.experiment.remove_sample("s2")
    store.commit("Remove Samples")
    assert "s2" in store._event_data  # still undoable

    for i in range(3):
        _add_gate(state, name=f"g{i}")
        store.commit(f"Add {i}")
    assert "s2" not in store._event_data


def test_reset_drops_everything_the_new_workspace_doesnt_use(store, state):
    state.data.umap_results["s0::root"] = [fake_umap_run()]
    store.commit("Run UMAP")
    state.data.experiment.remove_sample("s2")
    state.data.umap_results = {}
    store.reset()
    assert "s2" not in store._event_data
    assert store._umap_runs == {}


# ── Dirty tracking ────────────────────────────────────────────────────


def test_display_changes_dirty_without_an_undo_step(store):
    store.mark_display_dirty()
    assert store.is_dirty
    assert not store.history.can_undo()


def test_save_marks_what_it_captured_as_clean(store, state):
    _add_gate(state)
    store.commit("Add Gate")
    store.mark_display_dirty()
    token = store.begin_save()
    store.finish_save(token)
    assert not store.is_dirty


def test_edits_made_during_a_background_save_stay_dirty(store, state):
    _add_gate(state, name="saved")
    store.commit("Add Gate")
    token = store.begin_save()
    _add_gate(state, name="unsaved")
    store.commit("Add Gate 2")
    store.finish_save(token)
    assert store.is_dirty
    _undo(store)
    assert not store.is_dirty


def test_display_edit_during_a_save_stays_dirty(store):
    token = store.begin_save()
    store.mark_display_dirty()
    store.finish_save(token)
    assert store.is_dirty


def test_begin_save_records_unannounced_changes_first(store, state):
    state.data.experiment.samples["s0"].display_name = "Sneaky"
    token = store.begin_save()
    store.finish_save(token)
    assert not store.is_dirty
    assert store.history.undo_label() == UNRECORDED_CHANGE_LABEL


def test_dirty_listeners_fire_only_on_flips(store, state):
    seen = []
    store.add_dirty_listener(seen.append)
    _add_gate(state, name="a")
    store.commit("a")
    _add_gate(state, name="b")
    store.commit("b")
    _undo(store)
    _undo(store)
    assert seen == [True, False]


def test_reset_clears_display_dirty(store):
    store.mark_display_dirty()
    store.reset()
    assert not store.is_dirty
