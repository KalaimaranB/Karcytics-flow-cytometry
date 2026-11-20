"""The Statistics tab's results table: populations down, sample × statistic across.

Each sample's columns are tinted with its chart colour and set off by a thin
separator column in that colour, so sample boundaries read at a glance.
"""

from __future__ import annotations

from karcytics_sdk.plugin.components import BioMenu, BioTableWidget
from karcytics_sdk.plugin.theme_fallback import Colors
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from ...analysis.statistics import StatType
from ...analysis.statistics_table import StatisticsTable

_Column = tuple[str, int, StatType | None]  # (header, sample index, statistic; None: separator)

_SEPARATOR_PX = 6
_MIN_COLUMN_PX = 80
_ROW_HEIGHT_PX = 28
_TINT_ALPHA = 0x18  # a faint wash of the sample's chart colour behind its cells
_FONT_POINTS = 11


def _tint(color: str) -> QColor:
    """A sample's chart colour, faint (Qt reads 8-digit hex as #AARRGGBB, so set alpha)."""
    tint = QColor(color)
    tint.setAlpha(_TINT_ALPHA)
    return tint


def _cell_font(bold: bool) -> QFont:
    font = QFont()
    font.setBold(bold)
    font.setPointSize(_FONT_POINTS)
    return font


class StatisticsTableView(BioTableWidget):
    """Shows a `StatisticsTable`; right-click to copy rows or export."""

    # A class default: BioTableWidget's __init__ already calls _apply_theme_styles.
    _table: StatisticsTable | None = None

    copy_all_requested = Signal()
    export_requested = Signal()
    rows_copied = Signal(int)  # how many rows "Copy Selected Rows" put on the clipboard

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("StatsResultsTable")
        if (header := self.verticalHeader()) is not None:
            header.setVisible(False)
            header.setDefaultSectionSize(_ROW_HEIGHT_PX)
        if (header := self.horizontalHeader()) is not None:
            header.setStretchLastSection(False)
            header.setMinimumSectionSize(_SEPARATOR_PX)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_menu)

    def show_table(self, table: StatisticsTable) -> None:
        """Fill the grid: Population, then per sample a separator and its statistics."""
        self._table = table
        request = table.request
        palette = Colors.CHART_COLORS
        columns: list[_Column] = []
        for s, name in enumerate(table.sample_names):
            columns.append(("", s, None))  # separator
            columns += [(f"{name}\n{stat.label}", s, stat) for stat in request.stats]

        self.clear()
        self.setRowCount(len(table.rows))
        self.setColumnCount(1 + len(columns))
        self.setHorizontalHeaderLabels(["Population", *(header for header, _s, _st in columns)])
        tints = [_tint(palette[s % len(palette)]) for s in range(len(table.sample_names))]
        foreground = QBrush(QColor(Colors.FG_PRIMARY))
        population_bg = QBrush(QColor(Colors.BG_DARK))
        bold, normal = _cell_font(bold=True), _cell_font(bold=False)

        for r, row in enumerate(table.rows):
            self.setItem(r, 0, self._item(row.population, foreground, population_bg, bold))
            for c, (_header, s, stat) in enumerate(columns, start=1):
                color = palette[s % len(palette)]
                if stat is None:
                    separator = QTableWidgetItem("")
                    separator.setBackground(QBrush(QColor(color)))
                    separator.setFlags(Qt.ItemFlag.ItemIsEnabled)
                    self.setItem(r, c, separator)
                    continue
                cell = row.cell(request.sample_ids[s], stat)
                item = self._item(cell.shown, foreground, QBrush(tints[s]), normal)
                if cell.scale:
                    item.setForeground(QBrush(QColor(Colors.ACCENT_WARNING)))
                    item.setToolTip(
                        f"Estimated: UMAP only clustered a {100 / cell.scale:.0f}% subsample of "
                        "this sample. Scaled up to estimate the full population — treat as an "
                        "estimate, not an exact count."
                    )
                self.setItem(r, c, item)
        self._size_columns(columns)

    @staticmethod
    def _item(text: str, foreground: QBrush, background: QBrush, font: QFont) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        item.setForeground(foreground)
        item.setBackground(background)
        item.setFont(font)
        return item

    def _size_columns(self, columns: list[_Column]) -> None:
        separators = {c for c, (_h, _s, stat) in enumerate(columns, start=1) if stat is None}
        for c in range(self.columnCount()):
            if c in separators:
                self.setColumnWidth(c, _SEPARATOR_PX)
            else:
                self.resizeColumnToContents(c)
                self.setColumnWidth(c, max(self.columnWidth(c), _MIN_COLUMN_PX))

    def as_tsv(self, rows: list[int] | None = None) -> str:
        """The header and ``rows`` (default: every row) as tab-separated text."""

        def text(item: QTableWidgetItem | None) -> str:
            return item.text() if item is not None else ""

        columns = range(self.columnCount())
        # Headers wrap onto two lines on screen ("Sample 1\nCount"); one line each here.
        headers = (text(self.horizontalHeaderItem(c)).replace("\n", " ") for c in columns)
        lines = ["\t".join(headers)]
        for r in range(self.rowCount()) if rows is None else rows:
            lines.append("\t".join(text(self.item(r, c)) for c in columns))
        return "\n".join(lines)

    def selected_rows(self) -> list[int]:
        return sorted(
            {
                r
                for span in self.selectedRanges()
                for r in range(span.topRow(), span.bottomRow() + 1)
            }
        )

    def _apply_theme_styles(self) -> None:
        super()._apply_theme_styles()
        if self._table is not None:
            self.show_table(self._table)  # its tints come from the theme's chart colours

    def _show_menu(self, pos) -> None:
        menu = BioMenu(self)
        menu.addAction("📋 Copy Selected Rows", self._copy_selected)
        menu.addAction("📋 Copy All", self.copy_all_requested.emit)
        menu.addSeparator()
        menu.addAction("📤 Export Table as CSV...", self.export_requested.emit)
        if (viewport := self.viewport()) is not None:
            menu.exec(viewport.mapToGlobal(pos))

    def _copy_selected(self) -> None:
        rows = self.selected_rows()
        if not rows:
            return
        QApplication.clipboard().setText(self.as_tsv(rows))
        self.rows_copied.emit(len(rows))
