"""Tests for the Compensation tab's view: sources, the edit draft, and applying."""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from karcytics_plugins.flow_cytometry.analysis.compensation import CompensationMatrix
from karcytics_plugins.flow_cytometry.analysis.experiment import Sample, SampleRole
from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.ui.widgets import compensation_view, matrix_sources
from karcytics_plugins.flow_cytometry.ui.widgets.compensation_view import CompensationView
from karcytics_plugins.flow_cytometry.ui.widgets.matrix_sources import (
    MATRIX_SOURCES,
    FcsMetadataSource,
    MatrixSource,
    MatrixSourceError,
    SingleStainSource,
    SourceResult,
)

pytestmark = pytest.mark.ui

CHANNELS = ["FL1-A", "FL2-A"]
SPILLOVER = np.array([[1.0, 0.2], [0.05, 1.0]])


def _matrix(values=SPILLOVER) -> CompensationMatrix:
    return CompensationMatrix(matrix=np.array(values, dtype=float), channel_names=list(CHANNELS))


def _sample(sample_id: str) -> Sample:
    rng = np.random.default_rng(len(sample_id))
    raw = pd.DataFrame(np.abs(rng.normal(500, 200, (200, 2))) @ SPILLOVER, columns=CHANNELS)
    sample = Sample(sample_id=sample_id, display_name=sample_id.upper())
    sample.role = SampleRole.FULL_PANEL
    sample.fcs_data = MagicMock()
    sample.fcs_data.raw_events = raw
    sample.fcs_data.events = raw.copy()
    sample.fcs_data.is_compensated = False
    return sample


@pytest.fixture(autouse=True)
def quiet_edits(monkeypatch):
    """Model edits announce themselves on the (mocked) event bus; sync is a no-op here."""
    monkeypatch.setattr(compensation_view.experiment_edits, "sync_experiment", lambda _exp: None)


@pytest.fixture
def state():
    state = FlowState()
    state.data.experiment.samples["a"] = _sample("a")
    state.data.experiment.samples["b"] = _sample("b")
    return state


@pytest.fixture
def make_view(qtbot):
    def _make(state, sources=MATRIX_SOURCES):
        view = CompensationView(state, sources)
        qtbot.addWidget(view)
        return view

    return _make


class _FixedSource(MatrixSource):
    """A stand-in for any way of obtaining a matrix — e.g. a future estimator."""

    label = "🧪 Estimate"
    tooltip = "test source"
    object_name = "EstimateButton"

    def __init__(self, outcome) -> None:
        self._outcome = outcome

    def obtain(self, state, parent):
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome


def _button(view, object_name):
    return view.findChild(compensation_view.QWidget, object_name)


# ── Empty state and sources ───────────────────────────────────────────


def test_no_matrix_shows_the_empty_state_with_actions_disabled(make_view, state):
    view = make_view(state)

    assert view._body.currentWidget() is view._empty
    assert not view._btn_apply.isEnabled() and not view._btn_export.isEnabled()
    assert view._btn_revert.isHidden()


def test_tutorial_spotlight_names_survive_the_move_out_of_the_ribbon(make_view, state):
    view = make_view(state)

    assert _button(view, "ExtractFCSButton") is not None
    assert _button(view, "ApplyAllButton") is view._btn_apply


def test_a_new_source_gets_a_button_without_changing_the_view(make_view, state):
    result = SourceResult(_matrix(), "Estimate Compensation Matrix", "Estimated a 2×2 matrix.")
    view = make_view(state, sources=(_FixedSource(result),))
    changed = MagicMock()
    view.compensation_changed.connect(changed)

    _button(view, "EstimateButton").click()

    assert np.array_equal(state.data.compensation.matrix, SPILLOVER)
    assert view._body.currentWidget() is view._editor
    assert np.array_equal(view._editor.matrix.matrix, SPILLOVER)
    assert "Estimated a 2×2 matrix." in view._note.text()
    assert not view.has_unapplied_edits
    changed.assert_called_once()
    # Getting a matrix doesn't touch the samples; that is Apply to All's job.
    assert not state.data.experiment.samples["a"].is_compensated


def test_a_failing_source_warns_and_changes_nothing(make_view, state, monkeypatch):
    warn = MagicMock()
    monkeypatch.setattr(compensation_view, "show_warning", warn)
    view = make_view(state, sources=(_FixedSource(MatrixSourceError("Nope", "no evidence")),))

    _button(view, "EstimateButton").click()

    assert warn.call_args.args[1:] == ("Nope", "no evidence")
    assert state.data.compensation is None


def test_a_cancelled_source_changes_nothing(make_view, state):
    view = make_view(state, sources=(_FixedSource(None),))

    _button(view, "EstimateButton").click()

    assert state.data.compensation is None
    assert view._note.text() == ""


def test_fcs_source_reports_which_file_the_matrix_came_from(state, monkeypatch):
    monkeypatch.setattr(
        matrix_sources,
        "extract_spill_from_fcs",
        lambda fcs: _matrix() if fcs is state.data.experiment.samples["b"].fcs_data else None,
    )

    result = FcsMetadataSource().obtain(state, None)

    assert result.undo_label == "Extract Compensation Matrix"
    assert "B" in result.summary

    monkeypatch.setattr(matrix_sources, "extract_spill_from_fcs", lambda fcs: None)
    with pytest.raises(MatrixSourceError, match="SPILL"):
        FcsMetadataSource().obtain(state, None)


def test_single_stain_source_needs_two_controls(state):
    with pytest.raises(MatrixSourceError, match="Found 0 single-stain controls"):
        SingleStainSource().obtain(state, None)


# ── The edit draft ────────────────────────────────────────────────────


@pytest.fixture
def view(make_view, state):
    state.data.compensation = _matrix()
    return make_view(state)


def test_edits_are_a_draft_until_applied(view, state):
    view._editor._table.item(0, 1).setText("0.5")

    assert view.has_unapplied_edits
    assert state.data.compensation.matrix[0, 1] == 0.2
    assert not view._btn_revert.isHidden()
    assert "unapplied edits" in view._status.text()


def test_revert_discards_the_draft(view, state):
    view._editor._table.item(0, 1).setText("0.5")

    view._btn_revert.click()

    assert not view.has_unapplied_edits
    assert view._editor.matrix.matrix[0, 1] == 0.2
    assert view._btn_revert.isHidden()


def test_draft_survives_leaving_the_tab_but_not_a_replaced_matrix(view, state):
    view._editor._table.item(0, 1).setText("0.5")

    view.refresh()  # coming back to the tab
    assert view._editor.matrix.matrix[0, 1] == 0.5

    state.data.compensation = _matrix([[1.0, 0.9], [0.0, 1.0]])  # e.g. undo, workflow load
    view._on_state_restored({})
    assert view._editor.matrix.matrix[0, 1] == 0.9
    assert not view.has_unapplied_edits


def test_apply_commits_the_draft_and_compensates_the_samples(view, state):
    changed = MagicMock()
    view.compensation_changed.connect(changed)
    view._editor._table.item(0, 1).setText("0.5")

    view._btn_apply.click()

    assert state.data.compensation.matrix[0, 1] == 0.5
    assert not view.has_unapplied_edits
    sample = state.data.experiment.samples["a"]
    expected = sample.fcs_data.raw_events.to_numpy() @ np.linalg.inv(state.data.compensation.matrix)
    np.testing.assert_allclose(sample.fcs_data.events.to_numpy(), expected)
    assert "applied to 2 sample(s)" in view._note.text()
    assert "applied to 2 of 2 loaded samples" in view._status.text()
    changed.assert_called_once()


def test_an_edited_matrix_replaces_values_from_the_old_one(view, state):
    """Samples compensated with the old matrix must not be skipped as 'already done'."""
    view._btn_apply.click()
    sample = state.data.experiment.samples["a"]
    with_old = sample.fcs_data.events.copy()

    view._editor._table.item(0, 1).setText("0.5")
    view._btn_apply.click()

    assert not np.allclose(sample.fcs_data.events.to_numpy(), with_old.to_numpy())
    assert "applied to 2 sample(s)" in view._note.text()


def test_applying_an_unchanged_matrix_again_skips_compensated_samples(view, state):
    view._btn_apply.click()
    view._btn_apply.click()

    assert "applied to 0 sample(s)" in view._note.text()
    assert "2 skipped (already compensated)" in view._note.text()


def test_cleanup_unsubscribes(view):
    bus = compensation_view.CentralEventBus
    bus.unsubscribe.reset_mock()

    view.cleanup()
    view.cleanup()

    bus.unsubscribe.assert_called_once()
    view._on_state_restored({})  # late delivery is a no-op
