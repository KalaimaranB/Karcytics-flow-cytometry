"""Academy workflows: start, pause, resume, close, finish a course, leave.

Runs the real panel and the real flow courses against a test-local
AcademyManager (not the process-wide one, which persists under ~/.karcytics);
saving is captured instead of going to a project.
"""

from __future__ import annotations

import copy
import sys
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from karcytics_sdk.plugin.academy import AcademyManager
from PySide6.QtWidgets import QApplication

from karcytics_plugins.flow_cytometry import register_courses
from karcytics_plugins.flow_cytometry.main_tabs import MainTab
from karcytics_plugins.flow_cytometry.tutorials.courses import COURSES
from karcytics_plugins.flow_cytometry.ui import academy_workflow
from karcytics_plugins.flow_cytometry.ui.academy_workflow import (
    ACADEMY_KEY,
    BETWEEN_COURSES,
    GRADUATED,
    PAUSED,
    RUNNING,
    AcademyWorkflowController,
    course_order,
)
from tests.fixtures.workspace import build_rich_state, set_real_view_defaults

COURSE_1, COURSE_2, *_rest = course_order()
COURSE_5 = course_order()[-1]


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


class FakeBus:
    def __init__(self) -> None:
        self.subscriptions: dict[str, list[Any]] = {}

    def subscribe(self, topic: str, callback: Any) -> None:
        self.subscriptions.setdefault(topic, []).append(callback)

    def unsubscribe(self, topic: str, callback: Any) -> None:
        if callback in self.subscriptions.get(topic, []):
            self.subscriptions[topic].remove(callback)

    def emit(self, topic: str, *args: Any) -> None:
        for callback in list(self.subscriptions.get(topic, [])):
            callback(*args)


@pytest.fixture
def panel(qapp, qtbot, monkeypatch, tmp_path):
    from karcytics_plugins.flow_cytometry.ui.main_panel import FlowCytometryPanel

    p = FlowCytometryPanel(plugin_id="flow_academy_test")
    qtbot.addWidget(p)
    p.logger = MagicMock()
    rich = build_rich_state()
    p.state.data.experiment = rich.data.experiment
    set_real_view_defaults(p.state)
    p._store.reset()
    monkeypatch.setattr(p, "_refresh_all", lambda: None)

    manager = AcademyManager(event_bus=FakeBus(), persistence_dir=tmp_path / "academy")
    register_courses(manager)
    p._academy.dispose()
    p._academy = AcademyWorkflowController(p, manager=manager, event_bus=manager._event_bus)
    p.manager = manager

    pm = SimpleNamespace(project_dir=tmp_path)
    monkeypatch.setattr(p, "_get_project_manager", lambda: pm)

    p.saves = []

    def _fake_save(_pm, filename, metadata, on_success, _on_error):
        p.saves.append((filename, copy.deepcopy(metadata)))
        on_success(filename or "flow_academy.json")

    monkeypatch.setattr(p._workspace_io_handler, "_run_save_to_pm", _fake_save)
    p.overlay_calls = []
    monkeypatch.setattr(
        p._academy, "_show_overlay", lambda pausable: p.overlay_calls.append(pausable)
    )
    monkeypatch.setattr(p._academy, "_hide_overlay", lambda: p.overlay_calls.append("hide"))
    monkeypatch.setattr(academy_workflow, "ask_yes_no", lambda *_a, **_k: True)
    p.closed = []
    monkeypatch.setattr(p, "_close_window_when_idle", lambda: p.closed.append(True))
    yield p
    p._academy.dispose()


def block(panel) -> dict:
    return panel._current_workflow_metadata[ACADEMY_KEY]


def start_in_academy(panel, course_id: str = COURSE_1) -> None:
    panel.start_academy_course(course_id)
    card = panel._academy._card
    if card is not None and not card.input_field.isHidden():
        card.input_field.setText("My Academy")
    card.primary_button.click()


# ── Starting ──────────────────────────────────────────────────────────


def test_starting_in_an_ordinary_workflow_asks_first_and_locks_meanwhile(panel):
    panel.start_academy_course(COURSE_1)

    card = panel._academy._card
    assert card.is_locked
    assert "Academy workflow" in card.message_label.text()
    assert not card.input_field.isHidden()  # an unsaved workspace needs a name
    assert card.input_field.text() == "Flow Academy"
    assert not panel._tab_bar.isEnabled()
    assert panel.manager.active_course is None


def test_not_now_leaves_the_workflow_ordinary(panel):
    panel.start_academy_course(COURSE_1)
    panel._academy._card.secondary_button.click()

    assert not panel._academy.is_locked
    assert ACADEMY_KEY not in (getattr(panel, "_current_workflow_metadata", None) or {})
    assert panel.saves == []


def test_agreeing_converts_saves_and_starts_a_pausable_course(panel):
    start_in_academy(panel)

    assert panel.manager.active_course.id == COURSE_1
    assert panel.overlay_calls == [True]
    assert block(panel)["state"] == RUNNING
    assert panel._current_workflow_metadata["name"] == "My Academy"
    assert panel._current_workflow_filename == "flow_academy.json"
    saved_filename, saved = panel.saves[-1]
    assert saved_filename is None  # a new workflow
    assert saved[ACADEMY_KEY]["course_id"] == COURSE_1
    assert not panel._academy.is_locked


def test_each_step_keeps_the_block_current_but_the_catalog_waits_for_a_save(panel):
    start_in_academy(panel)
    panel.manager.next_step()

    assert block(panel)["step_id"] == panel.manager.current_step.id
    assert block(panel)["step_number"] == 2
    assert panel.manager.get_in_progress(COURSE_1)["step_number"] == 1  # saved at start

    panel._academy._on_workflow_saved({"filename": "flow_academy.json"})  # e.g. autosave
    attempt = panel.manager.get_in_progress(COURSE_1)
    assert attempt["workflow"] == "flow_academy.json"
    assert attempt["workflow_name"] == "My Academy"
    assert attempt["step_number"] == 2


# ── Pausing and resuming ──────────────────────────────────────────────


def test_pause_saves_the_place_and_locks(panel):
    start_in_academy(panel)
    panel.manager.next_step()
    step_id = panel.manager.current_step.id

    panel.on_academy_pause_requested()

    assert panel.manager.active_course is None
    assert panel._academy.is_locked
    assert panel._academy._card.progress_label.text().startswith("Step 2 of ")
    _filename, saved = panel.saves[-1]
    assert saved[ACADEMY_KEY]["state"] == PAUSED
    assert saved[ACADEMY_KEY]["step_id"] == step_id


def test_a_tab_saved_by_index_in_the_old_order_resumes_on_the_same_tab(panel):
    start_in_academy(panel)
    panel._tab_bar.setCurrentIndex(MainTab.GATING)
    panel.on_academy_pause_requested()
    assert block(panel)["ui"]["tab"] == "GATING"
    block(panel)["ui"]["tab"] = 4  # Statistics, before Sample Lens moved

    panel._academy._card.primary_button.click()

    assert panel._tab_bar.currentIndex() == MainTab.STATISTICS


@pytest.mark.parametrize("tab", list(MainTab))
def test_each_tab_shows_its_own_view(panel, tab):
    from karcytics_plugins.flow_cytometry.ui.builders.workspace_builder import WorkspaceBuilder
    from karcytics_plugins.flow_cytometry.ui.main_panel import _TAB_VIEWS

    if not hasattr(panel, "_graph_manager"):
        WorkspaceBuilder.build_heavy(panel)
    panel._tab_bar.setCurrentIndex(tab)
    panel._on_tab_changed(tab)  # also when the tab was already current

    view, ribbon = _TAB_VIEWS[tab]
    assert panel._tab_bar.tabText(tab) == tab.label
    assert panel._center_stack.currentWidget() is getattr(panel, view)
    assert panel._left_sidebar.isVisibleTo(panel) == (tab in (MainTab.WORKSPACE, MainTab.GATING))
    if ribbon is not None:
        assert panel._ribbon_stack.currentWidget() is getattr(panel, ribbon)


def test_resume_returns_to_the_saved_step_and_tab(panel):
    start_in_academy(panel)
    panel.manager.next_step()
    step_id = panel.manager.current_step.id
    panel._tab_bar.setCurrentIndex(1)
    panel.on_academy_pause_requested()
    panel._tab_bar.setCurrentIndex(0)

    panel._academy._card.primary_button.click()

    assert panel.manager.current_step.id == step_id
    assert panel._tab_bar.currentIndex() == 1
    assert not panel._academy.is_locked
    assert panel._tab_bar.isEnabled()
    assert block(panel)["state"] == RUNNING


def test_loading_a_mid_course_workflow_opens_locked(panel):
    start_in_academy(panel)
    panel.manager.next_step()
    panel.on_academy_pause_requested()
    panel._academy._card.unlock()
    block(panel)["state"] = RUNNING  # as if the module had closed without pausing

    panel._academy.on_workflow_loaded()

    assert panel._academy.is_locked
    assert block(panel)["state"] == PAUSED


def _answer_close(panel, monkeypatch, answer):
    asked: list[str] = []

    def _ask(text, _buttons):
        asked.append(text)
        return answer

    monkeypatch.setattr(panel, "_ask_unsaved_changes", _ask)
    return asked


def test_closing_mid_course_asks_and_save_pauses_then_closes(panel, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    start_in_academy(panel)
    panel.manager.next_step()
    asked = _answer_close(panel, monkeypatch, QMessageBox.StandardButton.Save)

    assert panel.confirm_close() is False  # closes once the save is written
    assert asked and "Course 1" in asked[0]
    _filename, saved = panel.saves[-1]
    assert saved[ACADEMY_KEY]["state"] == PAUSED
    assert panel._close_after_save
    assert panel.manager.get_in_progress(COURSE_1)["step_number"] == 2


def test_closing_mid_course_without_saving_saves_nothing(panel, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    start_in_academy(panel)
    panel.manager.next_step()
    saves = len(panel.saves)
    _answer_close(panel, monkeypatch, QMessageBox.StandardButton.Discard)

    assert panel.confirm_close() is True
    assert len(panel.saves) == saves
    assert panel.manager.get_in_progress(COURSE_1)["step_number"] == 1  # the last save


def test_cancel_keeps_the_course_running(panel, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    start_in_academy(panel)
    _answer_close(panel, monkeypatch, QMessageBox.StandardButton.Cancel)

    assert panel.confirm_close() is False
    assert panel.manager.active_course.id == COURSE_1


def test_closing_a_paused_clean_workflow_just_closes(panel):
    start_in_academy(panel)
    panel.on_academy_pause_requested()
    saves = len(panel.saves)

    assert panel.confirm_close() is True
    assert len(panel.saves) == saves


# ── Finishing and leaving ─────────────────────────────────────────────


def finish(panel) -> None:
    panel.manager.complete_course()
    panel.manager.current_step = None
    panel._academy._after_completion_screen()


def test_finishing_a_course_offers_the_next_one(panel):
    start_in_academy(panel)
    finish(panel)

    assert block(panel)["state"] == BETWEEN_COURSES
    assert block(panel)["next_course_id"] == COURSE_2
    assert block(panel)["completed_courses"] == [COURSE_1]
    assert panel._academy.is_locked
    assert panel._academy._card.primary_button.text() == "▶ Start Course 2"
    assert panel.manager.get_in_progress(COURSE_1) is None
    _filename, saved = panel.saves[-1]
    assert saved[ACADEMY_KEY]["course_number"] == 2  # the course to start next
    assert saved[ACADEMY_KEY]["completed_count"] == 1
    assert saved[ACADEMY_KEY]["course_count"] == len(COURSES)


def test_starting_the_next_course_continues_in_the_same_workflow(panel):
    start_in_academy(panel)
    finish(panel)

    panel._academy._card.primary_button.click()

    assert panel.manager.active_course.id == COURSE_2
    assert panel._current_workflow_filename == "flow_academy.json"
    assert block(panel)["state"] == RUNNING
    assert block(panel)["completed_courses"] == [COURSE_1]


def test_leaving_the_academy_keeps_an_ordinary_workflow(panel):
    start_in_academy(panel)
    finish(panel)

    panel._academy._card.secondary_button.click()

    assert ACADEMY_KEY not in panel._current_workflow_metadata
    assert not panel._academy.is_locked
    _filename, saved = panel.saves[-1]
    assert ACADEMY_KEY not in saved
    assert saved["name"] == "My Academy"


def test_leaving_a_paused_course_forgets_the_attempt(panel):
    start_in_academy(panel)
    panel.manager.next_step()
    panel.on_academy_pause_requested()

    panel._academy._card.secondary_button.click()

    assert ACADEMY_KEY not in panel._current_workflow_metadata
    assert panel.manager.get_in_progress(COURSE_1) is None


def test_the_last_course_graduates_and_unlocks(panel):
    start_in_academy(panel, COURSE_5)
    finish(panel)

    assert block(panel)["state"] == GRADUATED
    assert not panel._academy.is_locked
    assert panel._academy.confirm_close() is None  # the usual unsaved-changes prompt applies


def test_without_a_project_the_course_runs_unpausable(panel, monkeypatch):
    monkeypatch.setattr(panel, "_get_project_manager", lambda: None)

    panel.start_academy_course(COURSE_1)

    assert panel.manager.active_course.id == COURSE_1
    assert panel.overlay_calls == [False]
    assert panel.saves == []


def test_resume_from_the_catalog_in_another_project_explains(panel, monkeypatch):
    shown: list[str] = []
    monkeypatch.setattr(
        academy_workflow, "show_info", lambda _p, _t, message: shown.append(message)
    )

    panel.resume_academy_course(COURSE_1, {"workflow": "x.json", "project_dir": "/elsewhere"})

    assert shown and "another project" in shown[0]


# ── Resuming where the step can show ──────────────────────────────────


def _synthetic_course(manager, course_id: str):
    """Replaces the course with one whose steps target real panel widgets
    (or, for 'popup', a widget that only exists while a popup is open).
    """
    from karcytics_sdk.plugin.tutorial_models import InfoStep

    course = manager.find_course(course_id)
    course.steps = [
        InfoStep(id="tabs", text="Tabs", target_widget_names=["MainTabBar"], next_step_id="plain"),
        InfoStep(id="plain", text="No target", next_step_id="popup"),
        InfoStep(
            id="popup",
            text="In a popup",
            target_widget_names=["NotOpenRightNow"],
            next_step_id="dialog",
        ),
        InfoStep(id="dialog", text="In a dialog", next_step_id=None, resume_step_id="tabs"),
    ]
    return course


@pytest.fixture
def shown(panel, qtbot, monkeypatch):
    original = panel.manager.find_course(COURSE_1).steps
    _synthetic_course(panel.manager, COURSE_1)
    panel.show()
    qtbot.waitExposed(panel)
    yield panel
    panel.manager.find_course(COURSE_1).steps = original


def _pause_at(panel, step_id: str) -> None:
    start_in_academy(panel)
    while panel.manager.current_step.id != step_id:
        panel.manager.next_step()
    panel.on_academy_pause_requested()


def test_a_step_whose_target_shows_resumes_in_place(shown):
    _pause_at(shown, "plain")
    shown._academy._card.primary_button.click()
    assert shown.manager.current_step.id == "plain"


def test_a_step_whose_target_is_gone_resumes_on_the_step_before(shown):
    _pause_at(shown, "popup")
    shown._academy._card.primary_button.click()

    assert shown.manager.current_step.id == "plain"
    assert shown.manager.step_history == ["tabs", "plain"]


def test_resume_step_id_wins(shown):
    _pause_at(shown, "dialog")
    shown._academy._card.primary_button.click()

    assert shown.manager.current_step.id == "tabs"
    assert shown.manager.step_history == ["tabs"]


def test_a_step_moved_to_another_course_resumes_on_the_latest_step_left(shown):
    _pause_at(shown, "popup")
    course = shown.manager.find_course(COURSE_1)
    course.steps = [s for s in course.steps if s.id != "popup"]
    shown._academy._card.primary_button.click()

    assert shown.manager.current_step.id == "plain"
    assert shown.manager.step_history == ["tabs", "plain"]


def test_a_saved_workflow_converts_without_asking_for_a_name(panel):
    panel._current_workflow_filename = "mine.json"
    panel._current_workflow_metadata = {"name": "Mine", "tags": []}

    panel.start_academy_course(COURSE_1)
    assert panel._academy._card.input_field.isHidden()
    panel._academy._card.primary_button.click()

    assert panel._current_workflow_metadata["name"] == "Mine"
    assert panel.saves[-1][0] == "mine.json"


def test_a_blank_name_falls_back_to_the_default(panel):
    panel.start_academy_course(COURSE_1)
    panel._academy._card.input_field.setText("   ")
    panel._academy._card.primary_button.click()

    assert panel._current_workflow_metadata["name"] == "Flow Academy"


def test_the_real_leave_confirmation_answers_over_the_locked_panel(panel, monkeypatch):
    """The confirmation is parented to the locked panel; it must still take clicks."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QMessageBox

    # The real SDK dialog (tests/conftest.py mocks the karcytics_sdk.plugin package).
    dialogs = sys.modules["karcytics_sdk.plugin.dialogs"]
    assert isinstance(dialogs.QMessageBox, type)
    monkeypatch.setattr(academy_workflow, "ask_yes_no", dialogs.ask_yes_no)
    start_in_academy(panel)
    panel.on_academy_pause_requested()
    seen: list[bool] = []

    def _click_yes() -> None:
        box = QApplication.activeModalWidget()
        if not isinstance(box, QMessageBox):
            box = next(
                w
                for w in QApplication.topLevelWidgets()
                if isinstance(w, QMessageBox) and w.isVisible()
            )
        seen.append(box.isEnabled())
        box.button(QMessageBox.StandardButton.Yes).click()

    QTimer.singleShot(50, _click_yes)
    panel._academy._card.secondary_button.click()

    assert seen == [True]
    assert ACADEMY_KEY not in panel._current_workflow_metadata
    assert not panel._academy.is_locked
