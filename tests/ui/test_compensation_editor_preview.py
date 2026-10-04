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
from karcytics_plugins.flow_cytometry.ui.widgets import compensation_editor
from karcytics_plugins.flow_cytometry.ui.widgets.compensation_editor import (
    ALL_SAMPLES,
    CompensationEditor,
)
from karcytics_plugins.flow_cytometry.ui.widgets.compensation_preview import (
    VIEW_BOTH,
    VIEW_HISTOGRAM,
    VIEW_SCATTER,
    PreviewRequest,
    render_preview_image,
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
    widget = CompensationEditor(state)
    qtbot.addWidget(widget)
    widget.load(state.data.compensation)
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

    assert dialog._matrix.matrix[0, 1] == 0.5
    assert dialog._matrix.matrix[1, 0] == 0.05
    assert "FL1-A → FL2-A</b> = 0.5000" in dialog._pair_help.text()
    assert _tinted(dialog) == {(0, 1), (1, 0)}  # highlighting survives the edit


def test_cells_explain_their_direction(dialog):
    assert "FL2-A → FL3-A" in dialog._table.item(1, 2).toolTip()
    assert "FL2-A detector" not in dialog._table.item(1, 2).toolTip()


# ── Preview ───────────────────────────────────────────────────────────


def test_sample_selector_lists_loaded_samples_and_starts_on_the_open_one(dialog):
    combo = dialog._sample_combo

    assert [combo.itemData(i) for i in range(combo.count())] == ["blank", "fl1", ALL_SAMPLES]
    assert combo.currentData() == "fl1"
    assert combo.currentText() == "FL1 stain · Single Stain"


def test_preview_compares_raw_events_with_the_edited_matrix(dialog, state):
    dialog._preview.render = MagicMock()
    dialog._table.item(0, 1).setText("0.1")

    request = dialog._preview.render.call_args.args[0]
    raw = state.data.experiment.samples["fl1"].fcs_data.raw_events
    expected = raw.to_numpy() @ np.linalg.inv(dialog._matrix.matrix)

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

    dialog._matrix.matrix[0, :] = 0.0  # a row of zeros has no inverse
    dialog._update_plots()

    assert "can't be inverted" in dialog._preview.show_message.call_args.args[0]


def test_no_loaded_sample_shows_a_message(qtbot):
    state = FlowState()
    state.data.compensation = CompensationMatrix(matrix=np.eye(2), channel_names=["A", "B"])
    dialog = CompensationEditor(state)
    qtbot.addWidget(dialog)
    dialog.load(state.data.compensation)

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


# ── Working copy ──────────────────────────────────────────────────────


def test_edits_stay_in_a_working_copy_until_the_owner_applies_them(dialog, state, qtbot):
    with qtbot.waitSignal(dialog.edited):
        dialog._table.item(0, 1).setText("0.5")

    assert dialog.matrix.matrix[0, 1] == 0.5
    assert state.data.compensation.matrix[0, 1] == 0.2  # the workspace is untouched


def test_load_discards_edits_and_none_clears_the_table(dialog, state):
    dialog._table.item(0, 1).setText("0.5")

    dialog.load(state.data.compensation)
    assert dialog.matrix.matrix[0, 1] == 0.2

    dialog.load(None)
    assert dialog.matrix is None
    assert dialog._table.rowCount() == 0


# ── Scatter and histograms together ───────────────────────────────────


def test_both_view_shows_the_scatter_pair_above_the_two_histograms(dialog):
    dialog._view_combo.setCurrentIndex(dialog._view_combo.findData(VIEW_BOTH))

    titles = [ax.get_title() for ax in dialog._preview.axes]
    assert titles == [
        "Before — raw signal",
        "After — with this matrix",
        "FL1-A — before vs after",
        "FL2-A — before vs after",
    ]
    rows = {round(ax.get_position().y0, 2) for ax in dialog._preview.axes}
    assert len(rows) == 2  # two rows of two


# ── Every sample at once ──────────────────────────────────────────────


class _Signal:
    def __init__(self):
        self._slots = []

    def connect(self, slot):
        self._slots.append(slot)

    def disconnect(self, slot):
        self._slots.remove(slot)

    def emit(self, *args):
        for slot in list(self._slots):
            slot(*args)


class _Scheduler:
    """Queues tasks like the app's scheduler; ``run()`` plays the worker threads."""

    def __init__(self):
        self.task_finished, self.task_error = _Signal(), _Signal()
        self.queue = []

    def submit(self, task, state):
        worker = MagicMock(task_id=f"task-{len(self.queue)}")
        self.queue.append((worker.task_id, task))
        return worker

    def run(self):
        queue, self.queue = self.queue, []
        for task_id, task in queue:
            self.task_finished.emit(task_id, task.run(None))


@pytest.fixture
def all_samples(qtbot, state, monkeypatch):
    """The editor on 'All samples', with the debounce collapsed and a hand-cranked scheduler."""
    monkeypatch.setattr(compensation_editor, "_ALL_SAMPLES_DEBOUNCE_MS", 0)
    scheduler = _Scheduler()
    state.view.current_sample_id = "fl1"
    editor = CompensationEditor(state, scheduler=scheduler)
    qtbot.addWidget(editor)
    editor.load(state.data.compensation)
    editor.show()
    editor._sample_combo.setCurrentIndex(editor._sample_combo.findData(ALL_SAMPLES))
    editor._all_timer.stop()
    editor._render_all_samples()
    return editor, scheduler


def test_all_samples_shows_a_placeholder_row_per_sample_then_its_plots(all_samples):
    editor, scheduler = all_samples
    grid = editor._all_preview

    assert editor._preview_stack.currentWidget() is grid
    assert list(grid._rows) == ["blank", "fl1"]  # the sample without data has no row
    assert [row.text() for row in grid._rows.values()] == [
        "Rendering Blank…",
        "Rendering FL1 stain…",
    ]
    assert len(scheduler.queue) == 2  # nothing is drawn on the UI thread

    scheduler.run()

    for row in grid._rows.values():
        assert row.text() == "" and not row.pixmap().isNull()


def test_an_edit_re_renders_every_row_and_drops_renders_that_are_out_of_date(all_samples):
    editor, scheduler = all_samples
    scheduler.run()
    shown = {key: row.pixmap().cacheKey() for key, row in editor._all_preview._rows.items()}

    editor._table.item(0, 1).setText("0.6")
    editor._all_timer.stop()
    editor._render_all_samples()
    stale = list(scheduler.queue)
    editor._table.item(0, 1).setText("0.7")  # typed again before those ran
    editor._all_timer.stop()
    editor._render_all_samples()

    # The old images stay up while the new ones are on the way (no flicker).
    rows = editor._all_preview._rows
    assert {key: row.pixmap().cacheKey() for key, row in rows.items()} == shown
    assert all(task.run(None) == {"stale": True} for _id, task in stale)
    scheduler.run()
    assert all(row.pixmap().cacheKey() != shown[key] for key, row in rows.items())


def test_leaving_all_samples_goes_back_to_the_live_canvas(all_samples):
    editor, _scheduler = all_samples

    editor._sample_combo.setCurrentIndex(editor._sample_combo.findData("fl1"))

    assert editor._preview_stack.currentWidget() is editor._preview.canvas
    assert not editor._all_timer.isActive()


def test_a_preview_row_is_one_line_of_plots_rendered_off_screen(state):
    raw = state.data.experiment.samples["fl1"].fcs_data.raw_events
    request = PreviewRequest(
        before=raw,
        after=raw @ np.linalg.inv(SPILLOVER),
        x_param="FL1-A",
        y_param="FL2-A",
        x_scale=compensation_editor_scale(state, "FL1-A"),
        y_scale=compensation_editor_scale(state, "FL2-A"),
        view=VIEW_BOTH,
        caption="FL1 stain",
    )
    request.after.columns = raw.columns

    image = render_preview_image(request, 1000, 250, pixel_ratio=2.0)

    assert (image["width"], image["height"]) == (2000, 500)
    assert len(image["image_data"]) == 2000 * 500 * 4


def compensation_editor_scale(state, channel):
    from karcytics_plugins.flow_cytometry.analysis.axis_manager import AxisManager

    return AxisManager(state).get_scale(channel, "fl1")


# ── Guidance ──────────────────────────────────────────────────────────


def test_the_editor_states_the_goal_and_offers_the_full_guide(dialog):
    assert "sit level with the negatives" in compensation_editor._GOAL_LINE
    assert dialog._guide_button.objectName() == "CompensationGuideButton"
    for topic in (
        "On the scatter plots",
        "On the histograms",
        "What the values should be",
        "Which sample to judge on",
        "Why look across samples",
    ):
        assert topic in compensation_editor._GUIDE


# ── Previewing one population ─────────────────────────────────────────


def _gate_fl1_high(sample) -> None:
    from karcytics_plugins.flow_cytometry.analysis.gating.rectangle import RectangleGate

    median = float(sample.fcs_data.events["FL1-A"].median())
    sample.gate_tree.add_child(RectangleGate("FL1-A", x_min=median), "FL1 high")


def test_population_selector_previews_only_the_events_in_that_gate(dialog, state):
    sample = state.data.experiment.samples["fl1"]
    _gate_fl1_high(sample)
    dialog.refresh_samples()
    combo = dialog._population_combo
    assert [combo.itemData(i) for i in range(combo.count())] == [None, "FL1 high"]
    dialog._preview.render = MagicMock()

    combo.setCurrentIndex(combo.findData("FL1 high"))

    request = dialog._preview.render.call_args.args[0]
    raw = sample.fcs_data.raw_events
    assert len(request.before) == 200  # the upper half of 400 events
    assert request.before["FL1-A"].min() >= raw["FL1-A"].median()
    assert request.caption == "FL1 stain · 200 of 200 events in 'FL1 high'"


def test_a_sample_without_the_population_is_previewed_whole_and_says_so(dialog, state):
    _gate_fl1_high(state.data.experiment.samples["fl1"])
    dialog.refresh_samples()
    dialog._population_combo.setCurrentIndex(dialog._population_combo.findData("FL1 high"))
    dialog._preview.render = MagicMock()

    dialog._sample_combo.setCurrentIndex(dialog._sample_combo.findData("blank"))

    caption = dialog._preview.render.call_args.args[0].caption
    assert caption == "Blank · 400 of 400 events (no 'FL1 high' gate: all events)"


def test_an_empty_population_shows_a_message(dialog, state):
    from karcytics_plugins.flow_cytometry.analysis.gating.rectangle import RectangleGate

    sample = state.data.experiment.samples["fl1"]
    sample.gate_tree.add_child(RectangleGate("FL1-A", x_min=1e12), "Nothing")
    dialog.refresh_samples()
    dialog._preview.show_message = MagicMock()

    dialog._population_combo.setCurrentIndex(dialog._population_combo.findData("Nothing"))

    assert dialog._preview.show_message.call_args.args[0] == (
        "FL1 stain has no events in 'Nothing'."
    )
