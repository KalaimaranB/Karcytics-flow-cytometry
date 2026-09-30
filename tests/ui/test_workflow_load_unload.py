"""Workflow load/unload through the real panel + WorkflowService path.

Covers what the single serializer and FlowStore have to guarantee across
loads: a save reproduces exactly, a new workflow fully replaces the old one
(nothing leaks through), the loaded workflow is the clean undo baseline,
history from before a load can never undo into the new workspace, and a
failed / stuck / late-finishing load never leaves recording or undo broken.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication, QMessageBox

from karcytics_plugins.flow_cytometry.analysis.gating import RectangleGate
from karcytics_plugins.flow_cytometry.analysis.history_recorder import HistoryRecorder
from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.analysis.workspace_document import (
    capture_model,
    serialize_workspace,
)
from karcytics_plugins.flow_cytometry.ui.services.attachment_manager import AttachmentManager
from karcytics_plugins.flow_cytometry.ui.services.workflow_service import WorkflowService
from tests.fixtures.workspace import (
    FakeBus,
    ManualDefer,
    build_rich_state,
    fake_umap_run,
    make_fcs,
    set_real_view_defaults,
)


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


class FakeLoader:
    """Reattaches event data synchronously (no task scheduler)."""

    _scheduler = None

    def __init__(self) -> None:
        self.requested: list[list[tuple[str, Path]]] = []

    def reload_samples_batch(self, samples_with_paths, _compensation) -> dict[str, list[str]]:
        self.requested.append([(s.sample_id, p) for s, p in samples_with_paths])
        for sample, _path in samples_with_paths:
            sample.fcs_data = make_fcs(sample.sample_id)
        return {"loaded": [s.display_name for s, _ in samples_with_paths], "failed": []}


@pytest.fixture
def panel(qapp, qtbot, monkeypatch):
    from karcytics_plugins.flow_cytometry.ui.main_panel import FlowCytometryPanel

    p = FlowCytometryPanel(plugin_id="flow_load_test")
    qtbot.addWidget(p)
    p.logger = MagicMock()
    set_real_view_defaults(p.state)
    p._store.reset()
    p._workflow_service._data_loader = FakeLoader()
    monkeypatch.setattr(p, "_get_project_manager", lambda: None)
    # _refresh_all() touches Phase-2 widgets this minimal panel never built.
    monkeypatch.setattr(p, "_refresh_all", lambda: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.StandardButton.Ok)
    return p


def _saved(state: FlowState, project_dir: Path | None = None) -> dict[str, Any]:
    """What a real save writes to disk for `state` (JSON round-tripped)."""
    service = WorkflowService(state, FakeLoader(), AttachmentManager(MagicMock()))
    payload = service.export_workflow(project_dir=project_dir)
    return json.loads(json.dumps(payload))


def _normalized(document: dict) -> dict:
    return json.loads(json.dumps(document))


def _one_sample_state() -> FlowState:
    state = build_rich_state(n_samples=1)
    state.data.experiment.name = "Workflow B"
    exp = state.data.experiment
    sample = exp.samples.pop("s0")
    sample.sample_id = "b0"
    sample.display_name = "B zero"
    sample.group_ids = []
    sample.fcs_data = make_fcs("b0")
    exp.samples["b0"] = sample
    exp.groups.clear()
    exp.derived_parameters = []
    state.data.compensation = None
    state.view.current_sample_id = "b0"
    return state


def _edit(panel, name="Edited"):
    panel.state.data.experiment.samples[
        next(iter(panel.state.data.experiment.samples))
    ].gate_tree.add_child(
        RectangleGate("FSC-A", "SSC-A", x_min=0.0, x_max=1.0, y_min=0.0, y_max=1.0), name=name
    )
    panel._store.commit(f"Add Gate '{name}'")


# ── Round trip ────────────────────────────────────────────────────────


def test_load_reproduces_the_saved_workspace_exactly(panel):
    original = build_rich_state()
    panel.load_workflow(_saved(original))
    assert _normalized(serialize_workspace(panel.state)) == _normalized(
        serialize_workspace(original)
    )
    assert _normalized(capture_model(panel.state, {})) == _normalized(capture_model(original, {}))


def test_loaded_workflow_is_a_clean_baseline(panel):
    panel.load_workflow(_saved(build_rich_state()))
    assert not panel._workflow_loading
    assert not panel._store.is_dirty
    assert not panel.can_undo()
    assert panel._store.record_unannounced_changes() is False


def test_state_identity_survives_loads(panel):
    state, data, view = panel.state, panel.state.data, panel.state.view
    panel.load_workflow(_saved(build_rich_state()))
    panel.load_workflow(_saved(_one_sample_state()))
    assert panel.state is state and state.data is data and state.view is view


def test_project_relative_sample_paths_resolve_against_the_new_project(panel, tmp_path):
    original = build_rich_state()
    payload = _saved(original, project_dir=Path("/data"))
    assert payload["sample_paths"]["s0"] == "s0.fcs"

    monkeypatch_pm = MagicMock(project_dir=tmp_path)
    monkeypatch_pm.workflows.load_attachments.return_value = []
    panel._get_project_manager = lambda: monkeypatch_pm
    panel.load_workflow(payload)

    requested = dict(panel._workflow_service._data_loader.requested[-1])
    assert requested["s0"] == tmp_path / "s0.fcs"


# ── Replacing one workflow with another ───────────────────────────────


def test_loading_b_over_a_leaves_nothing_of_a(panel):
    a = build_rich_state()
    panel.load_workflow(_saved(a))
    panel.state.data.umap_results = {"s0::root": [fake_umap_run()]}
    panel.state.view.active_group_filter = "g1"
    panel.state.view.active_fmo_sample_id = "s2"

    b = _one_sample_state()
    panel.load_workflow(_saved(b))

    exp = panel.state.data.experiment
    assert list(exp.samples) == ["b0"]
    assert exp.groups == {}
    assert exp.derived_parameters == []
    assert panel.state.data.compensation is None
    assert panel.state.data.umap_results == {}
    assert panel.state.view.active_group_filter == "__all__"
    assert panel.state.view.active_fmo_sample_id is None
    assert _normalized(serialize_workspace(panel.state)) == _normalized(serialize_workspace(b))


def test_edits_before_a_load_can_never_undo_into_the_new_workspace(panel):
    panel.load_workflow(_saved(build_rich_state()))
    _edit(panel)
    assert panel.can_undo()

    panel.load_workflow(_saved(_one_sample_state()))
    assert not panel.can_undo()
    assert panel.undo() is False
    assert list(panel.state.data.experiment.samples) == ["b0"]
    assert not panel._store.is_dirty


def test_a_step_pending_at_load_time_does_not_leak_into_the_new_history(panel):
    bus, defer = FakeBus(), ManualDefer()
    panel._history_recorder = HistoryRecorder(panel._store, bus.subscribe, bus.unsubscribe, defer)
    panel.load_workflow(_saved(build_rich_state()))

    panel.state.data.experiment.samples["s0"].display_name = "pending edit"
    panel._history_recorder.request_commit("Rename Sample")  # end of turn not reached
    panel.load_workflow(_saved(_one_sample_state()))
    defer.run()

    assert not panel.can_undo()
    assert not panel._store.is_dirty


def test_undo_after_load_and_edits_returns_exactly_to_the_loaded_state(panel):
    panel.load_workflow(_saved(build_rich_state()))
    loaded = _normalized(capture_model(panel.state, {}))
    _edit(panel, "one")
    _edit(panel, "two")
    assert panel.undo() and panel.undo()
    assert _normalized(capture_model(panel.state, {})) == loaded
    assert not panel._store.is_dirty
    assert panel.redo() and panel.redo()
    assert panel._store.is_dirty


# ── Loads that don't go to plan ───────────────────────────────────────


def test_a_failed_load_leaves_an_unsaved_but_working_workspace(panel, monkeypatch):
    errors = []
    monkeypatch.setattr(
        "karcytics_plugins.flow_cytometry.ui.main_panel.show_error",
        lambda *a, **k: errors.append(a),
    )
    panel.load_workflow(_saved(build_rich_state()))

    broken = {"experiment": {"samples": {"x": {"sample_id": "x"}}}}  # no display_name
    panel.load_workflow(broken)

    assert errors, "the user must be told the load failed"
    assert not panel._workflow_loading
    assert panel._store.is_recording
    assert panel._store.is_dirty  # whatever is on screen was never saved
    _edit(panel)
    assert panel.undo()


def test_undo_is_refused_while_a_load_is_still_reloading_data(panel):
    messages = []
    panel.status_message.connect(messages.append)
    panel.load_workflow(_saved(build_rich_state()))
    _edit(panel)

    stuck = FakeLoader()
    stuck._scheduler = MagicMock()  # submit() never completes
    panel._workflow_service._data_loader = stuck
    panel.load_workflow(_saved(_one_sample_state()))

    assert panel._workflow_loading
    assert panel.undo() is False
    assert any("loading" in m for m in messages)
    assert panel._store.commit("ignored") is False


def test_a_late_load_completion_cannot_wipe_newer_history(panel):
    panel.load_workflow(_saved(build_rich_state()))
    _edit(panel)
    panel._finish_workflow_load(clean=True)  # e.g. a stray duplicate callback
    assert panel.can_undo()
    assert panel._store.is_dirty


def test_raw_fcs_injection_starts_unsaved(panel, monkeypatch):
    loader = MagicMock()

    def _load_samples_async(paths, state, on_done, on_error_cb):
        on_done({"x": object()})

    loader.load_samples_async.side_effect = _load_samples_async
    monkeypatch.setattr(panel._factory, "get", lambda name: loader)
    panel.load_workflow({}, filename="/tmp/raw.fcs")
    assert not panel._workflow_loading
    assert panel._store.is_dirty
    assert not panel.can_undo()


# ── Reload task errors (WorkflowService) ──────────────────────────────


class _Scheduler(QObject):
    task_finished = pyqtSignal(str, dict)
    task_error = pyqtSignal(str, str)

    def submit(self, _task, _state):
        return MagicMock(task_id="reload-1")


def test_a_reload_task_that_errors_still_completes_the_load():
    state = FlowState()
    loader = FakeLoader()
    loader._scheduler = _Scheduler()
    service = WorkflowService(state, loader, AttachmentManager(MagicMock()))

    completed = []
    assert service.load_workflow(_saved(build_rich_state()), on_complete=completed.append)
    assert completed == []  # still waiting on the task

    loader._scheduler.task_error.emit("some-other-task", "boom")
    assert completed == []
    loader._scheduler.task_error.emit("reload-1", "boom")
    assert len(completed) == 1
    assert sorted(completed[0]["failed"]) == ["Sample 0", "Sample 1", "Sample 2"]


# ── set_state ─────────────────────────────────────────────────────────


def test_set_state_adopts_contents_without_replacing_the_state(panel):
    state = panel.state
    other = build_rich_state()
    panel.set_state(other)
    assert panel.state is state
    assert list(state.data.experiment.samples) == ["s0", "s1", "s2"]
    assert state.data.experiment.samples["s0"] is not other.data.experiment.samples["s0"]
    assert panel._store.is_dirty
