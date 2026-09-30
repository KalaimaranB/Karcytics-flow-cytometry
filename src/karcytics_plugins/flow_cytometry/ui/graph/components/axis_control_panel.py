"""Axis Control Panel — axis selection and display mode."""

from __future__ import annotations

from karcytics_sdk.plugin.theme_fallback import Fonts, theme_manager
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from karcytics_plugins.flow_cytometry.ui.widgets.styled_combo import FlowComboBox

from ..flow_canvas import DisplayMode


class AxisControlPanel(QWidget):
    """Axis selection and display mode for GraphWindow."""

    axis_changed = pyqtSignal()
    display_mode_changed = pyqtSignal(object)  # DisplayMode
    fmo_overlay_changed = pyqtSignal(str)  # FMO sample ID or empty string
    transforms_requested = pyqtSignal()
    settings_requested = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:  # noqa: PLR0915
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._x_label = self._make_label("X:")
        layout.addWidget(self._x_label)
        self._x_combo = FlowComboBox()
        self._x_combo.setObjectName("AxisSelectorX")
        self._x_combo.setMinimumWidth(140)
        self._x_combo.currentTextChanged.connect(lambda _: self.axis_changed.emit())
        layout.addWidget(self._x_combo)

        layout.addSpacing(16)
        self._y_label = self._make_label("Y:")
        layout.addWidget(self._y_label)

        from PyQt6.QtWidgets import QStackedWidget

        self._y_stack = QStackedWidget()
        layout.addWidget(self._y_stack)

        self._y_combo = FlowComboBox()
        self._y_combo.setObjectName("AxisSelectorY")
        self._y_combo.setMinimumWidth(140)
        self._y_combo.currentTextChanged.connect(lambda _: self.axis_changed.emit())
        self._y_stack.addWidget(self._y_combo)

        self._y_count_label = self._make_label("Count")
        theme_manager.apply_style(
            self._y_count_label,
            "color: {FG_PRIMARY}; font-size: 12px; font-weight: 500; padding: 2px 8px;",
        )
        self._y_stack.addWidget(self._y_count_label)

        # Default to Y combo
        self._y_stack.setCurrentIndex(0)

        # Display mode
        layout.addSpacing(16)
        self._display_combo = FlowComboBox()
        self._display_combo.setObjectName("DisplayModeCombo")
        for mode in DisplayMode:
            self._display_combo.addItem(mode.value, mode)

        self._display_combo.currentIndexChanged.connect(self._on_display_mode_changed)
        layout.addWidget(self._display_combo)

        # ── FMO Overlay ──
        layout.addSpacing(16)
        self._fmo_label = self._make_label("FMO Overlay:")
        layout.addWidget(self._fmo_label)

        self._fmo_combo = FlowComboBox()
        self._fmo_combo.setObjectName("AxisSelectorFMO")
        self._fmo_combo.setMinimumWidth(120)
        self._fmo_combo.addItem("None", "")
        self._fmo_combo.currentTextChanged.connect(
            lambda _: self.fmo_overlay_changed.emit(self.get_current_fmo())
        )
        layout.addWidget(self._fmo_combo)

        self._fmo_label.setVisible(False)
        self._fmo_combo.setVisible(False)

        # ── Unified Transforms Button ──
        layout.addSpacing(16)
        self._transform_btn = QPushButton("⚙ Transforms")
        self._transform_btn.setObjectName("TransformsButton")
        self._transform_btn.setFixedHeight(24)
        self._transform_btn.setToolTip("Open Axis Scaling & Transforms dialog")
        self._transform_btn.clicked.connect(self.transforms_requested.emit)
        self._style_btn(self._transform_btn)
        layout.addWidget(self._transform_btn)

        # ── Render spinner ────────────────────────────────────────────
        self._render_spinner = QLabel("⟳ Rendering…")
        self._render_spinner.setVisible(False)
        theme_manager.apply_style(
            self._render_spinner,
            "color: {ACCENT_PRIMARY}; font-size: 11px; font-weight: 600;"
            " background: transparent; padding: 0 6px;",
        )
        layout.addWidget(self._render_spinner)

        # ── Render Settings Button ──
        layout.addSpacing(16)
        self._btn_settings = QPushButton("⚙ Settings")
        self._btn_settings.setObjectName("PseudocolorSettingsButton")
        self._btn_settings.setFixedHeight(24)
        self._btn_settings.setToolTip("Customize rendering parameters")
        self._btn_settings.clicked.connect(self.settings_requested.emit)
        self._style_btn(self._btn_settings)
        layout.addWidget(self._btn_settings)

        layout.addStretch()

    def set_spinner_visible(self, visible: bool) -> None:
        self._render_spinner.setVisible(visible)

    def _make_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        theme_manager.apply_style(
            lbl,
            f"color: {{FG_SECONDARY}}; font-size: {Fonts.SIZE_SMALL}px;"
            " font-weight: 600; background: transparent;",
        )
        return lbl

    def _style_btn(self, btn: QPushButton) -> None:
        theme_manager.apply_style(
            btn,
            "QPushButton { background: {BG_MEDIUM};"
            " color: {FG_PRIMARY}; border: 1px solid {BORDER};"
            " border-radius: 3px; font-size: 11px; font-weight: 600; padding: 2px 8px; }"
            "QPushButton:hover { background: {BG_DARK};"
            " color: {ACCENT_PRIMARY}; }",
        )

    # Proxy methods for combos
    def set_display_mode(self, mode_str: str) -> None:
        for i in range(self._display_combo.count()):
            mode = self._display_combo.itemData(i)
            if mode and mode.value.lower() == mode_str.lower():
                self._display_combo.setCurrentIndex(i)
                break

    def _on_display_mode_changed(self):
        mode = self._display_combo.currentData()
        if mode:
            is_hist = mode.value == "Histogram"
            self._fmo_label.setVisible(is_hist)
            self._fmo_combo.setVisible(is_hist)

            # Hide Y dropdown and show Count for histograms
            self._y_label.setVisible(not is_hist)
            self._y_stack.setCurrentIndex(1 if is_hist else 0)

            self.display_mode_changed.emit(mode)

    def get_current_x(self) -> str:
        return self._x_combo.currentData() or self._x_combo.currentText()

    def get_current_y(self) -> str:
        return self._y_combo.currentData() or self._y_combo.currentText()

    def get_current_x_text(self) -> str:
        return self._x_combo.currentText()

    def get_current_y_text(self) -> str:
        return self._y_combo.currentText()

    def get_current_display_mode(self) -> object:
        return self._display_combo.currentData()

    def get_current_fmo(self) -> str:
        return self._fmo_combo.currentData() or ""

    def block_combos(self, block: bool) -> None:
        self._x_combo.blockSignals(block)
        self._y_combo.blockSignals(block)

    def clear_combos(self) -> None:
        self._x_combo.clear()
        self._y_combo.clear()

    def clear_fmo_combo(self) -> None:
        self._fmo_combo.blockSignals(True)
        self._fmo_combo.clear()
        self._fmo_combo.addItem("None", "")
        self._fmo_combo.blockSignals(False)

    def set_defaults(self, defaults: list[str]) -> None:
        self.clear_combos()
        self._x_combo.addItems(defaults)
        self._y_combo.addItems(defaults)
        self._x_combo.setCurrentText("FSC-A")
        self._y_combo.setCurrentText("SSC-A")

    def add_channel(self, label: str, ch: str) -> None:
        self._x_combo.addItem(label, ch)
        self._y_combo.addItem(label, ch)

    def set_current_x(self, ch: str) -> None:
        for i in range(self._x_combo.count()):
            if self._x_combo.itemData(i) == ch:
                self._x_combo.setCurrentIndex(i)
                break

    def set_current_y(self, ch: str) -> None:
        for i in range(self._y_combo.count()):
            if self._y_combo.itemData(i) == ch:
                self._y_combo.setCurrentIndex(i)
                break

    def add_fmo_option(self, label: str, sample_id: str) -> None:
        self._fmo_combo.addItem(label, sample_id)

    def set_current_fmo(self, sample_id: str) -> None:
        self._fmo_combo.blockSignals(True)
        for i in range(self._fmo_combo.count()):
            if self._fmo_combo.itemData(i) == sample_id:
                self._fmo_combo.setCurrentIndex(i)
                break
        self._fmo_combo.blockSignals(False)
