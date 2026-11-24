"""Checks on the Compensation tab: method, pages, fit gate, editor, preview, matrices."""

from __future__ import annotations

from abc import abstractmethod
from typing import Any

from ...analysis.compensation import CELL_EDITED, extract_spill_from_fcs, same_matrix
from ...analysis.state import FlowState
from ...ui.academy_context import AcademyContext
from ...ui.widgets.method_illustration import STEP_REMOVED
from .base import FlowUIValidator, FlowValidator


class _CompensationTabValidator(FlowUIValidator):
    """A check on what the Compensation tab is showing."""

    def validate_ui(self, app_state: FlowState, ui: AcademyContext) -> bool:
        view = ui.compensation_view
        if view is None:
            return self.log_failure("The Compensation tab isn't built yet.")
        problem = self.problem(view, app_state)
        return self.log_failure(problem) if problem else True

    @abstractmethod
    def problem(self, view: Any, app_state: FlowState) -> str | None:
        """Why the check fails, or None if it passes."""


class CompensationMethodValidator(_CompensationTabValidator):
    """The Method dropdown is on the method with this key (e.g. "fmo")."""

    def __init__(self, method_key: str) -> None:
        self.expected = method_key

    def problem(self, view: Any, _app_state: FlowState) -> str | None:
        if view.method_key != self.expected:
            return f"Method is '{view.method_key}', expected '{self.expected}'."
        return None


class CompensationPageValidator(_CompensationTabValidator):
    """The tab is on this page: "setup", "matrix" or "matrices"."""

    def __init__(self, page: str) -> None:
        self.expected = page

    def problem(self, view: Any, _app_state: FlowState) -> str | None:
        if view.page != self.expected:
            return f"Showing the '{view.page}' page, expected '{self.expected}'."
        return None


class CompensationFitGateValidator(_CompensationTabValidator):
    """The selected method is set to fit on this population."""

    def __init__(self, gate: str) -> None:
        self.expected = gate

    def problem(self, view: Any, _app_state: FlowState) -> str | None:
        if (view.fit_gate or "").casefold() != self.expected.casefold():
            return f"Fit on is '{view.fit_gate}', expected '{self.expected}'."
        return None


class IllustrationPlayedValidator(_CompensationTabValidator):
    """The step-by-step picture has been taken to its last step."""

    def problem(self, view: Any, _app_state: FlowState) -> str | None:
        if view.illustration_step != STEP_REMOVED:
            return f"The picture is on step {view.illustration_step}, not the last one."
        return None


class EditorMatrixValidator(_CompensationTabValidator):
    """The matrix in the editor came from this method and, optionally, has
    ``dye`` → ``detector`` set to ``value`` by hand.
    """

    def __init__(
        self,
        source: str,
        dye: str | None = None,
        detector: str | None = None,
        value: float | None = None,
        tolerance: float = 0.02,
    ) -> None:
        self.source = source
        self.cell = (dye, detector) if dye and detector else None
        self.value = value
        self.tolerance = tolerance

    def problem(self, view: Any, _app_state: FlowState) -> str | None:
        matrix = view.editor.matrix
        if matrix is None:
            return "No matrix in the editor."
        if matrix.source != self.source:
            return f"The editor's matrix came from '{matrix.source}', expected '{self.source}'."
        return self._cell_problem(matrix, CELL_EDITED) if self.cell else None

    def _cell_problem(self, matrix: Any, edited: int) -> str | None:
        assert self.cell is not None
        dye, detector = self.cell
        if dye not in matrix.channel_names or detector not in matrix.channel_names:
            return f"The matrix has no {dye} → {detector} cell."
        row, column = matrix.channel_names.index(dye), matrix.channel_names.index(detector)
        if matrix.origin is None or matrix.origin[row, column] != edited:
            return f"{dye} → {detector} hasn't been edited by hand."
        found = float(matrix.matrix[row, column])
        if self.value is not None and abs(found - self.value) > self.tolerance:
            return f"{dye} → {detector} is {found:.3f}, expected about {self.value}."
        return None


class PreviewShowsValidator(_CompensationTabValidator):
    """The matrix preview is set as given; anything left as None isn't checked."""

    def __init__(
        self,
        x: str | None = None,
        y: str | None = None,
        view: str | None = None,
        sample: str | None = None,
        sample_name: str | None = None,
    ) -> None:
        self.expected = {"x": x, "y": y, "view": view, "sample": sample}
        self.sample_name = sample_name  # part of the sample's display name

    def problem(self, view: Any, app_state: FlowState) -> str | None:
        selection = view.editor.preview_selection._asdict()
        for name, wanted in self.expected.items():
            if wanted is not None and selection[name] != wanted:
                return f"Preview {name} is '{selection[name]}', expected '{wanted}'."
        if self.sample_name is not None:
            shown = app_state.data.experiment.samples.get(selection["sample"])
            if shown is None or self.sample_name.casefold() not in shown.display_name.casefold():
                return f"Preview isn't showing '{self.sample_name}'."
        return None


class MatricesComparedValidator(_CompensationTabValidator):
    """The Matrices page is comparing a matrix from one method with one from another."""

    def __init__(self, source: str, other_source: str) -> None:
        self.expected = {source, other_source}

    def problem(self, view: Any, _app_state: FlowState) -> str | None:
        shown, other = view.library_comparison
        if shown is None or other is None:
            return "No two matrices are being compared."
        if {shown.source, other.source} != self.expected:
            return f"Comparing '{shown.source}' with '{other.source}', expected {self.expected}."
        return None


class SavedMatrixValidator(FlowValidator):
    """The workspace keeps a matrix from this method, optionally a hand-tuned one."""

    def __init__(self, source: str, fine_tuned: bool | None = None) -> None:
        self.source = source
        self.fine_tuned = fine_tuned

    def validate_flow(self, app_state: FlowState) -> bool:
        for saved in app_state.data.matrix_library:
            if saved.matrix.source == self.source and self.fine_tuned in (
                None,
                saved.matrix.fine_tuned,
            ):
                return True
        return self.log_failure(
            f"No saved matrix from '{self.source}' (fine-tuned: {self.fine_tuned})."
        )


class EmbeddedMatrixInUseValidator(_CompensationTabValidator):
    """The matrix in use is the one the FCS files carry, and the samples are
    compensated with it.

    Every number the later courses quote was measured this way, so Course 2
    must hand over in this state whatever the learner tried along the way.
    """

    def problem(self, view: Any, app_state: FlowState) -> str | None:
        in_use = app_state.data.compensation
        if in_use is None:
            return "No compensation matrix is in use."
        samples = [s for s in app_state.data.experiment.samples.values() if s.fcs_data]
        embedded = next(
            (
                m
                for s in samples
                if s.fcs_data and (m := extract_spill_from_fcs(s.fcs_data)) is not None
            ),
            None,
        )
        if embedded is None:
            return "No loaded file carries a matrix."
        if not same_matrix(in_use, embedded):
            return "The matrix in use isn't the one embedded in the FCS files."
        if not view.samples_match_matrix or not all(s.is_compensated for s in samples):
            return "The embedded matrix is selected but not applied to every sample."
        return None


class CompensationSwitchValidator(FlowValidator):
    """Every loaded sample's data is compensated (``on``) or raw (not ``on``).

    What the Compensation tab's ON / OFF switch shows, read from the data
    itself so it holds whichever way the learner got there.
    """

    def __init__(self, on: bool) -> None:
        self.on = on

    def validate_flow(self, app_state: FlowState) -> bool:
        loaded = [s for s in app_state.data.experiment.samples.values() if s.fcs_data]
        if not loaded:
            return self.log_failure("No samples are loaded.")
        compensated = [s.fcs_data.is_compensated for s in loaded if s.fcs_data]
        if self.on and not all(compensated):
            return self.log_failure(f"{compensated.count(False)} sample(s) still show raw data.")
        if not self.on and any(compensated):
            return self.log_failure(f"{sum(compensated)} sample(s) are still compensated.")
        return True
