"""Radar/Spider chart options panel."""

from __future__ import annotations

from karcytics_sdk.plugin.components import BioComboBox, BioHelpButton
from karcytics_sdk.plugin.theme_fallback import Colors
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QSlider, QVBoxLayout

from karcytics_plugins.flow_cytometry.ui.widgets.checkbox_style import checkbox_qss

from .base import IOptionsPanel


class RadarOptionsPanel(IOptionsPanel):
    """SRP: owns controls for radar chart settings only."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Statistic
        stat_row = QHBoxLayout()
        stat_lbl = QLabel("Statistic per spoke:")
        stat_help = BioHelpButton()
        stat_help.setHelpText(
            "The value plotted on each channel spoke.\n\n"
            "• Median: robust, recommended for fluorescence data.\n"
            "• Mean: arithmetic average — affected by very bright outliers.\n\n"
            "Both are computed within each selected population.",
            "Statistic",
        )
        self._stat_combo = BioComboBox()
        self._stat_combo.addItem("Median", "median")
        self._stat_combo.addItem("Mean", "mean")
        stat_row.addWidget(stat_lbl)
        stat_row.addWidget(stat_help)
        stat_row.addStretch()
        layout.addLayout(stat_row)
        layout.addWidget(self._stat_combo)

        # Normalise
        norm_row = QHBoxLayout()
        self._norm_cb = QCheckBox("Normalise spokes (0–1 per channel)")
        self._norm_cb.setChecked(True)
        norm_help = BioHelpButton()
        norm_help.setHelpText(
            "Scales each channel spoke independently to [0, 1] across all selected populations.\n\n"
            "Without normalisation, channels with very high raw intensity (like SSC) "
            "would dominate and make the polygon look like a single spike.\n\n"
            "Keep checked unless you specifically want to compare absolute intensities.",
            "Normalise Spokes",
        )
        norm_row.addWidget(self._norm_cb)
        norm_row.addWidget(norm_help)
        norm_row.addStretch()
        layout.addLayout(norm_row)

        # Fill opacity
        fill_row = QHBoxLayout()
        self._fill_lbl = QLabel("Fill opacity:  25%")
        self._fill_lbl.setStyleSheet(f"color: {Colors.FG_PRIMARY}; font-size: 11px;")
        fill_help = BioHelpButton()
        fill_help.setHelpText(
            "Transparency of the coloured fill inside each polygon.\n\n"
            "Lower opacity (10–20%) prevents overlapping polygons from obscuring each other. "
            "Higher opacity (50–80%) makes individual populations stand out more.",
            "Fill Opacity",
        )
        fill_row.addWidget(self._fill_lbl)
        fill_row.addWidget(fill_help)
        fill_row.addStretch()
        layout.addLayout(fill_row)

        self._fill_slider = QSlider(Qt.Orientation.Horizontal)
        self._fill_slider.setRange(5, 80)
        self._fill_slider.setValue(25)
        self._fill_slider.valueChanged.connect(
            lambda v: self._fill_lbl.setText(f"Fill opacity:  {v}%")
        )
        layout.addWidget(self._fill_slider)

        self.apply_theme({})

    def get_config(self) -> dict:
        return {
            "stat": self._stat_combo.currentData() or "median",
            "normalise": self._norm_cb.isChecked(),
            "fill_alpha": self._fill_slider.value() / 100.0,
        }

    def apply_theme(self, colors: dict) -> None:
        fg = Colors.FG_PRIMARY
        sec = Colors.FG_SECONDARY
        self._norm_cb.setStyleSheet(checkbox_qss())
        for lbl in self.findChildren(QLabel):
            lbl.setStyleSheet(f"color: {sec}; font-size: 11px;")
        self._fill_lbl.setStyleSheet(f"color: {fg}; font-size: 11px;")
