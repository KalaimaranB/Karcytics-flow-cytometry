"""The selected population in every sample that has it."""

from __future__ import annotations

from karcytics_sdk.plugin.components import BioCaptionLabel, BioTableWidget, SubtitleLabel
from karcytics_sdk.plugin.theme_fallback import Colors
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableWidgetItem, QVBoxLayout, QWidget

from ....analysis.sample_lens import SampleCheck
from ....analysis.sample_lens.edges import FRAGILE_ABOVE

_COLUMNS = ("Sample", "% parent", "Events", "On edge", "Flags")


class AcrossSamples(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self._title = SubtitleLabel("Across samples")
        layout.addWidget(self._title)
        layout.addWidget(
            BioCaptionLabel(
                "“On edge” is the share of the parent sitting right at the gate's edge: above "
                f"{FRAGILE_ABOVE:.0%}, a small shift moves the result a lot. Outliers are far "
                "from the other samples' median."
            )
        )
        self._table = BioTableWidget()
        self._table.setColumnCount(len(_COLUMNS))
        self._table.setHorizontalHeaderLabels(_COLUMNS)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        header = self._table.horizontalHeader()
        for col in range(len(_COLUMNS) - 1):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(len(_COLUMNS) - 1, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self._table, 1)

    def show_checks(
        self, population: str | None, checks: list[SampleCheck], current_id: str | None
    ) -> None:
        self._title.setText(f"Across samples · {population}" if population else "Across samples")
        self._table.setRowCount(len(checks))
        for row, check in enumerate(checks):
            cells = (
                check.sample_name,
                f"{check.pct_parent:.1f}%",
                f"{check.count:,}",
                f"{check.edge_fraction:.1%}",
                "\n".join(f"⚠ {flag}" for flag in check.flags) or "✓",
            )
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if 0 < col < len(cells) - 1:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                if col == len(cells) - 1:
                    item.setForeground(
                        QColor(Colors.ACCENT_WARNING if check.flags else Colors.ACCENT_SUCCESS)
                    )
                if check.sample_id == current_id:
                    font = QFont(item.font())
                    font.setBold(True)
                    item.setFont(font)
                self._table.setItem(row, col, item)
        self._table.resizeRowsToContents()
