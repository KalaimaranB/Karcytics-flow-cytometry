"""Compensation view — the Compensation tab's full-window workspace.

The header walks the two steps every matrix goes through: pick a method and
run it (one ``MatrixSource`` per method), then fine-tune the result by hand
and apply it. Below: the matrix editor with its before/after preview, or an
empty state until there is a matrix.

Edits are a draft: they change the workspace only when the user applies
them, so every keystroke doesn't recompensate every sample.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from karcytics_sdk.plugin import CentralEventBus, get_logger
from karcytics_sdk.plugin.components import PrimaryButton, SecondaryButton
from karcytics_sdk.plugin.dialogs import show_error, show_warning
from karcytics_sdk.plugin.theme_fallback import Fonts, theme_manager
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from karcytics_plugins.flow_cytometry.analysis import events
from karcytics_plugins.flow_cytometry.analysis.compensation import (
    CompensationMatrix,
    export_matrix_to_csv,
)
from karcytics_plugins.flow_cytometry.analysis.services import experiment_edits
from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.ui.widgets.compensation_editor import CompensationEditor
from karcytics_plugins.flow_cytometry.ui.widgets.matrix_sources import (
    MATRIX_SOURCES,
    MatrixSource,
    MatrixSourceError,
)
from karcytics_plugins.flow_cytometry.ui.widgets.styled_combo import FlowComboBox

logger = get_logger(__name__, "flow_cytometry")

_NO_MATRIX_TEXT = (
    "No compensation matrix yet.\n\n"
    "Pick a method above and run it: read the matrix from your FCS files, calculate it\n"
    "from single-stain or FMO controls, or import a CSV. Then fine-tune it here."
)
_NO_ADVANCED_TEXT = "Advanced algorithms — none available yet"
_RUN_BUTTON_NAME = "RunMethodButton"
_FINE_TUNE_HINT = " Fine-tune any cell below, then Apply to All."


def _step_label(text: str) -> QLabel:
    label = QLabel(f"<b>{text}</b>")
    label.setTextFormat(Qt.TextFormat.RichText)
    return label


def _same_matrix(a: CompensationMatrix | None, b: CompensationMatrix | None) -> bool:
    if a is None or b is None:
        return a is b
    return a.channel_names == b.channel_names and np.array_equal(a.matrix, b.matrix)


class CompensationView(QWidget):
    """Centre view for the Compensation tab.

    Signals:
        compensation_changed: the workspace's matrix, or the data it is
            applied to, changed.
    """

    compensation_changed = pyqtSignal()

    def __init__(
        self,
        state: FlowState,
        sources: tuple[MatrixSource, ...] = MATRIX_SOURCES,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._state = state
        self._sources = sources
        # The loaded samples still hold values from an older matrix.
        self._data_stale = False
        # The workspace matrix the editor's working copy was taken from.
        self._draft_base: CompensationMatrix | None = None
        # The user picked a method themselves; stop following the default.
        self._method_picked = False
        self._is_alive = True
        self.setObjectName("CompensationView")
        self._setup_ui()

        # Undo/redo and workflow loads replace the matrix behind this view.
        CentralEventBus.subscribe(events.STATE_RESTORED, self._on_state_restored)
        self.destroyed.connect(self.cleanup)
        self.refresh()

    # ── UI ────────────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QWidget()
        header.setObjectName("CompensationHeader")
        header.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(16, 10, 16, 10)
        header_layout.setSpacing(8)
        header_layout.addLayout(self._build_method_row())
        self._method_hint = QLabel()  # what the selected method needs / found
        self._method_hint.setWordWrap(True)
        header_layout.addWidget(self._method_hint)
        header_layout.addLayout(self._build_status_row())
        theme_manager.apply_style(
            header,
            "#CompensationHeader { background: {BG_DARK}; border-bottom: 1px solid {BORDER}; }"
            f" QLabel {{ color: {{FG_SECONDARY}}; font-size: {Fonts.SIZE_SMALL}px;"
            " background: transparent; }",
        )
        layout.addWidget(header)

        self._body = QStackedWidget()
        self._empty = QLabel(_NO_MATRIX_TEXT)
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        theme_manager.apply_style(
            self._empty,
            f"color: {{FG_DISABLED}}; font-size: {Fonts.SIZE_SMALL}px; background: {{BG_DARKEST}};",
        )
        self._editor = CompensationEditor(self._state)
        self._editor.edited.connect(self._refresh_status)
        self._body.addWidget(self._empty)
        self._body.addWidget(self._editor)
        layout.addWidget(self._body, stretch=1)

    def _build_method_row(self) -> QHBoxLayout:
        """Step 1: the method selector and its run button, then the matrix actions."""
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(_step_label("1 · Get a matrix"))
        row.addWidget(QLabel("Method:"))

        self._method_combo = FlowComboBox()
        self._method_combo.setObjectName("CompensationMethodCombo")
        for source in (s for s in self._sources if not s.advanced):
            self._method_combo.addItem(source.label, source.key)
        self._method_combo.insertSeparator(self._method_combo.count())
        advanced = [s for s in self._sources if s.advanced]
        for source in advanced:
            self._method_combo.addItem(source.label, source.key)
        if not advanced:
            # The slot stays visible so the techniques read as one list.
            self._method_combo.addItem(_NO_ADVANCED_TEXT, None)
            # Qt's own role for an item's flags: 0 makes it unselectable.
            self._method_combo.setItemData(
                self._method_combo.count() - 1, 0, Qt.ItemDataRole.UserRole - 1
            )
        self._method_combo.activated.connect(self._on_method_picked)
        self._method_combo.currentIndexChanged.connect(self._refresh_method)
        row.addWidget(self._method_combo)

        self._btn_run = PrimaryButton("")
        self._btn_run.clicked.connect(self._on_run_method)
        row.addWidget(self._btn_run)
        row.addStretch()

        self._btn_export = SecondaryButton("📤 Export CSV")
        self._btn_export.setToolTip("Export the current spillover matrix to CSV.")
        self._btn_export.clicked.connect(self._on_export_csv)
        row.addWidget(self._btn_export)

        self._btn_toggle = SecondaryButton("🔄 Toggle Compensation")
        self._btn_toggle.setToolTip(
            "Toggle compensation on/off for all loaded samples to verify raw vs compensated states."
        )
        self._btn_toggle.clicked.connect(self._on_toggle_compensation)
        row.addWidget(self._btn_toggle)
        return row

    def _build_status_row(self) -> QHBoxLayout:
        """Step 2: what the matrix is and where it came from, then revert/apply."""
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(_step_label("2 · Fine-tune & apply"), alignment=Qt.AlignmentFlag.AlignTop)
        status = QVBoxLayout()
        status.setSpacing(2)
        self._status = QLabel()
        self._status.setTextFormat(Qt.TextFormat.RichText)
        self._note = QLabel()  # outcome of the last action
        self._note.setWordWrap(True)
        status.addWidget(self._status)
        status.addWidget(self._note)
        row.addLayout(status, stretch=1)

        self._btn_revert = SecondaryButton("↩ Revert Edits")
        self._btn_revert.setToolTip("Discard your edits and go back to the workspace's matrix.")
        self._btn_revert.clicked.connect(self._on_revert)
        row.addWidget(self._btn_revert)

        self._btn_apply = PrimaryButton("✅ Apply to All")
        self._btn_apply.setObjectName("ApplyAllButton")
        self._btn_apply.setToolTip(
            "Save any edits and apply the compensation matrix to all loaded samples."
        )
        self._btn_apply.clicked.connect(self._on_apply_all)
        row.addWidget(self._btn_apply)
        return row

    # ── State sync ────────────────────────────────────────────────────

    @property
    def has_unapplied_edits(self) -> bool:
        return not _same_matrix(self._editor.matrix, self._state.data.compensation)

    def refresh(self) -> None:
        """Re-read the workspace. Unapplied edits survive (the tab can be left
        and come back to) unless the workspace's matrix was replaced under them.
        """
        workspace = self._state.data.compensation
        if not self.has_unapplied_edits or not _same_matrix(self._draft_base, workspace):
            self._load(workspace)
        self._editor.refresh_samples()
        if not self._method_picked:
            self._select_method(self._default_source())
        self._refresh_method()
        self._refresh_status()

    # ── Method selection ──────────────────────────────────────────────

    def _source(self, key: str | None) -> MatrixSource | None:
        return next((s for s in self._sources if s.key == key), None)

    def _default_source(self) -> MatrixSource | None:
        """The method behind the current matrix; with none, the first that can run."""
        matrix = self._state.data.compensation
        used = self._source(matrix.source) if matrix is not None else None
        ready = (s for s in self._sources if s.readiness(self._state)[0])
        return used or next(ready, None) or next(iter(self._sources), None)

    def _select_method(self, source: MatrixSource | None) -> None:
        index = self._method_combo.findData(source.key) if source is not None else -1
        if index >= 0:
            self._method_combo.setCurrentIndex(index)

    def _on_method_picked(self, _index: int) -> None:
        self._method_picked = True

    def _refresh_method(self) -> None:
        """Point the run button and the hint at the selected method."""
        source = self._source(self._method_combo.currentData())
        self._btn_run.setEnabled(source is not None)
        if source is None:
            return
        self._btn_run.setText(source.action)
        self._btn_run.setToolTip(source.tooltip)
        self._btn_run.setObjectName(source.object_name or _RUN_BUTTON_NAME)
        self._method_combo.setToolTip(source.tooltip)
        readiness = source.readiness(self._state)
        self._method_hint.setText(readiness.text)
        self._method_hint.setToolTip(readiness.detail)

    def _on_run_method(self) -> None:
        source = self._source(self._method_combo.currentData())
        if source is not None:
            self._on_source(source)

    def _describe_method(self, matrix: CompensationMatrix) -> str:
        source = self._source(matrix.source)
        text = f"method: <b>{source.label if source else matrix.source}</b>"
        return text + (", then <b>fine-tuned by hand</b>" if matrix.fine_tuned else "")

    def _load(self, matrix: CompensationMatrix | None) -> None:
        self._draft_base = matrix
        self._editor.load(matrix)

    def _refresh_status(self) -> None:
        matrix = self._state.data.compensation
        has_matrix = self._editor.matrix is not None
        dirty = self.has_unapplied_edits
        self._body.setCurrentWidget(self._editor if has_matrix else self._empty)
        self._btn_revert.setVisible(dirty)
        for button in (self._btn_apply, self._btn_export, self._btn_toggle):
            button.setEnabled(has_matrix)

        if matrix is None:
            self._status.setText("No compensation matrix.")
            return
        samples = [s for s in self._state.data.experiment.samples.values() if s.fcs_data]
        applied = sum(1 for s in samples if s.is_compensated)
        text = (
            f"<b>{matrix.n_channels}×{matrix.n_channels} matrix</b>"
            f" · {self._describe_method(matrix)}"
            f" · applied to {applied} of {len(samples)} loaded samples"
        )
        if dirty:
            text += " · <b>unapplied edits</b>"
        elif self._data_stale and applied:
            text += " · <b>matrix changed since it was applied</b>"
        self._status.setText(text)

    def _on_state_restored(self, _data: dict | None = None) -> None:
        if self._is_alive:
            self.refresh()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.refresh()

    def cleanup(self) -> None:
        if not self._is_alive:
            return
        self._is_alive = False
        CentralEventBus.unsubscribe(events.STATE_RESTORED, self._on_state_restored)

    # ── Actions ───────────────────────────────────────────────────────

    def _set_workspace_matrix(self, matrix: CompensationMatrix, undo_label: str) -> None:
        if not _same_matrix(matrix, self._state.data.compensation):
            self._data_stale = True
        experiment_edits.set_compensation(self._state, matrix, undo_label)
        self._load(matrix)

    def _on_source(self, source: MatrixSource) -> None:
        try:
            result = source.obtain(self._state, self)
        except MatrixSourceError as exc:
            show_warning(self, exc.title, str(exc))
            return
        if result is None:
            return  # cancelled
        self._set_workspace_matrix(result.matrix, result.undo_label)
        self._note.setText(result.summary + _FINE_TUNE_HINT)
        self._refresh_status()
        self.compensation_changed.emit()
        logger.info("Compensation matrix from %s: %s", type(source).__name__, result.summary)

    def _on_apply_all(self) -> None:
        """Commit any edits, then compensate the loaded samples."""
        if self.has_unapplied_edits and self._editor.matrix is not None:
            self._set_workspace_matrix(self._editor.matrix, "Edit Compensation Matrix")
        if self._state.data.compensation is None:
            return

        # A changed matrix must also replace the values the old one produced.
        result = experiment_edits.apply_compensation_to_all(self._state, reapply=self._data_stale)
        self._data_stale = False

        note = f"Compensation applied to {result.changed} sample(s)."
        if result.already_compensated:
            note += f" {result.already_compensated} skipped (already compensated)."
        if result.no_data:
            note += f" {result.no_data} skipped (no data)."
        self._note.setText(note)
        self._refresh_status()
        self._editor.refresh_samples()
        self.compensation_changed.emit()
        logger.info("Compensation applied: %s", result)

    def _on_revert(self) -> None:
        self._load(self._state.data.compensation)
        self._note.setText("Edits discarded.")
        self._refresh_status()

    def _on_export_csv(self) -> None:
        """Export the matrix as shown, including unapplied edits."""
        matrix = self._editor.matrix
        if matrix is None:
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
            export_matrix_to_csv(matrix, Path(path))
        except Exception as exc:
            logger.error("Matrix export failed: %s", exc)
            show_error(self, "Export Error", f"Failed to export matrix:\n{exc}")
            return
        self._note.setText(f"Matrix saved to {Path(path).name}.")

    def _on_toggle_compensation(self) -> None:
        toggled, new_state = experiment_edits.toggle_compensation(self._state)
        if not toggled:
            self._note.setText(
                "Could not toggle compensation: samples need a raw-data backup and a matrix."
            )
            return
        self._note.setText(
            f"Compensation turned {'ON' if new_state else 'OFF'} for {toggled} sample(s)."
        )
        self._refresh_status()
        self._editor.refresh_samples()
        self.compensation_changed.emit()
