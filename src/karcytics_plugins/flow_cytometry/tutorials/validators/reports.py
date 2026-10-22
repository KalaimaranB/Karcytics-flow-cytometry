"""Checks on the Statistics and Comparisons tabs and on exports."""

from __future__ import annotations

from typing import Any

from ...analysis.state import FlowState
from ...ui.academy_context import AcademyContext
from ...ui.widgets.comparisons.plot_spec import PlotType
from .base import FlowUIValidator, context_field


class StatsChartTypeValidator(FlowUIValidator):
    """Verifies the Statistics tab's chart-type combo is set to a specific value (e.g. 'Heatmap')."""

    def __init__(self, expected_type: str) -> None:
        self._expected = expected_type.lower()

    def validate_ui(self, _app_state: FlowState, ui: AcademyContext) -> bool:
        explorer = ui.statistics_explorer
        if explorer is None:
            return self.log_failure("Statistics explorer missing.")
        current = explorer.academy_snapshot().chart_type_label.lower()
        if self._expected not in current:
            return self.log_failure(f"Chart type is '{current}', expected '{self._expected}'.")
        return True


class ComparisonPlotTypeValidator(FlowUIValidator):
    """Verifies the Comparisons tab's plot-type combo is set to a specific chart."""

    def __init__(self, expected_type: PlotType) -> None:
        self._expected = expected_type

    def validate_ui(self, _app_state: FlowState, ui: AcademyContext) -> bool:
        viewer = ui.comparisons_viewer
        if not viewer:
            return self.log_failure("Comparisons viewer missing.")
        current = viewer.current_plot_type()
        if current != self._expected:
            return self.log_failure(f"Plot type is '{current}', expected '{self._expected}'.")
        return True


class HistogramOverlayLayoutValidator(FlowUIValidator):
    """Verifies Histogram Overlay's Layout setting (its own options panel,
    not the plot-type combo) is set to a specific mode — the default is
    Ridge ("waterfall"); this lets a step require the user to actually
    switch it to Overlay rather than just reading about the difference.
    """

    def __init__(self, expected_layout: str) -> None:
        self._expected = expected_layout.lower()

    def validate_ui(self, _app_state: FlowState, ui: AcademyContext) -> bool:
        viewer = ui.comparisons_viewer
        if viewer is None:
            return self.log_failure("Comparisons viewer missing.")
        current = viewer.academy_snapshot().histogram_layout.lower()
        if current != self._expected:
            return self.log_failure(f"Layout is '{current}', expected '{self._expected}'.")
        return True


class PopulationsCheckedValidator(FlowUIValidator):
    """Verifies the Statistics/Comparisons tab's population selector has at
    least the given labels checked (substring/case-insensitive).

    The population picker defaults every population to checked the first
    time it's seen (see `PopulationSelectionPopup.refresh()`), so left
    unconstrained a user landing on this step already has EVERY gate + the
    UMAP exports checked at once — cramped, unreadable tables and charts.
    `max_checked`, when given, also fails until the user has pruned down to
    that many (or fewer) checked populations, on top of the required ones
    being present.
    """

    def __init__(
        self,
        explorer_attr: str,
        *required_labels: str,
        max_checked: int | None = None,
        require_popup_closed: bool = False,
    ) -> None:
        self._explorer_attr = context_field(explorer_attr)
        self._required = [lbl.lower() for lbl in required_labels]
        self._max_checked = max_checked
        self._require_popup_closed = require_popup_closed

    def validate_ui(self, _app_state: FlowState, ui: AcademyContext) -> bool:
        explorer = getattr(ui, self._explorer_attr)
        if explorer is None:
            return self.log_failure(f"{self._explorer_attr} missing.")
        picks = explorer.academy_snapshot().populations
        checked = picks.checked
        checked_labels = [label.lower() for (_sample_id, _node_id, label) in checked]
        missing = [
            req for req in self._required if not any(req in label for label in checked_labels)
        ]
        if missing:
            return self.log_failure(f"Missing required checked populations: {missing}")
        if self._max_checked is not None and len(checked) > self._max_checked:
            return self.log_failure(
                f"{len(checked)} populations checked, expected at most {self._max_checked} "
                "— uncheck the extras."
            )
        if self._require_popup_closed and picks.picker_open:
            return self.log_failure("Population picker popup is still open.")
        return True


class StatsCheckedValidator(FlowUIValidator):
    """Verifies the Statistics tab has at least the given StatType values
    checked, and — if `max_checked` is given — no more than that many
    overall (3 stats default to pre-checked, so simply adding more on top
    without unchecking any leaves the table/chart cramped).
    """

    def __init__(self, *required: Any, max_checked: int | None = None) -> None:
        self._required = required
        self._max_checked = max_checked

    def validate_ui(self, _app_state: FlowState, ui: AcademyContext) -> bool:
        explorer = ui.statistics_explorer
        if explorer is None:
            return self.log_failure("Statistics explorer missing.")
        checked = explorer.academy_snapshot().checked_stats
        missing = [stat for stat in self._required if stat not in checked]
        if missing:
            return self.log_failure(f"Missing required checked stats: {missing}")
        if self._max_checked is not None:
            total_checked = len(checked)
            if total_checked > self._max_checked:
                return self.log_failure(
                    f"{total_checked} stats checked, expected at most {self._max_checked} "
                    "— uncheck the extras."
                )
        return True


class StatsResultsReadyValidator(FlowUIValidator):
    """Verifies the Statistics tab's Compute Statistics run has actually
    finished — the table/chart stay on their placeholder (no numbers at
    all) until the user clicks Compute, which kicks off an async worker
    rather than updating live off the checkboxes.
    """

    def validate_ui(self, _app_state: FlowState, ui: AcademyContext) -> bool:
        explorer = ui.statistics_explorer
        if explorer is None or not explorer.academy_snapshot().has_results:
            return self.log_failure("Statistics haven't been computed yet.")
        return True


class ComparisonsPlotGeneratedValidator(FlowUIValidator):
    """Verifies the Comparisons tab has rendered a plot of the given type.

    Reads the last generated plot type, not the dropdown, so changing the
    dropdown without regenerating keeps failing.
    """

    def __init__(self, expected_type: PlotType) -> None:
        self._expected = expected_type

    def validate_ui(self, _app_state: FlowState, ui: AcademyContext) -> bool:
        viewer = ui.comparisons_viewer
        generated = viewer.academy_snapshot().last_generated if viewer is not None else None
        if generated != self._expected:
            return self.log_failure(
                f"Last generated plot was '{generated}', expected '{self._expected}'."
            )
        return True


class ExportDoneValidator(FlowUIValidator):
    """An export button on a tab has actually written its file (or clipboard).

    Reads the tab's ``completed_exports`` set, which each export handler
    adds to only on success — a cancelled save dialog doesn't count.
    """

    def __init__(self, view_attr: str, kind: str) -> None:
        self._view_attr = context_field(view_attr)
        self._kind = kind

    def validate_ui(self, _app_state: FlowState, ui: AcademyContext) -> bool:
        tab = getattr(ui, self._view_attr)
        if self._kind not in getattr(tab, "completed_exports", set()):
            return self.log_failure(f"No '{self._kind}' export from {self._view_attr} yet.")
        return True
