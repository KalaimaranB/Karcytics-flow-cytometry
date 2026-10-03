"""Shared UI utilities for render settings panels."""

from __future__ import annotations

from karcytics_sdk.plugin.theme_fallback import theme_manager
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QSpinBox,
    QWidget,
)

# ── Color picker button ───────────────────────────────────────────────────────


class ColorPickerButton(QPushButton):
    """A button that shows the current color and opens QColorDialog on click."""

    color_changed = pyqtSignal(str)  # emits hex string

    def __init__(self, initial_color: str = "#2196F3", parent=None):
        super().__init__(parent)
        self._color = initial_color
        self.setFixedSize(36, 24)
        self._refresh_style()
        self.clicked.connect(self._open_picker)

    @property
    def color(self) -> str:
        return self._color

    def set_color(self, hex_color: str) -> None:
        self._color = hex_color
        self._refresh_style()

    def _refresh_style(self) -> None:
        theme_manager.apply_style(
            self,
            f"QPushButton {{ background: {self._color}; border: 1px solid {{BORDER}};"
            f" border-radius: 3px; }}"
            f"QPushButton:hover {{ border: 1px solid {{ACCENT_PRIMARY}}; }}",
        )

    def _open_picker(self) -> None:
        from PyQt6.QtWidgets import QColorDialog

        dlg = QColorDialog(QColor(self._color), self)
        if dlg.exec():
            new_color = dlg.selectedColor().name()
            self.set_color(new_color)
            self.color_changed.emit(new_color)


# ── Slider + spin helper ──────────────────────────────────────────────────────

_SPIN_STYLE = (
    "QDoubleSpinBox, QSpinBox {"
    " color: {FG_PRIMARY}; background: {BG_MEDIUM};"
    " border: 1px solid {BORDER}; border-radius: 3px; }"
)

_LABEL_STYLE = "color: {FG_SECONDARY}; font-size: 11px;"


def make_float_row(  # noqa: PLR0913
    form_layout,
    label: str,
    tooltip: str,
    min_val: float,
    max_val: float,
    step: float,
    current: float,
    precision: int = 100,
) -> QDoubleSpinBox:
    """Add a float slider+spinbox row to a QFormLayout. Returns the spinbox."""
    spin = QDoubleSpinBox()
    spin.setRange(min_val, max_val)
    spin.setSingleStep(step)
    spin.setDecimals(2)
    spin.setValue(current)
    spin.setFixedWidth(90)
    spin.setToolTip(tooltip)
    theme_manager.apply_style(spin, _SPIN_STYLE)

    slider = QSlider(Qt.Orientation.Horizontal)
    slider.setRange(int(min_val * precision), int(max_val * precision))
    slider.setValue(int(current * precision))
    slider.setToolTip(tooltip)
    slider.valueChanged.connect(lambda v: spin.setValue(v / precision))
    spin.valueChanged.connect(lambda v: slider.setValue(int(v * precision)))

    row = QWidget()
    rl = QHBoxLayout(row)
    rl.setContentsMargins(0, 0, 0, 0)
    rl.addWidget(slider)
    rl.addWidget(spin)

    lbl = QLabel(label)
    theme_manager.apply_style(lbl, _LABEL_STYLE)
    lbl.setToolTip(tooltip)
    form_layout.addRow(lbl, row)
    return spin


def make_int_row(  # noqa: PLR0913
    form_layout,
    label: str,
    tooltip: str,
    min_val: int,
    max_val: int,
    step: int,
    current: int,
) -> QSpinBox:
    """Add an int slider+spinbox row to a QFormLayout. Returns the spinbox."""
    spin = QSpinBox()
    spin.setRange(min_val, max_val)
    spin.setSingleStep(step)
    spin.setValue(current)
    spin.setFixedWidth(90)
    spin.setToolTip(tooltip)
    theme_manager.apply_style(spin, _SPIN_STYLE)

    slider = QSlider(Qt.Orientation.Horizontal)
    slider.setRange(min_val, max_val)
    slider.setSingleStep(step)
    slider.setValue(current)
    slider.setToolTip(tooltip)
    slider.valueChanged.connect(spin.setValue)
    spin.valueChanged.connect(slider.setValue)

    row = QWidget()
    rl = QHBoxLayout(row)
    rl.setContentsMargins(0, 0, 0, 0)
    rl.addWidget(slider)
    rl.addWidget(spin)

    lbl = QLabel(label)
    theme_manager.apply_style(lbl, _LABEL_STYLE)
    lbl.setToolTip(tooltip)
    form_layout.addRow(lbl, row)
    return spin


def section_header(text: str) -> QLabel:
    lbl = QLabel(text)
    theme_manager.apply_style(
        lbl,
        "font-size: 12px; font-weight: 700; color: {FG_PRIMARY};"
        " padding-top: 4px; padding-bottom: 2px;",
    )
    return lbl


# Kept for backward-compat imports; panels should call theme_manager.apply_style directly.
PANEL_STYLE = "background: {BG_DARKEST};"
