"""Dot Plot settings panel."""

from __future__ import annotations

from karcytics_sdk.plugin.theme_fallback import theme_manager
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QFormLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from karcytics_plugins.flow_cytometry.analysis.config import DotPlotConfig

from ._utils import (
    ColorPickerButton,
    make_float_row,
    make_int_row,
    section_header,
)


class DotPlotSettingsPanel(QWidget):
    """Settings panel for the Dot Plot (scatter) renderer."""

    changed = pyqtSignal()

    def __init__(self, config: DotPlotConfig, max_sample_events: int = 300_000, parent=None):
        super().__init__(parent)
        self._max_sample_events = max_sample_events
        self._build_ui(config)

    def _build_ui(self, cfg: DotPlotConfig):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)
        theme_manager.apply_style(self, "background: {BG_DARKEST};")

        layout.addWidget(section_header("Dot Appearance"))
        form = QFormLayout()
        form.setSpacing(10)

        # Color picker
        color_row = QHBoxLayout()
        self._color_btn = ColorPickerButton(cfg.dot_color)
        self._color_btn.color_changed.connect(lambda _: self.changed.emit())
        color_lbl = QLabel("Dot Color:")
        theme_manager.apply_style(color_lbl, "color: {FG_SECONDARY}; font-size: 11px;")
        color_row.addWidget(self._color_btn)
        color_row.addStretch()
        form.addRow(color_lbl, color_row)

        self._spin_size = make_float_row(
            form,
            "Dot Size (px):",
            "Diameter of each rendered event dot in screen pixels.\n"
            "Smaller dots work better for dense samples.",
            1.0,
            10.0,
            0.5,
            cfg.dot_size,
        )
        self._spin_size.valueChanged.connect(lambda _: self.changed.emit())

        self._spin_opacity = make_float_row(
            form,
            "Opacity:",
            "Transparency of each dot (0 = invisible, 1 = fully opaque).\n"
            "Lower opacity reveals overlapping density in crowded regions.",
            0.01,
            1.0,
            0.05,
            cfg.opacity,
        )
        self._spin_opacity.valueChanged.connect(lambda _: self.changed.emit())

        layout.addLayout(form)

        layout.addWidget(section_header("Event Cap"))
        form2 = QFormLayout()
        form2.setSpacing(8)
        self._spin_events = make_int_row(
            form2,
            "Max Events:",
            "Maximum number of events to render. Lower values are faster.",
            10_000,
            self._max_sample_events,
            10_000,
            min(cfg.max_events, self._max_sample_events),
        )
        self._spin_events.valueChanged.connect(lambda _: self.changed.emit())
        layout.addLayout(form2)
        layout.addStretch()

    def get_config(self) -> DotPlotConfig:
        return DotPlotConfig(
            dot_color=self._color_btn.color,
            dot_size=self._spin_size.value(),
            opacity=self._spin_opacity.value(),
            max_events=self._spin_events.value(),
        )

    def set_config(self, config: DotPlotConfig) -> None:
        self._color_btn.set_color(config.dot_color)
        self._spin_size.setValue(config.dot_size)
        self._spin_opacity.setValue(config.opacity)
        self._spin_events.setValue(min(config.max_events, self._max_sample_events))
