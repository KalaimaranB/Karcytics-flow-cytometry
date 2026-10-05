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
    MethodOptions,
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

    def readiness(self, state, options):
        return Readiness(self._ready, "what the estimator needs")

    def obtain(self, state, parent, options):
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome


def _button(view, object_name):
    return view.findChild(compensation_view.QWidget, object_name)


# ── Empty state and sources ───────────────────────────────────────────


def test_no_matrix_shows_the_empty_state_with_actions_disabled(make_view, state):
    view = make_view(state)

    # Nothing to edit yet: the body is the method's setup, and Matrix is unavailable.
    assert view._body.currentWidget() is view._setup
    assert not view._btn_matrix_page.isEnabled()
    assert not view._library._btn_apply.isEnabled()
    assert not view._library._btn_export.isEnabled()
    assert view._btn_revert.isHidden()


def test_tutorial_spotlight_names_survive_the_move_out_of_the_ribbon(make_view, state):
    state.data.compensation = _matrix()
    state.data.compensation.source = "cytometer"
    view = make_view(state)

    assert _button(view, "ExtractFCSButton") is view._btn_run
    assert view._btn_run.text() == "📄 Extract from FCS"
    assert _button(view, "ApplyAllButton") is view._library._btn_apply


# ── Choosing a method ─────────────────────────────────────────────────


def test_the_method_behind_the_current_matrix_is_selected_and_named(make_view, state):
    state.data.compensation = _matrix()
    state.data.compensation.source = "imported"
    view = make_view(state)

    assert view._method_combo.currentData() == "imported"
    assert "<b>2×2 · Import from a file</b>" in view._status.text()
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
    view._library._btn_apply.click()

    assert state.data.compensation.source == "cytometer"
    assert state.data.compensation.fine_tuned
    assert "<b>2×2 · Embedded in the FCS files, fine-tuned by hand</b>" in view._status.text()

    # Running a method again starts over from its own numbers.
    result = SourceResult(_matrix(), "Estimate", "Estimated.")
    view = make_view(state, sources=(_FixedSource(result),))
    view._btn_run.click()
    assert not state.data.compensation.fine_tuned
    assert "Fine-tune any cell" in view._note.text()


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

    result = FcsMetadataSource().obtain(state, None, MethodOptions())

    assert result.undo_label == "Extract Compensation Matrix"
    assert "B" in result.summary

    monkeypatch.setattr(matrix_sources, "extract_spill_from_fcs", lambda fcs: None)
    with pytest.raises(MatrixSourceError, match="SPILL"):
        FcsMetadataSource().obtain(state, None, MethodOptions())


def test_single_stain_source_needs_two_controls(state):
    assert SingleStainSource().readiness(state, MethodOptions())[0] is False
    with pytest.raises(MatrixSourceError, match="Found 0 single-stain controls"):
        SingleStainSource().obtain(state, None, MethodOptions())


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


def _fmo_inputs(state) -> dict:
    """The FMO method's input rows, by tube name."""
    return {row.cells[0]: row for row in FmoSource().inputs(state, MethodOptions()).rows}


def _fmo_rows(state) -> dict[str, tuple[str, ...]]:
    """The FMO method's inputs table, by tube name: (lacks, how we know, events used)."""
    inputs = FmoSource().inputs(state, MethodOptions())
    return {row.cells[0]: row.cells[1:] for row in inputs.rows}


def test_fmo_source_matches_each_control_to_the_dye_it_lacks(state):
    source = FmoSource()
    assert source.readiness(state, MethodOptions()).ready is False
    with pytest.raises(MatrixSourceError, match="could be matched"):
        source.obtain(state, None, MethodOptions())

    # By its data, whatever its name says, and by the template's fmo_minus.
    state.data.experiment.samples["f1"] = _fmo("Specimen_001_FMO CD45", 0)
    state.data.experiment.samples["f2"] = _fmo("Tube 7", 1, fmo_minus="cd45")
    state.data.experiment.samples["f3"] = _fmo("Mystery FMO", 1)

    ready, text = source.readiness(state, MethodOptions())
    assert ready and "2 of 2" in text and "1 not used" in text
    rows = _fmo_rows(state)
    assert rows["Specimen_001_FMO CD45"][:2] == ("FL1-A", "from its data (dim in this channel)")
    assert rows["Tube 7"][:2] == ("FL2-A", "set by you")
    assert rows["Mystery FMO"][:2] == ("FL2-A", "not used — Tube 7 already covers it")

    result = source.obtain(state, None, MethodOptions())
    np.testing.assert_allclose(result.matrix.matrix, SPILLOVER, atol=1e-8)
    assert result.matrix.source == "fmo"
    assert result.summary == "Estimated a 2×2 matrix from 2 FMO control(s)."
    # The run says what it rested on: one fit per detector, with its tube.
    assert [row[:2] for row in result.report.rows] == [
        ("FL1-A", "Specimen_001_FMO CD45"),
        ("FL2-A", "Tube 7"),
    ]


def test_a_missing_dye_found_from_the_data_is_kept_on_the_tube(state, monkeypatch):
    for name, missing in (("a", 0), ("b", 1), ("c", 1)):
        state.data.experiment.samples[name] = _fmo(name, missing)

    rows = _fmo_inputs(state)

    # Kept as found, not as the user's choice, and offered in the dropdown.
    tube = state.data.experiment.samples["a"]
    assert (tube.fmo_minus, tube.fmo_minus_detected) == ("FL1-A", True)
    assert (rows["a"].choice, rows["a"].cells[2]) == (
        "FL1-A",
        "from its data (dim in this channel)",
    )
    assert rows["a"].choices[0] == ("Detect again", None)
    # A tube that isn't used keeps nothing: it may be placed differently later.
    assert state.data.experiment.samples["c"].fmo_minus is None

    # From then on the data isn't read again.
    monkeypatch.setattr(matrix_sources, "_signal_levels", lambda *_: pytest.fail("re-detected"))
    del state.data.experiment.samples["c"]
    assert _fmo_inputs(state)["a"].cells[2] == "from its data (dim in this channel)"

    # Confirming the found dye makes it the user's; clearing it detects again.
    FmoSource().set_choice(state, "a", "FL1-A")
    assert (tube.fmo_minus, tube.fmo_minus_detected) == ("FL1-A", False)
    assert _fmo_inputs(state)["a"].cells[2] == "set by you"
    FmoSource().set_choice(state, "a", None)
    assert tube.fmo_minus is None


def test_a_tube_name_is_only_a_guess_when_the_data_cannot_tell(state):
    """Two FMO tubes are too few to compare signal levels."""
    state.data.experiment.samples["f1"] = _fmo("FMO CD4", 0)
    state.data.experiment.samples["f2"] = _fmo("FMO", 1)

    rows = _fmo_inputs(state)

    assert (
        rows["FMO CD4"].cells[1] == "FL1-A" and "guessed from its name" in rows["FMO CD4"].cells[2]
    )
    assert rows["FMO CD4"].choice == "FL1-A"
    assert rows["FMO"].cells[1:3] == ("unknown", "not used — couldn't tell which dye it lacks")
    # A guess isn't kept: the data gets another try once more tubes are loaded.
    assert state.data.experiment.samples["f1"].fmo_minus is None


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

    view._library._btn_apply.click()

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
    view._library._btn_apply.click()
    sample = state.data.experiment.samples["a"]
    with_old = sample.fcs_data.events.copy()

    view._editor._table.item(0, 1).setText("0.5")
    view._library._btn_apply.click()

    assert not np.allclose(sample.fcs_data.events.to_numpy(), with_old.to_numpy())
    assert "applied to 2 sample(s)" in view._note.text()


def test_applying_an_unchanged_matrix_again_skips_compensated_samples(view, state):
    view._library._btn_apply.click()
    view._library._btn_apply.click()

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
def test_the_dye_named_in_a_tube_name_is_recognised(tube, expected):
    channels = ["FITC-A", "PE-A", "Pacific Blue-A", "APC-Cy7-A", "APC-A"]
    fcs = MagicMock(channels=channels, markers=["B220", "CD4", "CD3", "CD8", "CD45"])

    assert matrix_sources._named_channel(tube, fcs, channels) == expected


def test_fmo_tubes_are_placed_by_their_signal(state):
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

    ready, text = FmoSource().readiness(state, MethodOptions())

    assert ready and "3 of 3" in text and "1 not used" in text
    rows = _fmo_rows(state)
    assert rows["FMO e450"][:2] == ("Pacific Blue-A", "from its data (dim in this channel)")
    assert rows["FMO PE"][:2] == ("PE-A", "from its data (dim in this channel)")
    # Only one tube is used per channel.
    assert rows["FMO ???"][:2] == ("Pacific Blue-A", "not used — FMO e450 already covers it")
    result = FmoSource().obtain(state, None, MethodOptions())
    np.testing.assert_allclose(result.matrix.matrix, spillover, atol=1e-8)

    # A manual choice beats the signal.
    FmoSource().set_choice(state, "FMO PE", "FITC-A")
    rows = _fmo_rows(state)
    assert rows["FMO PE"][:2] == ("FITC-A", "set by you")
    assert rows["FMO FITC"][1] == "not used — FMO PE already covers it"
    assert rows["(no FMO control)"][:2] == ("PE-A", "not estimated — left at 0")


def test_cells_show_whether_the_method_produced_them(make_view, state):
    """Greyed: the method had no control for the cell. Green bold: edited by hand."""
    from karcytics_plugins.flow_cytometry.analysis.compensation import CELL_DEFAULT, CELL_EDITED

    matrix = _matrix()
    matrix.origin = np.array([[0, CELL_DEFAULT], [0, 0]], dtype=np.int8)
    state.data.compensation = matrix
    view = make_view(state)
    view.show()
    view._btn_matrix_page.click()
    table = view._editor._table

    assert table.item(0, 1).font().italic() and "Not set" in table.item(0, 1).toolTip()
    assert not table.item(1, 0).font().italic() and not table.item(1, 0).font().bold()
    assert view._editor._origin_legend.isVisible()

    table.item(1, 0).setText("0.3")
    assert table.item(1, 0).font().bold() and "Edited by hand" in table.item(1, 0).toolTip()
    assert view._editor.matrix.origin[1, 0] == CELL_EDITED

    view._library._btn_apply.click()  # the marks are part of the matrix: saved and reloaded with it
    assert state.data.compensation.origin[1, 0] == CELL_EDITED
    assert table.item(1, 0).font().bold() and table.item(0, 1).font().italic()


def test_the_legend_is_hidden_when_every_cell_is_from_the_method(make_view, state):
    state.data.compensation = _matrix()
    view = make_view(state)
    view.show()
    view._btn_matrix_page.click()

    assert not view._editor._origin_legend.isVisible()


# ── Manual entry ──────────────────────────────────────────────────────


def _three_colour_sample() -> Sample:
    from pathlib import Path

    from karcytics_plugins.flow_cytometry.analysis.fcs_io import FCSData

    channels = ["FSC-A", "SSC-A", "FITC-A", "PE-A", "APC-A", "Time"]
    rng = np.random.default_rng(5)
    events = pd.DataFrame(np.abs(rng.normal(500, 200, (300, 6))), columns=channels)
    sample = Sample(sample_id="tube", display_name="Tube 1")
    sample.role = SampleRole.FULL_PANEL
    sample.fcs_data = FCSData(
        file_path=Path("tube.fcs"),
        channels=channels,
        markers=["", "", "CD4", "", "CD8", ""],
        events=events,
        raw_events=events.copy(),
    )
    return sample


def test_manual_entry_starts_from_a_matrix_with_no_spill(make_view):
    from karcytics_plugins.flow_cytometry.analysis.compensation import CELL_DEFAULT
    from karcytics_plugins.flow_cytometry.ui.widgets.matrix_sources import ManualSource

    state = FlowState()
    source = ManualSource()
    assert not source.readiness(state, MethodOptions()).ready
    with pytest.raises(MatrixSourceError, match="at least two fluorescence channels"):
        source.obtain(state, None, MethodOptions())

    state.data.experiment.samples["tube"] = _three_colour_sample()
    assert "blank 3×3 matrix over Tube 1" in source.readiness(state, MethodOptions()).text
    inputs = source.inputs(state, MethodOptions())
    assert [row.cells for row in inputs.rows] == [
        ("FITC-A", "CD4"),
        ("PE-A", "—"),
        ("APC-A", "CD8"),
    ]

    matrix = source.obtain(state, None, MethodOptions()).matrix

    assert matrix.channel_names == ["FITC-A", "PE-A", "APC-A"]  # no scatter, no time
    np.testing.assert_array_equal(matrix.matrix, np.eye(3))
    assert matrix.source == "manual"
    assert (matrix.origin == CELL_DEFAULT).sum() == 6  # every spill value still to enter


def test_typed_values_are_marked_and_the_method_is_named_plainly(make_view):
    state = FlowState()
    state.data.experiment.samples["tube"] = _three_colour_sample()
    view = make_view(state)
    view.show()
    view._method_combo.setCurrentIndex(view._method_combo.findData("manual"))

    view._btn_run.click()

    table = view._editor._table
    assert view._body.currentWidget() is view._editor
    assert "Double-click a cell to enter its value" in view._note.text()
    assert table.item(0, 1).text() == "0.0000" and table.item(0, 1).font().italic()

    table.item(0, 1).setText("0.12")
    assert table.item(0, 1).font().bold() and not table.item(0, 1).font().italic()
    assert table.item(1, 0).font().italic()  # still to do

    view._library._btn_apply.click()
    assert state.data.compensation.matrix[0, 1] == 0.12
    # Entirely by hand: "fine-tuned by hand" would say nothing.
    assert "<b>3×3 · Manual entry</b>" in view._status.text()
