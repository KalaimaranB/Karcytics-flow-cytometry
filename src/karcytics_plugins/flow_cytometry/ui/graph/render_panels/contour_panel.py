"""Contour plot settings panel."""

from __future__ import annotations

from karcytics_sdk.plugin.theme_fallback import theme_manager
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from karcytics_plugins.flow_cytometry.analysis.config import COLORMAPS, ContourConfig
from karcytics_plugins.flow_cytometry.ui.widgets.styled_combo import FlowComboBox

from ._utils import make_float_row, make_int_row, section_header


class ContourSettingsPanel(QWidget):
    """Settings panel for the 2D Contour renderer."""

    changed = pyqtSignal()

    def __init__(self, config: ContourConfig, parent=None):
        super().__init__(parent)
        self._build_ui(config)

    def _build_ui(self, cfg: ContourConfig):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)
        theme_manager.apply_style(self, "background: {BG_DARKEST};")

        layout.addWidget(section_header("Contour Lines"))
        form1 = QFormLayout()
        form1.setSpacing(10)

        self._spin_levels = make_int_row(
            form1,
            "Number of Levels:",
            "How many contour levels to draw.\n"
            "More levels = finer resolution of population structure.",
            3,
            30,
            1,
            cfg.num_levels,
        )
        self._spin_levels.valueChanged.connect(lambda _: self.changed.emit())

        self._spin_sigma = make_float_row(
            form1,
            "Smoothing:",
            "Gaussian blur applied before contouring.\n"
            "Higher = smoother contours; lower = follows raw density more closely.",
            0.5,
            5.0,
            0.1,
            cfg.smoothing,
        )
        self._spin_sigma.valueChanged.connect(lambda _: self.changed.emit())

        # Line color mode
        color_lbl = QLabel("Line Color:")
        theme_manager.apply_style(color_lbl, "color: {FG_SECONDARY}; font-size: 11px;")
        self._color_mode_combo = FlowComboBox()
        self._color_mode_combo.addItem("Black", "black")
        self._color_mode_combo.addItem("Blue", "blue")
        self._color_mode_combo.addItem("By density (colormap)", "colormap")
        for i in range(self._color_mode_combo.count()):
            if self._color_mode_combo.itemData(i) == cfg.color_mode:
                self._color_mode_combo.setCurrentIndex(i)
                break
        self._color_mode_combo.currentIndexChanged.connect(self._on_color_mode_changed)
        form1.addRow(color_lbl, self._color_mode_combo)

        # Colormap (only shown when color_mode == "colormap")
        cmap_lbl = QLabel("Colormap:")
        theme_manager.apply_style(cmap_lbl, "color: {FG_SECONDARY}; font-size: 11px;")
        self._cmap_combo = FlowComboBox()
        for label, name in COLORMAPS:
            self._cmap_combo.addItem(label, name)
        for i in range(self._cmap_combo.count()):
            if self._cmap_combo.itemData(i) == cfg.colormap:
                self._cmap_combo.setCurrentIndex(i)
                break
        self._cmap_combo.setVisible(cfg.color_mode == "colormap")
        self._cmap_combo.currentIndexChanged.connect(lambda _: self.changed.emit())
        self._cmap_lbl = cmap_lbl
        self._cmap_lbl.setVisible(cfg.color_mode == "colormap")
        form1.addRow(cmap_lbl, self._cmap_combo)

        layout.addLayout(form1)

        # ── Overlays ─────────────────────────────────────────────────
        layout.addWidget(section_header("Overlays"))
        self._filled_check = QCheckBox("Show filled contours (shaded regions)")
        self._filled_check.setChecked(cfg.show_filled)
        theme_manager.apply_style(self._filled_check, "color: {FG_SECONDARY};")
        self._filled_check.stateChanged.connect(lambda _: self.changed.emit())
        layout.addWidget(self._filled_check)

        self._underlay_check = QCheckBox("Show dot underlay (sparse events)")
        self._underlay_check.setChecked(cfg.show_dot_underlay)
        self._underlay_check.setToolTip(
            "Draws a faint scatter layer under the contours so individual\n"
            "events outside dense regions remain visible."
        )
        theme_manager.apply_style(self._underlay_check, "color: {FG_SECONDARY};")
        self._underlay_check.stateChanged.connect(lambda _: self.changed.emit())
        layout.addWidget(self._underlay_check)

        layout.addStretch()

    def _on_color_mode_changed(self, _) -> None:
        is_cmap = self._color_mode_combo.currentData() == "colormap"
        self._cmap_combo.setVisible(is_cmap)
        self._cmap_lbl.setVisible(is_cmap)
        self.changed.emit()

    def get_config(self) -> ContourConfig:
        return ContourConfig(
            num_levels=self._spin_levels.value(),
            smoothing=self._spin_sigma.value(),
            color_mode=self._color_mode_combo.currentData(),
            colormap=self._cmap_combo.currentData() or "viridis",
            show_filled=self._filled_check.isChecked(),
            show_dot_underlay=self._underlay_check.isChecked(),
        )

    def set_config(self, config: ContourConfig) -> None:
        self._spin_levels.setValue(config.num_levels)
        self._spin_sigma.setValue(config.smoothing)
        for i in range(self._color_mode_combo.count()):
            if self._color_mode_combo.itemData(i) == config.color_mode:
                self._color_mode_combo.setCurrentIndex(i)
                break
        for i in range(self._cmap_combo.count()):
            if self._cmap_combo.itemData(i) == config.colormap:
                self._cmap_combo.setCurrentIndex(i)
                break
        self._filled_check.setChecked(config.show_filled)
        self._underlay_check.setChecked(config.show_dot_underlay)
