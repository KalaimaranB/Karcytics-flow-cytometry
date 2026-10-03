"""Tests for the spillover matrix editor's pair highlighting and before/after preview."""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest
from PyQt6.QtCore import Qt

from karcytics_plugins.flow_cytometry.analysis.compensation import CompensationMatrix
from karcytics_plugins.flow_cytometry.analysis.experiment import Sample, SampleRole
from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.ui.widgets.compensation_editor_dialog import (
    CompensationEditorDialog,
)
from karcytics_plugins.flow_cytometry.ui.widgets.compensation_preview import (
    VIEW_HISTOGRAM,
    VIEW_SCATTER,
)

pytestmark = pytest.mark.ui

CHANNELS = ["FL1-A", "FL2-A", "FL3-A"]
SPILLOVER = np.array([[1.0, 0.2, 0.0], [0.05, 1.0, 0.3], [0.0, 0.04, 1.0]])


def _sample(sample_id: str, name: str, role: SampleRole, seed: int) -> Sample:
    rng = np.random.default_rng(seed)
    true = np.abs(rng.normal(500, 200, (400, 3)))
    sample = Sample(sample_id=sample_id, display_name=name)
    sample.role = role
    sample.fcs_data = MagicMock()
    sample.fcs_data.raw_events = pd.DataFrame(true @ SPILLOVER, columns=CHANNELS)
    sample.fcs_data.events = sample.fcs_data.raw_events
    return sample


@pytest.fixture
def state():
    state = FlowState()
    state.data.compensation = CompensationMatrix(matrix=SPILLOVER.copy(), channel_names=CHANNELS)
    samples = state.data.experiment.samples
    samples["blank"] = _sample("blank", "Blank", SampleRole.UNSTAINED, 1)
    samples["fl1"] = _sample("fl1", "FL1 stain", SampleRole.SINGLE_STAIN, 2)
    samples["empty"] = Sample(sample_id="empty", display_name="Not loaded")
    return state


@pytest.fixture
def dialog(qtbot, state):
    state.view.current_sample_id = "fl1"
    widget = CompensationEditorDialog(state)
    qtbot.addWidget(widget)
    return widget


def _tinted(dialog) -> set[tuple[int, int]]:
    """Off-diagonal cells carrying a highlight."""
    table = dialog._table
    return {
        (i, j)
        for i in range(table.rowCount())
        for j in range(table.columnCount())
        if i != j and table.item(i, j).background().style() != Qt.BrushStyle.NoBrush
    }


# ── Matrix: direction and the plotted pair ────────────────────────────


def test_the_two_cells_of_the_plotted_pair_are_highlighted(dialog):
    assert (dialog._x_combo.currentText(), dialog._y_combo.currentText()) == ("FL1-A", "FL2-A")
    assert _tinted(dialog) == {(0, 1), (1, 0)}

    dialog._y_combo.setCurrentIndex(2)

    assert _tinted(dialog) == {(0, 2), (2, 0)}


def test_help_names_each_cell_of_the_pair_with_its_value(dialog):
    text = dialog._pair_help.text()

    assert "FL1-A → FL2-A</b> = 0.2000" in text
    assert "FL2-A → FL1-A</b> = 0.0500" in text


def test_selecting_a_cell_plots_its_dye_against_its_detector(dialog):
    dialog._table.setCurrentCell(2, 0)

    assert (dialog._x_combo.currentText(), dialog._y_combo.currentText()) == ("FL3-A", "FL1-A")
    assert _tinted(dialog) == {(2, 0), (0, 2)}


def test_selecting_a_diagonal_cell_keeps_the_current_pair(dialog):
    dialog._table.setCurrentCell(1, 1)

    assert (dialog._x_combo.currentText(), dialog._y_combo.currentText()) == ("FL1-A", "FL2-A")


def test_the_two_cells_of_a_pair_stay_independent(dialog):
    """Spillover is directional — editing one cell must never mirror into the other."""
    dialog._table.item(0, 1).setText("0.5")

    assert dialog._temp_matrix.matrix[0, 1] == 0.5
    assert dialog._temp_matrix.matrix[1, 0] == 0.05
    assert "FL1-A → FL2-A</b> = 0.5000" in dialog._pair_help.text()
    assert _tinted(dialog) == {(0, 1), (1, 0)}  # highlighting survives the edit


def test_cells_explain_their_direction(dialog):
    assert "FL2-A → FL3-A" in dialog._table.item(1, 2).toolTip()
    assert "FL2-A detector" not in dialog._table.item(1, 2).toolTip()


# ── Preview ───────────────────────────────────────────────────────────


def test_sample_selector_lists_loaded_samples_and_starts_on_the_open_one(dialog):
    combo = dialog._sample_combo

    assert [combo.itemData(i) for i in range(combo.count())] == ["blank", "fl1"]
    assert combo.currentData() == "fl1"
    assert combo.currentText() == "FL1 stain · Single Stain"


def test_preview_compares_raw_events_with_the_edited_matrix(dialog, state):
    dialog._preview.render = MagicMock()
    dialog._table.item(0, 1).setText("0.1")

    request = dialog._preview.render.call_args.args[0]
    raw = state.data.experiment.samples["fl1"].fcs_data.raw_events
    expected = raw.to_numpy() @ np.linalg.inv(dialog._temp_matrix.matrix)

    pd.testing.assert_frame_equal(request.before, raw)
    np.testing.assert_allclose(request.after.to_numpy(), expected)
    assert (request.x_param, request.y_param, request.view) == ("FL1-A", "FL2-A", VIEW_SCATTER)
    assert request.caption == "FL1 stain · 400 of 400 events"


def test_switching_sample_re_renders_with_that_sample(dialog):
    dialog._preview.render = MagicMock()

    dialog._sample_combo.setCurrentIndex(0)

    assert dialog._preview.render.call_args.args[0].caption.startswith("Blank")


def test_singular_matrix_shows_a_message_instead_of_raising(dialog):
    dialog._preview.show_message = MagicMock()

    dialog._temp_matrix.matrix[0, :] = 0.0  # a row of zeros has no inverse
    dialog._update_plots()

    assert "can't be inverted" in dialog._preview.show_message.call_args.args[0]


def test_no_loaded_sample_shows_a_message(qtbot):
    state = FlowState()
    state.data.compensation = CompensationMatrix(matrix=np.eye(2), channel_names=["A", "B"])
    dialog = CompensationEditorDialog(state)
    qtbot.addWidget(dialog)

    assert dialog._sample_combo.count() == 0
    assert any("Load a sample" in t.get_text() for t in dialog._preview._fig.texts)


def test_scatter_view_labels_both_sides(dialog):
    left, right = dialog._preview._left, dialog._preview._right

    assert (left.get_title(), right.get_title()) == (
        "Before — raw signal",
        "After — with this matrix",
    )
    assert left.get_xlabel() == right.get_xlabel() == "FL1-A"
    assert left.get_ylabel() == right.get_ylabel() == "FL2-A"
    assert left.get_xlim() == right.get_xlim() and left.get_ylim() == right.get_ylim()


def test_histogram_view_overlays_before_and_after_per_channel(dialog):
    dialog._view_combo.setCurrentIndex(dialog._view_combo.findData(VIEW_HISTOGRAM))
    left, right = dialog._preview._left, dialog._preview._right

    assert (left.get_title(), right.get_title()) == (
        "FL1-A — before vs after",
        "FL2-A — before vs after",
    )
    for ax in (left, right):
        assert [t.get_text() for t in ax.get_legend().get_texts()] == [
            "Before (raw)",
            "After (this matrix)",
        ]
        # One filled histogram per version (plus any axis shading).
        assert len(ax.patches) >= 2
