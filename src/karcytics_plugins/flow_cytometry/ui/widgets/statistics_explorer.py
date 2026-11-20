"""The Statistics tab: pick populations and statistics, then see them as a table or chart.

A sidebar picks the populations (across samples), the statistics and the
channel for the ★ ones; Compute builds the table in the background
(`analysis.statistics_table`). The chart draws one statistic of that table,
rendered off the GUI thread. The table exports to CSV or the clipboard, the
chart to PNG/SVG.
"""

from __future__ import annotations

import logging
from typing import Any

import shiboken6
from karcytics_sdk.plugin import BioSectionLabel, submit_task
from karcytics_sdk.plugin.components import (
    BioCaptionLabel,
    BioComboBox,
    BioHelpButton,
    BioScrollArea,
    BioToggleButton,
    PrimaryButton,
    SecondaryButton,
    repopulate_combo,
)
from karcytics_sdk.plugin.dialogs import get_save_path
from karcytics_sdk.plugin.managed_task import FunctionalTask
from karcytics_sdk.plugin.rendering.lock import MPL_RASTER_LOCK
from karcytics_sdk.plugin.runtime_services import diagnostics
from karcytics_sdk.plugin.theme_fallback import Colors, theme_manager
from matplotlib.figure import Figure
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ...analysis.fcs_io import get_channel_marker_label
from ...analysis.state import FlowState
from ...analysis.statistics_table import (
    StatisticsRequest,
    StatisticsTable,
    compute_table,
    picks_of,
    write_csv,
)
from ..academy_context import PopulationPicks, StatisticsSnapshot
from ..graph.figure_renderer import FigureRenderWorker
from .copyable import CopyableCanvas
from .selection.selector_panel import SampleAndPopulationSelector
from .stat_picker import StatPicker
from .statistics_chart_renderer import CHART_TYPES, StatisticsChartRenderer
from .statistics_table_view import StatisticsTableView

logger = logging.getLogger(__name__)

_SIDEBAR_PX = 300
_PLACEHOLDER, _TABLE, _CHART = 0, 1, 2  # pages of the display stack


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


class StatisticsExplorer(QWidget):
    """The Statistics tab: a picking sidebar beside a table/chart workspace."""

    def __init__(
        self,
        state: FlowState,
        gate_coordinator: Any | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._state = state
        self._gate_coordinator = gate_coordinator
        self._table: StatisticsTable | None = None  # the last computed results
        self._computing = False
        self._figure: Figure | None = None  # the chart on screen
        self._chart_worker: FigureRenderWorker | None = None
        self._chart_stale = False  # the chart's settings changed while it rendered
        # Exports that succeeded ("csv", "copy", "plot"); the Academy's export
        # checklist (ExportDoneValidator) reads it.
        self.completed_exports: set[str] = set()

        theme_manager.apply_style(self, "background-color: {BG_DARKEST};")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_sidebar())
        layout.addWidget(self._build_workspace(), stretch=1)
        self.refresh_samples()

    # ── Public API ───────────────────────────────────────────────────────

    def academy_snapshot(self) -> StatisticsSnapshot:
        return StatisticsSnapshot(
            PopulationPicks.of(self._selector),
            frozenset(self._stat_picker.selected()),
            self._chart_type_combo.currentText(),
            self._channel_combo.currentData(),
            self._table is not None and bool(self._table.rows),
        )

    def refresh_samples(self) -> None:
        """Re-list the experiment's samples (its selectionChanged refreshes the channels)."""
        self._selector.refresh(self._state.data.experiment.samples)

    def refresh_channels(self) -> None:
        """Rebuild the channel picker from the first checked sample (e.g. new derived channels)."""
        items: list[tuple[str, str]] = []
        sample_ids = self._selector.get_checked_sample_ids()
        sample = self._state.data.experiment.samples.get(sample_ids[0]) if sample_ids else None
        if sample is not None and sample.fcs_data is not None:
            fcs = sample.fcs_data
            items = [(get_channel_marker_label(fcs, ch), ch) for ch in fcs.channels]
        repopulate_combo(self._channel_combo, items, restore_data=self._channel_combo.currentData())

    # ── Layout ───────────────────────────────────────────────────────────

    def _build_sidebar(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        self._selector = SampleAndPopulationSelector(multi_population=True)
        self._selector.population_edit_button.setObjectName("StatsPopulationPickerButton")
        self._selector.selectionChanged.connect(self.refresh_channels)
        layout.addWidget(self._selector)

        layout.addLayout(
            _heading(
                "Statistics",
                "Select which statistics to compute. Statistics marked with ★ "
                "require a channel to be selected below.",
            )
        )
        self._stat_picker = StatPicker()
        layout.addWidget(self._stat_picker)
        star = QLabel("★ requires a channel selection")
        theme_manager.apply_style(
            star, "color: {FG_DISABLED}; font-size: 10px; font-style: italic;"
        )
        layout.addWidget(star)

        layout.addLayout(
            _heading(
                "Channel (★ stats)",
                "Select the fluorescence channel for parameter-dependent statistics "
                "(Mean, Median, MFI, CV, SD, etc.). This channel is used for all ★ stats.",
            )
        )
        self._channel_combo = BioComboBox()
        self._channel_combo.setObjectName("StatsChannelCombo")
        layout.addWidget(self._channel_combo)
        layout.addSpacing(16)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 0)  # busy, no percentage
        self._progress_bar.setFixedHeight(4)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.hide()
        layout.addWidget(self._progress_bar)
        self._compute_btn = PrimaryButton("📊 Compute Statistics")
        self._compute_btn.setObjectName("StatsComputeButton")
        self._compute_btn.clicked.connect(self._on_compute)
        layout.addWidget(self._compute_btn)
        self._export_btn = self._result_button(
            "📤 Export CSV", "StatsExportButton", "Export the statistics table to a CSV file"
        )
        self._export_btn.clicked.connect(self._on_export)
        layout.addWidget(self._export_btn)
        self._copy_all_btn = self._result_button(
            "📋 Copy All", "StatsCopyAllButton", "Copy all statistics data to clipboard"
        )
        self._copy_all_btn.clicked.connect(self._on_copy_all)
        layout.addWidget(self._copy_all_btn)
        layout.addStretch()

        scroll = BioScrollArea()
        scroll.setWidget(content)
        sidebar = QWidget()
        sidebar.setFixedWidth(_SIDEBAR_PX)
        theme_manager.apply_style(
            sidebar, "background-color: {BG_DARKEST}; border-right: 1px solid {BORDER};"
        )
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.addWidget(scroll)
        return sidebar

    @staticmethod
    def _result_button(text: str, name: str, tip: str) -> SecondaryButton:
        """A button that acts on computed results, so starts disabled."""
        button = SecondaryButton(text)
        button.setObjectName(name)
        button.setToolTip(tip)
        button.setEnabled(False)
        return button

    def _build_workspace(self) -> QWidget:
        workspace = QWidget()
        theme_manager.apply_style(workspace, "background-color: {BG_DARK};")
        layout = QVBoxLayout(workspace)
        layout.setContentsMargins(16, 12, 16, 16)
        layout.setSpacing(10)
        layout.addLayout(self._build_toolbar())

        self._display_stack = QStackedWidget()
        self._display_stack.addWidget(_placeholder())

        self._table_view = StatisticsTableView()
        self._table_view.copy_all_requested.connect(self._on_copy_all)
        self._table_view.export_requested.connect(self._on_export)
        self._table_view.rows_copied.connect(
            lambda n: self._status_lbl.setText(f"✓ Copied {_plural(n, 'row')} to clipboard")
        )
        self._estimated_caption = QLabel(
            "* estimated — scaled up from a UMAP subsample; see cell tooltip."
        )
        theme_manager.apply_style(
            self._estimated_caption, "color: {ACCENT_WARNING}; font-size: 11px; padding: 0 8px;"
        )
        self._estimated_caption.hide()
        table_page = QWidget()
        table_layout = QVBoxLayout(table_page)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.setSpacing(4)
        table_layout.addWidget(self._table_view)
        table_layout.addWidget(self._estimated_caption)
        self._display_stack.addWidget(table_page)

        self._chart_page = QWidget()
        self._chart_page.setObjectName("StatsChartCanvas")
        theme_manager.apply_style(self._chart_page, "background: {BG_DARKEST}; border-radius: 8px;")
        self._chart_layout = QVBoxLayout(self._chart_page)
        self._chart_layout.setContentsMargins(0, 0, 0, 0)
        self._display_stack.addWidget(self._chart_page)

        layout.addWidget(self._display_stack, stretch=1)
        return workspace

    def _build_toolbar(self) -> QHBoxLayout:
        toolbar = QHBoxLayout()
        self._status_lbl = QLabel("Select samples and populations, then click Compute.")
        theme_manager.apply_style(self._status_lbl, "color: {FG_SECONDARY}; font-size: 12px;")
        toolbar.addWidget(self._status_lbl)
        toolbar.addStretch()

        self._view_buttons = QButtonGroup(self)
        self._view_buttons.setExclusive(True)
        for page, text, tip, name in (
            (_TABLE, "📋 Table", "Show data as a table", "StatsTableMode"),
            (_CHART, "📈 Chart", "Show data as a chart", "StatsChartMode"),
        ):
            button = BioToggleButton(text)
            button.setObjectName(name)
            button.setToolTip(tip)
            button.setChecked(page == _TABLE)
            self._view_buttons.addButton(button, page)
            toolbar.addWidget(button)
        self._view_buttons.idClicked.connect(self._show_page)

        self._chart_type_combo = BioComboBox()
        self._chart_type_combo.setObjectName("StatsChartTypeCombo")
        self._chart_type_combo.addItems(list(CHART_TYPES))
        self._chart_type_combo.setFixedWidth(130)
        self._chart_type_combo.currentIndexChanged.connect(self._redraw_chart)
        self._chart_stat_combo = BioComboBox()
        self._chart_stat_combo.setFixedWidth(150)
        self._chart_stat_combo.currentIndexChanged.connect(self._redraw_chart)
        self._export_plot_btn = SecondaryButton("📸 Export")
        self._export_plot_btn.setObjectName("StatsExportPlotButton")
        self._export_plot_btn.setToolTip("Export plot to PNG/SVG")
        self._export_plot_btn.clicked.connect(self._on_export_plot)
        self._chart_controls: list[QWidget] = [
            self._chart_type_combo,
            self._chart_stat_combo,
            self._export_plot_btn,
        ]
        for control in self._chart_controls:
            control.hide()
            toolbar.addWidget(control)
        return toolbar

    def _show_page(self, page: int) -> None:
        """Show the table or the chart (and the chart's controls with it)."""
        self._display_stack.setCurrentIndex(page)
        button = self._view_buttons.button(page)
        if button is not None:
            button.setChecked(True)
        for control in self._chart_controls:
            control.setVisible(page == _CHART)
        if page == _CHART:
            self._redraw_chart()

    # ── Compute ──────────────────────────────────────────────────────────

    def _request(self) -> StatisticsRequest | str:
        """What Compute would compute, or why it can't yet."""
        sample_ids = self._selector.get_checked_sample_ids()
        populations = self._selector.get_checked_populations()
        stats = self._stat_picker.selected()
        channel = self._channel_combo.currentData()
        if not sample_ids:
            return "⚠ No samples selected."
        if not populations:
            return "⚠ No populations selected."
        if not stats:
            return "⚠ No statistics selected."
        if not channel and any(stat.needs_channel for stat in stats):
            return "⚠ Select a channel for parameter-dependent statistics."
        return StatisticsRequest(tuple(sample_ids), picks_of(populations), tuple(stats), channel)

    def _on_compute(self) -> None:
        if self._computing:
            return
        request = self._request()
        if isinstance(request, str):
            self._status_lbl.setText(request)
            return
        self._computing = True
        self._status_lbl.setText("⏳ Computing in background…")
        self._compute_btn.hide()
        self._progress_bar.show()
        for button in (self._export_btn, self._copy_all_btn, self._export_plot_btn):
            button.setEnabled(False)
        experiment = self._state.data.experiment
        submit_task(
            FunctionalTask(
                lambda: {"table": compute_table(experiment, request)},
                "flow_cytometry",
                "Statistics",
            ),
            on_finished=self._on_computed,
            on_error=self._on_compute_failed,
        )

    def _on_computed(self, results: dict) -> None:
        if not shiboken6.isValid(self):
            return  # the tab closed while computing
        self._end_compute()
        self.show_table(results["table"])

    def show_table(self, table: StatisticsTable) -> None:
        """Show computed results in the table (and the chart's statistic picker)."""
        self._table = table
        self._table_view.show_table(table)
        self._estimated_caption.setVisible(table.has_estimates)
        repopulate_combo(self._chart_stat_combo, [(s.label, s) for s in table.request.stats])
        for button in (self._export_btn, self._copy_all_btn, self._export_plot_btn):
            button.setEnabled(True)
        request = table.request
        self._status_lbl.setText(
            f"✓ {_plural(len(table.rows), 'population')} × {_plural(len(request.stats), 'stat')} "
            f"across {_plural(len(request.sample_ids), 'sample')}."
        )
        self._show_page(_TABLE)

    def _on_compute_failed(self, message: str) -> None:
        if not shiboken6.isValid(self):
            return
        logger.error("Statistics computation failed: %s", message)
        self._end_compute()
        self._status_lbl.setText(f"❌ Error: {message}")

    def _end_compute(self) -> None:
        self._computing = False
        self._progress_bar.hide()
        self._compute_btn.show()

    # ── Chart (rendered off the GUI thread) ──────────────────────────────

    def _redraw_chart(self) -> None:
        stat = self._chart_stat_combo.currentData()
        if self._table is None or stat is None or self._display_stack.currentIndex() != _CHART:
            return
        if self._chart_worker is not None and self._chart_worker.isRunning():
            self._chart_stale = True  # redrawn with the new settings when this one lands
            return
        self._chart_stale = False
        values, estimated = self._table.values(stat)
        worker = FigureRenderWorker(
            StatisticsChartRenderer(),
            {
                "chart_type": self._chart_type_combo.currentText(),
                "stat_label": stat.label,
                "population_labels": [row.population for row in self._table.rows],
                "sample_names": list(self._table.sample_names),
                "values": values,
                "estimated": estimated,
                "palette": list(Colors.CHART_COLORS),
                "background": Colors.BG_DARKEST,
                "panel": Colors.BG_DARK,
                "foreground": Colors.FG_PRIMARY,
                "secondary": Colors.FG_SECONDARY,
                "border": Colors.BORDER,
                "accent": Colors.ACCENT_PRIMARY,
                "warning": Colors.ACCENT_WARNING,
            },
            self,
        )
        worker.finished_ok.connect(self._on_chart_rendered)
        worker.finished_err.connect(self._on_chart_failed)
        # Qt aborts if a running QThread is destroyed with its parent: wait it out.
        self.destroyed.connect(lambda *_: worker.stop_and_wait())
        self._chart_worker = worker
        worker.start()

    def _on_chart_rendered(self, figure: Figure) -> None:
        self._figure = figure
        while (item := self._chart_layout.takeAt(0)) is not None:
            if (old := item.widget()) is not None:
                old.deleteLater()
        self._chart_layout.addWidget(CopyableCanvas(figure))
        if self._chart_stale:
            self._redraw_chart()

    def _on_chart_failed(self, message: str) -> None:
        logger.error("Statistics chart failed: %s", message)
        self._status_lbl.setText(f"❌ The chart could not be drawn: {message}")
        if self._chart_stale:
            self._redraw_chart()

    def _apply_theme_styles(self) -> None:
        self._redraw_chart()  # the theme's colours are drawn into the figure

    # ── Export ───────────────────────────────────────────────────────────

    def _on_export_plot(self) -> None:
        if self._figure is None:
            return
        path = get_save_path(
            self,
            "Export Plot",
            "statistics_plot.png",
            "PNG Image (*.png);;SVG Image (*.svg);;All Files (*)",
        )
        if not path:
            return
        try:
            with MPL_RASTER_LOCK:  # savefig rasterizes through the shared Agg backend
                self._figure.savefig(
                    path, dpi=300, bbox_inches="tight", facecolor=self._figure.get_facecolor()
                )
        except Exception as exc:  # noqa: BLE001 - reported as a diagnostic, not a crash
            self._report_export_failure("Statistics plot export failed", exc)
            return
        self._status_lbl.setText(f"✓ Plot exported to {path}")
        self.completed_exports.add("plot")

    def _on_copy_all(self) -> None:
        if self._table is None:
            return
        QApplication.clipboard().setText(self._table_view.as_tsv())
        self._status_lbl.setText(
            f"✓ Copied all {_plural(len(self._table.rows), 'row')} to clipboard"
        )
        self.completed_exports.add("copy")

    def _on_export(self) -> None:
        if self._table is None:
            return
        path = get_save_path(
            self,
            "Export Statistics to CSV",
            "statistics_export.csv",
            "CSV Files (*.csv);;All Files (*)",
        )
        if not path:
            return
        try:
            write_csv(path, self._table)
        except Exception as exc:  # noqa: BLE001 - a failed export reports, never crashes the button
            self._report_export_failure("Statistics CSV export failed", exc)
            return
        self._status_lbl.setText(f"✓ Exported to {path}")
        self.completed_exports.add("csv")

    def _report_export_failure(self, what: str, exc: Exception) -> None:
        logger.exception(what)
        self._status_lbl.setText(f"❌ Export failed: {exc}")
        diagnostics.report_error(what, exception=exc, fatal=False)


def _heading(text: str, help_text: str) -> QHBoxLayout:
    """A sidebar section label with its help button."""
    row = QHBoxLayout()
    row.addWidget(BioSectionLabel(text))
    help_button = BioHelpButton()
    help_button.setHelpText(help_text, text)
    row.addWidget(help_button)
    row.addStretch()
    return row


def _placeholder() -> QWidget:
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
    icon = QLabel("📊")
    icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
    icon.setStyleSheet("font-size: 48px;")
    layout.addWidget(icon)
    hint = BioCaptionLabel(
        "Select samples, populations and statistics\nthen click Compute to generate results."
    )
    hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
    layout.addWidget(hint)
    return page
