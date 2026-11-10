"""Apply to group: the proposed gates on every sample, and whether each sample fits them.

Accepted gates go to every sample unchanged. For each sample the split is also
redone on its own events (dashed grey): where that sits far from the gates,
the sample is flagged for a look.
"""

from __future__ import annotations

from karcytics_sdk.plugin.components import (
    BioCaptionLabel,
    BioScrollArea,
    BioTableWidget,
    SubtitleLabel,
)
from karcytics_sdk.plugin.theme_fallback import Colors, theme_manager
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QGridLayout,
    QHeaderView,
    QLabel,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ....analysis.autogate.models import GroupPreview, SampleOutcome
from ..panel_style import card, clear_layout
from .proposal_plot import ProposalPlot

PLOTS_PER_ROW = 3
MINI_PLOT_HEIGHT = 190
TABLE_HEIGHT = 200


class ApplyPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 12, 0, 0)
        layout.setSpacing(10)
        self._title = SubtitleLabel("Apply to the group")
        layout.addWidget(self._title)
        layout.addWidget(
            BioCaptionLabel(
                "Accepted gates go to every sample in the group unchanged, like any gate you draw. "
                "Dashed grey: where each sample's own split would be. A sample whose own split sits "
                "far from the gates is flagged. Control samples (unstained, single stains, FMOs) are skipped."
            )
        )
        self._table = BioTableWidget()
        self._table.setObjectName("AutoGateGroupTable")
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.setFixedHeight(TABLE_HEIGHT)
        layout.addWidget(self._table)

        scroll = BioScrollArea()
        scroll.setWidgetResizable(True)
        grid_host = QWidget()
        self._grid = QGridLayout(grid_host)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(10)
        scroll.setWidget(grid_host)
        layout.addWidget(scroll, 1)
        self.show_preview(None, "")

    def show_preview(self, preview: GroupPreview | None, group_name: str) -> None:
        self._title.setText(f"Apply to {group_name}" if group_name else "Apply to the group")
        clear_layout(self._grid)
        if preview is None:
            self._table.clear()
            self._table.setRowCount(0)
            self._table.setColumnCount(0)
            self._grid.addWidget(
                BioCaptionLabel("Propose a split on the Build page to see it on every sample."),
                0,
                0,
            )
            return
        self._fill_table(preview)
        for i, row in enumerate(preview.rows):
            self._grid.addWidget(self._sample_card(row), i // PLOTS_PER_ROW, i % PLOTS_PER_ROW)

    def _fill_table(self, preview: GroupPreview) -> None:
        headers = ["Sample", *[f"{p} %" for p in preview.populations], "Drift", "Status"]
        self._table.clear()
        self._table.setColumnCount(len(headers))
        self._table.setHorizontalHeaderLabels(headers)
        self._table.setRowCount(len(preview.rows))
        warn = QColor(Colors.ACCENT_WARNING)
        muted = QColor(Colors.FG_SECONDARY)
        for r, row in enumerate(preview.rows):
            cells = [row.sample]
            cells += [
                f"{row.percents[p]:.1f}" if p in row.percents else "—" for p in preview.populations
            ]
            cells += [f"{row.drift:.0%}" if row.plot is not None else "—", row.status]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if 0 < c < len(cells) - 1:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                if row.flagged:
                    item.setForeground(warn)
                elif row.plot is None:
                    item.setForeground(muted)
                self._table.setItem(r, c, item)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(len(headers) - 1, QHeaderView.ResizeMode.Stretch)

    @staticmethod
    def _sample_card(row: SampleOutcome) -> QWidget:
        frame = card("AutoGateSampleCard")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)
        name = QLabel(row.sample)
        tone = "ACCENT_WARNING" if row.flagged else "FG_PRIMARY"
        theme_manager.apply_style(name, f"color: {{{tone}}}; font-weight: bold;")
        layout.addWidget(name)
        plot = ProposalPlot(compact=True)
        plot.setFixedHeight(MINI_PLOT_HEIGHT)
        plot.set_plot(row.plot, dashed=False, empty_text=row.status)
        layout.addWidget(plot)
        layout.addWidget(BioCaptionLabel(row.status))
        return frame
