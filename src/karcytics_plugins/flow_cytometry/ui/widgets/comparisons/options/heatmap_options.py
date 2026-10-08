"""Heatmap options panel."""

from __future__ import annotations

from karcytics_sdk.plugin.components import BioComboBox, BioHelpButton
from karcytics_sdk.plugin.theme_fallback import Colors
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QVBoxLayout

from karcytics_plugins.flow_cytometry.ui.widgets.checkbox_style import checkbox_qss

from .base import IOptionsPanel


class HeatmapOptionsPanel(IOptionsPanel):
    """SRP: owns Qt controls for channel heatmap settings only."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Statistic
        stat_row = QHBoxLayout()
        stat_lbl = QLabel("Statistic:")
        stat_help = BioHelpButton()
        stat_help.setHelpText(
            "Which summary statistic to compute per (population × channel) cell.\n\n"
            "• Median: robust to outliers, recommended for skewed fluorescence.\n"
            "• Mean: arithmetic average — influenced by very bright/dim outliers.\n"
            "• Geometric Mean: log-space average, good for log-normal distributions.",
            "Statistic",
        )
        self._stat_combo = BioComboBox()
        self._stat_combo.addItem("Median", "median")
        self._stat_combo.addItem("Mean", "mean")
        self._stat_combo.addItem("Geometric Mean", "geometric_mean")
        stat_row.addWidget(stat_lbl)
        stat_row.addWidget(stat_help)
        stat_row.addStretch()
        layout.addLayout(stat_row)
        layout.addWidget(self._stat_combo)

        # Colour map
        cmap_row = QHBoxLayout()
        cmap_lbl = QLabel("Colour Map:")
        cmap_help = BioHelpButton()
        cmap_help.setHelpText(
            "Colour scale used to represent expression levels.\n\n"
            "• RdYlBu_r: red (high) → yellow → blue (low). Classic heatmap.\n"
            "• viridis: perceptually uniform, good for print.\n"
            "• magma: high contrast, good for presentations.",
            "Colour Map",
        )
        self._cmap_combo = BioComboBox()
        for label, val in [
            ("Red–Yellow–Blue (default)", "RdYlBu_r"),
            ("Viridis", "viridis"),
            ("Magma", "magma"),
            ("Plasma", "plasma"),
            ("Blues", "Blues_r"),
        ]:
            self._cmap_combo.addItem(label, val)
        cmap_row.addWidget(cmap_lbl)
        cmap_row.addWidget(cmap_help)
        cmap_row.addStretch()
        layout.addLayout(cmap_row)
        layout.addWidget(self._cmap_combo)

        # Normalise per channel
        norm_row = QHBoxLayout()
        self._norm_cb = QCheckBox("Normalise per channel (0–1 scale)")
        self._norm_cb.setChecked(True)
        norm_help = BioHelpButton()
        norm_help.setHelpText(
            "When checked, each channel column is independently scaled to [0, 1] "
            "so that high-intensity channels (like SSC) don't dominate the colour.\n\n"
            "Uncheck to see raw statistic values, which makes it easier to compare "
            "absolute intensities between populations.",
            "Normalise Per Channel",
        )
        norm_row.addWidget(self._norm_cb)
        norm_row.addWidget(norm_help)
        norm_row.addStretch()
        layout.addLayout(norm_row)

        # Annotate cells
        annot_row = QHBoxLayout()
        self._annot_cb = QCheckBox("Show values in cells")
        self._annot_cb.setChecked(False)
        annot_help = BioHelpButton()
        annot_help.setHelpText(
            "Prints the raw statistic value inside each cell. "
            "Turn off if the heatmap has many rows/columns and cell text becomes crowded.",
            "Cell Annotations",
        )
        annot_row.addWidget(self._annot_cb)
        annot_row.addWidget(annot_help)
        annot_row.addStretch()
        layout.addLayout(annot_row)

        self.apply_theme({})

    def get_config(self) -> dict:
        return {
            "stat": self._stat_combo.currentData() or "median",
            "cmap": self._cmap_combo.currentData() or "RdYlBu_r",
            "normalise": self._norm_cb.isChecked(),
            "annotate": self._annot_cb.isChecked(),
        }

    def apply_theme(self, colors: dict) -> None:
        sec = Colors.FG_SECONDARY
        for cb in (self._norm_cb, self._annot_cb):
            cb.setStyleSheet(checkbox_qss())
        for lbl in self.findChildren(QLabel):
            lbl.setStyleSheet(f"color: {sec}; font-size: 11px;")
