"""The core-intro handoff's Preferences detour: after saving a workflow the
user opens this module's Preferences, switches to the Workspace page to see
the autosave option, and closes it before heading back to the Hub.
"""

from __future__ import annotations

from PyQt6.QtWidgets import QDialog, QListWidget, QVBoxLayout

from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.tutorials.core_intro_handoff import core_intro_module
from karcytics_plugins.flow_cytometry.tutorials.validators import (
    PopupClosedValidator,
    PreferencesPageValidator,
)


class FakePreferencesDialog(QDialog):
    """Stand-in for the SDK's SDKPreferencesDialog (the SDK is mocked in this
    suite): same object name, same `current_page_title()` contract.
    """

    def __init__(self, *titles: str) -> None:
        super().__init__()
        self.setObjectName("PreferencesDialog")
        self.nav_list = QListWidget()
        self.nav_list.addItems(titles)
        self.nav_list.setCurrentRow(0)
        QVBoxLayout(self).addWidget(self.nav_list)

    def current_page_title(self) -> str:
        item = self.nav_list.currentItem()
        return item.text() if item is not None else ""


def _steps_by_id():
    return {step.id: step for step in core_intro_module.steps}


def test_save_step_leads_through_preferences_before_returning_home():
    steps = _steps_by_id()
    chain = []
    step = steps["handoff_save_action"]
    while step.id != "handoff_return_home":
        next_id = getattr(step, "on_success_step_id", None) or step.next_step_id
        step = steps[next_id]
        chain.append(step.id)

    assert chain == [
        "handoff_prefs_open",
        "handoff_prefs_workspace",
        "handoff_prefs_autosave",
        "handoff_return_home",
    ]
    assert steps["handoff_prefs_workspace"].target_widget_names == ["PreferencesNavList"]
    assert steps["handoff_prefs_autosave"].target_widget_names == ["AutosaveWorkflowsCheckbox"]


def test_preferences_validators_track_the_dialog(qtbot):
    state = FlowState()
    opened = PreferencesPageValidator()
    on_workspace = PreferencesPageValidator("Workspace")
    closed = PopupClosedValidator("PreferencesDialog")

    dialog = FakePreferencesDialog("Theme", "Workspace")
    qtbot.addWidget(dialog)
    assert not opened.validate(state)

    dialog.show()
    try:
        assert opened.validate(state)
        assert not on_workspace.validate(state)
        assert not closed.validate(state)

        dialog.nav_list.setCurrentRow(1)
        assert on_workspace.validate(state)
    finally:
        dialog.close()

    assert closed.validate(state)
    assert not opened.validate(state)
