"""Editor for a single derived parameter (name, formula, scale, preview).

Produces a :class:`DerivedParameterDraft`; saving/deleting is the dialog's
job. Validation runs through DerivedParameterService so the editor shows
exactly the errors a save would raise, and the live preview evaluates the
canonical formula on a subsample of the chosen sample/population.
"""

from __future__ import annotations

from itertools import permutations

from karcytics_sdk.plugin.components import BioLineEdit, SecondaryButton
from karcytics_sdk.plugin.theme_fallback import theme_manager
from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from karcytics_plugins.flow_cytometry.analysis.derived import (
    DerivedExpression,
    DerivedParameter,
    DerivedParameterDraft,
    FormulaError,
    parse_formula,
)
from karcytics_plugins.flow_cytometry.analysis.derived.preview import compute_preview
from karcytics_plugins.flow_cytometry.analysis.derived.templates import (
    TEMPLATES,
    FormulaTemplate,
    get_template,
    short_label,
)
from karcytics_plugins.flow_cytometry.analysis.fcs_io import get_fluorescence_channels
from karcytics_plugins.flow_cytometry.analysis.services.derived_parameter_service import (
    DerivedParameterError,
    DerivedParameterService,
)
from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.analysis.transforms import TransformType
from karcytics_plugins.flow_cytometry.ui.widgets.mini_histogram import MiniHistogram
from karcytics_plugins.flow_cytometry.ui.widgets.styled_combo import FlowComboBox

CUSTOM_TEMPLATE = "custom"
VALIDATION_DELAY_MS = 200
MANY_INVALID_PCT = 5.0
CHIP_COLUMNS = 3

# (button text, inserted text, cursor offset back from the end)
_OPERATORS = [
    ("+", " + ", 0),
    ("−", " - ", 0),
    ("×", " * ", 0),
    ("÷", " / ", 0),
    ("^", "^", 0),
    ("(", "(", 0),
    (")", ")", 0),
]
_FUNCTIONS = ["log10", "ln", "sqrt", "abs", "asinh"]

# Status labels switch colour through a dynamic property rather than
# restyling, so theme_manager's single registration keeps working.
_STATUS_QSS = (
    "QLabel { color: {FG_SECONDARY}; font-size: 11px; background: transparent; }"
    'QLabel[state="ok"] { color: {ACCENT_SUCCESS}; }'
    'QLabel[state="warn"] { color: {ACCENT_WARNING}; }'
    'QLabel[state="error"] { color: {ACCENT_DANGER}; }'
)
_SECTION_QSS = (
    "color: {FG_SECONDARY}; font-size: 11px; font-weight: 600;"
    " text-transform: uppercase; background: transparent;"
)


class DerivedParameterEditor(QWidget):
    """Edits one derived-parameter draft.

    Signals:
        changed():               Any field changed.
        validity_changed(bool):  The draft became valid / invalid.
    """

    changed = pyqtSignal()
    validity_changed = pyqtSignal(bool)

    def __init__(self, state: FlowState, service: DerivedParameterService, parent=None) -> None:
        super().__init__(parent)
        self._state = state
        self._service = service
        self._editing_id: str | None = None
        self._baseline: DerivedParameterDraft | None = None
        self._name_touched = False
        self._valid = False
        self._channels: dict[str, str] = {}

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(VALIDATION_DELAY_MS)
        self._timer.timeout.connect(self.revalidate)

        self._build_ui()

    # ── Public API ────────────────────────────────────────────────────────

    @property
    def is_valid(self) -> bool:
        return self._valid

    @property
    def editing_id(self) -> str | None:
        return self._editing_id

    @property
    def is_new(self) -> bool:
        return self._editing_id is None

    def draft(self) -> DerivedParameterDraft:
        return DerivedParameterDraft(
            name=self._name_edit.text(),
            formula=self._formula_edit.text(),
            preferred_transform=(
                TransformType.LOG.value
                if self._scale_log.isChecked()
                else TransformType.LINEAR.value
            ),
            positive_denominators=self._positive_denominators.isChecked(),
        )

    def is_dirty(self) -> bool:
        """Changed since loading (a fresh template draft starts clean)."""
        return self._baseline is not None and self.draft() != self._baseline

    @property
    def can_save(self) -> bool:
        return self._valid and (self.is_new or self.is_dirty())

    def values_changed(self) -> bool:
        """True if the edit changes computed values (not just name/scale)."""
        if self._baseline is None or self.is_new:
            return True
        now = self.draft()
        return (now.formula, now.positive_denominators) != (
            self._baseline.formula,
            self._baseline.positive_denominators,
        )

    def mark_clean(self, param_id: str | None = None) -> None:
        if param_id is not None:
            self._editing_id = param_id
        self._baseline = self.draft()
        self._name_touched = True

    def refresh_sources(self) -> None:
        """Reload channels and samples (call when the dialog is shown)."""
        self._channels = self._service.available_channels()
        self._fill_channel_combos()
        self._fill_chips()
        self._fill_preview_samples()

    def load(self, defn: DerivedParameter | None) -> None:
        """Edit an existing definition, or start a fresh one (None)."""
        self._editing_id = defn.param_id if defn else None
        if defn is None:
            self._load_new()
        else:
            self._load_fields(
                DerivedParameterDraft(
                    defn.name, defn.formula, defn.preferred_transform, defn.positive_denominators
                )
            )
            self._name_touched = True
        self._baseline = self.draft()
        self.revalidate()

    def load_copy(self, draft: DerivedParameterDraft) -> None:
        """Start a new definition pre-filled from ``draft`` (Duplicate)."""
        self._editing_id = None
        self._load_fields(draft)
        self._name_touched = True
        self._baseline = self.draft()
        self.revalidate()

    def revalidate(self) -> None:
        """Validate now (normally debounced) and refresh status + preview."""
        self._timer.stop()
        draft = self.draft()
        name_ok = self._check_name(draft.name)
        expr = self._check_formula(draft.formula)
        self._positive_denominators.setEnabled(expr is not None and expr.has_division)
        self._update_preview(expr, draft)

        valid = name_ok and expr is not None
        if valid != self._valid:
            self._valid = valid
            self.validity_changed.emit(valid)

    # ── UI construction ───────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self._build_name(layout)
        self._build_template(layout)
        self._build_formula(layout)
        self._build_palette(layout)
        self._build_options(layout)
        self._build_preview(layout)
        layout.addStretch()

    def _section(self, layout: QVBoxLayout, text: str) -> None:
        lbl = QLabel(text)
        theme_manager.apply_style(lbl, _SECTION_QSS)
        layout.addWidget(lbl)

    def _status_label(self, object_name: str) -> QLabel:
        lbl = QLabel("")
        lbl.setObjectName(object_name)
        lbl.setWordWrap(True)
        theme_manager.apply_style(lbl, _STATUS_QSS)
        return lbl

    def _build_name(self, layout: QVBoxLayout) -> None:
        self._section(layout, "Name")
        self._name_edit = BioLineEdit()
        self._name_edit.setObjectName("DerivedNameEdit")
        self._name_edit.setPlaceholderText("e.g. B220/CD45")
        self._name_edit.textEdited.connect(self._on_name_edited)
        self._name_edit.textChanged.connect(self._schedule)
        layout.addWidget(self._name_edit)
        self._name_status = self._status_label("DerivedNameStatus")
        layout.addWidget(self._name_status)

    def _build_template(self, layout: QVBoxLayout) -> None:
        self._section(layout, "Start from")
        self._template_combo = FlowComboBox()
        self._template_combo.setObjectName("DerivedTemplateCombo")
        for tpl in TEMPLATES:
            self._template_combo.addItem(tpl.label, tpl.key)
        self._template_combo.addItem("Custom formula", CUSTOM_TEMPLATE)
        self._template_combo.currentIndexChanged.connect(self._apply_template)
        layout.addWidget(self._template_combo)

        row = QHBoxLayout()
        self._chan_a = FlowComboBox()
        self._chan_a.setObjectName("DerivedChannelA")
        self._chan_b = FlowComboBox()
        self._chan_b.setObjectName("DerivedChannelB")
        for tag, combo in (("A:", self._chan_a), ("B:", self._chan_b)):
            row.addWidget(QLabel(tag))
            combo.currentIndexChanged.connect(self._apply_template)
            row.addWidget(combo, stretch=1)
        layout.addLayout(row)

        self._template_hint = self._status_label("DerivedTemplateHint")
        layout.addWidget(self._template_hint)

    def _build_formula(self, layout: QVBoxLayout) -> None:
        self._section(layout, "Formula")
        self._formula_edit = BioLineEdit()
        self._formula_edit.setObjectName("DerivedFormulaEdit")
        self._formula_edit.setPlaceholderText("[FITC-A] / [APC-A]")
        self._formula_edit.setToolTip(
            "Per-cell formula. Wrap channels in brackets — [FITC-A] or a marker "
            "name like [B220]. Operators: + - * / ^ ( ). Functions: "
            + ", ".join(f"{f}()" for f in _FUNCTIONS)
            + ", min(a, b), max(a, b)."
        )
        self._formula_edit.textEdited.connect(self._on_formula_edited)
        self._formula_edit.textChanged.connect(self._schedule)
        layout.addWidget(self._formula_edit)
        self._formula_status = self._status_label("DerivedFormulaStatus")
        layout.addWidget(self._formula_status)

    def _build_palette(self, layout: QVBoxLayout) -> None:
        self._chip_grid = QGridLayout()
        self._chip_grid.setSpacing(4)
        layout.addLayout(self._chip_grid)

        for items in (
            [(text, insert, back) for text, insert, back in _OPERATORS],
            [(f"{fn}()", f"{fn}()", 1) for fn in _FUNCTIONS],
        ):
            row = QHBoxLayout()
            row.setSpacing(4)
            for text, insert, back in items:
                row.addWidget(self._palette_button(text, insert, back))
            row.addStretch()
            layout.addLayout(row)

    def _palette_button(self, text: str, insert: str, back: int) -> SecondaryButton:
        btn = SecondaryButton(text)
        btn.clicked.connect(lambda: self._insert(insert, back))
        return btn

    def _build_options(self, layout: QVBoxLayout) -> None:
        self._section(layout, "Options")
        row = QHBoxLayout()
        row.addWidget(QLabel("Default axis scale:"))
        self._scale_log = QRadioButton("Log")
        self._scale_log.setObjectName("DerivedScaleLog")
        self._scale_linear = QRadioButton("Linear")
        self._scale_linear.setObjectName("DerivedScaleLinear")
        group = QButtonGroup(self)
        for btn in (self._scale_log, self._scale_linear):
            group.addButton(btn)
            btn.toggled.connect(self._schedule)
            row.addWidget(btn)
        row.addStretch()
        layout.addLayout(row)

        self._positive_denominators = QCheckBox(
            "Treat events with a zero or negative denominator as invalid"
        )
        self._positive_denominators.setObjectName("DerivedPositiveDenominators")
        self._positive_denominators.setToolTip(
            "Compensated values can dip to or below zero. Dividing by them gives "
            "huge or sign-flipped ratios; with this on, those events are left "
            "out of plots, gates and statistics on this parameter instead."
        )
        self._positive_denominators.toggled.connect(self._schedule)
        layout.addWidget(self._positive_denominators)

    def _build_preview(self, layout: QVBoxLayout) -> None:
        self._section(layout, "Preview")
        row = QHBoxLayout()
        self._preview_sample = FlowComboBox()
        self._preview_sample.setObjectName("DerivedPreviewSample")
        self._preview_sample.currentIndexChanged.connect(self._on_preview_sample_changed)
        self._preview_population = FlowComboBox()
        self._preview_population.setObjectName("DerivedPreviewPopulation")
        self._preview_population.currentIndexChanged.connect(self._schedule)
        row.addWidget(self._preview_sample, stretch=1)
        row.addWidget(self._preview_population, stretch=1)
        layout.addLayout(row)

        self._histogram = MiniHistogram()
        self._histogram.setObjectName("DerivedPreviewHistogram")
        layout.addWidget(self._histogram)
        self._preview_summary = self._status_label("DerivedPreviewSummary")
        layout.addWidget(self._preview_summary)

    # ── Sources ───────────────────────────────────────────────────────────

    def _fill_channel_combos(self) -> None:
        for combo in (self._chan_a, self._chan_b):
            previous = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            for ch, label in self._channels.items():
                combo.addItem(label, ch)
            if previous is not None:
                idx = combo.findData(previous)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
            combo.blockSignals(False)

    def _fill_chips(self) -> None:
        while self._chip_grid.count():
            item = self._chip_grid.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()
        for i, (ch, label) in enumerate(self._channels.items()):
            btn = self._palette_button(short_label(label), f"[{ch}]", 0)
            btn.setToolTip(f"Insert [{ch}] — {label}")
            self._chip_grid.addWidget(btn, i // CHIP_COLUMNS, i % CHIP_COLUMNS)

    def _fill_preview_samples(self) -> None:
        previous = self._preview_sample.currentData()
        self._preview_sample.blockSignals(True)
        self._preview_sample.clear()
        for sid, sample in self._state.data.experiment.samples.items():
            if sample.fcs_data is not None:
                self._preview_sample.addItem(sample.display_name, sid)
        target = previous or self._state.view.current_sample_id
        idx = self._preview_sample.findData(target) if target else -1
        self._preview_sample.setCurrentIndex(max(idx, 0))
        self._preview_sample.blockSignals(False)
        self._fill_preview_populations(prefer=self._state.view.current_gate_id)

    def _fill_preview_populations(self, prefer: str | None = None) -> None:
        self._preview_population.blockSignals(True)
        self._preview_population.clear()
        self._preview_population.addItem("All events", None)
        sample = self._state.data.experiment.samples.get(self._preview_sample.currentData() or "")
        if sample is not None:
            for node in sample.gate_tree.iter_dag():
                if not node.is_root:
                    self._preview_population.addItem(node.name, node.node_id)
        idx = self._preview_population.findData(prefer) if prefer else -1
        self._preview_population.setCurrentIndex(max(idx, 0))
        self._preview_population.blockSignals(False)

    def _on_preview_sample_changed(self) -> None:
        self._fill_preview_populations()
        self._schedule()

    # ── Loading ───────────────────────────────────────────────────────────

    def _load_new(self) -> None:
        fluoro = self._fluorescence_channels() or list(self._channels)
        tpl = TEMPLATES[0]
        self._block(True)
        self._template_combo.setCurrentIndex(self._template_combo.findData(tpl.key))
        for combo, ch in zip((self._chan_a, self._chan_b), fluoro[:2], strict=False):
            combo.setCurrentIndex(max(combo.findData(ch), 0))
        self._name_edit.clear()
        self._formula_edit.clear()
        self._positive_denominators.setChecked(True)
        self._block(False)
        self._name_touched = False
        self._apply_template()

    def _load_fields(self, draft: DerivedParameterDraft) -> None:
        self._block(True)
        self._name_edit.setText(draft.name)
        self._formula_edit.setText(draft.formula)
        self._set_scale(draft.preferred_transform)
        self._positive_denominators.setChecked(draft.positive_denominators)
        tpl, a, b = self._match_template(draft.formula)
        self._template_combo.setCurrentIndex(
            self._template_combo.findData(tpl.key if tpl else CUSTOM_TEMPLATE)
        )
        if tpl is not None:
            self._chan_a.setCurrentIndex(max(self._chan_a.findData(a), 0))
            self._chan_b.setCurrentIndex(max(self._chan_b.findData(b), 0))
        self._block(False)
        self._update_template_hint()

    def _match_template(self, formula: str) -> tuple[FormulaTemplate | None, str, str]:
        for tpl in TEMPLATES:
            for a, b in permutations(self._channels, 2):
                if tpl.formula(a, b) == formula:
                    return tpl, a, b
        return None, "", ""

    def _fluorescence_channels(self) -> list[str]:
        for sample in self._state.data.experiment.samples.values():
            if sample.fcs_data is not None:
                fluoro = set(get_fluorescence_channels(sample.fcs_data))
                return [ch for ch in self._channels if ch in fluoro]
        return []

    def _block(self, blocked: bool) -> None:
        for w in (
            self._name_edit,
            self._formula_edit,
            self._template_combo,
            self._chan_a,
            self._chan_b,
            self._scale_log,
            self._scale_linear,
            self._positive_denominators,
        ):
            w.blockSignals(blocked)

    # ── Editing ───────────────────────────────────────────────────────────

    def _current_template(self) -> FormulaTemplate | None:
        return get_template(self._template_combo.currentData() or "")

    def _apply_template(self) -> None:
        self._update_template_hint()
        tpl = self._current_template()
        a, b = self._chan_a.currentData(), self._chan_b.currentData()
        if tpl is None or not a or not b:
            self._schedule()
            return
        self._formula_edit.setText(tpl.formula(a, b))
        self._set_scale(tpl.preferred_transform)
        if not self._name_touched:
            self._name_edit.setText(
                tpl.suggested_name(self._chan_a.currentText(), self._chan_b.currentText())
            )
        self._schedule()

    def _update_template_hint(self) -> None:
        tpl = self._current_template()
        for combo in (self._chan_a, self._chan_b):
            combo.setEnabled(tpl is not None)
        self._template_hint.setText(
            tpl.hint
            if tpl
            else "Type any formula below, or use the buttons to insert channels and functions."
        )

    def _set_scale(self, transform: str) -> None:
        is_log = transform == TransformType.LOG.value
        self._scale_log.setChecked(is_log)
        self._scale_linear.setChecked(not is_log)

    def _on_name_edited(self, _text: str) -> None:
        self._name_touched = True

    def _on_formula_edited(self, _text: str = "") -> None:
        # Hand-editing a template's output turns it into a custom formula.
        tpl = self._current_template()
        if tpl is None:
            return
        a, b = self._chan_a.currentData(), self._chan_b.currentData()
        if self._formula_edit.text() != tpl.formula(a, b):
            self._template_combo.blockSignals(True)
            self._template_combo.setCurrentIndex(self._template_combo.findData(CUSTOM_TEMPLATE))
            self._template_combo.blockSignals(False)
            self._update_template_hint()

    def _insert(self, text: str, cursor_back: int) -> None:
        self._formula_edit.insert(text)
        if cursor_back:
            self._formula_edit.setCursorPosition(self._formula_edit.cursorPosition() - cursor_back)
        self._formula_edit.setFocus()
        self._on_formula_edited()

    def _schedule(self, *_args) -> None:
        self.changed.emit()
        self._timer.start()

    # ── Validation & preview ──────────────────────────────────────────────

    def _check_name(self, name: str) -> bool:
        try:
            self._service.validate_name(name, self._editing_id)
        except DerivedParameterError as exc:
            _set_status(self._name_status, "error", f"✗ {exc}")
            return False
        _set_status(self._name_status, "", "")
        return True

    def _check_formula(self, formula: str) -> DerivedExpression | None:
        try:
            expr = parse_formula(self._service.canonicalize(formula))
        except FormulaError as exc:
            _set_status(self._formula_status, "error", _describe_error(formula, exc))
            return None
        used = ", ".join(self._channels.get(ch, ch) for ch in expr.channels)
        _set_status(self._formula_status, "ok", f"✓ Valid · uses {used}")
        return expr

    def _update_preview(self, expr: DerivedExpression | None, draft: DerivedParameterDraft) -> None:
        if expr is None:
            self._histogram.set_message("Fix the formula to see a preview")
            _set_status(self._preview_summary, "", "")
            return
        sample = self._state.data.experiment.samples.get(self._preview_sample.currentData() or "")
        if sample is None or sample.fcs_data is None or sample.fcs_data.events is None:
            self._histogram.set_message("Load a sample to see a preview")
            _set_status(self._preview_summary, "", "")
            return

        events = sample.fcs_data.events
        node_id = self._preview_population.currentData()
        node = sample.gate_tree.find_node_by_id(node_id) if node_id else None
        if node is not None:
            events = node.apply_hierarchy(events)
        missing = expr.missing_channels(events.columns)
        if missing:
            self._histogram.set_message(f"{sample.display_name} has no {', '.join(missing)}")
            _set_status(self._preview_summary, "warn", "")
            return

        summary = compute_preview(
            expr,
            events,
            positive_denominators=draft.positive_denominators,
            log_scale=draft.preferred_transform == TransformType.LOG.value,
        )
        self._histogram.set_counts(summary.counts)
        _set_status(self._preview_summary, *_summary_text(summary))


def _set_status(label: QLabel, state: str, text: str) -> None:
    label.setText(text)
    label.setProperty("state", state)
    style = label.style()
    if style is not None:  # re-evaluate the [state=...] selectors
        style.unpolish(label)
        style.polish(label)


def _describe_error(formula: str, exc: FormulaError) -> str:
    if exc.position is None:
        return f"✗ {exc.message}"
    snippet = formula[exc.position : exc.position + 12]
    return f"✗ {exc.message} — at “{snippet}” (character {exc.position + 1})"


def _summary_text(summary) -> tuple[str, str]:
    if summary.n_events == 0:
        return "warn", "This population has no events."
    median = "—" if summary.median is None else f"{summary.median:.4g}"
    parts = [f"median {median}", f"{summary.pct_invalid:.1f}% invalid", f"n = {summary.n_events:,}"]
    text = " · ".join(parts)
    if summary.log_scale and summary.n_plotted < summary.n_valid:
        text += " · values ≤ 0 not shown on log scale"
    if summary.pct_invalid > MANY_INVALID_PCT:
        return "warn", text + "\n⚠ Many invalid events — is the denominator bright enough here?"
    return "ok", text
