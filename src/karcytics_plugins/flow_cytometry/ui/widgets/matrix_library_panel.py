"""Matrices — the matrices kept in this workspace, side by side.

Lists the matrix in the editor and every saved one, shows the selected
matrix (optionally against another, cell by cell), and is where a matrix
is named, exported and applied to the samples.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from karcytics_sdk.plugin import get_logger
from karcytics_sdk.plugin.components import PrimaryButton, SecondaryButton
from karcytics_sdk.plugin.dialogs import show_error
from karcytics_sdk.plugin.theme_fallback import Colors, Fonts, theme_manager
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from karcytics_plugins.flow_cytometry.analysis.compensation import (
    CompensationMatrix,
    SavedMatrix,
    export_matrix_to_csv,
)
from karcytics_plugins.flow_cytometry.analysis.services import experiment_edits
from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.ui.widgets.styled_combo import FlowComboBox

logger = get_logger(__name__, "flow_cytometry")

_CURRENT_KEY = "current"
_CURRENT_TITLE = "Current matrix (in the editor)"
_IN_USE_MARK = "  ✓ in use"
_EMPTY_TEXT = (
    "No matrices yet. Run a method at the top to get one; every run is kept here, and "
    "you can save fine-tuned versions under their own names."
)
_HIGHER_COLOR = "#FFB74D"
_LOWER_COLOR = "#2188FF"
# A difference this large gets the full tint; smaller ones fade towards none.
_FULL_TINT_DIFFERENCE = 0.05
_MAX_TINT_ALPHA = 150
# Below this two cells count as equal (four decimals are shown).
_SAME_VALUE = 5e-5


@dataclass(frozen=True)
class _Entry:
    key: str  # _CURRENT_KEY, or a saved matrix's id
    title: str
    matrix: CompensationMatrix
    saved: SavedMatrix | None  # None for the editor's matrix


def same_values(a: CompensationMatrix | None, b: CompensationMatrix | None) -> bool:
    """Same channels and, to the four decimals shown, the same numbers."""
    if a is None or b is None:
        return a is b
    return (
        a.channel_names == b.channel_names
        and a.matrix.shape == b.matrix.shape
        and np.allclose(a.matrix, b.matrix, rtol=0.0, atol=_SAME_VALUE)
    )


class MatrixLibraryPanel(QWidget):
    """Browse, compare, name, export and apply the workspace's matrices.

    Signals:
        apply_requested: apply this matrix to the samples — a ``SavedMatrix``,
            or None for the editor's current matrix.
        open_requested: load this ``SavedMatrix`` into the editor.
        note: one line describing what an action here just did.
    """

    apply_requested = pyqtSignal(object)
    open_requested = pyqtSignal(object)
    note = pyqtSignal(str)

    def __init__(
        self,
        state: FlowState,
        describe: Callable[[CompensationMatrix], str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._state = state
        self._describe = describe  # a matrix's method, in words (plain text)
        self._entries: list[_Entry] = []
        self.setObjectName("MatrixLibraryPanel")
        self._setup_ui()

    # ── UI ────────────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter)
        splitter.addWidget(self._build_list_side())
        splitter.addWidget(self._build_matrix_side())
        splitter.setSizes([340, 760])

        theme_manager.apply_style(
            self,
            f"QLabel {{ color: {{FG_SECONDARY}}; font-size: {Fonts.SIZE_SMALL}px;"
            " background: transparent; }"
            " QListWidget, QTableWidget { background: {BG_DARKEST}; color: {FG_PRIMARY};"
            " border: 1px solid {BORDER}; }"
            " QListWidget::item { padding: 6px 8px; }"
            " QListWidget::item:selected { background: {BG_MEDIUM}; color: {FG_PRIMARY}; }",
        )

    def _build_list_side(self) -> QWidget:
        """The matrices, and the buttons that manage the saved ones."""
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self._list = QListWidget()
        self._list.setObjectName("MatrixLibraryList")
        self._list.currentRowChanged.connect(lambda _row: self._on_selection_changed())
        left_layout.addWidget(self._list, stretch=1)

        manage = QHBoxLayout()
        self._btn_save = SecondaryButton("💾 Save current as…")
        self._btn_save.setToolTip("Keep the matrix in the editor under a name of its own.")
        self._btn_save.clicked.connect(self._on_save_current)
        self._btn_rename = SecondaryButton("Rename")
        self._btn_rename.clicked.connect(self._on_rename)
        self._btn_delete = SecondaryButton("Delete")
        self._btn_delete.clicked.connect(self._on_delete)
        for button in (self._btn_save, self._btn_rename, self._btn_delete):
            manage.addWidget(button)
        manage.addStretch()
        left_layout.addLayout(manage)
        return left

    def _build_matrix_side(self) -> QWidget:
        """The selected matrix, what it is compared with, and what to do with it."""
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

        compare = QHBoxLayout()
        self._title = QLabel()
        self._title.setTextFormat(Qt.TextFormat.RichText)
        compare.addWidget(self._title, stretch=1)
        compare.addWidget(QLabel("Compare with:"))
        self._compare_combo = FlowComboBox()
        self._compare_combo.setObjectName("MatrixCompareCombo")
        self._compare_combo.currentIndexChanged.connect(lambda _i: self._show_selected())
        compare.addWidget(self._compare_combo)
        right_layout.addLayout(compare)

        self._table = QTableWidget()
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        right_layout.addWidget(self._table, stretch=1)

        self._summary = QLabel()
        self._summary.setWordWrap(True)
        self._summary.setTextFormat(Qt.TextFormat.RichText)
        right_layout.addWidget(self._summary)

        actions = QHBoxLayout()
        self._btn_open = SecondaryButton("✏ Open in editor")
        self._btn_open.setToolTip("Load this saved matrix into the Matrix page to fine-tune it.")
        self._btn_open.clicked.connect(self._on_open)
        self._btn_export = SecondaryButton("📤 Export CSV")
        self._btn_export.setToolTip("Save the selected matrix as a CSV file.")
        self._btn_export.clicked.connect(self._on_export)
        self._btn_apply = PrimaryButton("✅ Apply to all samples")
        self._btn_apply.setObjectName("ApplyAllButton")
        self._btn_apply.setToolTip(
            "Make the selected matrix the workspace's matrix and compensate every loaded "
            "sample with it."
        )
        self._btn_apply.clicked.connect(self._on_apply)
        actions.addStretch()
        actions.addWidget(self._btn_open)
        actions.addWidget(self._btn_export)
        actions.addWidget(self._btn_apply)
        right_layout.addLayout(actions)
        return right

    # ── Public API ────────────────────────────────────────────────────

    def refresh(self, current: CompensationMatrix | None) -> None:
        """Re-read the library; ``current`` is the matrix in the editor."""
        selected = self._selected_key()
        compared = self._compare_combo.currentData()
        self._entries = []
        if current is not None:
            self._entries.append(_Entry(_CURRENT_KEY, _CURRENT_TITLE, current, None))
        self._entries += [
            _Entry(saved.saved_id, saved.name, saved.matrix, saved)
            for saved in self._state.data.matrix_library
        ]

        in_use = self._state.data.compensation
        self._list.blockSignals(True)
        self._list.clear()
        for entry in self._entries:
            mark = _IN_USE_MARK if in_use is not None and same_values(entry.matrix, in_use) else ""
            item = QListWidgetItem(f"{entry.title}{mark}\n{self._describe(entry.matrix)}")
            item.setData(Qt.ItemDataRole.UserRole, entry.key)
            self._list.addItem(item)
        keys = [entry.key for entry in self._entries]
        self._list.setCurrentRow(keys.index(selected) if selected in keys else 0 if keys else -1)
        self._list.blockSignals(False)
        self._fill_compare(compared)
        self._show_selected()

    # ── Selection ─────────────────────────────────────────────────────

    def _selected_key(self) -> str | None:
        item = self._list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    def _entry(self, key: str | None) -> _Entry | None:
        return next((entry for entry in self._entries if entry.key == key), None)

    def _on_selection_changed(self) -> None:
        self._fill_compare(self._compare_combo.currentData())
        self._show_selected()

    def _fill_compare(self, keep: str | None) -> None:
        """Every other matrix can be compared against; keep the choice if it is still there."""
        selected = self._selected_key()
        self._compare_combo.blockSignals(True)
        self._compare_combo.clear()
        self._compare_combo.addItem("— nothing —", None)
        for entry in self._entries:
            if entry.key != selected:
                self._compare_combo.addItem(entry.title, entry.key)
        self._compare_combo.setCurrentIndex(max(0, self._compare_combo.findData(keep)))
        self._compare_combo.blockSignals(False)

    # ── The matrix on show ────────────────────────────────────────────

    def _show_selected(self) -> None:
        entry = self._entry(self._selected_key())
        other = self._entry(self._compare_combo.currentData())
        saved = entry is not None and entry.saved is not None
        self._btn_save.setEnabled(self._entry(_CURRENT_KEY) is not None)
        self._btn_rename.setEnabled(saved)
        self._btn_delete.setEnabled(saved)
        self._btn_open.setEnabled(saved)
        self._btn_export.setEnabled(entry is not None)
        self._btn_apply.setEnabled(entry is not None)
        self._compare_combo.setEnabled(len(self._entries) > 1)

        self._table.clear()
        if entry is None:
            self._table.setRowCount(0)
            self._table.setColumnCount(0)
            self._title.setText("")
            self._summary.setText(_EMPTY_TEXT)
            return
        matrix = entry.matrix
        channels = matrix.channel_names
        self._title.setText(f"<b>{entry.title}</b> · {self._describe(matrix)}")
        self._table.setRowCount(len(channels))
        self._table.setColumnCount(len(channels))
        self._table.setHorizontalHeaderLabels(channels)
        self._table.setVerticalHeaderLabels(channels)

        comparable = other is not None and other.matrix.channel_names == channels
        differences: list[tuple[float, int, int]] = []
        for i, row_channel in enumerate(channels):
            for j, column_channel in enumerate(channels):
                value = float(matrix.matrix[i, j])
                item = QTableWidgetItem(f"{value:.4f}")
                item.setToolTip(f"{row_channel} → {column_channel}")
                if i == j:
                    item.setBackground(QColor(Colors.BG_DARK))
                elif comparable and other is not None:
                    delta = value - float(other.matrix.matrix[i, j])
                    if abs(delta) > _SAME_VALUE:
                        differences.append((delta, i, j))
                        item.setText(f"{value:.4f}  ({delta:+.4f})")
                        item.setBackground(_tint(delta))
                        item.setToolTip(
                            f"{row_channel} → {column_channel}: {value:.4f} here, "
                            f"{value - delta:.4f} in {other.title}"
                        )
                self._table.setItem(i, j, item)
        self._table.resizeColumnsToContents()
        self._summary.setText(self._summarise(entry, other, comparable, differences))

    @staticmethod
    def _summarise(
        entry: _Entry,
        other: _Entry | None,
        comparable: bool,
        differences: list[tuple[float, int, int]],
    ) -> str:
        channels = entry.matrix.channel_names
        if other is None:
            return "Rows are dyes, columns are detectors. Pick another matrix to compare against."
        if not comparable:
            return f"<b>{other.title}</b> has different channels, so it can't be compared cell by cell."
        if not differences:
            return f"Identical to <b>{other.title}</b> (to four decimals)."
        delta, i, j = max(differences, key=lambda d: abs(d[0]))
        return (
            f"<b>{len(differences)} cell(s) differ</b> from <b>{other.title}</b>; shown as "
            f"this matrix's value and (difference). "
            f'<span style="color:{_HIGHER_COLOR};">■</span> higher here, '
            f'<span style="color:{_LOWER_COLOR};">■</span> lower here. '
            f"Largest: {channels[i]} → {channels[j]}, {delta:+.4f}."
        )

    # ── Actions ───────────────────────────────────────────────────────

    def _ask_name(self, title: str, suggestion: str) -> str | None:
        name, accepted = QInputDialog.getText(self, title, "Name:", text=suggestion)
        return name.strip() if accepted and name.strip() else None

    def _on_save_current(self) -> None:
        current = self._entry(_CURRENT_KEY)
        if current is None:
            return
        name = self._ask_name("Save Matrix", self._describe(current.matrix))
        saved = experiment_edits.save_matrix(self._state, name, current.matrix) if name else None
        if saved is None:
            return
        self.refresh(current.matrix)
        self._select(saved.saved_id)
        self.note.emit(f"Saved the current matrix as '{saved.name}'.")

    def _on_rename(self) -> None:
        entry = self._entry(self._selected_key())
        if entry is None or entry.saved is None:
            return
        name = self._ask_name("Rename Matrix", entry.saved.name)
        if name and experiment_edits.rename_matrix(self._state, entry.saved.saved_id, name):
            self._refresh_keeping_current()

    def _on_delete(self) -> None:
        entry = self._entry(self._selected_key())
        if entry is None or entry.saved is None:
            return
        if experiment_edits.delete_matrix(self._state, entry.saved.saved_id):
            self._refresh_keeping_current()
            self.note.emit(f"Deleted the saved matrix '{entry.saved.name}' (Undo brings it back).")

    def _refresh_keeping_current(self) -> None:
        current = self._entry(_CURRENT_KEY)
        self.refresh(current.matrix if current is not None else None)

    def _select(self, key: str) -> None:
        keys = [entry.key for entry in self._entries]
        if key in keys:
            self._list.setCurrentRow(keys.index(key))

    def _on_open(self) -> None:
        entry = self._entry(self._selected_key())
        if entry is not None and entry.saved is not None:
            self.open_requested.emit(entry.saved)

    def _on_apply(self) -> None:
        entry = self._entry(self._selected_key())
        if entry is not None:
            self.apply_requested.emit(entry.saved)

    def _on_export(self) -> None:
        entry = self._entry(self._selected_key())
        if entry is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Spillover Matrix",
            "spillover_matrix.csv",
            "CSV Files (*.csv);;TSV Files (*.tsv)",
        )
        if not path:
            return
        try:
            export_matrix_to_csv(entry.matrix, Path(path))
        except Exception as exc:
            logger.error("Matrix export failed: %s", exc)
            show_error(self, "Export Error", f"Failed to export matrix:\n{exc}")
            return
        self.note.emit(f"{entry.title} saved to {Path(path).name}.")


def _tint(delta: float) -> QColor:
    color = QColor(_HIGHER_COLOR if delta > 0 else _LOWER_COLOR)
    strength = min(1.0, abs(delta) / _FULL_TINT_DIFFERENCE)
    color.setAlpha(int(40 + (_MAX_TINT_ALPHA - 40) * strength))
    return color
