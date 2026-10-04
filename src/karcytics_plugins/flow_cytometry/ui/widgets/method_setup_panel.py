"""Method setup — how the selected compensation method works and what it uses.

One page for any ``MatrixSource``: its explanation, its options (which
sample to read, which gate to fit on), the samples it would use right now
with any per-sample choice, and the report of its last run. Everything
shown comes from the source, so a new method needs no changes here.
"""

from __future__ import annotations

from karcytics_sdk.plugin.theme_fallback import Fonts, theme_manager
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFormLayout,
    QHeaderView,
    QLabel,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.ui.widgets.matrix_sources import (
    Inputs,
    MatrixSource,
    MethodOptions,
    Table,
)
from karcytics_plugins.flow_cytometry.ui.widgets.method_illustration import (
    FitIllustrationView,
    pass_wheel_to_page,
)
from karcytics_plugins.flow_cytometry.ui.widgets.styled_combo import FlowComboBox

_ALL_EVENTS = "All events"
_FIRST_SAMPLE = "The first sample that has one"
_NO_GATES_NOTE = (
    "No scatter gate on these controls yet. To fit on the real cells only, draw a gate "
    "on FSC/SSC (for example Cells) on the control samples in the Workspace tab."
)
_NO_REPORT_NOTE = "Run the method to see what its result rests on."
_ROW_HEIGHT = 30


class MethodSetupPanel(QWidget):
    """Shows and edits one method's setup.

    Signals:
        changed: an option or a per-sample choice changed; what the method
            would do is different now.
    """

    changed = pyqtSignal()

    def __init__(self, state: FlowState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = state
        self._source: MatrixSource | None = None
        self._options = MethodOptions()
        self.setObjectName("MethodSetupPanel")
        self._setup_ui()

    # ── UI ────────────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        outer.addWidget(scroll)

        content = QWidget()
        content.setObjectName("MethodSetupContent")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 12, 16, 16)
        layout.setSpacing(10)
        scroll.setWidget(content)

        self._title = _heading("")
        layout.addWidget(self._title)
        self._explanation = _note("")
        layout.addWidget(self._explanation)

        self._build_illustration(layout)

        self._options_form = QFormLayout()
        self._options_form.setContentsMargins(0, 0, 0, 0)
        self._sample_combo = FlowComboBox()
        self._sample_combo.setObjectName("MethodSampleCombo")
        self._sample_combo.currentIndexChanged.connect(self._on_sample_picked)
        self._gate_combo = FlowComboBox()
        self._gate_combo.setObjectName("MethodGateCombo")
        self._gate_combo.currentIndexChanged.connect(self._on_gate_picked)
        for combo in (self._sample_combo, self._gate_combo):
            pass_wheel_to_page(combo)
        self._options_form.addRow("Read from:", self._sample_combo)
        self._options_form.addRow("Fit on:", self._gate_combo)
        layout.addLayout(self._options_form)
        self._gate_note = _note(_NO_GATES_NOTE)
        layout.addWidget(self._gate_note)

        self._inputs_title = _heading("What this method will use")
        layout.addWidget(self._inputs_title)
        self._inputs_table = _table()
        layout.addWidget(self._inputs_table)

        self._report_title = _heading("What the last run rested on")
        layout.addWidget(self._report_title)
        self._report_note = _note(_NO_REPORT_NOTE)
        layout.addWidget(self._report_note)
        self._report_table = _table()
        layout.addWidget(self._report_table)
        layout.addStretch()

        theme_manager.apply_style(
            content,
            "#MethodSetupContent { background: {BG_DARKEST}; }"
            f" QLabel {{ color: {{FG_SECONDARY}}; font-size: {Fonts.SIZE_SMALL}px;"
            " background: transparent; }"
            " QTableWidget { background: {BG_DARKEST}; color: {FG_PRIMARY};"
            " gridline-color: {BORDER}; border: 1px solid {BORDER}; }"
            " QHeaderView::section { background: {BG_DARK}; color: {FG_SECONDARY};"
            " border: none; padding: 4px 8px; }",
        )

    def _build_illustration(self, layout: QVBoxLayout) -> None:
        """The method's mechanism, drawn on the user's own events. The plot is
        built on first use: most methods have nothing to draw.
        """
        self._illustration_title = _heading("See it step by step")
        layout.addWidget(self._illustration_title)
        self._illustration_combo = FlowComboBox()
        self._illustration_combo.setObjectName("MethodIllustrationCombo")
        self._illustration_combo.currentIndexChanged.connect(lambda _i: self._load_illustration())
        pass_wheel_to_page(self._illustration_combo)
        layout.addWidget(self._illustration_combo, alignment=Qt.AlignmentFlag.AlignLeft)
        self._illustration_slot = QVBoxLayout()
        layout.addLayout(self._illustration_slot)
        self._illustration: FitIllustrationView | None = None
        self._illustration_shown: tuple | None = None

    # ── Public API ────────────────────────────────────────────────────

    def show_method(
        self, source: MatrixSource, options: MethodOptions, report: Table | None
    ) -> None:
        """Render ``source``'s setup. ``options`` is edited in place."""
        self._source = source
        self._options = options
        self._title.setText(f"<b>{source.label}</b>")
        self._explanation.setText(source.explanation)
        self._fill_options(source)
        self._fill_illustration(source)
        self._fill_inputs(source.inputs(self._state, options))
        self._fill_report(report, expected=source.reports)

    # ── Options ───────────────────────────────────────────────────────

    def _fill_options(self, source: MatrixSource) -> None:
        samples = source.sample_choices(self._state)
        gates = source.gate_choices(self._state)
        # A choice that no longer exists (sample removed, gate deleted) falls
        # back to the default rather than silently applying to nothing.
        if samples is None or self._options.sample_id not in {sid for _, sid in samples}:
            self._options.sample_id = None
        if gates is None or self._options.gate not in gates:
            self._options.gate = None

        _repopulate(
            self._sample_combo,
            [(_FIRST_SAMPLE, None), *(samples or [])],
            self._options.sample_id,
        )
        _repopulate(
            self._gate_combo,
            [(_ALL_EVENTS, None), *((gate, gate) for gate in gates or [])],
            self._options.gate,
        )
        self._options_form.setRowVisible(self._sample_combo, samples is not None)
        self._options_form.setRowVisible(self._gate_combo, gates is not None)
        self._gate_combo.setEnabled(bool(gates))
        self._gate_note.setVisible(gates is not None and not gates)

    def _on_sample_picked(self, index: int) -> None:
        self._options.sample_id = self._sample_combo.itemData(index)
        self.changed.emit()

    def _on_gate_picked(self, index: int) -> None:
        self._options.gate = self._gate_combo.itemData(index)
        self.changed.emit()

    # ── Illustration ──────────────────────────────────────────────────

    def _fill_illustration(self, source: MatrixSource) -> None:
        choices = source.illustration_choices(self._state)
        visible = bool(choices)
        self._illustration_title.setVisible(visible)
        self._illustration_combo.setVisible(visible)
        if self._illustration is not None:
            self._illustration.setVisible(visible)
        if not choices:
            self._illustration_shown = None
            return
        _repopulate(self._illustration_combo, choices, self._illustration_combo.currentData())
        self._load_illustration()

    def _load_illustration(self) -> None:
        """Draw the chosen fit, unless that exact fit is already on show
        (a refresh must not restart the steps under the user).
        """
        source = self._source
        if source is None:
            return
        key = self._illustration_combo.currentData()
        labels = tuple(
            self._illustration_combo.itemText(i) for i in range(self._illustration_combo.count())
        )
        wanted = (source.key, key, self._options.gate, labels)
        if wanted == self._illustration_shown or key is None:
            return
        if self._illustration is None:
            self._illustration = FitIllustrationView()
            self._illustration_slot.addWidget(self._illustration)
            self._illustration.show()  # a child added to a visible page isn't shown for us
        self._illustration_shown = wanted
        self._illustration.show_fit(source.illustration(self._state, self._options, key))

    # ── Tables ────────────────────────────────────────────────────────

    def _fill_inputs(self, inputs: Inputs | None) -> None:
        visible = inputs is not None
        self._inputs_title.setVisible(visible)
        self._inputs_table.setVisible(visible)
        if inputs is None:
            return
        headers = list(inputs.headers)
        choice_column = 1 if inputs.choice_header else None
        if choice_column is not None:
            headers.insert(choice_column, inputs.choice_header)
        _fill(
            self._inputs_table,
            headers,
            [
                row.cells
                if choice_column is None
                else (*row.cells[:choice_column], "", *row.cells[choice_column:])
                for row in inputs.rows
            ],
        )
        if choice_column is None:
            return
        for index, row in enumerate(inputs.rows):
            if not row.choices:
                continue
            combo = FlowComboBox()
            _repopulate(combo, list(row.choices), row.choice)
            pass_wheel_to_page(combo)
            combo.currentIndexChanged.connect(
                lambda _i, c=combo, sample_id=row.sample_id: self._on_choice(sample_id, c)
            )
            self._inputs_table.setCellWidget(index, choice_column, combo)
        self._inputs_table.resizeColumnsToContents()

    def _on_choice(self, sample_id: str, combo: FlowComboBox) -> None:
        if self._source is not None:
            self._source.set_choice(self._state, sample_id, combo.currentData())
        self.changed.emit()

    def _fill_report(self, report: Table | None, expected: bool) -> None:
        self._report_title.setVisible(expected)
        self._report_note.setVisible(expected and report is None)
        self._report_table.setVisible(report is not None)
        if report is not None:
            _fill(self._report_table, list(report.headers), list(report.rows))


def _heading(text: str) -> QLabel:
    label = QLabel(f"<b>{text}</b>")
    label.setTextFormat(Qt.TextFormat.RichText)
    return label


def _note(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setTextFormat(Qt.TextFormat.RichText)
    return label


def _table() -> QTableWidget:
    table = QTableWidget()
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
    rows, columns = table.verticalHeader(), table.horizontalHeader()
    assert rows is not None and columns is not None
    rows.setVisible(False)
    rows.setDefaultSectionSize(_ROW_HEIGHT)
    columns.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    columns.setStretchLastSection(True)
    table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    pass_wheel_to_page(table)
    return table


def _fill(table: QTableWidget, headers: list[str], rows: list[tuple[str, ...]]) -> None:
    """Replace the table's contents and size it to show every row (the page scrolls)."""
    table.clear()
    table.setColumnCount(len(headers))
    table.setRowCount(len(rows))
    table.setHorizontalHeaderLabels(headers)
    for r, cells in enumerate(rows):
        for c, text in enumerate(cells):
            table.setItem(r, c, QTableWidgetItem(text))
    header = table.horizontalHeader()
    header_height = header.height() if header is not None else _ROW_HEIGHT
    table.setFixedHeight(header_height + _ROW_HEIGHT * len(rows) + 4)


def _repopulate(combo: FlowComboBox, items: list, current: str | None) -> None:
    """Set a combo's (label, value) items and selection without announcing it."""
    combo.blockSignals(True)
    combo.clear()
    for label, value in items:
        combo.addItem(label, value)
    combo.setCurrentIndex(max(0, combo.findData(current)))
    combo.blockSignals(False)
