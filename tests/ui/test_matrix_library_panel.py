"""Tests for the Compensation tab's Matrices page: keep, compare, export, apply."""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtWidgets import QApplication

from karcytics_plugins.flow_cytometry.analysis.compensation import CompensationMatrix
from karcytics_plugins.flow_cytometry.analysis.experiment import Sample, SampleRole
from karcytics_plugins.flow_cytometry.analysis.services import experiment_edits
from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.ui.widgets import compensation_view, matrix_library_panel
from karcytics_plugins.flow_cytometry.ui.widgets.compensation_view import CompensationView
from karcytics_plugins.flow_cytometry.ui.widgets.matrix_sources import (
    FmoSource,
    MatrixSource,
    MethodOptions,
    Readiness,
    SourceResult,
)
from karcytics_plugins.flow_cytometry.ui.widgets.method_setup_panel import MethodSetupPanel

pytestmark = pytest.mark.ui

CHANNELS = ["FL1-A", "FL2-A"]
EMBEDDED = [[1.0, 0.2], [0.05, 1.0]]
ESTIMATE = [[1.0, 0.26], [0.05, 1.0]]


def _matrix(values, source="cytometer") -> CompensationMatrix:
    return CompensationMatrix(np.array(values, dtype=float), list(CHANNELS), source)


def _sample(sample_id: str) -> Sample:
    rng = np.random.default_rng(len(sample_id))
    raw = pd.DataFrame(
        np.abs(rng.normal(500, 200, (200, 2))) @ np.array(EMBEDDED), columns=CHANNELS
    )
    sample = Sample(sample_id=sample_id, display_name=sample_id.upper())
    sample.role = SampleRole.FULL_PANEL
    sample.fcs_data = MagicMock()
    sample.fcs_data.raw_events = raw
    sample.fcs_data.events = raw.copy()
    sample.fcs_data.is_compensated = False
    return sample


class _Estimator(MatrixSource):
    key = "fmo"
    label = "Test estimator"
    action = "Estimate"
    tooltip = ""

    def readiness(self, state, options):
        return Readiness(True, "ready")

    def obtain(self, state, parent, options):
        return SourceResult(_matrix(ESTIMATE, "fmo"), "Estimate", "Estimated.")


@pytest.fixture(autouse=True)
def quiet_edits(monkeypatch):
    monkeypatch.setattr(compensation_view.experiment_edits, "sync_experiment", lambda _exp: None)


@pytest.fixture
def state():
    state = FlowState()
    state.data.experiment.samples["a"] = _sample("a")
    state.data.compensation = _matrix(EMBEDDED)
    return state


@pytest.fixture
def view(qtbot, state):
    view = CompensationView(state, sources=(_Estimator(),))
    qtbot.addWidget(view)
    view.show()
    return view


@pytest.fixture
def name_prompt(monkeypatch):
    """Stand-in for the name dialog: answers with ``prompt.answer``."""
    prompt = MagicMock(answer="Tuned by hand")
    monkeypatch.setattr(
        matrix_library_panel.QInputDialog,
        "getText",
        lambda *args, **kwargs: (prompt.answer, prompt.answer is not None),
    )
    return prompt


def _titles(library) -> list[str]:
    return [library._list.item(i).text().split("\n")[0] for i in range(library._list.count())]


def _select(library, title: str) -> None:
    library._list.setCurrentRow(
        next(i for i, t in enumerate(_titles(library)) if t.startswith(title))
    )


# ── What is listed ────────────────────────────────────────────────────


def test_the_page_lists_the_editors_matrix_and_marks_the_one_in_use(view, state):
    library = view._library

    assert _titles(library) == ["Current matrix (in the editor)  ✓ in use"]
    assert "2×2 · cytometer" in library._list.item(0).text()
    assert not library._btn_rename.isEnabled() and not library._btn_open.isEnabled()
    assert library._btn_apply.isEnabled() and library._btn_export.isEnabled()


def test_every_method_run_is_kept_but_the_same_result_only_once(view, state):
    view._btn_run.click()
    view._btn_run.click()

    assert [saved.name for saved in state.data.matrix_library] == ["Test estimator"]
    assert _titles(view._library) == [
        "Current matrix (in the editor)  ✓ in use",
        "Test estimator  ✓ in use",
    ]


def test_a_fine_tuned_matrix_is_saved_under_its_own_name(view, state, name_prompt):
    view._editor._table.item(0, 1).setText("0.3")

    view._library._btn_save.click()

    [saved] = state.data.matrix_library
    assert saved.name == "Tuned by hand" and saved.matrix.matrix[0, 1] == 0.3
    assert saved.matrix.fine_tuned
    assert "Saved the current matrix as 'Tuned by hand'" in view._note.text()
    # Saving keeps a copy; it doesn't apply anything.
    assert state.data.compensation.matrix[0, 1] == 0.2


def test_saved_matrices_can_be_renamed_and_deleted(view, state, name_prompt):
    view._library._btn_save.click()
    _select(view._library, "Tuned by hand")

    name_prompt.answer = "Version B"
    view._library._btn_rename.click()
    assert [saved.name for saved in state.data.matrix_library] == ["Version B"]

    name_prompt.answer = None  # cancelled
    view._library._btn_rename.click()
    assert [saved.name for saved in state.data.matrix_library] == ["Version B"]

    _select(view._library, "Version B")
    view._library._btn_delete.click()
    assert state.data.matrix_library == []
    assert _titles(view._library) == ["Current matrix (in the editor)  ✓ in use"]


# ── Comparing ─────────────────────────────────────────────────────────


def test_comparing_shows_each_difference_and_the_largest(view, state):
    experiment_edits.save_matrix(state, "FMO estimate", _matrix(ESTIMATE, "fmo"))
    view.refresh()
    library = view._library
    _select(library, "FMO estimate")

    library._compare_combo.setCurrentIndex(library._compare_combo.findData("current"))

    assert library._table.item(0, 1).text() == "0.2600  (+0.0600)"
    assert library._table.item(1, 0).text() == "0.0500"  # identical cells stay plain
    assert "1 cell(s) differ" in library._summary.text()
    assert "FL1-A → FL2-A, +0.0600" in library._summary.text()

    experiment_edits.save_matrix(state, "Copy", _matrix(ESTIMATE, "fmo"))
    view.refresh()
    _select(library, "Copy")
    library._compare_combo.setCurrentIndex(library._compare_combo.findText("FMO estimate"))
    assert "Identical to <b>FMO estimate</b>" in library._summary.text()


def test_matrices_with_different_channels_are_not_compared_cell_by_cell(view, state):
    other = CompensationMatrix(np.eye(3), ["A", "B", "C"], "imported")
    experiment_edits.save_matrix(state, "Other panel", other)
    view.refresh()
    library = view._library

    library._compare_combo.setCurrentIndex(library._compare_combo.findText("Other panel"))

    assert "different channels" in library._summary.text()
    assert library._table.item(0, 1).text() == "0.2000"


# ── Applying, opening, exporting ──────────────────────────────────────


def test_applying_a_saved_matrix_makes_it_the_workspace_matrix_and_recompensates(view, state):
    view._library._btn_apply.click()  # the embedded matrix first
    sample = state.data.experiment.samples["a"]
    with_embedded = sample.fcs_data.events.copy()

    experiment_edits.save_matrix(state, "FMO estimate", _matrix(ESTIMATE, "fmo"))
    view.refresh()
    _select(view._library, "FMO estimate")
    view._library._btn_apply.click()

    assert state.data.compensation.matrix[0, 1] == 0.26 and state.data.compensation.source == "fmo"
    expected = sample.fcs_data.raw_events.to_numpy() @ np.linalg.inv(np.array(ESTIMATE))
    np.testing.assert_allclose(sample.fcs_data.events.to_numpy(), expected)
    assert not np.allclose(sample.fcs_data.events.to_numpy(), with_embedded.to_numpy())
    assert "applied to 1 sample(s)" in view._note.text()
    assert not view.has_unapplied_edits
    # The saved copy is untouched by what happens to the workspace matrix afterwards.
    view._editor._table.item(0, 1).setText("0.9")
    assert state.data.matrix_library[0].matrix.matrix[0, 1] == 0.26


def test_opening_a_saved_matrix_edits_a_draft_and_leaves_the_samples_alone(view, state):
    experiment_edits.save_matrix(state, "FMO estimate", _matrix(ESTIMATE, "fmo"))
    view.refresh()
    view._btn_library_page.click()
    _select(view._library, "FMO estimate")

    view._library._btn_open.click()

    assert view._body.currentWidget() is view._editor
    assert view._editor.matrix.matrix[0, 1] == 0.26
    assert state.data.compensation.matrix[0, 1] == 0.2 and view.has_unapplied_edits
    view.refresh()  # the draft survives leaving and re-entering the tab
    assert view._editor.matrix.matrix[0, 1] == 0.26

    view._btn_revert.click()
    assert view._editor.matrix.matrix[0, 1] == 0.2


def test_export_writes_the_selected_matrix(view, state, tmp_path, monkeypatch):
    experiment_edits.save_matrix(state, "FMO estimate", _matrix(ESTIMATE, "fmo"))
    view.refresh()
    _select(view._library, "FMO estimate")
    target = tmp_path / "estimate.csv"
    monkeypatch.setattr(
        matrix_library_panel.QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), "")
    )

    view._library._btn_export.click()

    assert pd.read_csv(target, index_col=0).loc["FL1-A", "FL2-A"] == 0.26
    assert "FMO estimate saved to estimate.csv" in view._note.text()


# ── The header and the pages ──────────────────────────────────────────


def test_the_header_is_two_rows_without_export_toggle_or_apply(view):
    assert not hasattr(view, "_btn_export") and not hasattr(view, "_btn_toggle")
    assert view.findChild(compensation_view.QWidget, "ApplyAllButton") is view._library._btn_apply

    # Set the method up first: the tab opens on Method setup, the first of the three.
    toggle = view.findChild(compensation_view.QWidget, "CompensationPageToggle")
    assert [b.text() for b in toggle.findChildren(compensation_view.QPushButton)] == [
        "⚙ Method setup",
        "Matrix",
        "🗂 Matrices",
    ]
    assert view._body.currentWidget() is view._setup
    view._btn_library_page.click()
    assert view._body.currentWidget() is view._library
    view._btn_matrix_page.click()
    assert view._body.currentWidget() is view._editor


def test_the_wheel_scrolls_the_setup_page_past_its_plot_tables_and_combos(qtbot):
    """Nothing in the scrolling page may swallow the wheel — or change a setting with it."""
    panel = MethodSetupPanel(FlowState())
    qtbot.addWidget(panel)
    panel.show()
    panel.show_method(FmoSource(), MethodOptions(), None)
    combo = panel._illustration_combo
    combo.addItem("another", "x")

    for widget in (panel._illustration.canvas, panel._inputs_table, combo, panel._gate_combo):
        event = QWheelEvent(
            QPointF(5, 5),
            QPointF(widget.mapToGlobal(QPoint(5, 5))),
            QPoint(0, 0),
            QPoint(0, -120),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )
        widget.wheelEvent(event)
        assert not event.isAccepted(), type(widget).__name__
    assert combo.currentIndex() == 0
    assert QApplication.instance() is not None
