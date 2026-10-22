"""Checks on derived parameters: the ratio exists and each tab uses it."""

from __future__ import annotations

from typing import Any

from karcytics_sdk.plugin.tutorial_models import ValidationFailure

from ...analysis.state import FlowState
from ...ui.academy_context import AcademyContext
from .base import FlowUIValidator, FlowValidator


def _is_ratio_formula(formula: str, numerator: str, denominator: str) -> bool:
    """True for exactly ``[numerator] / [denominator]`` (whitespace ignored)."""
    return "".join(formula.split()) == f"[{numerator}]/[{denominator}]"


def _ratio_param_ids(app_state: FlowState, numerator: str, denominator: str) -> set[str]:
    return {
        d.param_id
        for d in app_state.data.experiment.derived_parameters
        if _is_ratio_formula(d.formula, numerator, denominator)
    }


class DerivedRatioExistsValidator(FlowValidator):
    """A derived parameter computing ``numerator ÷ denominator`` exists.

    Matches on the saved (canonical, channel-name) formula, so it doesn't
    care what the learner named it or whether they typed marker names.
    """

    def __init__(self, numerator: str, denominator: str) -> None:
        self._num = numerator
        self._den = denominator

    def validate_flow(self, app_state: FlowState) -> bool:
        if not _ratio_param_ids(app_state, self._num, self._den):
            return self.log_failure(f"No derived parameter [{self._num}] / [{self._den}] yet.")
        return True

    def describe_failure(self, app_state: Any) -> ValidationFailure | None:
        if not isinstance(app_state, FlowState):
            return None
        if _ratio_param_ids(app_state, self._den, self._num):
            return ValidationFailure(
                reason=(
                    "That one is upside down — it divides the reference by the "
                    "marker. Edit it and swap A and B, or build a new one with "
                    f"A = {self._num} and B = {self._den}."
                )
            )
        return None


class DerivedEditorClosedValidator(FlowUIValidator):
    """The Derived Parameters dialog is not currently open."""

    def validate_ui(self, _app_state: FlowState, ui: AcademyContext) -> bool:
        editor = ui.derived_editor
        if editor is not None and editor.is_open:
            return self.log_failure("Derived Parameters dialog is still open.")
        return True


class ActiveGraphDerivedAxisValidator(FlowUIValidator):
    """The active graph's X axis shows the ``numerator ÷ denominator`` parameter."""

    def __init__(self, numerator: str, denominator: str) -> None:
        self._num = numerator
        self._den = denominator

    def validate_ui(self, app_state: FlowState, ui: AcademyContext) -> bool:
        graph_manager = ui.graph_manager
        graph = graph_manager.get_active_graph() if graph_manager else None
        if graph is None:
            return self.log_failure("No active graph.")
        x_param = graph.axis_panel.get_current_x()
        if x_param not in _ratio_param_ids(app_state, self._num, self._den):
            return self.log_failure(f"Active X axis is '{x_param}', not the derived ratio.")
        return True


class StatsDerivedChannelValidator(FlowUIValidator):
    """The Statistics ★ channel picker is set to the ``numerator ÷ denominator`` ratio."""

    def __init__(self, numerator: str, denominator: str) -> None:
        self._num = numerator
        self._den = denominator

    def validate_ui(self, app_state: FlowState, ui: AcademyContext) -> bool:
        explorer = ui.statistics_explorer
        if explorer is None:
            return self.log_failure("Statistics channel picker missing.")
        channel = explorer.academy_snapshot().channel
        if channel not in _ratio_param_ids(app_state, self._num, self._den):
            return self.log_failure(f"Statistics channel is '{channel}', not the ratio.")
        return True


class ComparisonsDerivedChannelValidator(FlowUIValidator):
    """The Comparisons Channels list has exactly the ``numerator ÷ denominator`` ratio checked."""

    def __init__(self, numerator: str, denominator: str) -> None:
        self._num = numerator
        self._den = denominator

    def validate_ui(self, app_state: FlowState, ui: AcademyContext) -> bool:
        viewer = ui.comparisons_viewer
        if viewer is None:
            return self.log_failure("Comparisons viewer missing.")
        checked = list(viewer.academy_snapshot().checked_channels)
        if len(checked) != 1 or checked[0] not in _ratio_param_ids(app_state, self._num, self._den):
            return self.log_failure(f"Comparisons channels are {checked}, not just the ratio.")
        return True
