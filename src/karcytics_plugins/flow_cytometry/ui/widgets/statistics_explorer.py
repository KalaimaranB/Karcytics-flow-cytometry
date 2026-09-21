"""Statistics Explorer — full-screen statistics view for the Statistics tab.

Follows the same architectural pattern as ``PopulationAnalysisViewer``:
a fixed-width left sidebar for data/stat selection and a right workspace
for table and chart visualizations.

Features
--------
* Multi-select samples and populations (gated nodes).
* Checklist of statistic types (Count, Mean, Median, CV, %Parent, etc.).
* Channel selector for parameter-dependent statistics.
* Table view: rows = populations, columns = sample × stat combinations.
* Chart view: matplotlib bar chart comparing one stat across samples/populations.
* CSV export via QFileDialog.
* Karcytics SDK components (BioHelpButton, BioComboBox, PrimaryButton, etc.)
  and full theme_manager integration.
"""

from __future__ import annotations

import csv
import logging
from typing import TYPE_CHECKING, Any

import numpy as np
from karcytics_sdk.plugin.components import (
    BioComboBox,
    BioHelpButton,
    PrimaryButton,
    SecondaryButton,
)
from karcytics_sdk.plugin.rendering.lock import MPL_RASTER_LOCK
from karcytics_sdk.plugin.theme_fallback import Colors, get_contrast_text_color, theme_manager
from karcytics_sdk.plugin.worker_thread import OneShotWorkerThread
from matplotlib.colors import LinearSegmentedColormap, to_hex
from matplotlib.figure import Figure
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QBrush, QColor, QFont
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QProgressBar,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from karcytics_plugins.flow_cytometry.analysis.fcs_io import get_channel_marker_label
from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.analysis.statistics import (
    StatType,
    compute_statistic,
)
from karcytics_plugins.flow_cytometry.ui.graph._mpl_compat import (
    LockedFigureCanvas as FigureCanvasQTAgg,  # thread-safe vs RenderTask's Agg rasterization
)
from karcytics_plugins.flow_cytometry.ui.widgets.checkbox_style import checkbox_qss
from karcytics_plugins.flow_cytometry.ui.widgets.selection.selector_panel import (
    SampleAndPopulationSelector,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


# ── Stat type metadata ────────────────────────────────────────────────────────

_STAT_NEEDS_CHANNEL = {
    StatType.COUNT: False,
    StatType.MEAN: True,
    StatType.MEDIAN: True,
    StatType.GEOMETRIC_MEAN: True,
    StatType.MODE: True,
    StatType.SD: True,
    StatType.CV: True,
    StatType.MFI: True,
    StatType.PERCENT_PARENT: False,
    StatType.PERCENT_GRANDPARENT: False,
    StatType.PERCENT_TOTAL: False,
    StatType.MIN: True,
    StatType.MAX: True,
}

_STAT_HELP = {
    StatType.COUNT: "<b>Count</b><br>Total number of events (cells/particles) in the population.<br><br><i>When to use:</i> Useful for quantifying absolute yield or analyzing absolute counts from volumetric data.",
    StatType.MEAN: "<b>Arithmetic Mean</b><br>The average fluorescence intensity.<br><br><i>When to use:</i> Use for linear data (like FSC or SSC). <b>Not recommended</b> for log-scaled fluorescence, as outliers heavily skew the mean.",
    StatType.MEDIAN: "<b>Median</b><br>The 50th percentile of fluorescence intensity.<br><br><i>When to use:</i> The standard metric for reporting fluorescence intensity. Robust against outliers and highly skewed log-normal distributions.",
    StatType.GEOMETRIC_MEAN: "<b>Geometric Mean</b><br>The average of the logarithmic values.<br><br><i>When to use:</i> Good for log-normally distributed fluorescence data. Often behaves similarly to the median.",
    StatType.MODE: "<b>Mode</b><br>The most frequent value (the peak of the histogram).<br><br><i>When to use:</i> Useful when comparing the primary peak position of a highly skewed or bimodal population.",
    StatType.SD: "<b>Standard Deviation (SD)</b><br>Measures the absolute spread of the data.<br><br><i>When to use:</i> Typically used on linear channels (like FSC/SSC) to quantify the width of a population.",
    StatType.CV: "<b>Coefficient of Variation (CV)</b><br>The standard deviation divided by the mean, expressed as a percentage.<br><br><i>When to use:</i> Critical for assessing peak sharpness in fluorescence channels. A high CV indicates a very broad, spread-out population.",
    StatType.MFI: "<b>Median Fluorescence Intensity (MFI)</b><br>Exactly the same as Median, but explicitly names Fluorescence.<br><br><i>When to use:</i> The standard choice for comparing expression levels of a fluorescent marker between samples.",
    StatType.PERCENT_PARENT: "<b>% Parent</b><br>The fraction of events relative to the immediate parent gate.<br><br><i>When to use:</i> Shows the step-by-step breakdown of your gating hierarchy (e.g. % CD4+ out of T-cells).",
    StatType.PERCENT_GRANDPARENT: "<b>% Grandparent</b><br>The fraction of events relative to the parent of the parent gate.<br><br><i>When to use:</i> Skips one generation, useful if the immediate parent is just a technical gate (like a doublet discriminator).",
    StatType.PERCENT_TOTAL: "<b>% Total</b><br>The fraction of events relative to all events in the sample.<br><br><i>When to use:</i> Represents the absolute frequency of this population within the entire un-gated tube.",
    StatType.MIN: "<b>Minimum</b><br>The lowest channel value in the population.<br><br><i>When to use:</i> Used primarily for quality control or verifying gate boundaries.",
    StatType.MAX: "<b>Maximum</b><br>The highest channel value in the population.<br><br><i>When to use:</i> Useful for detecting off-scale events or saturation.",
}

_CHART_TYPES = ["Grouped Bar", "Horizontal Bar", "Heatmap"]


class ComputeWorker(OneShotWorkerThread):
    def __init__(
        self,
        explorer: StatisticsExplorer,
        sample_ids: list[str],
        pop_pairs: list[tuple[str, str | None, str]],
        selected_stats: list[StatType],
        channel: str | None,
    ):
        super().__init__(explorer)
        self.explorer = explorer
        self.sample_ids = sample_ids
        self.pop_pairs = pop_pairs
        self.selected_stats = selected_stats
        self.channel = channel

    def _execute(self):
        # We call the computation method on the background thread.
        # This method ONLY reads data, so it is safe to run off the main thread.
        return self.explorer._compute_results(
            self.sample_ids, self.pop_pairs, self.selected_stats, self.channel
        )


class StatisticsExplorer(QWidget):
    """Full-screen statistics workspace — select samples, populations, and stats,
    then compute a cross-sample table and optional chart.

    Parameters
    ----------
    state:
        The shared :class:`~analysis.state.FlowState` object.
    gate_coordinator:
        Optional gate coordinator (used for population event retrieval).
    parent:
        Optional Qt parent.
    """

    def __init__(
        self,
        state: FlowState,
        gate_coordinator=None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._state = state
        self._gate_coordinator = gate_coordinator
        self._last_results: list[dict[str, Any]] = []
        self._section_labels: list[QLabel] = []
        self._worker: ComputeWorker | None = None

        self._setup_ui()
        self.refresh_samples()

        # Listen for theme changes to dynamically update plot and table colors
        theme_manager.theme_changed.connect(self._on_theme_changed)
        self.destroyed.connect(self._cleanup)

    def _cleanup(self) -> None:
        """Disconnect from theme_manager so a destroyed Qt widget isn't
        invoked by a later theme change (RuntimeError: wrapped C/C++ object
        has been deleted), and block on any in-flight compute so its worker
        thread can't be torn down mid-run (Qt aborts if a QThread is
        destroyed while still running). This widget is tab-embedded, not a
        window, so `closeEvent` never fires here -- `destroyed` (connected
        above) is the one teardown hook Qt guarantees for it.
        """
        if self._worker is not None:
            self._worker.stop_and_wait()
        try:
            theme_manager.theme_changed.disconnect(self._on_theme_changed)
        except (TypeError, RuntimeError):
            pass

    # ── Section label helper ──────────────────────────────────────────────────

    def _section_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"color: {Colors.FG_SECONDARY}; font-weight: bold; font-size: 11px;"
            " text-transform: uppercase; letter-spacing: 0.5px;"
        )
        self._section_labels.append(lbl)
        return lbl

    # ── UI Construction ───────────────────────────────────────────────────────

    def _setup_ui(self) -> None:  # noqa: PLR0915
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── Left Sidebar ──────────────────────────────────────────────────────
        self._sidebar = QWidget()
        self._sidebar.setFixedWidth(300)
        left_layout = QVBoxLayout(self._sidebar)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setStyleSheet("background: transparent; border: none;")

        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(14, 14, 14, 14)
        scroll_layout.setSpacing(12)

        # ── 1 & 2. Samples + Populations (shared selector) ──────────────────────
        self._selector = SampleAndPopulationSelector(
            multi_population=True,
            sample_help_text=(
                "Select one or more samples to include in the statistics table. "
                "Each selected sample will appear as a column group in the results."
            ),
            population_help_text=(
                "Select gated populations to include. 'Shared Populations' are "
                "present under the same name in every checked sample (the usual "
                "result of group gate propagation); 'Sample-Specific' lists "
                "anything that doesn't match across all checked samples. Check "
                "'All Events' to include ungated data."
            ),
        )
        self._selector.selectionChanged.connect(self._on_selection_changed)
        scroll_layout.addWidget(self._selector)

        # ── 3. Statistics ─────────────────────────────────────────────────────
        stats_hdr = QHBoxLayout()
        stats_hdr.addWidget(self._section_label("Statistics"))
        stats_help = BioHelpButton()
        stats_help.setHelpText(
            "Select which statistics to compute. Statistics marked with ★ "
            "require a channel to be selected below.",
            "Statistics",
        )
        stats_hdr.addWidget(stats_help)
        stats_hdr.addStretch()
        scroll_layout.addLayout(stats_hdr)

        self._stat_checkboxes: dict[StatType, QCheckBox] = {}
        for stat in StatType:
            needs_ch = _STAT_NEEDS_CHANNEL[stat]
            suffix = " ★" if needs_ch else ""
            display = stat.value.replace("_", " ").title() + suffix
            cb = QCheckBox(display)
            cb.setToolTip(_STAT_HELP.get(stat, ""))
            # Default: check Count, %Parent, MFI
            if stat in (StatType.COUNT, StatType.PERCENT_PARENT, StatType.MFI):
                cb.setChecked(True)
            self._stat_checkboxes[stat] = cb

            # Layout with checkbox and help button
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(cb)

            help_btn = BioHelpButton()
            # Remove HTML tags for the popover title, use the plain string
            help_btn.setHelpText(
                _STAT_HELP.get(stat, ""), stat.value.replace("_", " ").title() + " Info"
            )
            row.addWidget(help_btn)
            row.addStretch()
            scroll_layout.addLayout(row)

        scroll_layout.addSpacing(4)
        lbl_star = QLabel("★ requires a channel selection")
        self._lbl_star = lbl_star
        scroll_layout.addWidget(lbl_star)

        # ── 4. Channel ────────────────────────────────────────────────────────
        ch_hdr = QHBoxLayout()
        ch_hdr.addWidget(self._section_label("Channel (★ stats)"))
        ch_help = BioHelpButton()
        ch_help.setHelpText(
            "Select the fluorescence channel for parameter-dependent statistics "
            "(Mean, Median, MFI, CV, SD, etc.). This channel is used for all ★ stats.",
            "Channel",
        )
        ch_hdr.addWidget(ch_help)
        ch_hdr.addStretch()
        scroll_layout.addLayout(ch_hdr)

        self._channel_combo = BioComboBox()
        scroll_layout.addWidget(self._channel_combo)

        scroll_layout.addSpacing(16)

        # ── 5. Action buttons ─────────────────────────────────────────────────
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 0)  # Indeterminate spinner
        self._progress_bar.setFixedHeight(4)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.hide()
        scroll_layout.addWidget(self._progress_bar)

        self._compute_btn = PrimaryButton("📊 Compute Statistics")
        self._compute_btn.clicked.connect(self._on_compute)
        scroll_layout.addWidget(self._compute_btn)

        self._export_btn = SecondaryButton("📤 Export CSV")
        self._export_btn.setEnabled(False)
        self._export_btn.setToolTip("Export the statistics table to a CSV file")
        self._export_btn.clicked.connect(self._on_export)
        scroll_layout.addWidget(self._export_btn)

        self._copy_all_btn = SecondaryButton("📋 Copy All")
        self._copy_all_btn.setEnabled(False)
        self._copy_all_btn.setToolTip("Copy all statistics data to clipboard")
        self._copy_all_btn.clicked.connect(self._on_copy_all)
        scroll_layout.addWidget(self._copy_all_btn)

        scroll_layout.addStretch()

        scroll_area.setWidget(scroll_content)
        left_layout.addWidget(scroll_area)
        main_layout.addWidget(self._sidebar)

        # ── Right Workspace ───────────────────────────────────────────────────
        right_panel = QWidget()
        self._right_panel = right_panel
        right_panel.setStyleSheet(f"background-color: {Colors.BG_DARK};")
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(16, 12, 16, 16)
        right_layout.setSpacing(10)

        # Toolbar row
        toolbar = QHBoxLayout()

        self._status_lbl = QLabel("Select samples and populations, then click Compute.")
        self._status_lbl.setStyleSheet(f"color: {Colors.FG_SECONDARY}; font-size: 12px;")
        toolbar.addWidget(self._status_lbl)
        toolbar.addStretch()

        # View toggle: Table vs Chart
        self._view_table_btn = PrimaryButton("📋 Table")
        self._view_table_btn.setToolTip("Show data as a table")
        self._view_table_btn.clicked.connect(lambda: self._set_view(0))
        toolbar.addWidget(self._view_table_btn)

        self._view_chart_btn = SecondaryButton("📈 Chart")
        self._view_chart_btn.setObjectName("StatsChartMode")
        self._view_chart_btn.setToolTip("Show data as a chart")
        self._view_chart_btn.clicked.connect(lambda: self._set_view(1))
        toolbar.addWidget(self._view_chart_btn)

        # Chart type picker (only visible in chart mode)
        self._chart_type_combo = BioComboBox()
        self._chart_type_combo.setObjectName("StatsChartTypeCombo")
        for ct in _CHART_TYPES:
            self._chart_type_combo.addItem(ct)
        self._chart_type_combo.setFixedWidth(130)
        self._chart_type_combo.currentIndexChanged.connect(self._redraw_chart)
        self._chart_type_combo.hide()
        toolbar.addWidget(self._chart_type_combo)

        # Stat picker for chart
        self._chart_stat_combo = BioComboBox()
        self._chart_stat_combo.setFixedWidth(150)
        self._chart_stat_combo.currentIndexChanged.connect(self._redraw_chart)
        self._chart_stat_combo.hide()
        toolbar.addWidget(self._chart_stat_combo)

        # Chart export button
        self._export_plot_btn = SecondaryButton("📸 Export")
        self._export_plot_btn.setToolTip("Export plot to PNG/SVG")
        self._export_plot_btn.clicked.connect(self._on_export_plot)
        self._export_plot_btn.hide()
        toolbar.addWidget(self._export_plot_btn)

        right_layout.addLayout(toolbar)

        # Stacked: 0=placeholder, 1=table, 2=chart
        self._display_stack = QStackedWidget()
        self._display_stack.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

        # 0 — Placeholder
        placeholder = QWidget()
        ph_layout = QVBoxLayout(placeholder)
        ph_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ph_icon = QLabel("📊")
        ph_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ph_icon.setStyleSheet("font-size: 48px;")
        ph_layout.addWidget(ph_icon)
        ph_lbl = QLabel(
            "Select samples, populations and statistics\nthen click Compute to generate results."
        )
        ph_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ph_lbl.setStyleSheet(f"color: {Colors.FG_SECONDARY}; font-size: 14px;")
        ph_layout.addWidget(ph_lbl)
        self._display_stack.addWidget(placeholder)

        # 1 — Table
        self._table = QTableWidget()
        self._table.setStyleSheet(
            f"""
            QTableWidget {{
                background-color: {Colors.BG_DARKEST};
                color: {Colors.FG_PRIMARY};
                border: none;
                gridline-color: {Colors.BORDER};
                font-size: 12px;
                selection-background-color: {Colors.ACCENT_PRIMARY}33;
            }}
            QTableWidget::item {{
                padding: 4px 8px;
                border-bottom: 1px solid {Colors.BORDER};
            }}
            QTableWidget::item:selected {{
                background-color: {Colors.ACCENT_PRIMARY}33;
                color: {Colors.FG_PRIMARY};
            }}
            QHeaderView::section {{
                background-color: {Colors.BG_MEDIUM};
                color: {Colors.FG_SECONDARY};
                font-weight: bold;
                font-size: 11px;
                padding: 6px 8px;
                border: none;
                border-bottom: 2px solid {Colors.BORDER};
                border-right: 1px solid {Colors.BORDER};
            }}
            QScrollBar:horizontal {{
                background: {Colors.BG_DARK};
                height: 8px;
            }}
            QScrollBar::handle:horizontal {{
                background: {Colors.BORDER};
                border-radius: 4px;
            }}
            QScrollBar:vertical {{
                background: {Colors.BG_DARK};
                width: 8px;
            }}
            QScrollBar::handle:vertical {{
                background: {Colors.BORDER};
                border-radius: 4px;
            }}
            """
        )
        self._table.setAlternatingRowColors(True)
        hh = self._table.horizontalHeader()
        if hh:
            hh.setStretchLastSection(False)
        vh = self._table.verticalHeader()
        if vh:
            vh.setVisible(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._show_table_context_menu)
        self._display_stack.addWidget(self._table)

        # 2 — Chart
        chart_wrapper = QWidget()
        chart_wrapper.setStyleSheet(f"background: {Colors.BG_DARKEST}; border-radius: 8px;")
        chart_wr_layout = QVBoxLayout(chart_wrapper)
        chart_wr_layout.setContentsMargins(0, 0, 0, 0)
        self._figure = Figure(facecolor=Colors.BG_DARKEST)
        self._canvas = FigureCanvasQTAgg(self._figure)
        self._canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._canvas.setStyleSheet("background-color: transparent; border: none;")
        chart_wr_layout.addWidget(self._canvas)
        self._display_stack.addWidget(chart_wrapper)

        right_layout.addWidget(self._display_stack, stretch=1)
        main_layout.addWidget(right_panel, stretch=1)

    # ── Public API ────────────────────────────────────────────────────────────

    def refresh_samples(self) -> None:
        """Populate the sample list from the current experiment state.

        Called by the main panel whenever samples are loaded or changed.
        """
        self._selector.refresh(self._state.data.experiment.samples)
        # selectionChanged (emitted by refresh()) already triggers
        # _on_selection_changed -> _refresh_channel_combo().

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _on_selection_changed(self) -> None:
        self._refresh_channel_combo()

    def _refresh_channel_combo(self) -> None:
        """Populate channel combo from the first checked sample."""
        prev_ch = self._channel_combo.currentData()
        self._channel_combo.blockSignals(True)
        self._channel_combo.clear()

        sample_ids = self._selector.get_checked_sample_ids()
        if not sample_ids:
            self._channel_combo.blockSignals(False)
            return

        sample = self._state.data.experiment.samples.get(sample_ids[0])
        if not sample or sample.fcs_data is None:
            self._channel_combo.blockSignals(False)
            return

        for ch in sample.fcs_data.channels:
            label = get_channel_marker_label(sample.fcs_data, ch)
            self._channel_combo.addItem(label, ch)

        # Try to restore previous selection
        if prev_ch:
            idx = self._channel_combo.findData(prev_ch)
            if idx >= 0:
                self._channel_combo.setCurrentIndex(idx)

        self._channel_combo.blockSignals(False)

    def _get_selected_stats(self) -> list[StatType]:
        return [st for st, cb in self._stat_checkboxes.items() if cb.isChecked()]

    def _set_view(self, index: int) -> None:
        """Switch between table (0) and chart (1) views."""
        stack_idx = index + 1
        if self._display_stack.count() <= stack_idx:
            return
        self._display_stack.setCurrentIndex(stack_idx)

        is_chart = index == 1
        self._chart_type_combo.setVisible(is_chart)
        self._chart_stat_combo.setVisible(is_chart)
        self._export_plot_btn.setVisible(is_chart)

        # Style the active button with the accent color; reset the inactive one
        _active_ss = (
            f"QPushButton {{ background: {Colors.ACCENT_PRIMARY}; "
            f"color: {Colors.BG_DARKEST}; border-radius: 4px; "
            f"padding: 4px 12px; font-weight: bold; }}"
        )
        _inactive_ss = ""  # fall back to the theme's SecondaryButton default

        if is_chart:
            self._view_chart_btn.setStyleSheet(_active_ss)
            self._view_table_btn.setStyleSheet(_inactive_ss)
            self._redraw_chart()
        else:
            self._view_table_btn.setStyleSheet(_active_ss)
            self._view_chart_btn.setStyleSheet(_inactive_ss)

    # ── Core computation ──────────────────────────────────────────────────────

    def _on_compute(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return

        sample_ids = self._selector.get_checked_sample_ids()
        pop_pairs = self._selector.get_checked_populations()
        selected_stats = self._get_selected_stats()
        channel = self._channel_combo.currentData()

        if not sample_ids:
            self._status_lbl.setText("⚠ No samples selected.")
            return
        if not pop_pairs:
            self._status_lbl.setText("⚠ No populations selected.")
            return
        if not selected_stats:
            self._status_lbl.setText("⚠ No statistics selected.")
            return

        channel_stats = [s for s in selected_stats if _STAT_NEEDS_CHANNEL[s]]
        if channel_stats and not channel:
            self._status_lbl.setText("⚠ Select a channel for parameter-dependent statistics.")
            return

        self._status_lbl.setText("⏳ Computing in background…")
        self._compute_btn.hide()
        self._progress_bar.show()
        self._export_btn.setEnabled(False)
        self._copy_all_btn.setEnabled(False)
        self._export_plot_btn.setEnabled(False)

        # Store references for when the thread finishes
        self._current_sample_ids = sample_ids
        self._current_pop_pairs = pop_pairs
        self._current_stats = selected_stats
        self._current_channel = channel

        self._worker = ComputeWorker(self, sample_ids, pop_pairs, selected_stats, channel)
        self._worker.finished_ok.connect(self._on_compute_success)
        self._worker.finished_err.connect(self._on_compute_error)
        self._worker.start()

    def _on_compute_success(self, results: list[dict]):
        self._last_results = results

        try:
            self._populate_table(
                self._current_sample_ids,
                self._current_pop_pairs,
                self._current_stats,
                self._current_channel,
            )

            # Populate chart stat combo
            self._chart_stat_combo.blockSignals(True)
            self._chart_stat_combo.clear()
            for st in self._current_stats:
                self._chart_stat_combo.addItem(st.value.replace("_", " ").title(), userData=st)
            self._chart_stat_combo.blockSignals(False)

            # If we are currently in chart mode, redraw
            if self._display_stack.currentIndex() == 2:  # noqa: PLR2004
                self._redraw_chart()

            self._export_btn.setEnabled(True)
            self._copy_all_btn.setEnabled(True)
            self._export_plot_btn.setEnabled(True)

            n_rows = len(self._current_pop_pairs)
            self._status_lbl.setText(
                f"✓ {n_rows} population{'s' if n_rows != 1 else ''} × "
                f"{len(self._current_stats)} stat{'s' if len(self._current_stats) != 1 else ''} "
                f"across {len(self._current_sample_ids)} sample{'s' if len(self._current_sample_ids) != 1 else ''}."
            )
            # Switch to table view automatically, keeping the toggle buttons
            # and chart-only controls (type/stat combos, export button) in
            # sync with the now-active view.
            self._set_view(0)
        except Exception as exc:
            logger.exception("UI update after stats compute failed: %s", exc)
            self._status_lbl.setText(f"❌ Error updating UI: {exc}")
        finally:
            self._progress_bar.hide()
            self._compute_btn.show()
            self._worker = None

    def _on_compute_error(self, err_msg: str):
        logger.error("Statistics computation failed: %s", err_msg)
        self._status_lbl.setText(f"❌ Error: {err_msg}")
        self._progress_bar.hide()
        self._compute_btn.show()
        self._worker = None

    def _get_population_events(self, sample, node_id: str | None):
        """Return the gated DataFrame for a population in a sample."""
        if sample.fcs_data is None:
            return None
        events = sample.fcs_data.events
        if node_id is None:
            return events  # All Events
        if sample.gate_tree is None:
            return events
        node = sample.gate_tree.find_node_by_id(node_id)
        if node is None:
            return events
        return node.apply_hierarchy(events)

    def _get_parent_counts(self, sample, node_id: str | None) -> tuple[int | None, int | None, int]:
        """Return (parent_count, grandparent_count, total_count) for a node."""
        if sample.fcs_data is None:
            return None, None, 0
        total = len(sample.fcs_data.events)
        if node_id is None:
            return total, total, total
        if sample.gate_tree is None:
            return total, total, total

        node = sample.gate_tree.find_node_by_id(node_id)
        if node is None or not node.parents:
            return total, total, total

        parent_node = node.parents[0]
        if parent_node.is_root:
            parent_events = sample.fcs_data.events
        else:
            parent_events = parent_node.apply_hierarchy(sample.fcs_data.events)
        parent_count = len(parent_events)

        if not parent_node.parents or parent_node.parents[0].is_root:
            gp_count = total
        else:
            gp_node = parent_node.parents[0]
            gp_events = gp_node.apply_hierarchy(sample.fcs_data.events)
            gp_count = len(gp_events)

        return parent_count, gp_count, total

    def _compute_results(  # noqa: PLR0912
        self,
        sample_ids: list[str],
        checked_populations: list[tuple[str, str | None, str]],
        stats: list[StatType],
        channel: str | None,
    ) -> list[dict]:
        """Compute all requested stats and return as a list of row dicts."""
        # Group by population label so they align into rows
        pop_groups: dict = {}
        for sid, nid, label in checked_populations:
            if label not in pop_groups:
                pop_groups[label] = {}
            pop_groups[label][sid] = nid

        rows = []
        for pop_label, sample_nodes in pop_groups.items():
            row: dict[str, Any] = {"population": pop_label}
            for sid in sample_ids:
                if sid not in sample_nodes:
                    for st in stats:
                        row[f"{sid}::{st.value}"] = "—"
                    continue

                node_id = sample_nodes[sid]
                sample = self._state.data.experiment.samples.get(sid)
                if sample is None:
                    for st in stats:
                        row[f"{sid}::{st.value}"] = "—"
                    continue

                events = self._get_population_events(sample, node_id)
                if events is None or len(events) == 0:
                    for st in stats:
                        row[f"{sid}::{st.value}"] = "0"
                    continue

                parent_count, gp_count, total_count = self._get_parent_counts(sample, node_id)

                for st in stats:
                    key = f"{sid}::{st.value}"
                    param = channel if _STAT_NEEDS_CHANNEL[st] else None
                    try:
                        val = compute_statistic(
                            events,
                            param,
                            st,
                            parent_count=parent_count,
                            grandparent_count=gp_count,
                            total_count=total_count,
                        )
                        # Format
                        if st == StatType.COUNT:
                            row[key] = f"{int(val):,}"
                        elif st in (
                            StatType.PERCENT_PARENT,
                            StatType.PERCENT_GRANDPARENT,
                            StatType.PERCENT_TOTAL,
                            StatType.CV,
                        ):
                            row[key] = f"{val:.2f}%"
                        else:
                            row[key] = f"{val:.2f}"
                    except Exception as exc:
                        row[key] = "Err"
                        logger.warning("Stat %s failed for %s/%s: %s", st, sid, node_id, exc)

            rows.append(row)
        return rows

    # ── Table population ──────────────────────────────────────────────────────

    def _populate_table(  # noqa: PLR0915
        self,
        sample_ids: list[str],
        pop_pairs: list[tuple[str, str | None, str]],
        stats: list[StatType],
        channel: str | None,
    ) -> None:
        """Fill the QTableWidget with computed results.

        Column layout::

            Population | [sep] | Sample1/Stat1 | Sample1/Stat2 | [sep] | Sample2/Stat1 ...

        A 4-px wide separator column with the sample accent colour is inserted
        before every sample group so boundaries are visually unambiguous.
        """
        stat_labels = [s.value.replace("_", " ").title() for s in stats]
        sample_names = []
        for sid in sample_ids:
            s = self._state.data.experiment.samples.get(sid)
            sample_names.append(s.display_name if s else sid)

        # Per-sample accent colours (drawn from theme)
        _SAMPLE_ACCENT_HEX = Colors.CHART_COLORS
        # Append '18' to the hex to create a low-opacity background tint
        _SAMPLE_BG_HEX = [color + "18" for color in Colors.CHART_COLORS]

        # Build column descriptor list:
        # Each entry is a dict with keys: kind ('pop'|'sep'|'stat'),
        # 'key', 'label', 'sample_idx'
        col_descs: list[dict] = []
        col_descs.append(
            {
                "kind": "pop",
                "label": "Population",
                "key": "population",
                "sample_idx": -1,
            }
        )

        for s_idx, (sid, sname) in enumerate(zip(sample_ids, sample_names, strict=False)):
            # Separator before each sample group
            col_descs.append({"kind": "sep", "label": "", "key": "", "sample_idx": s_idx})
            for st, slabel in zip(stats, stat_labels, strict=False):
                col_descs.append(
                    {
                        "kind": "stat",
                        "label": f"{sname}\n{slabel}",
                        "key": f"{sid}::{st.value}",
                        "sample_idx": s_idx,
                    }
                )

        n_rows = len(self._last_results)
        n_cols = len(col_descs)

        self._table.clear()
        self._table.setRowCount(n_rows)
        self._table.setColumnCount(n_cols)
        # Disable alternating row colors — we apply manual backgrounds per-cell
        # so Qt's alternating palette would overwrite them.
        self._table.setAlternatingRowColors(False)

        # Column headers
        header_labels = [d["label"] for d in col_descs]
        self._table.setHorizontalHeaderLabels(header_labels)

        # Pre-build QBrush/QColor objects so we aren't recreating them per cell
        fg_primary = QColor(Colors.FG_PRIMARY)
        bg_pop_col = QColor(Colors.BG_DARK)  # population name column
        bold_font = QFont()
        bold_font.setBold(True)
        bold_font.setPointSize(11)
        normal_font = QFont()
        normal_font.setPointSize(11)

        for row_idx, row_data in enumerate(self._last_results):
            for col_idx, desc in enumerate(col_descs):
                kind = desc["kind"]

                if kind == "sep":
                    # Thin separator column — fixed 6px wide, accent colour
                    s_idx = desc["sample_idx"]
                    sep_color = QColor(_SAMPLE_ACCENT_HEX[s_idx % len(_SAMPLE_ACCENT_HEX)])
                    item = QTableWidgetItem("")
                    item.setBackground(QBrush(sep_color))
                    item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                    self._table.setItem(row_idx, col_idx, item)
                    self._table.setColumnWidth(col_idx, 6)
                    continue

                value = row_data.get(desc["key"], "")
                item = QTableWidgetItem(str(value))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if kind == "pop":
                    item.setForeground(QBrush(fg_primary))
                    item.setBackground(QBrush(bg_pop_col))
                    item.setFont(bold_font)
                else:
                    s_idx = desc["sample_idx"]
                    item.setForeground(QBrush(fg_primary))
                    item.setBackground(QBrush(QColor(_SAMPLE_BG_HEX[s_idx % len(_SAMPLE_BG_HEX)])))
                    item.setFont(normal_font)
                self._table.setItem(row_idx, col_idx, item)

        for col_idx, desc in enumerate(col_descs):
            if desc["kind"] == "sep":
                self._table.setColumnWidth(col_idx, 6)
            else:
                self._table.resizeColumnToContents(col_idx)
                if self._table.columnWidth(col_idx) < 80:  # noqa: PLR2004
                    self._table.setColumnWidth(col_idx, 80)

        hh = self._table.horizontalHeader()
        if hh:
            hh.setMinimumSectionSize(6)
            hh.setDefaultSectionSize(100)
        vh = self._table.verticalHeader()
        if vh:
            vh.setDefaultSectionSize(28)

    def _make_bold_font(self) -> QFont:
        f = QFont()
        f.setBold(True)
        f.setPointSize(11)
        return f

    # ── Chart ─────────────────────────────────────────────────────────────────

    def _redraw_chart(self) -> None:  # noqa: PLR0912, PLR0915
        """Redraw the matplotlib chart from cached results."""
        if not self._last_results:
            return

        chart_type = self._chart_type_combo.currentText()
        chart_stat = self._chart_stat_combo.currentData()
        if chart_stat is None:
            return

        # Use the snapshot taken at Compute time, not the live checkbox state —
        # otherwise checking a sample/population after computing (without
        # re-running Compute) would look up keys absent from _last_results and
        # silently render as fabricated zeros instead of the actual data.
        sample_ids = self._current_sample_ids
        sample_names = []
        for sid in sample_ids:
            s = self._state.data.experiment.samples.get(sid)
            sample_names.append(s.display_name if s else sid)

        # Figure/axes construction and layout below invoke matplotlib's Agg/
        # FreeType C backend, which is not thread-safe with RenderTask's
        # background-thread rendering of the main canvas / group previews.
        # MPL_RASTER_LOCK must be held for the same reason ComparisonsWorker holds it.
        with MPL_RASTER_LOCK:
            self._redraw_chart_locked(chart_type, chart_stat, sample_ids, sample_names)

        self._canvas.draw_idle()

    def _redraw_chart_locked(  # noqa: PLR0912, PLR0915
        self,
        chart_type: str,
        chart_stat: StatType,
        sample_ids: list[str],
        sample_names: list[str],
    ) -> None:
        """Matplotlib drawing body of `_redraw_chart`, run under MPL_RASTER_LOCK."""
        self._figure.clear()

        pop_labels = [r["population"] for r in self._last_results]
        ax = self._figure.add_subplot(111)
        ax.set_facecolor(Colors.BG_DARK)
        self._figure.patch.set_facecolor(Colors.BG_DARKEST)
        ax.tick_params(colors=Colors.FG_SECONDARY, labelsize=9)
        for spine in ("bottom", "left"):
            ax.spines[spine].set_color(Colors.BORDER)
        for spine in ("top", "right"):
            ax.spines[spine].set_visible(False)

        # Use the theme's chart palette
        palette = Colors.CHART_COLORS

        x = np.arange(len(pop_labels))
        n_samples = len(sample_ids)

        stat_label = chart_stat.value.replace("_", " ").title()

        if chart_type == "Heatmap":
            # Build 2D array [populations, samples]
            data = np.zeros((len(pop_labels), n_samples))
            for p_idx, row in enumerate(self._last_results):
                for s_idx, sid in enumerate(sample_ids):
                    key = f"{sid}::{chart_stat.value}"
                    raw = row.get(key, "0")
                    try:
                        data[p_idx, s_idx] = float(str(raw).replace("%", "").replace(",", ""))
                    except (ValueError, TypeError):
                        data[p_idx, s_idx] = 0.0

            # Theme-derived sequential colormap (low -> high) instead of a fixed
            # matplotlib colormap, so the heatmap matches the active theme.
            heatmap_cmap = LinearSegmentedColormap.from_list(
                "theme_heatmap", [Colors.BG_DARK, Colors.ACCENT_PRIMARY]
            )
            im = ax.imshow(data, aspect="auto", cmap=heatmap_cmap)

            vmin, vmax = data.min(), data.max()
            # Add text annotations
            for i in range(len(pop_labels)):
                for j in range(n_samples):
                    val = data[i, j]
                    norm_val = 0.0 if vmax <= vmin else (val - vmin) / (vmax - vmin)
                    cell_hex = to_hex(heatmap_cmap(norm_val))
                    text_col = get_contrast_text_color(cell_hex)
                    ax.text(
                        j,
                        i,
                        f"{val:.1f}",
                        ha="center",
                        va="center",
                        color=text_col,
                        fontsize=8,
                    )

            ax.set_xticks(np.arange(n_samples))
            ax.set_xticklabels(
                sample_names,
                rotation=30,
                ha="right",
                color=Colors.FG_PRIMARY,
                fontsize=9,
            )
            ax.set_yticks(np.arange(len(pop_labels)))
            ax.set_yticklabels(pop_labels, color=Colors.FG_PRIMARY, fontsize=9)

            # Colorbar
            cbar = self._figure.colorbar(im, ax=ax)
            cbar.ax.yaxis.set_tick_params(color=Colors.FG_SECONDARY, labelcolor=Colors.FG_SECONDARY)
            cbar.outline.set_edgecolor(Colors.BORDER)  # type: ignore

        else:  # Grouped or Horizontal Bar
            bar_width = max(0.1, 0.7 / max(n_samples, 1))
            for s_idx, (sid, sname) in enumerate(zip(sample_ids, sample_names, strict=False)):
                key = f"{sid}::{chart_stat.value}"
                vals = []
                for row in self._last_results:
                    raw = row.get(key, "0")
                    try:
                        vals.append(float(str(raw).replace("%", "").replace(",", "")))
                    except (ValueError, TypeError):
                        vals.append(0.0)

                offset = (s_idx - n_samples / 2 + 0.5) * bar_width
                color = palette[s_idx % len(palette)]

                if chart_type == "Grouped Bar":
                    bars = ax.bar(
                        x + offset,
                        vals,
                        bar_width,
                        label=sname,
                        color=color,
                        alpha=0.85,
                    )
                    # Value labels on top of bars
                    for bar, val in zip(bars, vals, strict=False):
                        ax.text(
                            bar.get_x() + bar.get_width() / 2,
                            bar.get_height() * 1.01,
                            f"{val:.1f}",
                            ha="center",
                            va="bottom",
                            color=Colors.FG_SECONDARY,
                            fontsize=7,
                        )
                elif chart_type == "Horizontal Bar":
                    y_pos = x + offset
                    ax.barh(y_pos, vals, bar_width, label=sname, color=color, alpha=0.85)

            if chart_type == "Horizontal Bar":
                ax.set_yticks(x)
                ax.set_yticklabels(pop_labels, color=Colors.FG_PRIMARY, fontsize=9)
                ax.set_xlabel(stat_label, color=Colors.FG_SECONDARY, fontsize=10)
            else:
                ax.set_xticks(x)
                ax.set_xticklabels(
                    pop_labels,
                    rotation=30,
                    ha="right",
                    color=Colors.FG_PRIMARY,
                    fontsize=9,
                )
                ax.set_ylabel(stat_label, color=Colors.FG_SECONDARY, fontsize=10)

        ax.set_title(f"{stat_label} by Population", color=Colors.FG_PRIMARY, fontsize=12, pad=12)

        # Legend
        if chart_type != "Heatmap" and n_samples > 1:
            ax.legend(
                facecolor=Colors.BG_DARK,
                edgecolor=Colors.BORDER,
                labelcolor=Colors.FG_PRIMARY,
                fontsize=9,
            )

        self._figure.tight_layout(pad=1.5)

    def _on_export_plot(self) -> None:
        """Export the current matplotlib figure to a file."""
        if not self._last_results:
            return

        default_name = "statistics_plot.png"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Plot",
            default_name,
            "PNG Image (*.png);;SVG Image (*.svg);;All Files (*)",
        )
        if path:
            try:
                # Save with high DPI for crisp rendering. savefig() triggers a
                # full Agg rasterization pass — needs MPL_RASTER_LOCK for the
                # same reason _redraw_chart_locked() does.
                with MPL_RASTER_LOCK:
                    self._figure.savefig(
                        path,
                        dpi=300,
                        bbox_inches="tight",
                        facecolor=self._figure.get_facecolor(),
                    )
                self._status_lbl.setText(f"✓ Plot exported to {path}")
            except Exception as e:
                logger.error("Failed to export plot: %s", e)
                self._status_lbl.setText(f"❌ Export failed: {e}")

    def _on_copy_all(self) -> None:
        """Copy all table data to clipboard in TSV format."""
        if not self._last_results:
            return

        # Build headers
        header_items = [
            self._table.horizontalHeaderItem(c) for c in range(self._table.columnCount())
        ]
        header_text = "\t".join((item.text() if item is not None else "") for item in header_items)

        # Build data rows
        lines = [header_text]
        for row in range(self._table.rowCount()):
            row_data = []
            for col in range(self._table.columnCount()):
                item = self._table.item(row, col)
                if item is not None:
                    row_data.append(item.text())
                else:
                    row_data.append("")
            lines.append("\t".join(row_data))

        clipboard_text = "\n".join(lines)
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(clipboard_text)
        self._status_lbl.setText(f"✓ Copied all {self._table.rowCount()} row(s) to clipboard")

    # ── Export ────────────────────────────────────────────────────────────────

    def _on_export(self) -> None:
        if not self._last_results:
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Statistics to CSV",
            "statistics_export.csv",
            "CSV Files (*.csv);;All Files (*)",
        )
        if not path:
            return

        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                if self._last_results:
                    writer = csv.DictWriter(f, fieldnames=list(self._last_results[0].keys()))
                    writer.writeheader()
                    writer.writerows(self._last_results)
            self._status_lbl.setText(f"✓ Exported to {path}")
        except OSError as exc:
            logger.error("Export failed: %s", exc)
            self._status_lbl.setText(f"❌ Export failed: {exc}")

    def _show_table_context_menu(self, pos) -> None:
        """Show context menu for the statistics table."""
        menu = QMenu(self)
        menu.setStyleSheet(
            f"background-color: {Colors.BG_DARKEST}; color: {Colors.FG_PRIMARY};"
            f" border: 1px solid {Colors.BORDER};"
        )

        copy_action = menu.addAction("📋 Copy Selected Rows")
        if copy_action:
            copy_action.triggered.connect(self._copy_selected_rows)

        copy_all_action = menu.addAction("📋 Copy All")
        if copy_all_action:
            copy_all_action.triggered.connect(self._on_copy_all)

        menu.addSeparator()

        export_action = menu.addAction("📤 Export Table as CSV...")
        if export_action:
            export_action.triggered.connect(self._on_export)

        viewport = self._table.viewport()
        if viewport:
            menu.exec(viewport.mapToGlobal(pos))

    def _copy_selected_rows(self) -> None:
        """Copy selected table rows to clipboard in TSV format."""
        selected_ranges = self._table.selectedRanges()
        if not selected_ranges:
            return

        rows = sorted({r for sr in selected_ranges for r in range(sr.topRow(), sr.bottomRow() + 1)})

        # Build headers
        header_items = [
            self._table.horizontalHeaderItem(c) for c in range(self._table.columnCount())
        ]
        header_text = "\\t".join((item.text() if item is not None else "") for item in header_items)

        # Build data rows
        lines = [header_text]
        for row in rows:
            row_data = []
            for col in range(self._table.columnCount()):
                item = self._table.item(row, col)
                if item is not None:
                    row_data.append(item.text())
                else:
                    row_data.append("")
            lines.append("\\t".join(row_data))

        clipboard_text = "\\n".join(lines)
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(clipboard_text)
        self._status_lbl.setText(f"✓ Copied {len(rows)} row(s) to clipboard")

    # ── Theme refresh ─────────────────────────────────────────────────────────

    def _on_theme_changed(self) -> None:
        """Handle dynamic theme switching."""
        self._apply_theme_styles()

        # Repaint the table and chart with the new theme colors if data is loaded.
        # Use the Compute-time snapshot, not the live checkbox state, so a
        # selection change since the last Compute doesn't repaint stale rows
        # under a mismatched set of samples/populations.
        if self._last_results:
            sample_ids = self._current_sample_ids
            pop_pairs = self._current_pop_pairs
            selected_stats = self._current_stats
            channel = self._current_channel
            self._populate_table(sample_ids, pop_pairs, selected_stats, channel)

            if self._display_stack.currentIndex() == 2:  # noqa: PLR2004
                self._redraw_chart()

    def _apply_theme_styles(self) -> None:
        """Refresh all color-dependent styles when the theme changes."""
        self.setStyleSheet(f"background-color: {Colors.BG_DARKEST};")
        if hasattr(self, "_sidebar") and self._sidebar:
            self._sidebar.setStyleSheet(
                f"background-color: {Colors.BG_DARKEST}; border-right: 1px solid {Colors.BORDER};"
            )
        if hasattr(self, "_right_panel") and self._right_panel:
            self._right_panel.setStyleSheet(f"background-color: {Colors.BG_DARK};")

        # Note: the sample checklist and population tree (self._selector) theme
        # themselves independently via their own theme_manager subscription —
        # see ui/widgets/selection/.

        for combo in (
            getattr(self, "_channel_combo", None),
            getattr(self, "_chart_type_combo", None),
            getattr(self, "_chart_stat_combo", None),
        ):
            if combo and hasattr(combo, "_apply_theme_styles"):
                combo._apply_theme_styles()

        self._table.setStyleSheet(
            f"""
            QTableWidget {{
                background-color: {Colors.BG_DARKEST};
                color: {Colors.FG_PRIMARY};
                border: none;
                gridline-color: {Colors.BORDER};
                font-size: 12px;
                selection-background-color: {Colors.ACCENT_PRIMARY}33;
            }}
            QTableWidget::item {{
                padding: 4px 8px;
                border-bottom: 1px solid {Colors.BORDER};
            }}
            QHeaderView::section {{
                background-color: {Colors.BG_MEDIUM};
                color: {Colors.FG_SECONDARY};
                font-weight: bold;
                font-size: 11px;
                padding: 6px 8px;
                border: none;
                border-bottom: 2px solid {Colors.BORDER};
                border-right: 1px solid {Colors.BORDER};
            }}
            """
        )
        self._figure.patch.set_facecolor(Colors.BG_DARKEST)

        for cb in self._stat_checkboxes.values():
            cb.setStyleSheet(checkbox_qss())

        if hasattr(self, "_lbl_star"):
            self._lbl_star.setStyleSheet(
                f"color: {Colors.FG_DISABLED}; font-size: 10px; font-style: italic;"
            )

        for lbl in getattr(self, "_section_labels", []):
            lbl.setStyleSheet(
                f"color: {Colors.FG_SECONDARY}; font-weight: bold; font-size: 11px;"
                " text-transform: uppercase; letter-spacing: 0.5px;"
            )

        self._status_lbl.setStyleSheet(f"color: {Colors.FG_SECONDARY}; font-size: 12px;")

        self._canvas.draw_idle()
        self.update()
