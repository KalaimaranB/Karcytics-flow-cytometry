"""Spillover matrix editor — the matrix table and its before/after preview."""

from __future__ import annotations

import typing
from dataclasses import replace

import numpy as np
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

if typing.TYPE_CHECKING:
    from karcytics_plugins.flow_cytometry.analysis.state import FlowState

from karcytics_sdk.plugin.components import repopulate_combo
from karcytics_sdk.plugin.theme_fallback import Colors, Fonts

from karcytics_plugins.flow_cytometry.analysis.compensation import (
    CompensationMatrix,
    compensate_events,
)
from karcytics_plugins.flow_cytometry.ui.widgets.compensation_preview import (
    VIEW_HISTOGRAM,
    VIEW_SCATTER,
    CompensationPreview,
    PreviewRequest,
)
from karcytics_plugins.flow_cytometry.ui.widgets.styled_combo import FlowComboBox

# Events drawn in the preview.
_PREVIEW_MAX_EVENTS = 10_000

# The two cells behind the plotted channel pair: X dye → Y detector, and back.
_X_INTO_Y_COLOR = "#2188FF"
_Y_INTO_X_COLOR = "#FFB74D"
_PAIR_CELL_ALPHA = 110

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
    """

    edited = pyqtSignal()

    def __init__(self, state: FlowState, parent=None):
        super().__init__(parent)
        self._state = state
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

        note_style = (
            f"color: {Colors.FG_SECONDARY}; font-size: {Fonts.SIZE_SMALL}px;"
            " background: transparent;"
        )

        # ── Left side: Matrix Editor ──
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)

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

        # What the two highlighted cells do to the plotted pair.
        self._pair_help = QLabel()
        self._pair_help.setWordWrap(True)
        self._pair_help.setTextFormat(Qt.TextFormat.RichText)
        self._pair_help.setStyleSheet(note_style)
        left_layout.addWidget(self._pair_help)

        splitter.addWidget(left_widget)

        # ── Right side: Visualization ──
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)

        right_layout.addLayout(self._build_controls())

        self._preview = CompensationPreview()
        right_layout.addWidget(self._preview.canvas, stretch=1)

        splitter.addWidget(right_widget)
        splitter.setSizes([450, 650])

    def _build_controls(self) -> QHBoxLayout:
        controls_layout = QHBoxLayout()
        self._sample_combo = FlowComboBox()
        self._x_combo = FlowComboBox()
        self._y_combo = FlowComboBox()
        self._view_combo = FlowComboBox()
        self._view_combo.addItem("Scatter (X vs Y)", VIEW_SCATTER)
        self._view_combo.addItem("Histogram (before vs after)", VIEW_HISTOGRAM)
        for text, combo, slot in (
            ("Sample:", self._sample_combo, self._update_plots),
            ("X (dye):", self._x_combo, self._on_pair_changed),
            ("Y (detector):", self._y_combo, self._on_pair_changed),
            ("View:", self._view_combo, self._update_plots),
        ):
            controls_layout.addWidget(QLabel(text))
            combo.currentIndexChanged.connect(slot)
            controls_layout.addWidget(combo)
        controls_layout.addStretch()
        return controls_layout

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
        keep = self._sample_combo.currentData() or self._state.view.current_sample_id
        self._sample_combo.blockSignals(True)
        repopulate_combo(self._sample_combo, items, restore_data=keep)
        self._sample_combo.blockSignals(False)
        self._update_plots()

    def _populate_matrix(self) -> None:
        self._table.blockSignals(True)
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
                    item.setToolTip(
                        f"{channels[i]} → {channels[j]}: share of {channels[i]}'s signal "
                        f"picked up by the {channels[j]} detector."
                    )
                self._table.setItem(i, j, item)
        self._table.blockSignals(False)

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
            + "<br>Tip: judge each cell on the single-stain control for its dye."
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
        # Keep where the matrix came from; record that it was adjusted by hand.
        self._matrix = replace(self._matrix, matrix=m, fine_tuned=True)
        self._refresh_pair_help()
        self._update_plots()
        self.edited.emit()

    # ── Preview ───────────────────────────────────────────────────────

    def _update_plots(self) -> None:
        sample_id = self._sample_combo.currentData()
        sample = self._state.data.experiment.samples.get(sample_id) if sample_id else None
        if not self._matrix or sample is None or sample.fcs_data is None:
            self._preview.show_message("Load a sample to preview the matrix.")
            return

        x_ch = self._x_combo.currentText()
        y_ch = self._y_combo.currentText()

        raw_events = getattr(sample.fcs_data, "raw_events", sample.fcs_data.events)
        if raw_events is None or x_ch not in raw_events.columns or y_ch not in raw_events.columns:
            self._preview.show_message(f"{sample.display_name} has no {x_ch} / {y_ch} data.")
            return

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
            self._preview.show_message(
                "This matrix can't be inverted — check the value you just entered."
            )
            return

        self._preview.render(
            PreviewRequest(
                before=before,
                after=after,
                x_param=x_ch,
                y_param=y_ch,
                x_scale=self._axis_manager.get_scale(x_ch, sample_id),
                y_scale=self._axis_manager.get_scale(y_ch, sample_id),
                view=self._view_combo.currentData(),
                caption=f"{sample.display_name} · {len(before):,} of {n_events:,} events",
                render_config=self._state.view.render_config,
            )
        )
