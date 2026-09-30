"""The single workspace serializer: exact round-trips and load semantics.

Exactness matters beyond saving: FlowStore compares a fresh capture against
the current undo step to detect changes nothing announced, so any field that
doesn't survive deserialize → serialize unchanged would turn every undo into
a phantom "Edit" step that wipes the redo stack.
"""

from __future__ import annotations

import json

import pytest

from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.analysis.workspace_document import (
    PERSISTED_VIEW_FIELDS,
    apply_workspace,
    capture_model,
    detached,
    model_experiment,
    serialize_workspace,
)
from tests.fixtures.workspace import build_rich_state, fake_umap_run, make_fcs


def _reserialize(document: dict) -> dict:
    """Load `document` into a fresh state and save it again.

    Reattaches event data the way a real load's FCS reload does — each
    sample's ``file_path`` is read from it, and a document carries none.
    """
    state = FlowState()
    apply_workspace(state, document)
    for sid, sample in state.data.experiment.samples.items():
        sample.fcs_data = make_fcs(sid)
    return serialize_workspace(state)


def _json_round_trip(document: dict) -> dict:
    return json.loads(json.dumps(document))


def test_document_round_trip_is_exact():
    document = serialize_workspace(build_rich_state())
    assert _reserialize(document) == document


def test_document_survives_json_and_reserializes_identically():
    """What's actually written to disk is JSON (tuples become lists)."""
    document = serialize_workspace(build_rich_state())
    on_disk = _json_round_trip(document)
    assert _json_round_trip(_reserialize(on_disk)) == on_disk


def test_model_snapshot_round_trip_is_exact():
    state = build_rich_state()
    snapshot = capture_model(state, {})
    rebuilt = FlowState()
    rebuilt.data.experiment = model_experiment(snapshot)
    rebuilt.data.compensation = state.data.compensation
    for sid, sample in rebuilt.data.experiment.samples.items():
        sample.fcs_data = state.data.experiment.samples[sid].fcs_data
    assert capture_model(rebuilt, {}) == snapshot


def test_model_snapshot_leaves_out_navigation_and_display_settings():
    snapshot = capture_model(build_rich_state(), {})
    assert "view" not in snapshot
    for sample in snapshot["experiment"]["samples"].values():
        assert "last_viewed_axes" not in sample
    for group in snapshot["experiment"]["groups"].values():
        assert "channel_scales" not in group


def test_model_snapshot_is_detached_from_live_containers():
    state = build_rich_state()
    snapshot = capture_model(state, {})
    before = json.dumps(snapshot, sort_keys=True, default=list)

    sample = state.data.experiment.samples["s0"]
    sample.group_ids.append("other")
    sample.markers.append("CD3")
    sample.keywords["NEW"] = "1"
    state.data.experiment.groups["g1"].sample_ids.append("s2")

    assert json.dumps(snapshot, sort_keys=True, default=list) == before


def test_large_subset_indices_are_shared_not_copied():
    state = build_rich_state()
    snap_a = capture_model(state, {})
    snap_b = capture_model(state, {})

    def _subset_indices(snap):
        nodes = snap["experiment"]["samples"]["s0"]["gate_tree"]["nodes"]
        return [n["gate"]["indices"] for n in nodes if n["gate"] and "indices" in n["gate"]]

    a, b = _subset_indices(snap_a), _subset_indices(snap_b)
    assert a and all(isinstance(x, tuple) for x in a)
    assert all(x is y for x, y in zip(a, b, strict=True))


def test_detached_copies_containers_and_shares_tuples():
    shared = (1, 2, 3)
    original = {"a": [1, {"b": [2]}], "t": shared, "s": {1, 2}}
    copy_ = detached(original)
    assert copy_ == original
    assert copy_["a"] is not original["a"]
    assert copy_["a"][1] is not original["a"][1]
    assert copy_["s"] is not original["s"]
    assert copy_["t"] is shared


# ── Load semantics ────────────────────────────────────────────────────


def test_apply_replaces_the_previous_workspace_entirely():
    state = build_rich_state()
    state.data.umap_results = {"s0::root": [fake_umap_run()]}
    state.view.active_group_filter = "g1"
    state.view.active_fmo_sample_id = "s2"
    state.view.fallback_scales = {"FSC-A": object()}

    apply_workspace(state, {"experiment": {"name": "Other", "samples": {}}})

    assert state.data.experiment.name == "Other"
    assert state.data.experiment.samples == {}
    assert state.data.compensation is None
    assert state.data.umap_results == {}
    assert state.view.active_group_filter == "__all__"
    assert state.view.active_fmo_sample_id is None
    assert state.view.fallback_scales == {}


def test_apply_with_no_experiment_still_clears_the_old_one():
    """Previously an empty payload silently kept the old samples."""
    state = build_rich_state()
    apply_workspace(state, {})
    assert state.data.experiment.samples == {}


def test_apply_keeps_state_identity():
    state = build_rich_state()
    data, view = state.data, state.view
    apply_workspace(state, serialize_workspace(build_rich_state(1)))
    assert state.data is data
    assert state.view is view


def test_view_defaults_match_a_fresh_state():
    state = build_rich_state()
    apply_workspace(state, {"experiment": {}})
    fresh = FlowState()
    for name in PERSISTED_VIEW_FIELDS:
        assert getattr(state.view, name) == getattr(fresh.view, name), name


@pytest.mark.parametrize("field", PERSISTED_VIEW_FIELDS)
def test_every_persisted_view_field_round_trips(field):
    state = build_rich_state()
    value = {
        "current_sample_id": "s1",
        "current_gate_id": "some-gate",
        "active_x_param": "FITC-A",
        "active_y_param": "APC-A",
        "active_transform_x": "biexponential",
        "active_transform_y": "log",
        "active_plot_type": "contour",
        "auto_range_on_quality": False,
    }[field]
    setattr(state.view, field, value)
    restored = FlowState()
    apply_workspace(restored, serialize_workspace(state))
    assert getattr(restored.view, field) == value


def test_render_config_round_trips():
    from karcytics_plugins.flow_cytometry.analysis.config import PseudocolorConfig, RenderConfig

    state = build_rich_state()
    state.view.render_config = RenderConfig(pseudocolor=PseudocolorConfig(max_events=42000))
    restored = FlowState.from_dict(state.to_dict())
    assert restored.view.render_config.to_dict() == state.view.render_config.to_dict()


def test_flow_state_to_dict_is_the_workflow_document():
    state = build_rich_state()
    assert state.to_dict() == serialize_workspace(state)
