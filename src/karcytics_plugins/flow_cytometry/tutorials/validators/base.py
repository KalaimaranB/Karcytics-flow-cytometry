"""Validator base classes and the checks every course uses (tabs, saving, popups)."""

from __future__ import annotations

import time
from abc import abstractmethod
from collections.abc import Callable
from dataclasses import fields
from typing import Any

import shiboken6
from karcytics_sdk.plugin import CentralEventBus, get_logger
from karcytics_sdk.plugin.tutorial_models import IValidator
from PySide6.QtWidgets import QApplication

from ...analysis import events
from ...analysis.state import FlowState
from ...main_tabs import MainTab
from ...ui.academy_context import AcademyContext

logger = get_logger(__name__, "flow_cytometry")


class LoggingValidator(IValidator):
    """Base validator that provides stateful logging to avoid spam during polling."""

    def log_failure(self, reason: str) -> bool:
        last_reason = getattr(self, "_last_log_reason", "")
        if reason != last_reason:
            logger.info("%s: %s", self.__class__.__name__, reason)
            self._last_log_reason = reason
        return False


class FlowValidator(LoggingValidator):
    """Adapter that strongly types the IValidator interface to FlowState."""

    def validate(self, app_state: Any) -> bool:
        return self._guarded(app_state, self.validate_flow)

    def _guarded(self, app_state: Any, run: Callable[[FlowState], bool]) -> bool:
        if not isinstance(app_state, FlowState):
            return self.log_failure(f"Expected FlowState, got {type(app_state).__name__}")
        try:
            return run(app_state)
        except Exception as exc:
            # Logged here: otherwise a step stalls with no trace of why.
            logger.exception(
                "%s: validate_flow raised an exception — treating as failed.",
                self.__class__.__name__,
            )
            return self.log_failure(f"Validator raised {type(exc).__name__}: {exc}")

    @abstractmethod
    def validate_flow(self, app_state: FlowState) -> bool:
        pass


def context_field(name: str) -> str:
    """`name` if it is an `AcademyContext` field; a course with a typo fails when built."""
    if name not in {f.name for f in fields(AcademyContext)}:
        raise ValueError(f"AcademyContext has no field {name!r}")
    return name


class FlowUIValidator(FlowValidator):
    """Also reads widgets, via the `AcademyContext` the SDK passes `check()` (none: fails)."""

    def check(self, app_state: Any, context: Any = None) -> bool:
        ui = context if isinstance(context, AcademyContext) else AcademyContext()
        return self._guarded(app_state, lambda state: self.validate_ui(state, ui))

    def validate_flow(self, app_state: FlowState) -> bool:
        return self.validate_ui(app_state, AcademyContext())

    @abstractmethod
    def validate_ui(self, _app_state: FlowState, ui: AcademyContext) -> bool:
        pass


class TabActiveValidator(FlowValidator):
    """Verifies that the user has navigated to a specific main tab."""

    def __init__(self, expected: MainTab) -> None:
        self.expected = expected

    def validate_flow(self, app_state: FlowState) -> bool:
        if app_state.view.active_main_tab_index != self.expected:
            return self.log_failure(
                f"Expected the {self.expected.label} tab, but tab "
                f"{app_state.view.active_main_tab_index} is open."
            )
        return True


class PropertiesViewValidator(FlowValidator):
    """Verifies which view the properties panel's top pane is showing.

    ``expected_view`` is one of the ``PROPERTIES_VIEW_*`` constants.
    """

    def __init__(self, expected_view: str) -> None:
        self.expected = expected_view

    def validate_flow(self, app_state: FlowState) -> bool:
        current = app_state.view.properties_view
        if current != self.expected:
            return self.log_failure(
                f"Properties panel is showing '{current}', expected '{self.expected}'."
            )
        return True


class WorkflowSavedValidator(FlowValidator):
    """Verifies that the user has saved a workflow since this step became current."""

    def __init__(self):
        self._saved_payload = None
        self._saved_at: float | None = None
        # Every course's instance hears every save from plugin load on, so a
        # later course would pass on an earlier course's save. Armed at the
        # first poll (its step is current), only saves from then on count;
        # prerequisite unlocking below still counts any past save.
        self._armed_at: float | None = None

        CentralEventBus.subscribe(events.WORKFLOW_SAVED, self._on_workflow_saved)

    def _on_workflow_saved(self, payload: dict) -> None:
        self._saved_payload = payload
        self._saved_at = time.monotonic()

    def validate_flow(self, _app_state: FlowState) -> bool:
        if self._armed_at is None:
            self._armed_at = time.monotonic()

        if self._saved_payload and self._saved_at is not None and self._saved_at >= self._armed_at:
            return True

        return self.log_failure("Waiting for workflow to be saved...")


class PopupClosedValidator(FlowValidator):
    """Verifies an ephemeral top-level popup (found by objectName) is no longer visible.

    Lets a step auto-advance once the user dismisses a popup (e.g. the
    All-Samples quick stats view) instead of requiring a manual Next click.
    """

    def __init__(self, popup_object_name: str) -> None:
        self._name = popup_object_name

    def validate_flow(self, _app_state: FlowState) -> bool:
        for w in QApplication.topLevelWidgets():
            if w.objectName() != self._name:
                continue
            try:
                if not shiboken6.isValid(w):
                    return True
                if w.isVisible():
                    return self.log_failure("Popup is still visible.")
            except Exception:
                return True
        return True


class PreferencesPageValidator(FlowValidator):
    """Verifies the SDK Preferences dialog is open — and, if `page_title` is
    given, showing that page (e.g. "Workspace").

    The dialog is a separate top-level window (parented to the main window,
    not the panel), so it's found via `QApplication.topLevelWidgets()` by
    the SDK's stable object name rather than through app_state.
    """

    def __init__(self, page_title: str | None = None) -> None:
        self._page_title = page_title

    def validate_flow(self, _app_state: FlowState) -> bool:
        for w in QApplication.topLevelWidgets():
            if w.objectName() != "PreferencesDialog" or not w.isVisible():
                continue
            if self._page_title is None:
                return True
            current = w.current_page_title() if hasattr(w, "current_page_title") else ""
            if current == self._page_title:
                return True
            return self.log_failure(
                f"Preferences is on '{current}', waiting for '{self._page_title}'."
            )
        return self.log_failure("Preferences dialog is not open.")


class AllOf(FlowUIValidator):
    """Passes only when every wrapped validator passes (one step, several settings)."""

    def __init__(self, *validators: FlowValidator) -> None:
        self._validators = validators

    def validate_ui(self, app_state: FlowState, ui: AcademyContext) -> bool:
        return all(v.check(app_state, ui) for v in self._validators)
