"""Violin plot options panel."""

from __future__ import annotations

from karcytics_sdk.plugin.components import BioComboBox, BioHelpButton
from karcytics_sdk.plugin.theme_fallback import Colors
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QSlider,
    QVBoxLayout,
)

from karcytics_plugins.flow_cytometry.ui.widgets.checkbox_style import checkbox_qss

from .base import IOptionsPanel

# Slider integer scale for a 0.5-percentile step (50.0..100.0 in 0.5 increments).
_RANGE_PRECISION = 2
_RANGE_MIN_PCT = 50.0
_RANGE_MAX_PCT = 100.0


class ViolinOptionsPanel(IOptionsPanel):
    """SRP: owns Qt controls for violin plot settings only."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        form = QFormLayout()
        form.setSpacing(10)

        self._setup_orientation(layout)
        self._setup_axis_range(layout)
        self._setup_box_overlay(layout)
        self._setup_individual_points(layout)

        self.apply_theme({})

    def _setup_orientation(self, layout: QVBoxLayout) -> None:
        orient_row = QHBoxLayout()
        orient_lbl = QLabel("Orientation:")
        orient_help = BioHelpButton()
        orient_help.setHelpText(
            "Vertical: violins grow upward (channels on X axis).\n"
            "Horizontal: violins grow rightward (channels on Y axis).",
            "Orientation",
        )
        self._orient_combo = BioComboBox()
        self._orient_combo.addItem("Vertical", "vertical")
        self._orient_combo.addItem("Horizontal", "horizontal")
        orient_row.addWidget(orient_lbl)
        orient_row.addWidget(orient_help)
        orient_row.addStretch()
        layout.addLayout(orient_row)
        layout.addWidget(self._orient_combo)

    def _setup_axis_range(self, layout: QVBoxLayout) -> None:
        range_row = QHBoxLayout()
        range_lbl = QLabel("Axis Range:")
        range_help = BioHelpButton()
        range_help.setHelpText(
            "Flow cytometry channels are often heavily right-skewed by a "
            "small number of very bright outlier events, which stretches "
            "the axis and compresses the bulk of each violin into a sliver "
            "near zero. Dragging below 100 clips the axis to where that "
            "percentile of events actually sit — outliers beyond that point "
            "are cut off from view only, not removed from the plotted "
            "distribution. Leave at 100 for the full, unclipped range.",
            "Axis Range",
        )
        range_row.addWidget(range_lbl)
        range_row.addWidget(range_help)
        range_row.addStretch()
        layout.addLayout(range_row)

        range_ctrl_row = QHBoxLayout()
        self._range_slider = QSlider(Qt.Orientation.Horizontal)
        self._range_slider.setRange(
            int(_RANGE_MIN_PCT * _RANGE_PRECISION), int(_RANGE_MAX_PCT * _RANGE_PRECISION)
        )
        self._range_slider.setValue(int(_RANGE_MAX_PCT * _RANGE_PRECISION))
        self._range_spin = QDoubleSpinBox()
        self._range_spin.setRange(_RANGE_MIN_PCT, _RANGE_MAX_PCT)
        self._range_spin.setSingleStep(0.5)
        self._range_spin.setDecimals(1)
        self._range_spin.setSuffix("th pct")
        self._range_spin.setValue(_RANGE_MAX_PCT)
        self._range_spin.setFixedWidth(90)
        self._range_slider.valueChanged.connect(
            lambda v: self._range_spin.setValue(v / _RANGE_PRECISION)
        )
        self._range_spin.valueChanged.connect(
            lambda v: self._range_slider.setValue(round(v * _RANGE_PRECISION))
        )
        self._range_spin.valueChanged.connect(self._update_range_status)
        range_ctrl_row.addWidget(self._range_slider)
        range_ctrl_row.addWidget(self._range_spin)
        layout.addLayout(range_ctrl_row)

        self._range_status_lbl = QLabel()
        layout.addWidget(self._range_status_lbl)
        self._update_range_status(_RANGE_MAX_PCT)

    def _setup_box_overlay(self, layout: QVBoxLayout) -> None:
        box_row = QHBoxLayout()
        self._show_box_cb = QCheckBox("Show box plot overlay")
        self._show_box_cb.setChecked(True)
        box_help = BioHelpButton()
        box_help.setHelpText(
            "Draws a thin box-and-whisker plot inside each violin showing "
            "the median, IQR and 1.5×IQR whiskers.",
            "Box Overlay",
        )
        box_row.addWidget(self._show_box_cb)
        box_row.addWidget(box_help)
        box_row.addStretch()
        layout.addLayout(box_row)

    def _setup_individual_points(self, layout: QVBoxLayout) -> None:
        pts_row = QHBoxLayout()
        self._show_pts_cb = QCheckBox("Show individual data points")
        self._show_pts_cb.setChecked(False)
        pts_help = BioHelpButton()
        pts_help.setHelpText(
            "Overlays individual event values as small dots (capped at 500 per sample). "
            "Useful for small populations where the shape alone is not informative.",
            "Individual Points",
        )
        pts_row.addWidget(self._show_pts_cb)
        pts_row.addWidget(pts_help)
        pts_row.addStretch()
        layout.addLayout(pts_row)

        self.apply_theme({})

    def _update_range_status(self, value: float) -> None:
        if value >= _RANGE_MAX_PCT:
            self._range_status_lbl.setText("Showing the full, unclipped range.")
        else:
            self._range_status_lbl.setText(f"Zoomed to the {value:g}th percentile.")

    def get_config(self) -> dict:
        return {
            "orientation": self._orient_combo.currentData() or "vertical",
            "show_box": self._show_box_cb.isChecked(),
            "show_points": self._show_pts_cb.isChecked(),
            "axis_range_pct": self._range_spin.value(),
        }

    def apply_theme(self, colors: dict) -> None:
        sec = Colors.FG_SECONDARY
        for cb in (self._show_box_cb, self._show_pts_cb):
            cb.setStyleSheet(checkbox_qss())
        for lbl in self.findChildren(QLabel):
            lbl.setStyleSheet(f"color: {sec}; font-size: 11px;")
        self._range_spin.setStyleSheet(
            f"color: {Colors.FG_PRIMARY}; background: {Colors.BG_MEDIUM};"
            f" border: 1px solid {Colors.BORDER}; border-radius: 3px; padding: 2px 4px;"
        )
