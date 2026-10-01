"""Unsaved-changes prompts: closing the window and loading over edits."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest
from PyQt6.QtWidgets import QApplication, QMessageBox

from karcytics_plugins.flow_cytometry.analysis.gating import RectangleGate
from tests.fixtures.workspace import build_rich_state, set_real_view_defaults

Btn = QMessageBox.StandardButton


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


class Answers:
    def __init__(self) -> None:
        self.queue: list[QMessageBox.StandardButton] = []
        self.asked: list[str] = []

    def __call__(self, text, _buttons):
        self.asked.append(text)
        return self.queue.pop(0)


@pytest.fixture
def panel(qapp, qtbot, monkeypatch):
    from karcytics_plugins.flow_cytometry.ui.main_panel import FlowCytometryPanel

    p = FlowCytometryPanel(plugin_id="flow_prompt_test")
    qtbot.addWidget(p)
    p.logger = MagicMock()
    rich = build_rich_state()
    p.state.data.experiment = rich.data.experiment
    set_real_view_defaults(p.state)
    p._store.reset()
    monkeypatch.setattr(p, "_refresh_all", lambda: None)
    p.answers = Answers()
    monkeypatch.setattr(p, "_ask_unsaved_changes", p.answers)
    p.saves = []
    p.closed = []
    monkeypatch.setattr(p, "_close_window_when_idle", lambda: p.closed.append(True))
    return p


def _dirty(panel):
    panel.state.data.experiment.samples["s0"].gate_tree.add_child(
        RectangleGate("FSC-A", "SSC-A", x_min=0.0, x_max=1.0, y_min=0.0, y_max=1.0), name="x"
    )
    panel._store.commit("Add Gate")
    assert panel._store.is_dirty


def _fake_save(panel, *, starts: bool):
    def _save():
        panel.saves.append(True)
        if starts:
            panel._loading = True  # what WorkspaceIOHandler does when a save starts

    return _save


# ── Closing ───────────────────────────────────────────────────────────


def test_clean_workspace_closes_without_asking(panel):
    assert panel.confirm_close() is True
    assert panel.answers.asked == []


def test_cancel_keeps_the_window_open(panel):
    _dirty(panel)
    panel.answers.queue = [Btn.Cancel]
    assert panel.confirm_close() is False
    assert panel._store.is_dirty


def test_discard_closes(panel):
    _dirty(panel)
    panel.answers.queue = [Btn.Discard]
    assert panel.confirm_close() is True


def test_save_closes_only_once_the_save_succeeds(panel, monkeypatch):
    _dirty(panel)
    panel._current_workflow_filename = "wf.json"
    monkeypatch.setattr(panel, "_handle_update", _fake_save(panel, starts=True))
    panel.answers.queue = [Btn.Save]

    token = panel._store.begin_save()
    assert panel.confirm_close() is False
    assert panel.saves == [True]
    assert panel.confirm_close() is False  # still writing: no second prompt
    assert len(panel.answers.asked) == 1

    panel._loading = False
    panel._finish_save(token)
    assert panel.closed == [True]
    assert not panel._store.is_dirty


def test_unnamed_workspace_saves_through_the_save_dialog(panel, monkeypatch):
    _dirty(panel)
    monkeypatch.setattr(panel, "_handle_save", _fake_save(panel, starts=True))
    panel.answers.queue = [Btn.Save]
    assert panel.confirm_close() is False
    assert panel.saves == [True]


def test_cancelling_the_save_dialog_does_not_close_later(panel, monkeypatch):
    _dirty(panel)
    monkeypatch.setattr(panel, "_handle_save", _fake_save(panel, starts=False))
    panel.answers.queue = [Btn.Save, Btn.Cancel]
    assert panel.confirm_close() is False
    assert panel._close_after_save is False
    assert panel.confirm_close() is False  # asks again
    assert len(panel.answers.asked) == 2


def test_a_failed_save_asks_again_on_the_next_close(panel, monkeypatch):
    _dirty(panel)
    monkeypatch.setattr(panel, "_handle_save", _fake_save(panel, starts=True))
    panel.answers.queue = [Btn.Save, Btn.Discard]
    assert panel.confirm_close() is False
    panel._loading = False  # the save errored out
    assert panel.confirm_close() is True
    assert len(panel.answers.asked) == 2
    assert panel.closed == []


# ── Loading over unsaved edits ────────────────────────────────────────


def test_cancelling_a_load_over_unsaved_edits_keeps_everything(panel, monkeypatch):
    _dirty(panel)
    service_load = MagicMock()
    monkeypatch.setattr(panel._workflow_service, "load_workflow", service_load)
    panel.answers.queue = [Btn.Cancel]

    panel.load_workflow({"experiment": {}})

    service_load.assert_not_called()
    assert not panel._workflow_loading
    assert panel._store.is_dirty
    assert "s0" in panel.state.data.experiment.samples
    assert panel.can_undo()


def test_discard_proceeds_with_the_load(panel, monkeypatch):
    _dirty(panel)
    service_load = MagicMock(return_value=True)
    monkeypatch.setattr(panel._workflow_service, "load_workflow", service_load)
    panel.answers.queue = [Btn.Discard]
    panel.load_workflow({"experiment": {}})
    service_load.assert_called_once()


def test_loading_over_a_clean_workspace_does_not_ask(panel, monkeypatch):
    monkeypatch.setattr(panel._workflow_service, "load_workflow", MagicMock(return_value=True))
    panel.load_workflow({"experiment": {}})
    assert panel.answers.asked == []


# ── Autosave ──────────────────────────────────────────────────────────


def test_autosave_is_told_whether_there_is_anything_to_save(qapp, qtbot, monkeypatch):
    from tests.conftest import DummyPluginBase

    captured = {}

    def _setup(self, has_saved_once, save, **kwargs):
        captured.update(kwargs)
        return MagicMock()

    monkeypatch.setattr(DummyPluginBase, "setup_workflow_autosave", _setup)
    from karcytics_plugins.flow_cytometry.ui.main_panel import FlowCytometryPanel

    panel = FlowCytometryPanel(plugin_id="flow_autosave_test")
    qtbot.addWidget(panel)
    has_unsaved = captured["has_unsaved_changes"]
    assert has_unsaved() is False
    panel._store.mark_unsaved_change()
    assert has_unsaved() is True
