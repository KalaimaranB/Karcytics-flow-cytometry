"""Tests for the Compensation tab's Method setup page and its switch."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from karcytics_plugins.flow_cytometry.analysis.compensation_sources import (
    FcsMetadataSource,
    FmoSource,
    MethodOptions,
)
from karcytics_plugins.flow_cytometry.analysis.experiment import Sample, SampleRole
from karcytics_plugins.flow_cytometry.analysis.fcs_io import FCSData
from karcytics_plugins.flow_cytometry.analysis.gating.rectangle import RectangleGate
from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.ui.widgets import compensation_view
from karcytics_plugins.flow_cytometry.ui.widgets.compensation_view import CompensationView
from karcytics_plugins.flow_cytometry.ui.widgets.method_setup_panel import MethodSetupPanel
from karcytics_plugins.flow_cytometry.ui.widgets.styled_combo import FlowComboBox

pytestmark = pytest.mark.ui

DYES = ["FITC-A", "PE-A", "APC-A"]
CHANNELS = ["FSC-A", *DYES]
SPILLOVER = np.array([[1.0, 0.15, 0.0], [0.02, 1.0, 0.08], [0.0, 0.01, 1.0]])


def _fmo(name: str, missing: int, spill: str | None = None) -> Sample:
    """An FMO tube: real cells at high FSC that follow SPILLOVER, plus low-FSC
    debris whose signal in the missing dye's detector tracks another detector —
    which a fit on all events reads as spill.
    """
    rng = np.random.default_rng(missing + 1)
    true = np.abs(rng.normal(900, 400, (600, 3)))
    true[:, missing] = 0.0
    raw = true @ SPILLOVER + rng.normal(0, 25, (600, 3))  # detector noise
    fsc = np.full(600, 500.0)
    fsc[:150] = 10.0
    raw[:150, missing] += 0.6 * raw[:150, (missing + 1) % 3]
    events = pd.DataFrame(np.column_stack([fsc, raw]), columns=CHANNELS)

    sample = Sample(sample_id=name, display_name=name)
    sample.role = SampleRole.FMO_CONTROL
    sample.fcs_data = FCSData(
        file_path=Path(f"{name}.fcs"),
        channels=list(CHANNELS),
        markers=[""] * 4,
        events=events,
        metadata={"$SPILLOVER": spill} if spill else {},
    )
    return sample


def _spill_keyword(values) -> str:
    return ",".join(["3", *DYES, *(str(v) for v in np.asarray(values).ravel())])


@pytest.fixture(autouse=True)
def quiet_edits(monkeypatch):
    monkeypatch.setattr(compensation_view.experiment_edits, "sync_experiment", lambda _exp: None)


@pytest.fixture
def state():
    state = FlowState()
    for name, missing in (("FMO FITC", 0), ("FMO PE", 1), ("FMO APC", 2)):
        state.data.experiment.samples[name] = _fmo(name, missing)
    return state


@pytest.fixture
def panel(qtbot, state):
    panel = MethodSetupPanel(state)
    qtbot.addWidget(panel)
    panel.show()
    return panel


def _column(table, column: int) -> list[str]:
    return [table.item(row, column).text() for row in range(table.rowCount())]


def _add_cells_gate(state, *names: str) -> None:
    for name in names:
        state.data.experiment.samples[name].gate_tree.add_child(
            RectangleGate("FSC-A", x_min=100, x_max=1000), "Cells"
        )


# ── The page itself ───────────────────────────────────────────────────


def test_the_page_explains_the_method_and_lists_what_it_will_use(panel, state):
    panel.show_method(FmoSource(), MethodOptions(), None)

    assert "How it works" in panel._explanation.text()
    assert "not a published standard" in panel._explanation.text()
    table = panel._inputs_table
    headers = [table.horizontalHeaderItem(c).text() for c in range(table.columnCount())]
    assert headers == ["FMO tube", "Missing dye", "Lacks", "How we know", "Events used"]
    assert _column(table, 0) == ["FMO FITC", "FMO PE", "FMO APC"]
    assert _column(table, 2) == ["FITC-A", "PE-A", "APC-A"]
    assert all("from its" in how for how in _column(table, 3))
    assert panel._report_note.isVisible() and not panel._report_table.isVisible()


def test_setting_a_tubes_missing_dye_here_is_stored_and_shown(panel, state):
    source = FmoSource()
    panel.changed.connect(lambda: panel.show_method(source, MethodOptions(), None))
    panel.show_method(source, MethodOptions(), None)

    # The dropdown starts on the dye that was found for the tube.
    combo = panel._inputs_table.cellWidget(2, 1)
    assert isinstance(combo, FlowComboBox) and combo.currentData() == "APC-A"
    assert combo.itemText(0) == "Detect again"
    combo.setCurrentIndex(combo.findData("PE-A"))
    combo.activated.emit(combo.currentIndex())

    assert state.data.experiment.samples["FMO APC"].fmo_minus == "PE-A"
    assert _column(panel._inputs_table, 3)[1:3] == [
        "not used — FMO APC already covers it",
        "set by you",
    ]
    assert panel._inputs_table.cellWidget(2, 1).currentData() == "PE-A"

    # Picking the dye already shown confirms it as the user's choice.
    combo = panel._inputs_table.cellWidget(0, 1)
    combo.activated.emit(combo.currentIndex())
    assert _column(panel._inputs_table, 3)[0] == "set by you"


def test_fit_on_offers_the_controls_scatter_gates_and_reports_events_used(panel, state):
    source, options = FmoSource(), MethodOptions()
    panel.show_method(source, options, None)
    assert not panel._gate_combo.isEnabled() and panel._gate_note.isVisible()

    _add_cells_gate(state, "FMO FITC", "FMO PE")
    panel.changed.connect(lambda: panel.show_method(source, options, None))
    panel.show_method(source, options, None)
    panel._gate_combo.setCurrentIndex(panel._gate_combo.findData("Cells"))

    assert options.gate == "Cells" and not panel._gate_note.isVisible()
    assert _column(panel._inputs_table, 4) == [
        "450 of 600 (in 'Cells')",
        "450 of 600 (in 'Cells')",
        "600 — all events: no 'Cells' gate on this sample",
    ]


def test_a_choice_that_no_longer_exists_falls_back_to_the_default(panel, state):
    options = MethodOptions(gate="Deleted gate", sample_id="gone")

    panel.show_method(FmoSource(), options, None)

    assert options.gate is None and options.sample_id is None


def test_fitting_on_a_gate_uses_only_that_population(state):
    _add_cells_gate(state, "FMO FITC", "FMO PE", "FMO APC")
    source = FmoSource()

    everything = source.obtain(state, None, MethodOptions())
    gated = source.obtain(state, None, MethodOptions(gate="Cells"))

    assert np.abs(gated.matrix.matrix - SPILLOVER).max() < 0.02
    assert not np.array_equal(gated.matrix.matrix, everything.matrix.matrix)
    assert "fitted on 'Cells'" in gated.summary and "fitted on" not in everything.summary
    # The report states how many events each fit really used.
    assert gated.report.rows[0][2] == "450 of 600 (in 'Cells')"
    assert everything.report.rows[0][2] == "600 — all events"


def test_fcs_method_shows_which_files_agree_and_reads_the_chosen_one(panel, state):
    other = SPILLOVER.copy()
    other[0, 1] = 0.5
    samples = state.data.experiment.samples
    samples["A"] = _fmo("A", 0, _spill_keyword(SPILLOVER))
    # Files round the last digits differently; that is still the same matrix.
    samples["B"] = _fmo("B", 0, _spill_keyword(SPILLOVER + 1e-7))
    samples["C"] = _fmo("C", 0, _spill_keyword(other))
    source, options = FcsMetadataSource(), MethodOptions()

    panel.show_method(source, options, None)

    table = panel._inputs_table
    assert dict(zip(_column(table, 0), _column(table, 2), strict=True)) == {
        "FMO FITC": "",
        "FMO PE": "",
        "FMO APC": "",
        "A": "read from this sample",
        "B": "same matrix",
        "C": "different matrix",
    }
    assert "Other files carry a different one" in source.readiness(state, options).text

    panel._sample_combo.setCurrentIndex(panel._sample_combo.findData("C"))
    assert options.sample_id == "C"
    assert source.obtain(state, None, options).matrix.matrix[0, 1] == 0.5


# ── In the view ───────────────────────────────────────────────────────


@pytest.fixture
def view(qtbot, state):
    view = CompensationView(state)
    qtbot.addWidget(view)
    view.show()
    return view


def test_running_a_method_shows_the_matrix_and_keeps_its_report(view, state):
    view._method_combo.setCurrentIndex(view._method_combo.findData("fmo"))
    assert view._body.currentWidget() is view._setup  # no matrix yet

    view._btn_run.click()
    assert view._body.currentWidget() is view._editor
    assert view._btn_matrix_page.isEnabled() and view._btn_matrix_page.isChecked()

    view._btn_setup_page.click()
    assert view._body.currentWidget() is view._setup
    report = view._setup._report_table
    assert report.isVisible() and _column(report, 0) == DYES
    assert _column(report, 1) == ["FMO FITC", "FMO PE", "FMO APC"]

    view._btn_matrix_page.click()
    assert view._body.currentWidget() is view._editor


def test_the_setup_page_follows_the_selected_method_and_keeps_its_options(view, state):
    _add_cells_gate(state, "FMO FITC")
    view.refresh()  # as on coming back from drawing the gate in the Workspace tab
    view._method_combo.setCurrentIndex(view._method_combo.findData("fmo"))
    view._setup._gate_combo.setCurrentIndex(view._setup._gate_combo.findData("Cells"))

    view._method_combo.setCurrentIndex(view._method_combo.findData("imported"))
    assert "Nothing is calculated" in view._setup._explanation.text()
    assert not view._setup._inputs_table.isVisible()

    view._method_combo.setCurrentIndex(view._method_combo.findData("fmo"))
    assert view._setup._gate_combo.currentData() == "Cells"
    view._btn_run.click()
    assert "fitted on 'Cells'" in view._note.text()


# ── The illustrated fit ───────────────────────────────────────────────


def test_fmo_method_can_draw_the_fit_of_each_tube_it_uses(state):
    source = FmoSource()

    assert source.illustration_choices(state) == [
        ("FMO FITC (no FITC-A)", "FITC-A"),
        ("FMO PE (no PE-A)", "PE-A"),
        ("FMO APC (no APC-A)", "APC-A"),
    ]
    fit = source.illustration(state, MethodOptions(), "PE-A")

    # FITC is what leaks into PE here (15%); the picture shows that pair.
    assert (fit.tube, fit.missing, fit.other) == ("FMO PE", "PE-A", "FITC-A")
    assert fit.slope == pytest.approx(0.15, abs=0.02)
    assert len(fit.x) == len(fit.y) == len(fit.ignored) == 600 and fit.events == 600
    # With the other dyes' share and the constant removed, y is just the leak.
    assert np.polyfit(fit.x[~fit.ignored], fit.y[~fit.ignored], 1)[0] == pytest.approx(
        fit.slope, abs=0.02
    )


def test_the_illustration_follows_the_fit_on_gate(state):
    _add_cells_gate(state, "FMO PE")

    fit = FmoSource().illustration(state, MethodOptions(gate="Cells"), "PE-A")

    assert fit.events == 450


def test_without_fmo_controls_the_method_is_shown_on_example_data():
    source, empty = FmoSource(), FlowState()

    [(label, key)] = source.illustration_choices(empty)
    fit = source.illustration(empty, MethodOptions(), key)

    assert "Example data" in label and fit.example
    assert fit.slope == pytest.approx(0.12, abs=0.01) and fit.ignored.any()


def test_the_page_draws_the_selected_tube_and_keeps_its_place_on_refresh(panel, state):
    source, options = FmoSource(), MethodOptions()
    panel.show_method(source, options, None)
    view = panel._illustration

    assert view is not None and view.isVisible()
    assert "FMO FITC has no FITC-A dye" in view._caption.text()

    view.go_to(2)
    panel.show_method(source, options, None)  # e.g. coming back to the tab
    assert view.step == 2

    panel._illustration_combo.setCurrentIndex(panel._illustration_combo.findData("PE-A"))
    assert view.step == 0 and "FMO PE has no PE-A dye" in view._caption.text()


def test_methods_with_nothing_to_draw_show_no_illustration(panel, state):
    panel.show_method(FmoSource(), MethodOptions(), None)
    panel.show_method(FcsMetadataSource(), MethodOptions(), None)

    assert not panel._illustration.isVisible()
    assert not panel._illustration_combo.isVisible()
