"""Spillover matrix editor — the matrix table and its before/after preview."""

from __future__ import annotations

import typing
from dataclasses import replace

import numpy as np
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

if typing.TYPE_CHECKING:
    from karcytics_plugins.flow_cytometry.analysis.state import FlowState

from karcytics_sdk.plugin.components import BioHelpButton, repopulate_combo
from karcytics_sdk.plugin.theme_fallback import Colors, Fonts

from karcytics_plugins.flow_cytometry.analysis.compensation import (
    CELL_DEFAULT,
    CELL_EDITED,
    CELL_ESTIMATED,
    CompensationMatrix,
    compensate_events,
)
from karcytics_plugins.flow_cytometry.analysis.fit_population import (
    population_gates,
    population_rows,
)
from karcytics_plugins.flow_cytometry.ui.widgets.compensation_preview import (
    VIEW_BOTH,
    VIEW_HISTOGRAM,
    VIEW_SCATTER,
    CompensationPreview,
    PreviewRequest,
)
from karcytics_plugins.flow_cytometry.ui.widgets.compensation_preview_grid import (
    CompensationPreviewGrid,
)
from karcytics_plugins.flow_cytometry.ui.widgets.styled_combo import FlowComboBox

# Events drawn in the preview.
_PREVIEW_MAX_EVENTS = 10_000
# The sample selector's entry for every sample at once, one row each.
ALL_SAMPLES = "__all__"
_ALL_EVENTS = "All events"
_MIN_SAMPLES_FOR_ALL = 2
# Typing in a cell re-renders every row; wait for a pause first.
_ALL_SAMPLES_DEBOUNCE_MS = 250

_GOAL_LINE = (
    "<b>Aim:</b> on the After side, events positive for one dye sit level with the "
    "negatives in the other detector — not tilted up, not pushed below."
)
_GUIDE_TITLE = "What a good matrix looks like"
_GUIDE = (
    "<b>The goal.</b> A dye should only be seen by its own detector. After compensation, "
    "cells that carry dye A but not dye B must read the same in B's detector as cells "
    "that carry neither. Each cell of the matrix is the one number that makes that true "
    "for one dye and one detector.<br><br>"
    "<b>On the scatter plots.</b> Look at the population that is bright on X only. "
    "Before, it climbs diagonally: the brighter the dye, the more leaks into Y. After, "
    "it should lie <b>level</b>, its centre at the same height as the negative "
    "population's centre.<br>"
    "• Still tilted upwards → the cell is too low (under-compensated).<br>"
    "• Bent downwards, below the negatives → the cell is too high (over-compensated).<br>"
    "• Bright events fan out wider than dim ones. That spread is measurement noise and "
    "no value removes it: judge the <b>centre</b> of the cloud, not its edges.<br><br>"
    "<b>On the histograms.</b> In a sample without dye B, the After curve of B's "
    "detector should be one peak centred on the unstained level (around zero), roughly "
    "symmetric. A tail or shoulder left on the right means under-compensated; a peak "
    "pushed left of zero means over-compensated.<br><br>"
    "<b>What the values should be.</b> There is no target number: a value is right when "
    "the plots are. As a sanity check, the diagonal is 1, most cells are between 0 and "
    "about 0.3, neighbouring dyes off the same laser are the large ones, and a value "
    "near or above 1 usually means the wrong pairing or a bad control.<br><br>"
    "<b>Which sample to judge on.</b> Judge a cell on a sample where its row dye is "
    "bright and its column dye is absent: the single-stain control for the row dye is "
    "ideal, an FMO lacking the column dye also works. Don't tune on fully stained "
    "samples alone: cells that really carry both markers look like spill, and "
    "compensating them away removes real biology.<br><br>"
    "<b>Why look across samples.</b> Spill is a property of the dyes and the instrument "
    "settings, not of a tube, so one matrix has to work for every sample of the run. "
    "<i>All samples</i> shows whether a value that fixes one tube tilts another: if it "
    "does, it was fitted to that tube's quirk, not to the spill. Samples that disagree "
    "consistently (tandem dyes that degraded, a tube acquired with other settings) "
    "need their own matrix."
)

# The two cells behind the plotted channel pair: X dye → Y detector, and back.
_X_INTO_Y_COLOR = "#2188FF"
_Y_INTO_X_COLOR = "#FFB74D"
_PAIR_CELL_ALPHA = 110

# How a cell's origin is shown (see ``CompensationMatrix.origin``).
_EDITED_COLOR = "#7EE787"
_ORIGIN_LEGEND = (
    "<i>Grey italic</i>: not set — nothing measured or entered for this cell, so it "
    f'is left at its default. &nbsp;<b style="color:{_EDITED_COLOR};">Green bold</b>: '
    "edited by hand. &nbsp;Plain: from the method."
)
_ORIGIN_NOTES = {
    CELL_DEFAULT: "\nNot set: nothing measured or entered for this cell, so it is left at 0.",
    CELL_EDITED: "\nEdited by hand.",
}

_MATRIX_CAPTION = (
    "<b>↓ Rows: dye</b> (the signal's source) &nbsp;·&nbsp; "
    "<b>→ Columns: detector</b> (where it spills into)<br>"
    "A cell is the share of the row dye's signal picked up by the column detector, so "
    "the two cells of a pair are separate numbers. Click a cell to plot its pair; "
    "double-click to fine-tune its value."
)


class CompensationEditor(QWidget):
    """Edits a working copy of a spillover matrix and previews its effect.

    The copy is handed in with ``load()`` and read back from ``matrix``;
    nothing here writes to the workspace — the owner decides when to apply.

    Signals:
        edited: a cell of the working copy changed.
        matrix_chosen: the user picked another matrix (its key from
            ``set_matrix_choices``) to edit instead.
    """

    edited = pyqtSignal()
    matrix_chosen = pyqtSignal(object)

    def __init__(self, state: FlowState, parent=None, scheduler=None):
        super().__init__(parent)
        self._state = state
        self._scheduler = scheduler  # renders the all-samples rows; None = the app's
        self._matrix: CompensationMatrix | None = None

        if self._state.axis_manager is not None:
            self._axis_manager = self._state.axis_manager
        else:
            from karcytics_plugins.flow_cytometry.analysis.axis_manager import AxisManager

            self._axis_manager = AxisManager(self._state)

        self._setup_ui()
        self.refresh_samples()
        self.load(None)

    # ── Public API ────────────────────────────────────────────────────

    @property
    def matrix(self) -> CompensationMatrix | None:
        """The working copy, including any edits."""
        return self._matrix

    def load(self, matrix: CompensationMatrix | None) -> None:
        """Start editing a private copy of ``matrix``, discarding any edits."""
        self._matrix = CompensationMatrix.from_dict(matrix.to_dict()) if matrix else None
        self._populate_matrix()
        self._on_pair_changed()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter)
        splitter.addWidget(self._build_matrix_side())
        splitter.addWidget(self._build_preview_side())
        splitter.setSizes([450, 650])

    def _build_matrix_side(self) -> QWidget:
        """The matrix table, with what its cells mean underneath."""
        note_style = (
            f"color: {Colors.FG_SECONDARY}; font-size: {Fonts.SIZE_SMALL}px;"
            " background: transparent;"
        )
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)

        # Which matrix is in the editor; the owner knows what there is to pick from.
        matrix_row = QHBoxLayout()
        matrix_label = QLabel("Matrix:")
        matrix_label.setStyleSheet(note_style)
        matrix_row.addWidget(matrix_label)
        self._matrix_combo = FlowComboBox()
        self._matrix_combo.setObjectName("EditorMatrixCombo")
        self._matrix_combo.setToolTip(
            "Switch the editor to another matrix kept in this workspace. Nothing is "
            "applied to the samples until you apply it from the Matrices page."
        )
        self._matrix_combo.activated.connect(
            lambda index: self.matrix_chosen.emit(self._matrix_combo.itemData(index))
        )
        matrix_row.addWidget(self._matrix_combo, stretch=1)
        left_layout.addLayout(matrix_row)

        caption = QLabel(_MATRIX_CAPTION)
        caption.setWordWrap(True)
        caption.setStyleSheet(note_style)
        left_layout.addWidget(caption)

        self._table = QTableWidget()
        self._table.itemChanged.connect(self._on_cell_changed)
        self._table.currentCellChanged.connect(self._on_current_cell_changed)
        self._table.setStyleSheet(
            f"background-color: {Colors.BG_DARKEST}; color: {Colors.FG_PRIMARY};"
        )
        left_layout.addWidget(self._table, stretch=1)

        self._origin_legend = QLabel(_ORIGIN_LEGEND)
        self._origin_legend.setWordWrap(True)
        self._origin_legend.setTextFormat(Qt.TextFormat.RichText)
        self._origin_legend.setStyleSheet(note_style)
        left_layout.addWidget(self._origin_legend)

        # What the two highlighted cells do to the plotted pair.
        self._pair_help = QLabel()
        self._pair_help.setWordWrap(True)
        self._pair_help.setTextFormat(Qt.TextFormat.RichText)
        self._pair_help.setStyleSheet(note_style)
        left_layout.addWidget(self._pair_help)

        goal_row = QHBoxLayout()
        goal = QLabel(_GOAL_LINE)
        goal.setWordWrap(True)
        goal.setTextFormat(Qt.TextFormat.RichText)
        goal.setStyleSheet(note_style)
        goal_row.addWidget(goal, stretch=1)
        self._guide_button = BioHelpButton()
        self._guide_button.setObjectName("CompensationGuideButton")
        self._guide_button.setHelpText(_GUIDE, title=_GUIDE_TITLE)
        goal_row.addWidget(self._guide_button)
        left_layout.addLayout(goal_row)

        return left_widget

    def _build_preview_side(self) -> QWidget:
        """The preview's selectors and the before/after plots."""
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)

        right_layout.addLayout(self._build_controls())

        # One sample on a live canvas, or every sample as background-rendered rows.
        self._preview = CompensationPreview()
        self._all_preview = CompensationPreviewGrid(self._scheduler)
        self._preview_stack = QStackedWidget()
        self._preview_stack.addWidget(self._preview.canvas)
        self._preview_stack.addWidget(self._all_preview)
        right_layout.addWidget(self._preview_stack, stretch=1)

        self._all_timer = QTimer(self)
        self._all_timer.setSingleShot(True)
        self._all_timer.setInterval(_ALL_SAMPLES_DEBOUNCE_MS)
        self._all_timer.timeout.connect(self._render_all_samples)

        return right_widget

    def _build_controls(self) -> QVBoxLayout:
        """The preview's selectors, on two rows: what to look at, then how.

        One row of five was wider than a laptop-sized window could give the
        preview, which then couldn't be made any narrower.
        """
        controls_layout = QVBoxLayout()
        what_row, how_row = QHBoxLayout(), QHBoxLayout()
        self._sample_combo = FlowComboBox()
        self._population_combo = FlowComboBox()
        self._population_combo.setObjectName("PreviewPopulationCombo")
        self._population_combo.setToolTip(
            "Preview only the events inside a gate (for example Cells). A sample "
            "without that gate is shown whole."
        )
        self._x_combo = FlowComboBox()
        self._y_combo = FlowComboBox()
        self._view_combo = FlowComboBox()
        self._view_combo.addItem("Scatter (X vs Y)", VIEW_SCATTER)
        self._view_combo.addItem("Histogram (before vs after)", VIEW_HISTOGRAM)
        self._view_combo.addItem("Scatter + histograms", VIEW_BOTH)
        for row, text, combo, slot in (
            (what_row, "Sample:", self._sample_combo, self._update_plots),
            (what_row, "Population:", self._population_combo, self._update_plots),
            (how_row, "X (dye):", self._x_combo, self._on_pair_changed),
            (how_row, "Y (detector):", self._y_combo, self._on_pair_changed),
            (how_row, "View:", self._view_combo, self._update_plots),
        ):
            row.addWidget(QLabel(text))
            combo.currentIndexChanged.connect(slot)
            row.addWidget(combo)
        for row in (what_row, how_row):
            row.addStretch()
            controls_layout.addLayout(row)
        return controls_layout

    def set_matrix_choices(self, choices: list[tuple[str, str]], current: str | None) -> None:
        """The matrices the editor can switch to, as (label, key), and the one it holds."""
        self._matrix_combo.blockSignals(True)
        self._matrix_combo.clear()
        for label, key in choices:
            self._matrix_combo.addItem(label, key)
        self._matrix_combo.setCurrentIndex(max(0, self._matrix_combo.findData(current)))
        self._matrix_combo.blockSignals(False)
        self._matrix_combo.setEnabled(len(choices) > 1)

    def refresh_samples(self) -> None:
        """List the samples that have data, keeping the one on show if it still does.

        Starts on the sample open in the workspace.
        """
        samples = self._state.data.experiment.samples
        items = [
            (f"{s.display_name} · {s.role.value.replace('_', ' ').title()}", s_id)
            for s_id, s in samples.items()
            if s.fcs_data is not None
        ]
        if len(items) >= _MIN_SAMPLES_FOR_ALL:
            items.append(("All samples (one row each)", ALL_SAMPLES))
        keep = self._sample_combo.currentData() or self._state.view.current_sample_id
        self._sample_combo.blockSignals(True)
        repopulate_combo(self._sample_combo, items, restore_data=keep)
        self._sample_combo.blockSignals(False)

        # Every population any loaded sample has, in first-seen order.
        populations = dict.fromkeys(
            path
            for sample in samples.values()
            if sample.fcs_data is not None
            for path in population_gates(sample)
        )
        self._population_combo.blockSignals(True)
        repopulate_combo(
            self._population_combo,
            [(_ALL_EVENTS, None), *((path, path) for path in populations)],
            restore_data=self._population_combo.currentData(),
        )
        self._population_combo.blockSignals(False)
        self._update_plots()

    def _populate_matrix(self) -> None:
        self._table.blockSignals(True)
        self._refresh_origin_legend()
        if not self._matrix:
            self._table.clear()
            self._table.setRowCount(0)
            self._table.setColumnCount(0)
            self._table.blockSignals(False)
            return

        channels = self._matrix.channel_names
        n = len(channels)
        self._table.setRowCount(n)
        self._table.setColumnCount(n)
        self._table.setHorizontalHeaderLabels(channels)
        self._table.setVerticalHeaderLabels(channels)

        items = [(ch, ch) for ch in channels]
        first = channels[0] if channels else None
        for combo, default in (
            (self._x_combo, first),
            (self._y_combo, channels[1] if n >= 2 else first),  # noqa: PLR2004
        ):
            combo.blockSignals(True)
            repopulate_combo(combo, items, restore_data=default)
            combo.blockSignals(False)

        for i in range(n):
            for j in range(n):
                val = self._matrix.matrix[i, j]
                item = QTableWidgetItem(f"{val:.4f}")
                if i == j:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    item.setToolTip(f"{channels[i]} in its own detector — always 1.")
                else:
                    self._style_by_origin(item, i, j)
                self._table.setItem(i, j, item)
        self._table.blockSignals(False)

    def _origin(self, row: int, col: int) -> int:
        origin = self._matrix.origin if self._matrix else None
        return CELL_ESTIMATED if origin is None else int(origin[row, col])

    def _style_by_origin(self, item: QTableWidgetItem, row: int, col: int) -> None:
        """Show whether the method produced a cell, skipped it, or the user set it.

        Callers block the table's signals: styling an item fires itemChanged.
        """
        assert self._matrix is not None
        channels = self._matrix.channel_names
        origin = self._origin(row, col)
        font = item.font()
        font.setItalic(origin == CELL_DEFAULT)
        font.setBold(origin == CELL_EDITED)
        item.setFont(font)
        item.setForeground(
            QColor(
                {CELL_DEFAULT: Colors.FG_DISABLED, CELL_EDITED: _EDITED_COLOR}.get(
                    origin, Colors.FG_PRIMARY
                )
            )
        )
        item.setToolTip(
            f"{channels[row]} → {channels[col]}: share of {channels[row]}'s signal "
            f"picked up by the {channels[col]} detector." + _ORIGIN_NOTES.get(origin, "")
        )

    def _refresh_origin_legend(self) -> None:
        """The legend only earns its space when some cell isn't from the method."""
        origin = self._matrix.origin if self._matrix else None
        self._origin_legend.setVisible(origin is not None and bool(origin.any()))

    # ── The plotted pair ──────────────────────────────────────────────

    def _on_current_cell_changed(self, row: int, col: int, *_previous: int) -> None:
        """Plot the pair behind the cell being edited: its dye on X, its detector on Y."""
        if row < 0 or col < 0 or row == col:
            return
        for combo, index in ((self._x_combo, row), (self._y_combo, col)):
            combo.blockSignals(True)
            combo.setCurrentIndex(index)
            combo.blockSignals(False)
        self._on_pair_changed()

    def _on_pair_changed(self) -> None:
        self._highlight_pair()
        self._refresh_pair_help()
        self._update_plots()

    def _pair_indices(self) -> tuple[int, int] | None:
        """Matrix indices of the plotted (X, Y) channels, if they are a real pair."""
        if not self._matrix:
            return None
        channels = self._matrix.channel_names
        x_ch, y_ch = self._x_combo.currentText(), self._y_combo.currentText()
        if x_ch not in channels or y_ch not in channels or x_ch == y_ch:
            return None
        return channels.index(x_ch), channels.index(y_ch)

    def _highlight_pair(self) -> None:
        """Tint the two cells that move the plotted pair; reset every other cell."""
        pair = self._pair_indices()
        tints = {}
        if pair is not None:
            x, y = pair
            tints = {(x, y): _X_INTO_Y_COLOR, (y, x): _Y_INTO_X_COLOR}

        self._table.blockSignals(True)  # setBackground fires itemChanged
        for i in range(self._table.rowCount()):
            for j in range(self._table.columnCount()):
                item = self._table.item(i, j)
                if item is None:
                    continue
                if (i, j) in tints:
                    color = QColor(tints[(i, j)])
                    color.setAlpha(_PAIR_CELL_ALPHA)
                    item.setBackground(color)
                elif i == j:
                    item.setBackground(QColor(Colors.BG_DARK))
                else:
                    item.setBackground(QBrush())
        self._table.blockSignals(False)

    def _refresh_pair_help(self) -> None:
        pair = self._pair_indices()
        if pair is None or self._matrix is None:
            self._pair_help.setText("Pick two different channels to see which cells correct them.")
            return
        x, y = pair
        channels, matrix = self._matrix.channel_names, self._matrix.matrix

        def _line(color: str, dye: int, detector: int, low: str, high: str) -> str:
            return (
                f'<span style="color:{color};">■</span> '
                f"<b>{channels[dye]} → {channels[detector]}</b> = {matrix[dye, detector]:.4f}: "
                f"{channels[dye]} signal spilling into the {channels[detector]} detector. "
                f"Too low and {channels[dye]}-positive events drift <b>{low}</b> on the After "
                f"plot; too high and they dip <b>{high}</b>."
            )

        self._pair_help.setText(
            _line(_X_INTO_Y_COLOR, x, y, "up", "down")
            + "<br>"
            + _line(_Y_INTO_X_COLOR, y, x, "right", "left")
        )

    def _on_cell_changed(self, item: QTableWidgetItem) -> None:
        if not self._matrix:
            return

        row = item.row()
        col = item.column()
        try:
            val = float(item.text())
        except ValueError:
            return  # Ignore invalid input
        # Recreate matrix because we can't mutate the cached inverse easily
        m = self._matrix.matrix.copy()
        m[row, col] = val
        origin = (
            np.zeros(m.shape, dtype=np.int8)
            if self._matrix.origin is None
            else self._matrix.origin.copy()
        )
        origin[row, col] = CELL_EDITED
        # Keep where the matrix came from; record that it was adjusted by hand.
        self._matrix = replace(self._matrix, matrix=m, fine_tuned=True, origin=origin)
        self._table.blockSignals(True)
        self._style_by_origin(item, row, col)
        self._table.blockSignals(False)
        self._refresh_origin_legend()
        self._refresh_pair_help()
        self._update_plots()
        self.edited.emit()

    # ── Preview ───────────────────────────────────────────────────────

    def _update_plots(self) -> None:
        if self._sample_combo.currentData() == ALL_SAMPLES:
            self._preview_stack.setCurrentWidget(self._all_preview)
            if not self._all_preview.isVisible():
                return  # rendered when the page is shown
            self._all_timer.start()
            return
        self._all_timer.stop()
        self._preview_stack.setCurrentWidget(self._preview.canvas)
        sample_id = self._sample_combo.currentData()
        request = (
            self._request_for(sample_id) if sample_id else "Load a sample to preview the matrix."
        )
        if isinstance(request, str):
            self._preview.show_message(request)
        else:
            self._preview.render(request)

    def _render_all_samples(self) -> None:
        samples = self._state.data.experiment.samples
        self._all_preview.show_requests(
            [
                (sample_id, sample.display_name, self._request_for(sample_id))
                for sample_id, sample in samples.items()
                if sample.fcs_data is not None
            ]
        )

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if self._sample_combo.currentData() == ALL_SAMPLES:
            self._all_timer.start()

    def _request_for(self, sample_id: str) -> PreviewRequest | str:
        """The preview of one sample with the matrix as edited — or why there is none."""
        sample = self._state.data.experiment.samples.get(sample_id)
        if not self._matrix or sample is None or sample.fcs_data is None:
            return "Load a sample to preview the matrix."

        x_ch = self._x_combo.currentText()
        y_ch = self._y_combo.currentText()

        raw_events = getattr(sample.fcs_data, "raw_events", sample.fcs_data.events)
        if raw_events is None or x_ch not in raw_events.columns or y_ch not in raw_events.columns:
            return f"{sample.display_name} has no {x_ch} / {y_ch} data."

        population = self._population_combo.currentData()
        where = ""
        if population is not None:
            rows = population_rows(sample, population)
            if rows is None:
                where = f" (no '{population}' gate: all events)"
            elif len(rows) == 0:
                return f"{sample.display_name} has no events in '{population}'."
            else:
                raw_events = raw_events.loc[rows]
                where = f" in '{population}'"

        # Downsample for preview performance
        n_events = len(raw_events)
        if n_events > _PREVIEW_MAX_EVENTS:
            # stable_subsample_mask, not Generator.choice — stable under
            # small population-size differences (see its docstring).
            from karcytics_plugins.flow_cytometry.analysis.rendering import stable_subsample_mask

            before = raw_events[stable_subsample_mask(n_events, _PREVIEW_MAX_EVENTS)].copy()
        else:
            before = raw_events.copy()

        try:
            after = compensate_events(before.copy(), self._matrix)
        except np.linalg.LinAlgError:
            return "This matrix can't be inverted — check the value you just entered."

        return PreviewRequest(
            before=before,
            after=after,
            x_param=x_ch,
            y_param=y_ch,
            x_scale=self._axis_manager.get_scale(x_ch, sample_id),
            y_scale=self._axis_manager.get_scale(y_ch, sample_id),
            view=self._view_combo.currentData(),
            caption=f"{sample.display_name} · {len(before):,} of {n_events:,} events{where}",
            render_config=self._state.view.render_config,
        )
