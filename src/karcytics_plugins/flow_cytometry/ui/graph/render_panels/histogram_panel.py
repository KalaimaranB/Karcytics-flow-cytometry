"""Histogram settings panel."""

from __future__ import annotations

from karcytics_sdk.plugin.theme_fallback import Colors, Fonts
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from karcytics_plugins.flow_cytometry.analysis.config import HistogramConfig
from karcytics_plugins.flow_cytometry.ui.widgets.styled_combo import FlowComboBox

from ._utils import PANEL_STYLE, ColorPickerButton, make_int_row, section_header


class HistogramSettingsPanel(QWidget):
    """Settings panel for the 1D Histogram renderer."""

    changed = Signal()

    def __init__(self, config: HistogramConfig, parent=None):
        super().__init__(parent)
        self._build_ui(config)

    def _build_ui(self, cfg: HistogramConfig):  # noqa: PLR0915
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)
        self.setStyleSheet(PANEL_STYLE)

        # ── Appearance ────────────────────────────────────────────────
        layout.addWidget(section_header("Bar Appearance"))
        form1 = QFormLayout()
        form1.setSpacing(10)

        color_lbl = QLabel("Bar Color:")
        color_lbl.setStyleSheet(f"color: {Colors.FG_SECONDARY}; font-size: {Fonts.SIZE_SMALL}px;")
        self._color_btn = ColorPickerButton(cfg.bar_color)
        self._color_btn.color_changed.connect(lambda _: self.changed.emit())
        color_row = QHBoxLayout()
        color_row.addWidget(self._color_btn)
        color_row.addStretch()
        form1.addRow(color_lbl, color_row)

        # Style toggle
        style_lbl = QLabel("Fill Style:")
        style_lbl.setStyleSheet(f"color: {Colors.FG_SECONDARY}; font-size: {Fonts.SIZE_SMALL}px;")
        self._style_combo = FlowComboBox()
        self._style_combo.addItem("Filled", True)
        self._style_combo.addItem("Outline Only", False)
        self._style_combo.setCurrentIndex(0 if cfg.filled else 1)
        self._style_combo.currentIndexChanged.connect(lambda _: self.changed.emit())
        form1.addRow(style_lbl, self._style_combo)

        layout.addLayout(form1)

        # ── Binning ───────────────────────────────────────────────────
        layout.addWidget(section_header("Binning"))
        form2 = QFormLayout()
        form2.setSpacing(8)

        self._auto_bins_check = QCheckBox("Auto (Sturges' rule)")
        self._auto_bins_check.setChecked(cfg.auto_bins)
        self._auto_bins_check.setStyleSheet(f"color: {Colors.FG_SECONDARY};")
        self._auto_bins_check.stateChanged.connect(self._on_auto_bins_changed)
        form2.addRow(QLabel(), self._auto_bins_check)

        self._spin_bins = make_int_row(
            form2,
            "Number of Bins:",
            "Number of histogram bins. More bins = finer resolution.\n"
            "Use 'Auto' to let the software choose based on event count.",
            32,
            1024,
            32,
            cfg.bins,
        )
        self._spin_bins.valueChanged.connect(lambda _: self.changed.emit())
        self._spin_bins.setEnabled(not cfg.auto_bins)

        layout.addLayout(form2)

        # ── Y-axis ────────────────────────────────────────────────────
        layout.addWidget(section_header("Y-Axis"))
        form3 = QFormLayout()
        form3.setSpacing(8)

        y_lbl = QLabel("Y-Axis Mode:")
        y_lbl.setStyleSheet(f"color: {Colors.FG_SECONDARY}; font-size: {Fonts.SIZE_SMALL}px;")
        self._y_combo = FlowComboBox()
        self._y_combo.addItem("Event Count", "count")
        self._y_combo.addItem("Frequency (%)", "frequency")
        self._y_combo.setCurrentIndex(0 if cfg.y_axis_mode == "count" else 1)
        self._y_combo.currentIndexChanged.connect(lambda _: self.changed.emit())
        form3.addRow(y_lbl, self._y_combo)

        layout.addLayout(form3)

        # ── KDE overlay ───────────────────────────────────────────────
        layout.addWidget(section_header("Smoothing"))
        self._kde_check = QCheckBox("Overlay smooth KDE curve")
        self._kde_check.setChecked(cfg.smooth_kde)
        self._kde_check.setToolTip(
            "Draws a kernel density estimate curve over the histogram.\n"
            "Toggle off to revert to the raw bar chart."
        )
        self._kde_check.setStyleSheet(f"color: {Colors.FG_SECONDARY};")
        self._kde_check.stateChanged.connect(lambda _: self.changed.emit())
        layout.addWidget(self._kde_check)

        # ── FMO Overlay ───────────────────────────────────────────────
        layout.addWidget(section_header("FMO Overlay"))
        fmo_form = QFormLayout()
        fmo_form.setSpacing(10)

        fmo_color_lbl = QLabel("FMO Histogram Fill:")
        fmo_color_lbl.setStyleSheet(
            f"color: {Colors.FG_SECONDARY}; font-size: {Fonts.SIZE_SMALL}px;"
        )
        self._fmo_color_btn = ColorPickerButton(cfg.fmo_color)
        self._fmo_color_btn.color_changed.connect(lambda _: self.changed.emit())
        fmo_color_row = QHBoxLayout()
        fmo_color_row.addWidget(self._fmo_color_btn)
        fmo_color_row.addStretch()
        fmo_form.addRow(fmo_color_lbl, fmo_color_row)

        self._fmo_check = QCheckBox("Show percentile threshold")
        self._fmo_check.setChecked(cfg.show_fmo_threshold)
        self._fmo_check.setToolTip(
            "Draws a dashed line at the specified percentile of the FMO control data."
        )
        self._fmo_check.setStyleSheet(f"color: {Colors.FG_SECONDARY};")
        self._fmo_check.stateChanged.connect(self._on_fmo_threshold_toggled)
        fmo_form.addRow(QLabel(), self._fmo_check)

        from PySide6.QtWidgets import QDoubleSpinBox

        self._spin_percentile = QDoubleSpinBox()
        self._spin_percentile.setRange(0.0, 100.0)
        self._spin_percentile.setDecimals(1)
        self._spin_percentile.setSingleStep(0.1)
        self._spin_percentile.setValue(cfg.fmo_threshold_percentile)
        self._spin_percentile.setSuffix("%")
        self._spin_percentile.setStyleSheet(
            f"QDoubleSpinBox {{ background: {Colors.BG_MEDIUM}; color: {Colors.FG_PRIMARY};"
            f" border: 1px solid {Colors.BORDER}; border-radius: 3px; padding: 2px 6px; }}"
        )
        self._spin_percentile.valueChanged.connect(lambda _: self.changed.emit())
        self._spin_percentile.setEnabled(cfg.show_fmo_threshold)

        perc_lbl = QLabel("Threshold Percentile:")
        perc_lbl.setStyleSheet(f"color: {Colors.FG_SECONDARY}; font-size: {Fonts.SIZE_SMALL}px;")
        fmo_form.addRow(perc_lbl, self._spin_percentile)

        fmo_line_color_lbl = QLabel("Threshold Line Color:")
        fmo_line_color_lbl.setStyleSheet(
            f"color: {Colors.FG_SECONDARY}; font-size: {Fonts.SIZE_SMALL}px;"
        )
        self._fmo_line_color_btn = ColorPickerButton(cfg.fmo_threshold_color)
        self._fmo_line_color_btn.color_changed.connect(lambda _: self.changed.emit())
        fmo_line_color_row = QHBoxLayout()
        fmo_line_color_row.addWidget(self._fmo_line_color_btn)
        fmo_line_color_row.addStretch()
        fmo_form.addRow(fmo_line_color_lbl, fmo_line_color_row)

        layout.addLayout(fmo_form)
        layout.addStretch()

    def _on_fmo_threshold_toggled(self, state: int) -> None:
        self._spin_percentile.setEnabled(state != 0)
        self._fmo_line_color_btn.setEnabled(state != 0)
        self.changed.emit()

    def _on_auto_bins_changed(self, state: int) -> None:
        self._spin_bins.setEnabled(state == 0)
        self.changed.emit()

    def get_config(self) -> HistogramConfig:
        return HistogramConfig(
            bar_color=self._color_btn.color,
            bins=self._spin_bins.value(),
            auto_bins=self._auto_bins_check.isChecked(),
            y_axis_mode=self._y_combo.currentData(),
            filled=bool(self._style_combo.currentData()),
            smooth_kde=self._kde_check.isChecked(),
            fmo_color=self._fmo_color_btn.color,
            show_fmo_threshold=self._fmo_check.isChecked(),
            fmo_threshold_percentile=self._spin_percentile.value(),
            fmo_threshold_color=self._fmo_line_color_btn.color,
        )

    def set_config(self, config: HistogramConfig) -> None:
        self._color_btn.set_color(config.bar_color)
        self._spin_bins.setValue(config.bins)
        self._auto_bins_check.setChecked(config.auto_bins)
        self._y_combo.setCurrentIndex(0 if config.y_axis_mode == "count" else 1)
        self._style_combo.setCurrentIndex(0 if config.filled else 1)
        self._kde_check.setChecked(config.smooth_kde)

        self._fmo_color_btn.set_color(config.fmo_color)
        self._fmo_check.setChecked(config.show_fmo_threshold)
        self._spin_percentile.setValue(config.fmo_threshold_percentile)
        self._fmo_line_color_btn.set_color(config.fmo_threshold_color)
