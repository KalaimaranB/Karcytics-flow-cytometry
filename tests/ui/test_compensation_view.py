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
    FmoSource,
    MatrixSource,
    MatrixSourceError,
    Readiness,
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

    key = "estimated"
    label = "Test estimator"
    action = "🧪 Estimate"
    tooltip = "test source"
    object_name = "EstimateButton"

    def __init__(self, outcome, ready: bool = True) -> None:
        self._outcome = outcome
        self._ready = ready

    def readiness(self, state):
        return Readiness(self._ready, "what the estimator needs", "the specifics")

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
    state.data.compensation = _matrix()
    state.data.compensation.source = "cytometer"
    view = make_view(state)

    assert _button(view, "ExtractFCSButton") is view._btn_run
    assert view._btn_run.text() == "📄 Extract from FCS"
    assert _button(view, "ApplyAllButton") is view._btn_apply


# ── Choosing a method ─────────────────────────────────────────────────


def test_the_method_behind_the_current_matrix_is_selected_and_named(make_view, state):
    state.data.compensation = _matrix()
    state.data.compensation.source = "imported"
    view = make_view(state)

    assert view._method_combo.currentData() == "imported"
    assert "method: <b>Import from a file</b>" in view._status.text()
    assert "fine-tuned" not in view._status.text()


def test_without_a_matrix_the_first_method_that_can_run_is_the_default(make_view, state):
    sources = (
        _FixedSource(None, ready=False),
        *(s for s in MATRIX_SOURCES if s.key == "imported"),
    )
    view = make_view(state, sources=sources)

    assert view._method_combo.currentData() == "imported"
    assert view._btn_run.text() == "📥 Import CSV"


def test_picking_a_method_retargets_the_run_button_and_sticks(make_view, state):
    view = make_view(state)
    index = view._method_combo.findData("fmo")

    view._method_combo.setCurrentIndex(index)
    view._method_combo.activated.emit(index)

    assert view._btn_run.text() == "🧮 Estimate from FMOs"
    assert "No FMO controls loaded" in view._method_hint.text()
    assert view._method_hint.toolTip() == ""
    view.refresh()  # coming back to the tab keeps the user's choice
    assert view._method_combo.currentData() == "fmo"


def test_the_selector_lists_exactly_the_registered_methods(make_view, state):
    combo = make_view(state)._method_combo

    assert [combo.itemData(i) for i in range(combo.count())] == [s.key for s in MATRIX_SOURCES]


def test_fine_tuning_is_recorded_on_top_of_the_method(make_view, state):
    state.data.compensation = _matrix()
    state.data.compensation.source = "cytometer"
    view = make_view(state)

    view._editor._table.item(0, 1).setText("0.5")
    view._btn_apply.click()

    assert state.data.compensation.source == "cytometer"
    assert state.data.compensation.fine_tuned
    assert "method: <b>Embedded in the FCS files</b>, then <b>fine-tuned by hand</b>" in (
        view._status.text()
    )

    # Running a method again starts over from its own numbers.
    result = SourceResult(_matrix(), "Estimate", "Estimated.")
    view = make_view(state, sources=(_FixedSource(result),))
    view._btn_run.click()
    assert not state.data.compensation.fine_tuned
    assert "Fine-tune any cell below" in view._note.text()


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
    assert SingleStainSource().readiness(state)[0] is False
    with pytest.raises(MatrixSourceError, match="Found 0 single-stain controls"):
        SingleStainSource().obtain(state, None)


def _fmo(name: str, missing: int, fmo_minus: str | None = None) -> Sample:
    """An FMO control: both dyes spill per SPILLOVER, but dye ``missing`` is absent."""
    rng = np.random.default_rng(missing + 1)
    true = np.abs(rng.normal(800, 400, (500, 2)))
    true[:, missing] = 0.0
    sample = Sample(sample_id=name, display_name=name, fmo_minus=fmo_minus)
    sample.role = SampleRole.FMO_CONTROL
    sample.fcs_data = MagicMock()
    sample.fcs_data.channels = list(CHANNELS)
    sample.fcs_data.markers = ["CD4", "CD45"]
    sample.fcs_data.raw_events = pd.DataFrame(true @ SPILLOVER, columns=CHANNELS)
    return sample


def test_fmo_source_matches_each_control_to_the_dye_it_lacks(state):
    source = FmoSource()
    assert source.readiness(state)[0] is False
    with pytest.raises(MatrixSourceError, match="could be matched"):
        source.obtain(state, None)

    # By name ("CD4" must not match inside "CD45"), and by the template's fmo_minus.
    state.data.experiment.samples["f1"] = _fmo("Specimen_001_FMO CD4", 0)
    state.data.experiment.samples["f2"] = _fmo("Tube 7", 1, fmo_minus="cd45")
    state.data.experiment.samples["f3"] = _fmo("Mystery FMO", 1)

    ready, text, detail = source.readiness(state)
    assert ready and "2 of 2" in text and "1 not used" in text
    assert "FL1-A: Specimen_001_FMO CD4" in detail and "FL2-A: Tube 7" in detail
    assert "Not used: Mystery FMO" in detail

    result = source.obtain(state, None)
    np.testing.assert_allclose(result.matrix.matrix, SPILLOVER, atol=1e-8)
    assert result.matrix.source == "fmo"
    assert result.summary == "Estimated a 2×2 matrix from 2 FMO control(s)."


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


@pytest.mark.parametrize(
    "tube, expected",
    [
        ("Specimen_001_FMO APC", "APC-A"),
        ("Specimen_001_FMO APCCy7", "APC-Cy7-A"),
        ("FMO APC Cy7", "APC-Cy7-A"),
        ("FMO minus PE-A", "PE-A"),
        ("FMO Pacific Blue", "Pacific Blue-A"),
        ("FMO CD3", "Pacific Blue-A"),  # by marker
        ("Specimen_001_FMO e450", None),  # a dye name the file doesn't use
        ("FMO", None),
    ],
)
def test_an_fmo_tube_is_placed_by_the_dye_named_in_its_name(tube, expected):
    channels = ["FITC-A", "PE-A", "Pacific Blue-A", "APC-Cy7-A", "APC-A"]
    fcs = MagicMock(channels=channels, markers=["B220", "CD4", "CD3", "CD8", "CD45"])
    sample = Sample(sample_id="s", display_name=tube)

    assert matrix_sources.fmo_missing_channel(sample, fcs, channels) == expected


def test_an_fmo_with_an_unrecognised_name_is_placed_by_its_signal(state):
    """It is clearly dimmer than the other FMOs only in the dye it lacks."""
    channels = ["FITC-A", "PE-A", "Pacific Blue-A"]
    spillover = np.array([[1.0, 0.1, 0.0], [0.02, 1.0, 0.05], [0.0, 0.03, 1.0]])
    for name, missing in (("FMO FITC", 0), ("FMO PE", 1), ("FMO e450", 2), ("FMO ???", 2)):
        rng = np.random.default_rng(missing)
        true = np.abs(rng.normal(900, 400, (2000, 3)))
        true[:, missing] = 0.0
        sample = Sample(sample_id=name, display_name=name)
        sample.role = SampleRole.FMO_CONTROL
        sample.fcs_data = MagicMock(channels=channels, markers=[])
        sample.fcs_data.raw_events = pd.DataFrame(true @ spillover + 20.0, columns=channels)
        state.data.experiment.samples[name] = sample

    ready, text, detail = FmoSource().readiness(state)

    assert ready and "3 of 3" in text and "1 matched by signal" in text
    assert "Pacific Blue-A: FMO e450 (matched by its signal" in detail
    # The channel is taken, so a second unnamed tube isn't forced onto it.
    assert "Not used: FMO ???" in detail
    result = FmoSource().obtain(state, None)
    np.testing.assert_allclose(result.matrix.matrix, spillover, atol=1e-8)

    # A manual choice beats both the name and the signal.
    state.data.experiment.samples["FMO PE"].fmo_minus = "FITC-A"
    detail = FmoSource().readiness(state).detail
    assert "FITC-A: FMO PE" in detail and "Not used: FMO FITC" in detail


def test_cells_show_whether_the_method_produced_them(make_view, state):
    """Greyed: the method had no control for the cell. Green bold: edited by hand."""
    from karcytics_plugins.flow_cytometry.analysis.compensation import CELL_DEFAULT, CELL_EDITED

    matrix = _matrix()
    matrix.origin = np.array([[0, CELL_DEFAULT], [0, 0]], dtype=np.int8)
    state.data.compensation = matrix
    view = make_view(state)
    view.show()
    table = view._editor._table

    assert table.item(0, 1).font().italic() and "Not estimated" in table.item(0, 1).toolTip()
    assert not table.item(1, 0).font().italic() and not table.item(1, 0).font().bold()
    assert view._editor._origin_legend.isVisible()

    table.item(1, 0).setText("0.3")
    assert table.item(1, 0).font().bold() and "Edited by hand" in table.item(1, 0).toolTip()
    assert view._editor.matrix.origin[1, 0] == CELL_EDITED

    view._btn_apply.click()  # the marks are part of the matrix: saved and reloaded with it
    assert state.data.compensation.origin[1, 0] == CELL_EDITED
    assert table.item(1, 0).font().bold() and table.item(0, 1).font().italic()


def test_the_legend_is_hidden_when_every_cell_is_from_the_method(make_view, state):
    state.data.compensation = _matrix()
    view = make_view(state)
    view.show()

    assert not view._editor._origin_legend.isVisible()
