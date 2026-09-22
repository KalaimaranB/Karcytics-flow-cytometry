"""Unit tests for WorkspaceIOHandler.handle_autosave and its shared plumbing
with handle_update — the quiet save path the SDK's WorkflowAutosaveController
calls (see FlowCytometryPanel._setup_services / PluginBase.setup_workflow_autosave).

Unlike handle_save/handle_update, handle_autosave must never show a blocking
QMessageBox — a periodic background save shouldn't interrupt the user. It
reports success/failure through a plain callback instead, which the SDK
controller turns into a toast.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from karcytics_plugins.flow_cytometry.ui.services.workspace_io_handler import WorkspaceIOHandler


class _FakeSignal:
    """Stand-in for AnalysisWorker's pyqtSignal-based .finished/.error.

    Real code connects a callback to whichever signal actually fires, after
    task_scheduler.submit() has already returned — so this defers "emission"
    until .connect() is called, immediately invoking the slot only if this
    is the outcome the fake worker was built to represent.
    """

    def __init__(self, worker: _FakeWorker, name: str) -> None:
        self._worker = worker
        self._name = name

    def connect(self, slot) -> None:
        if self._worker.outcome == self._name:
            slot(self._worker.value)


class _FakeWorker:
    def __init__(self, outcome: str, value) -> None:
        self.outcome = outcome
        self.value = value
        self.finished = _FakeSignal(self, "finished")
        self.error = _FakeSignal(self, "error")


def _fake_submit(task, _state):
    """Runs `task.run()` synchronously — mirrors real dispatch closely
    enough (same success/exception -> finished/error split) without needing
    a real QThreadPool in these tests.
    """
    try:
        return _FakeWorker("finished", task.run())
    except Exception as exc:  # noqa: BLE001
        return _FakeWorker("error", str(exc))


@pytest.fixture
def fake_task_scheduler():
    """Both `handle_autosave`/`handle_update`/`_run_save_to_pm` import
    `task_scheduler` from `karcytics_sdk.plugin.runtime_services`, which
    tests/conftest.py already replaces with a MagicMock for the whole
    session — configure its `.submit` to actually run tasks synchronously.
    """
    module = sys.modules["karcytics_sdk.plugin.runtime_services"]
    module.task_scheduler.submit = MagicMock(side_effect=_fake_submit)
    yield module.task_scheduler


@pytest.fixture
def parent_widget():
    widget = MagicMock()
    widget._current_workflow_filename = "wf_123.json"
    widget._current_workflow_metadata = {"name": "Test Workflow"}
    widget.window.return_value.project_manager = MagicMock()
    widget.window.return_value.current_module_id = "flow_cytometry"
    return widget


@pytest.fixture
def handler(parent_widget):
    return WorkspaceIOHandler(workflow_service=MagicMock(), parent_widget=parent_widget)


class TestHandleAutosave:
    def test_never_shows_a_blocking_dialog_on_success(
        self, handler, parent_widget, fake_task_scheduler
    ):  # noqa: ARG002
        with patch(
            "karcytics_plugins.flow_cytometry.ui.services.workspace_save_service.WorkspaceSaveService.save_to_pm",
            return_value="wf_123.json",
        ):
            with (
                patch("karcytics_sdk.plugin.dialogs.show_info") as mock_info,
                patch("karcytics_sdk.plugin.dialogs.show_error") as mock_error,
            ):
                results = []
                handler.handle_autosave(results.append)

        mock_info.assert_not_called()
        mock_error.assert_not_called()
        assert results == [True]

    def test_on_success_clears_dirty_and_publishes_saved_event(
        self, handler, parent_widget, fake_task_scheduler
    ):  # noqa: ARG002
        with patch(
            "karcytics_plugins.flow_cytometry.ui.services.workspace_save_service.WorkspaceSaveService.save_to_pm",
            return_value="wf_123.json",
        ):
            with (
                patch("karcytics_sdk.plugin.dialogs.show_info"),
                patch("karcytics_sdk.plugin.dialogs.show_error"),
            ):
                handler.handle_autosave(lambda success: None)

        parent_widget.set_dirty.assert_called_once_with(False)

    def test_never_shows_a_blocking_dialog_on_failure(
        self, handler, parent_widget, fake_task_scheduler
    ):  # noqa: ARG002
        with patch(
            "karcytics_plugins.flow_cytometry.ui.services.workspace_save_service.WorkspaceSaveService.save_to_pm",
            side_effect=RuntimeError("disk full"),
        ):
            with (
                patch("karcytics_sdk.plugin.dialogs.show_info") as mock_info,
                patch("karcytics_sdk.plugin.dialogs.show_error") as mock_error,
            ):
                results = []
                handler.handle_autosave(results.append)

        mock_info.assert_not_called()
        mock_error.assert_not_called()
        assert results == [False]
        parent_widget.set_dirty.assert_not_called()

    def test_reports_failure_without_saving_when_nothing_saved_yet(
        self, handler, parent_widget, fake_task_scheduler
    ):  # noqa: ARG002
        parent_widget._current_workflow_filename = None
        results = []

        handler.handle_autosave(results.append)

        assert results == [False]
        fake_task_scheduler.submit.assert_not_called()

    def test_reports_failure_without_saving_when_no_project_manager(
        self, handler, parent_widget, fake_task_scheduler
    ):  # noqa: ARG002
        parent_widget.window.return_value.project_manager = None
        results = []

        handler.handle_autosave(results.append)

        assert results == [False]
        fake_task_scheduler.submit.assert_not_called()


class TestHandleUpdateStillShowsDialogs:
    """handle_update() shares _run_save_to_pm with handle_autosave() now —
    confirm the refactor didn't silently drop its user-facing feedback.
    """

    def test_shows_the_updated_info_dialog_on_success(
        self, handler, parent_widget, fake_task_scheduler
    ):  # noqa: ARG002
        with patch(
            "karcytics_plugins.flow_cytometry.ui.services.workspace_save_service.WorkspaceSaveService.save_to_pm",
            return_value="wf_123.json",
        ):
            with patch("karcytics_sdk.plugin.dialogs.show_info") as mock_info:
                handler.handle_update()

        mock_info.assert_called_once()
        assert mock_info.call_args.args[1] == "Workflow Updated"
