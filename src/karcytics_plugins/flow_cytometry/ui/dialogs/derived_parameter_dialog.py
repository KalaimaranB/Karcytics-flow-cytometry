"""Derived Parameters manager: list of definitions + editor.

Non-modal, so the user can keep looking at plots while building a formula
(and so Academy steps can drive it). Every save/delete goes through
DerivedParameterService, which re-syncs all samples and publishes
DERIVED_PARAMS_CHANGED — each is therefore one undo step.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from karcytics_sdk.plugin import CentralEventBus, get_logger
from karcytics_sdk.plugin.components import (
    BioListWidget,
    DangerButton,
    PrimaryButton,
    SecondaryButton,
)
from karcytics_sdk.plugin.dialogs import ask_ok_cancel, ask_yes_no, show_warning
from karcytics_sdk.plugin.theme_fallback import theme_manager
from PyQt6.QtCore import QRect, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidgetItem,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from karcytics_plugins.flow_cytometry.analysis import events
from karcytics_plugins.flow_cytometry.analysis.constants import MAX_DERIVED_PARAMETERS
from karcytics_plugins.flow_cytometry.analysis.derived import FormulaError
from karcytics_plugins.flow_cytometry.analysis.services.derived_parameter_service import (
    DerivedParameterError,
    DerivedParameterService,
    GateDependent,
)
from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.ui.widgets.derived_formula_editor import (
    DerivedParameterEditor,
)
from karcytics_plugins.flow_cytometry.ui.widgets.tutorial_highlight import TutorialHighlight

logger = get_logger(__name__, "flow_cytometry")

RemovePopulation = Callable[[str, str], bool]

_DIALOG_QSS = (
    "QDialog#DerivedParameterDialog { background: {BG_DARKER}; }"
    "QLabel { color: {FG_PRIMARY}; background: transparent; }"
    "QRadioButton, QCheckBox { color: {FG_PRIMARY}; }"
    "QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; border: none; }"
)
_CAPTION_QSS = "color: {FG_SECONDARY}; font-size: 11px; background: transparent;"


class DerivedParameterDialog(QDialog):
    """Create, edit and delete the experiment's derived parameters.

    Signals:
        parameter_saved(str, bool): param_id, and True if newly created.
    """

    parameter_saved = pyqtSignal(str, bool)

    def __init__(
        self,
        state: FlowState,
        service: DerivedParameterService,
        remove_population: RemovePopulation | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._state = state
        self._service = service
        self._remove_population = remove_population
        self._syncing_list = False

        self.setObjectName("DerivedParameterDialog")
        self.setWindowTitle("Derived Parameters")
        self.setModal(False)
        # A Tool window stays above the main window, like the population
        # picker popups. As a plain Dialog, clicking the main window — e.g.
        # the Academy bubble's Next button mid-course — sends it behind.
        self.setWindowFlags(
            (self.windowFlags() & ~Qt.WindowType.WindowType_Mask) | Qt.WindowType.Tool
        )
        self.resize(940, 820)
        theme_manager.apply_style(self, _DIALOG_QSS)

        self._build_ui()
        self._tutorial_highlight = TutorialHighlight(self)
        CentralEventBus.subscribe(events.DERIVED_PARAMS_CHANGED, self._on_external_change)
        self.destroyed.connect(self._unsubscribe)

    # ── Public API ────────────────────────────────────────────────────────

    def get_tutorial_target_rects(self, step) -> list[QRect]:
        """Academy driver hook — spotlight this dialog's own widgets."""
        return self._tutorial_highlight.rects_for_step(step)

    @property
    def editor(self) -> DerivedParameterEditor:
        return self._editor

    def open_new(self) -> None:
        """Show the dialog on a fresh definition."""
        self._present()
        if self._confirm_discard():
            self._start_new()

    def open_existing(self, param_id: str | None = None) -> None:
        """Show the dialog on ``param_id``, or on the first definition."""
        self._present()
        if param_id is not None:
            if param_id != self._editor.editing_id and self._confirm_discard():
                self._select(param_id)
        elif self._editor.is_new and not self._editor.is_dirty():
            self._select_first_or_new()

    # ── UI ────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(16)
        root.addLayout(self._build_sidebar(), stretch=0)
        root.addLayout(self._build_main(), stretch=1)

    def _build_sidebar(self) -> QVBoxLayout:
        side = QVBoxLayout()
        header = QLabel("ƒ Derived parameters")
        header.setStyleSheet("font-weight: 700;")
        side.addWidget(header)
        caption = QLabel(
            "Per-cell formulas you can plot, gate on and use in statistics — "
            "like any other channel."
        )
        caption.setWordWrap(True)
        theme_manager.apply_style(caption, _CAPTION_QSS)
        side.addWidget(caption)

        self._list = BioListWidget()
        self._list.setObjectName("DerivedParamList")
        self._list.setMinimumWidth(220)
        self._list.currentItemChanged.connect(self._on_list_selection)
        side.addWidget(self._list, stretch=1)

        row = QHBoxLayout()
        self._btn_new = SecondaryButton("+ New")
        self._btn_new.setObjectName("DerivedNewButton")
        self._btn_new.clicked.connect(self.open_new)
        self._btn_duplicate = SecondaryButton("Duplicate")
        self._btn_duplicate.setObjectName("DerivedDuplicateButton")
        self._btn_duplicate.clicked.connect(self._on_duplicate)
        self._btn_delete = DangerButton("Delete")
        self._btn_delete.setObjectName("DerivedDeleteButton")
        self._btn_delete.clicked.connect(self._on_delete)
        for btn in (self._btn_new, self._btn_duplicate, self._btn_delete):
            row.addWidget(btn)
        side.addLayout(row)
        return side

    def _build_main(self) -> QVBoxLayout:
        main = QVBoxLayout()
        self._editor = DerivedParameterEditor(self._state, self._service)
        self._editor.changed.connect(self._update_buttons)
        self._editor.validity_changed.connect(self._update_buttons)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        holder = QWidget()
        holder_layout = QVBoxLayout(holder)
        holder_layout.setContentsMargins(0, 0, 8, 0)
        holder_layout.addWidget(self._editor)
        scroll.setWidget(holder)
        main.addWidget(scroll, stretch=1)

        self._dependents = QLabel("")
        self._dependents.setObjectName("DerivedDependentsLabel")
        self._dependents.setWordWrap(True)
        theme_manager.apply_style(self._dependents, _CAPTION_QSS)
        main.addWidget(self._dependents)

        row = QHBoxLayout()
        row.addStretch()
        btn_close = SecondaryButton("Close")
        btn_close.setObjectName("DerivedCloseButton")
        btn_close.clicked.connect(self.close)
        self._btn_save = PrimaryButton("Save")
        self._btn_save.setObjectName("DerivedSaveButton")
        self._btn_save.clicked.connect(self._on_save)
        row.addWidget(btn_close)
        row.addWidget(self._btn_save)
        main.addLayout(row)
        return main

    # ── List ──────────────────────────────────────────────────────────────

    def _present(self) -> None:
        if not self.isVisible():
            self._editor.refresh_sources()
            self._refresh_list(self._editor.editing_id)
        self.show()
        self.raise_()
        self.activateWindow()

    def _refresh_list(self, select_id: str | None) -> None:
        self._syncing_list = True
        self._list.clear()
        for defn in self._service.definitions:
            item = QListWidgetItem(defn.label)
            item.setData(Qt.ItemDataRole.UserRole, defn.param_id)
            item.setToolTip(defn.formula)
            self._list.addItem(item)
            if defn.param_id == select_id:
                self._list.setCurrentItem(item)
        self._syncing_list = False
        self._update_buttons()

    def _select(self, param_id: str) -> None:
        self._refresh_list(param_id)
        self._editor.load(self._service.get(param_id))
        self._update_buttons()

    def _select_first_or_new(self) -> None:
        if self._service.definitions:
            self._select(self._service.definitions[0].param_id)
        else:
            self._start_new()

    def _start_new(self) -> None:
        self._syncing_list = True
        self._list.setCurrentItem(None)
        self._syncing_list = False
        self._editor.load(None)
        self._update_buttons()

    def _on_list_selection(self, current: QListWidgetItem | None, previous) -> None:
        if self._syncing_list or current is None:
            return
        param_id = current.data(Qt.ItemDataRole.UserRole)
        if param_id == self._editor.editing_id:
            return
        if not self._confirm_discard():
            self._syncing_list = True
            self._list.setCurrentItem(previous)
            self._syncing_list = False
            return
        self._editor.load(self._service.get(param_id))
        self._update_buttons()

    def _on_external_change(self, _payload: dict) -> None:
        """Keep the list in step with changes made elsewhere (e.g. undo)."""
        try:
            current = self._editor.editing_id
            if current is not None and self._service.get(current) is None:
                self._start_new()
                current = None
            self._refresh_list(current)
        except RuntimeError:  # dialog already destroyed on the C++ side
            self._unsubscribe()

    def _unsubscribe(self, *_args) -> None:
        try:
            CentralEventBus.unsubscribe(events.DERIVED_PARAMS_CHANGED, self._on_external_change)
        except Exception:
            pass

    # ── Actions ───────────────────────────────────────────────────────────

    def _update_buttons(self, *_args) -> None:
        editing = self._editor.editing_id
        self._btn_save.setEnabled(self._editor.can_save)
        # Hidden rather than disabled: the SDK's danger button has no
        # disabled look, so a greyed-out Delete would still read as active.
        self._btn_delete.setVisible(editing is not None)
        self._btn_duplicate.setVisible(editing is not None)
        at_limit = len(self._service.definitions) >= MAX_DERIVED_PARAMETERS
        self._btn_new.setEnabled(not at_limit)
        self._btn_new.setToolTip(
            f"Limit of {MAX_DERIVED_PARAMETERS} reached" if at_limit else "New derived parameter"
        )
        self._show_dependents(self._service.find_dependents(editing) if editing else [])

    def _show_dependents(self, dependents: list[GateDependent]) -> None:
        if not dependents:
            self._dependents.setText("")
            return
        by_gate: dict[str, list[str]] = {}
        for d in dependents:
            by_gate.setdefault(d.node_name, []).append(d.sample_name)
        text = "; ".join(f"{gate} ({', '.join(samples)})" for gate, samples in by_gate.items())
        self._dependents.setText(f"Used by gates: {text}")

    def _on_save(self) -> None:
        draft = self._editor.draft()
        editing = self._editor.editing_id
        try:
            if editing is None:
                defn = self._service.create(draft)
                created = True
            else:
                if not self._confirm_update(editing):
                    return
                defn = self._service.update(editing, draft)
                created = False
        except (DerivedParameterError, FormulaError) as exc:
            show_warning(self, "Can't save", str(exc))
            return
        self._editor.mark_clean(defn.param_id)
        self._refresh_list(defn.param_id)
        self.parameter_saved.emit(defn.param_id, created)

    def _confirm_update(self, param_id: str) -> bool:
        dependents = self._service.find_dependents(param_id)
        if not dependents or not self._editor.values_changed():
            return True
        return ask_ok_cancel(
            self,
            "Recompute gates?",
            f"{len(dependents)} gate(s) are drawn on this parameter. Saving the new "
            "formula recomputes their populations and statistics — the gate "
            "boundaries themselves don't move.",
        )

    def _on_duplicate(self) -> None:
        if not self._confirm_discard():
            return
        source = self._editor.draft()
        self._start_new()
        self._editor.load_copy(replace(source, name=f"{source.name.strip()} copy"))
        self._update_buttons()

    def _on_delete(self) -> None:
        param_id = self._editor.editing_id
        defn = self._service.get(param_id) if param_id else None
        if defn is None:
            return
        dependents = self._service.find_dependents(defn.param_id)
        if dependents and not self._remove_dependents(defn.label, dependents):
            return
        if not dependents and not ask_yes_no(
            self, "Delete derived parameter?", f"Delete {defn.label}?"
        ):
            return
        try:
            self._service.delete(defn.param_id)
        except DerivedParameterError as exc:
            show_warning(self, "Can't delete", str(exc))
            return
        self._refresh_list(None)
        self._select_first_or_new()

    def _remove_dependents(self, label: str, dependents: list[GateDependent]) -> bool:
        if self._remove_population is None:
            show_warning(self, "In use", f"{label} is used by gates; delete them first.")
            return False
        names = "\n".join(f"• {d.node_name} — {d.sample_name}" for d in dependents)
        if not ask_yes_no(
            self,
            "Delete gates too?",
            f"{label} is used by these gates:\n{names}\n\n"
            "Deleting it also deletes those gates and everything gated inside them. "
            "Continue?",
        ):
            return False
        for dep in dependents:
            self._remove_population(dep.sample_id, dep.node_id)
        return True

    def _confirm_discard(self) -> bool:
        if not self._editor.is_dirty():
            return True
        return ask_yes_no(self, "Discard changes?", "Discard unsaved changes to this parameter?")

    def closeEvent(self, event) -> None:
        if not self._confirm_discard():
            event.ignore()
            return
        # Discarded edits must not reappear next time the dialog opens.
        editing = self._editor.editing_id
        self._editor.load(self._service.get(editing) if editing else None)
        self._tutorial_highlight.clear()
        event.accept()
