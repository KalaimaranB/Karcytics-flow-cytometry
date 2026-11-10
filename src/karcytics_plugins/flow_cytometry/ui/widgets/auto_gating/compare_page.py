"""Compare methods: each method's strategy beside your own gates.

Previews only: nothing is added from here.
"""

from __future__ import annotations

from karcytics_sdk.plugin.components import (
    BioCaptionLabel,
    BioScrollArea,
    SecondaryButton,
    SubtitleLabel,
)
from karcytics_sdk.plugin.theme_fallback import theme_manager
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ....analysis.autogate.models import MethodOutcome
from ..panel_style import card, clear_layout, section_header
from .proposal_plot import ProposalPlot

COLUMN_MIN_WIDTH = 220
MINI_PLOT_HEIGHT = 200


class ComparePage(QWidget):
    use_clicked = Signal(str)  # method key

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 12, 0, 0)
        layout.setSpacing(10)
        self._title = SubtitleLabel("Compare methods")
        layout.addWidget(self._title)
        layout.addWidget(
            BioCaptionLabel(
                "Every method's first split of the same population, beside the gates you drew under "
                "it. “Agrees” is F1 against your best-matching gate (1 = the same cells). Previews "
                "only: nothing is added from here."
            )
        )
        scroll = BioScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        self._columns = QHBoxLayout(host)
        self._columns.setContentsMargins(0, 0, 0, 0)
        self._columns.setSpacing(12)
        scroll.setWidget(host)
        layout.addWidget(scroll, 1)
        self.show_outcomes((), "")

    def show_outcomes(self, outcomes: tuple[MethodOutcome, ...], population: str) -> None:
        self._title.setText(f"Compare methods on {population}" if population else "Compare methods")
        clear_layout(self._columns)
        if not outcomes:
            self._columns.addWidget(
                BioCaptionLabel("Pick a population to compare the methods on it.")
            )
            return
        for outcome in outcomes:
            self._columns.addWidget(self._column(outcome), 1)

    def _column(self, outcome: MethodOutcome) -> QWidget:
        frame = card("AutoGateCompareCard")
        frame.setMinimumWidth(COLUMN_MIN_WIDTH)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        title = QLabel(outcome.label)
        theme_manager.apply_style(title, "color: {FG_PRIMARY}; font-weight: bold; font-size: 14px;")
        layout.addWidget(title)
        if outcome.summary:
            layout.addWidget(BioCaptionLabel(outcome.summary))
        plot = ProposalPlot(compact=True)
        plot.setFixedHeight(MINI_PLOT_HEIGHT)
        own = "Each of your gates is on its own axes: compare by the numbers below."
        empty = outcome.error or (own if not outcome.method_key else "")
        plot.set_plot(outcome.plot, dashed=bool(outcome.method_key), empty_text=empty)
        layout.addWidget(plot)
        if outcome.error:
            layout.addStretch()
            return frame

        layout.addWidget(section_header("Populations"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.addWidget(BioCaptionLabel(""), 0, 0)
        grid.addWidget(BioCaptionLabel("% parent"), 0, 1, Qt.AlignmentFlag.AlignRight)
        grid.addWidget(BioCaptionLabel("agrees"), 0, 2, Qt.AlignmentFlag.AlignRight)
        for r, (name, pct) in enumerate(outcome.percents.items(), start=1):
            name_label = QLabel(name)
            theme_manager.apply_style(name_label, "color: {FG_PRIMARY};")
            grid.addWidget(name_label, r, 0)
            grid.addWidget(QLabel(f"{pct:.1f}"), r, 1, Qt.AlignmentFlag.AlignRight)
            f1 = outcome.agreement.get(name)
            grid.addWidget(
                QLabel("—" if f1 is None else f"{f1:.2f}"), r, 2, Qt.AlignmentFlag.AlignRight
            )
        layout.addLayout(grid)
        layout.addStretch()
        if outcome.method_key:
            use = SecondaryButton("Use this method")
            use.setToolTip("Switch the Build page to this method.")
            use.setObjectName(f"AutoGateUse_{outcome.method_key}")
            use.clicked.connect(lambda _c=False, key=outcome.method_key: self.use_clicked.emit(key))
            layout.addWidget(use)
        return frame
