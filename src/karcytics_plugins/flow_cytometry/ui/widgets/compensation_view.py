"""Compensation view — the Compensation tab's full-window workspace.

A slim header picks a method and runs it (one ``MatrixSource`` per method)
and says what the current matrix is. Below, three pages:

* **Method setup** — how the selected method works, its options, what it
  will use, what its last run rested on. The page the tab opens on.
* **Matrix** — the matrix editor with its before/after preview.
* **Matrices** — every matrix kept in the workspace: compare them, name
  them, export one, apply one to the samples.

Edits are a draft: they change the workspace only when a matrix is applied
from the Matrices page, so every keystroke doesn't recompensate every sample.
"""

from __future__ import annotations

from karcytics_sdk.plugin import CentralEventBus, get_logger
from karcytics_sdk.plugin.components import PrimaryButton, SecondaryButton
from karcytics_sdk.plugin.dialogs import show_warning
from karcytics_sdk.plugin.theme_fallback import Fonts, theme_manager
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from karcytics_plugins.flow_cytometry.analysis import events
from karcytics_plugins.flow_cytometry.analysis.compensation import (
    CompensationMatrix,
    SavedMatrix,
)
from karcytics_plugins.flow_cytometry.analysis.services import experiment_edits
from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.ui.widgets.compensation_editor import CompensationEditor
from karcytics_plugins.flow_cytometry.ui.widgets.matrix_library_panel import (
    MatrixLibraryPanel,
    same_values,
)
from karcytics_plugins.flow_cytometry.ui.widgets.matrix_sources import (
    MATRIX_SOURCES,
    MatrixSource,
    MatrixSourceError,
    MethodOptions,
    Table,
)
from karcytics_plugins.flow_cytometry.ui.widgets.method_setup_panel import MethodSetupPanel
from karcytics_plugins.flow_cytometry.ui.widgets.styled_combo import FlowComboBox

logger = get_logger(__name__, "flow_cytometry")

_RUN_BUTTON_NAME = "RunMethodButton"
# Keys of the editor's matrix selector that aren't a saved matrix's id.
_WORKSPACE_KEY = "workspace"
_UNSAVED_KEY = "unsaved"
_FINE_TUNE_HINT = " Fine-tune any cell, then apply it from the Matrices page."


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
        # Per method (by key): the user's setup choices, and its last run's report.
        self._options: dict[str, MethodOptions] = {}
        self._reports: dict[str, Table] = {}
        # Edits the user switched away from in the editor's matrix selector,
        # kept so switching back doesn't lose them.
        self._set_aside: CompensationMatrix | None = None
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
        header_layout.setContentsMargins(12, 6, 12, 6)
        header_layout.setSpacing(4)
        header_layout.addLayout(self._build_method_row())
        header_layout.addLayout(self._build_status_row())
        theme_manager.apply_style(
            header,
            "#CompensationHeader { background: {BG_DARK}; border-bottom: 1px solid {BORDER}; }"
            f" QLabel {{ color: {{FG_SECONDARY}}; font-size: {Fonts.SIZE_SMALL}px;"
            " background: transparent; }",
        )
        layout.addWidget(header)
        layout.addWidget(self._build_page_toggle())

        self._body = QStackedWidget()
        self._editor = CompensationEditor(self._state)
        self._editor.edited.connect(self._refresh_status)
        self._editor.matrix_chosen.connect(self._on_matrix_chosen)
        self._setup = MethodSetupPanel(self._state)
        self._setup.changed.connect(self._refresh_method)
        self._library = MatrixLibraryPanel(self._state, self._describe_matrix)
        self._library.apply_requested.connect(self._on_apply)
        self._library.open_requested.connect(self._on_open_saved)
        self._library.note.connect(self._note.setText)
        for page in (self._setup, self._editor, self._library):
            self._body.addWidget(page)
        layout.addWidget(self._body, stretch=1)

    def _build_method_row(self) -> QHBoxLayout:
        """The method selector, its run button, and what the method found."""
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(QLabel("Method:"))

        self._method_combo = FlowComboBox()
        self._method_combo.setObjectName("CompensationMethodCombo")
        for source in self._sources:
            self._method_combo.addItem(source.label, source.key)
        self._method_combo.activated.connect(self._on_method_picked)
        self._method_combo.currentIndexChanged.connect(self._refresh_method)
        row.addWidget(self._method_combo)

        self._btn_run = PrimaryButton("")
        self._btn_run.clicked.connect(self._on_run_method)
        row.addWidget(self._btn_run)

        self._method_hint = QLabel()  # what the selected method needs / found
        self._method_hint.setWordWrap(True)
        row.addWidget(self._method_hint, stretch=1)
        return row

    def _build_status_row(self) -> QHBoxLayout:
        """What the current matrix is, the last action's outcome, and Revert."""
        row = QHBoxLayout()
        row.setSpacing(12)
        self._status = QLabel()
        self._status.setTextFormat(Qt.TextFormat.RichText)
        row.addWidget(self._status)
        self._note = QLabel()  # outcome of the last action
        self._note.setWordWrap(True)
        row.addWidget(self._note, stretch=1)

        self._btn_revert = SecondaryButton("↩ Revert Edits")
        self._btn_revert.setToolTip("Discard your edits and go back to the workspace's matrix.")
        self._btn_revert.clicked.connect(self._on_revert)
        row.addWidget(self._btn_revert)
        return row

    def _build_page_toggle(self) -> QWidget:
        """The Method setup | Matrix | Matrices switch for the body."""
        row = QWidget()
        row.setObjectName("CompensationPageToggle")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(0)

        self._btn_matrix_page = QPushButton("Matrix")
        self._btn_matrix_page.setToolTip("The spillover matrix and its before/after preview.")
        self._btn_setup_page = QPushButton("⚙ Method setup")
        self._btn_setup_page.setToolTip(
            "How the selected method works, its options, and what it uses."
        )
        self._btn_library_page = QPushButton("🗂 Matrices")
        self._btn_library_page.setToolTip(
            "Every matrix kept in this workspace: compare, name, export and apply them."
        )
        self._page_buttons = QButtonGroup(self)
        for button in (self._btn_setup_page, self._btn_matrix_page, self._btn_library_page):
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            self._page_buttons.addButton(button)
            row_layout.addWidget(button)
        self._btn_setup_page.setChecked(True)  # set the method up first
        self._page_buttons.buttonToggled.connect(lambda *_: self._sync_page())

        theme_manager.apply_style(
            row,
            f"QPushButton {{ color: {{FG_SECONDARY}}; background: {{BG_DARK}};"
            f" font-size: {Fonts.SIZE_SMALL}px; padding: 5px 0; border: none;"
            " border-bottom: 2px solid {BORDER}; }"
            " QPushButton:checked { color: {FG_PRIMARY};"
            " border-bottom: 2px solid {ACCENT_PRIMARY}; }"
            " QPushButton:disabled { color: {FG_DISABLED}; }",
        )
        return row

    # ── State sync ────────────────────────────────────────────────────

    @property
    def has_unapplied_edits(self) -> bool:
        return not same_values(self._editor.matrix, self._state.data.compensation)

    def refresh(self) -> None:
        """Re-read the workspace. Unapplied edits survive (the tab can be left
        and come back to) unless the workspace's matrix was replaced under them.
        """
        workspace = self._state.data.compensation
        if not self.has_unapplied_edits or not same_values(self._draft_base, workspace):
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
        ready = (s for s in self._sources if s.readiness(self._state, self._options_for(s)).ready)
        return used or next(ready, None) or next(iter(self._sources), None)

    def _select_method(self, source: MatrixSource | None) -> None:
        index = self._method_combo.findData(source.key) if source is not None else -1
        if index >= 0:
            self._method_combo.setCurrentIndex(index)

    def _on_method_picked(self, _index: int) -> None:
        self._method_picked = True

    def _options_for(self, source: MatrixSource) -> MethodOptions:
        return self._options.setdefault(source.key, MethodOptions())

    def _refresh_method(self) -> None:
        """Point the run button, the hint and the setup page at the selected method."""
        source = self._source(self._method_combo.currentData())
        self._btn_run.setEnabled(source is not None)
        if source is None:
            return
        self._btn_run.setText(source.action)
        self._btn_run.setToolTip(source.tooltip)
        self._btn_run.setObjectName(source.object_name or _RUN_BUTTON_NAME)
        self._method_combo.setToolTip(source.tooltip)
        options = self._options_for(source)
        if self._body.currentWidget() is self._setup:
            # Before the hint: the page drops choices that no longer exist.
            self._setup.show_method(source, options, self._reports.get(source.key))
        self._method_hint.setText(source.readiness(self._state, options).text)

    def _on_run_method(self) -> None:
        source = self._source(self._method_combo.currentData())
        if source is not None:
            self._on_source(source)

    def _describe_matrix(self, matrix: CompensationMatrix) -> str:
        """A matrix's size and the method behind it, in plain words."""
        source = self._source(matrix.source)
        method = source.label if source else matrix.source
        text = f"{matrix.n_channels}×{matrix.n_channels} · {method}"
        return text + (", fine-tuned by hand" if matrix.fine_tuned else "")

    # ── Pages ─────────────────────────────────────────────────────────

    def _sync_page(self) -> None:
        """Show the page the user chose; with no matrix to edit, the method's setup."""
        has_matrix = self._editor.matrix is not None
        self._btn_matrix_page.setEnabled(has_matrix)
        page: QWidget
        if self._btn_library_page.isChecked():
            page = self._library
        elif self._btn_setup_page.isChecked() or not has_matrix:
            page = self._setup
        else:
            page = self._editor
        if self._body.currentWidget() is not page:
            self._body.setCurrentWidget(page)
            if page is self._setup:
                self._refresh_method()

    def _load(self, matrix: CompensationMatrix | None) -> None:
        self._draft_base = matrix
        self._set_aside = None
        self._editor.load(matrix)

    def _sync_matrix_choices(self) -> None:
        """Fill the editor's matrix selector: the one in use, the saved ones,
        and any unsaved edits.
        """
        in_editor = self._editor.matrix
        workspace = self._state.data.compensation
        choices: list[tuple[str, str]] = []
        current: str | None = None
        if workspace is not None:
            choices.append((f"In use · {self._describe_matrix(workspace)}", _WORKSPACE_KEY))
            if same_values(in_editor, workspace):
                current = _WORKSPACE_KEY
        for saved in self._state.data.matrix_library:
            choices.append((saved.name, saved.saved_id))
            if current is None and same_values(in_editor, saved.matrix):
                current = saved.saved_id
        if in_editor is not None and current is None:
            self._set_aside = in_editor  # edits that exist nowhere else
            current = _UNSAVED_KEY
        if self._set_aside is not None:
            choices.insert(0, ("Unsaved edits", _UNSAVED_KEY))
        self._editor.set_matrix_choices(choices, current)

    def _on_matrix_chosen(self, key: str | None) -> None:
        """Put another matrix in the editor as a draft; the samples keep theirs."""
        workspace = self._state.data.compensation
        if key == _UNSAVED_KEY:
            matrix = self._set_aside
        elif key == _WORKSPACE_KEY:
            matrix = workspace
        else:
            saved = next((s for s in self._state.data.matrix_library if s.saved_id == key), None)
            matrix = saved.matrix if saved is not None else None
        if matrix is None:
            return
        self._draft_base = workspace
        self._editor.load(matrix)
        self._refresh_status()

    def _refresh_status(self) -> None:
        matrix = self._state.data.compensation
        dirty = self.has_unapplied_edits
        self._sync_page()
        self._btn_revert.setVisible(dirty)
        self._library.refresh(self._editor.matrix)
        self._sync_matrix_choices()

        if matrix is None and self._editor.matrix is None:
            self._status.setText("No compensation matrix.")
            return
        samples = [s for s in self._state.data.experiment.samples.values() if s.fcs_data]
        applied = sum(1 for s in samples if s.is_compensated)
        text = "<b>No matrix in use</b>"
        if matrix is not None:
            text = (
                f"<b>{self._describe_matrix(matrix)}</b>"
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
        if not same_values(matrix, self._state.data.compensation):
            self._data_stale = True
        experiment_edits.set_compensation(self._state, matrix, undo_label)
        self._load(matrix)

    def _on_source(self, source: MatrixSource) -> None:
        options = self._options_for(source)
        try:
            result = source.obtain(self._state, self, options)
        except MatrixSourceError as exc:
            show_warning(self, exc.title, str(exc))
            return
        if result is None:
            return  # cancelled
        if result.report is not None:
            self._reports[source.key] = result.report
        self._set_workspace_matrix(result.matrix, result.undo_label)
        self._keep_run(source, options, result.matrix)
        self._note.setText(result.summary + _FINE_TUNE_HINT)
        self._btn_matrix_page.setChecked(True)  # look at what the method produced
        self._refresh_status()
        self.compensation_changed.emit()
        logger.info("Compensation matrix from %s: %s", type(source).__name__, result.summary)

    def _keep_run(
        self, source: MatrixSource, options: MethodOptions, matrix: CompensationMatrix
    ) -> None:
        """Keep a method's result in the library, so the next run doesn't lose it.

        Not when that exact result is already there (e.g. re-reading the FCS files).
        """
        if any(
            saved.matrix.source == matrix.source and same_values(saved.matrix, matrix)
            for saved in self._state.data.matrix_library
        ):
            return
        name = source.label + (f" · {options.gate}" if options.gate else "")
        experiment_edits.save_matrix(self._state, name, matrix)

    def _on_apply(self, saved: SavedMatrix | None) -> None:
        """Apply a saved matrix — or, for None, the one in the editor — to the samples."""
        if saved is not None:
            copy = CompensationMatrix.from_dict(saved.matrix.to_dict())
            self._set_workspace_matrix(copy, f"Apply Matrix '{saved.name}'")
        self._on_apply_all()

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

    def _on_open_saved(self, saved: SavedMatrix) -> None:
        """Put a saved matrix in the editor as a draft; the samples keep theirs."""
        self._draft_base = self._state.data.compensation
        self._editor.load(saved.matrix)
        self._note.setText(
            f"'{saved.name}' is open in the editor. The samples are unchanged until you "
            "apply it from the Matrices page."
        )
        self._btn_matrix_page.setEnabled(True)
        self._btn_matrix_page.setChecked(True)
        self._refresh_status()

    def _on_revert(self) -> None:
        self._load(self._state.data.compensation)
        self._note.setText("Edits discarded.")
        self._refresh_status()
