"""Pseudocolor settings panel."""

from __future__ import annotations

from karcytics_sdk.plugin.theme_fallback import Colors, Fonts
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from karcytics_plugins.flow_cytometry.analysis.config import COLORMAPS, PseudocolorConfig
from karcytics_plugins.flow_cytometry.ui.widgets.styled_combo import FlowComboBox

from ._utils import PANEL_STYLE, make_float_row, make_int_row, section_header


class PseudocolorSettingsPanel(QWidget):
    """Settings panel for the Pseudocolor density renderer."""

    changed = pyqtSignal()  # emitted on any value change

    def __init__(self, config: PseudocolorConfig, max_sample_events: int = 300_000, parent=None):
        super().__init__(parent)
        self._cfg = PseudocolorConfig(
            colormap=config.colormap,
            max_events=config.max_events,
            population_detail=config.population_detail,
            population_smoothing=config.population_smoothing,
            background_suppression=config.background_suppression,
            vibrancy_min=config.vibrancy_min,
            vibrancy_range=config.vibrancy_range,
            point_size=config.point_size,
            opacity=config.opacity,
        )
        self._max_sample_events = max_sample_events
        self._build_ui()

    def _build_ui(self) -> None:  # noqa: PLR0915
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)
        self.setStyleSheet(PANEL_STYLE)

        # ── Presets ───────────────────────────────────────────────────
        layout.addWidget(section_header("Quick Presets"))
        preset_row = QHBoxLayout()
        self._preset_buttons: list[QPushButton] = []
        for label, func in [
            ("Standard", self._preset_standard),
            ("Publication", self._preset_publication),
            ("Fast Preview", self._preset_fast),
        ]:
            btn = QPushButton(label)
            btn.setFixedHeight(26)
            btn.clicked.connect(func)
            preset_row.addWidget(btn)
            self._preset_buttons.append(btn)
        layout.addLayout(preset_row)

        # ── Color scheme ──────────────────────────────────────────────
        layout.addWidget(section_header("Color Scheme"))
        form1 = QFormLayout()
        form1.setSpacing(8)
        self._cmap_combo = FlowComboBox()
        self._cmap_combo.setMinimumWidth(220)  # Prevent truncation of long names
        for label, name in COLORMAPS:
            self._cmap_combo.addItem(label, name)
        # Set current
        for i in range(self._cmap_combo.count()):
            if self._cmap_combo.itemData(i) == self._cfg.colormap:
                self._cmap_combo.setCurrentIndex(i)
                break
        self._cmap_combo.currentIndexChanged.connect(lambda _: self.changed.emit())
        self._cmap_label = QLabel("Colormap:")
        form1.addRow(self._cmap_label, self._cmap_combo)
        layout.addLayout(form1)

        # ── Event cap ─────────────────────────────────────────────────
        layout.addWidget(section_header("Event Cap"))
        form2 = QFormLayout()
        form2.setSpacing(8)
        cap = min(self._cfg.max_events, self._max_sample_events)
        self._spin_events = make_int_row(
            form2,
            "Max Events:",
            "Maximum events rendered. Lower = faster UI, higher = more detail.\n"
            "Cap is set to your sample size — no point going higher.",
            10_000,
            max(self._max_sample_events, 10_000),
            10_000,
            cap,
        )
        self._spin_events.valueChanged.connect(lambda _: self.changed.emit())

        # Quick cap buttons
        cap_row = QHBoxLayout()
        self._cap_buttons: list[QPushButton] = []
        for label, val in [
            ("10k", 10_000),
            ("50k", 50_000),
            ("100k", 100_000),
            (f"All ({self._max_sample_events // 1000}k)", self._max_sample_events),
        ]:
            b = QPushButton(label)
            b.setFixedHeight(22)
            b.clicked.connect(
                lambda _, v=val: self._spin_events.setValue(min(v, self._max_sample_events))
            )
            cap_row.addWidget(b)
            self._cap_buttons.append(b)
        form2.addRow("", QWidget())  # spacer row
        layout.addLayout(form2)
        layout.addLayout(cap_row)

        # ── Visual Styling ────────────────────────────────────────────
        layout.addWidget(section_header("Visual Styling"))
        form_style = QFormLayout()
        form_style.setSpacing(8)

        self._spin_size = make_float_row(
            form_style,
            "Point Size:",
            "Diameter of each event marker. Larger dots create the 'thick' cluster look.",
            0.5,
            10.0,
            0.5,
            self._cfg.point_size,
        )
        self._spin_size.valueChanged.connect(lambda _: self.changed.emit())

        self._spin_opacity = make_float_row(
            form_style,
            "Opacity:",
            "Transparency of markers. Higher values make populations look more solid.",
            0.1,
            1.0,
            0.05,
            self._cfg.opacity,
        )
        self._spin_opacity.valueChanged.connect(lambda _: self.changed.emit())

        layout.addLayout(form_style)

        # ── Density appearance ────────────────────────────────────────
        layout.addWidget(section_header("Density Appearance"))
        form3 = QFormLayout()
        form3.setSpacing(8)

        self._spin_detail = make_float_row(
            form3,
            "Population Detail:",
            "How finely the density grid is computed.\n"
            "Higher = sharper cluster boundaries but slower render.",
            0.5,
            12.0,
            0.1,
            self._cfg.population_detail,
        )
        self._spin_detail.valueChanged.connect(lambda _: self.changed.emit())

        self._spin_smooth = make_float_row(
            form3,
            "Population Smoothing:",
            "Gaussian blur applied to the density grid.\n"
            "Higher = softer, more continuous appearance.",
            0.0,
            12.0,
            0.1,
            self._cfg.population_smoothing,
        )
        self._spin_smooth.valueChanged.connect(lambda _: self.changed.emit())

        self._spin_bg = make_float_row(
            form3,
            "Background Suppression:",
            "Events below this density are forced to background blue.\n"
            "Increase to hide sparse noise. Decrease to show every event.",
            0.0,
            0.8,
            0.01,
            self._cfg.background_suppression,
            precision=1000,
        )
        self._spin_bg.valueChanged.connect(lambda _: self.changed.emit())

        self._spin_vib_min = make_float_row(
            form3,
            "Color Floor:",
            "Minimum color brightness for above-threshold events.\n"
            "Higher = low-density regions appear more colorful immediately.",
            0.0,
            1.0,
            0.05,
            self._cfg.vibrancy_min,
        )
        self._spin_vib_min.valueChanged.connect(lambda _: self.changed.emit())

        self._spin_vib_range = make_float_row(
            form3,
            "Color Contrast:",
            "Amplification of the color range between sparse and dense regions.\n"
            "Higher = more vivid cores; lower = more uniform appearance.",
            0.1,
            3.0,
            0.05,
            self._cfg.vibrancy_range,
        )
        self._spin_vib_range.valueChanged.connect(lambda _: self.changed.emit())

        layout.addLayout(form3)
        layout.addStretch()

        self._apply_theme_styles()

    # ── Theme ─────────────────────────────────────────────────────────

    def _apply_theme_styles(self) -> None:
        """Re-apply Colors-derived QSS baked in at construction time.

        The workspace dialog always rebuilds this panel fresh (so it's
        never stale), but a caller that constructs it once and reuses it
        (e.g. the Comparisons tab's embedded copy) needs to call this on
        every theme change to avoid frozen colors.
        """
        self.setStyleSheet(PANEL_STYLE)
        for btn in self._preset_buttons:
            btn.setStyleSheet(
                f"QPushButton {{ background: {Colors.BG_MEDIUM}; color: {Colors.FG_PRIMARY};"
                f" border: 1px solid {Colors.BORDER}; border-radius: 4px;"
                f" font-size: 11px; font-weight: 600; padding: 2px 8px; }}"
                f"QPushButton:hover {{ background: {Colors.ACCENT_PRIMARY};"
                f" color: {Colors.BG_DARKEST}; }}"
            )
        for btn in self._cap_buttons:
            btn.setStyleSheet(
                f"QPushButton {{ background: {Colors.BG_MEDIUM}; color: {Colors.FG_SECONDARY};"
                f" border: 1px solid {Colors.BORDER}; border-radius: 3px; font-size: 10px; }}"
                f"QPushButton:hover {{ color: {Colors.ACCENT_PRIMARY}; }}"
            )
        self._cmap_label.setStyleSheet(
            f"color: {Colors.FG_SECONDARY}; font-size: {Fonts.SIZE_SMALL}px;"
        )

    # ── Presets ───────────────────────────────────────────────────────

    def _preset_standard(self) -> None:
        self._spin_detail.setValue(1.5)
        self._spin_smooth.setValue(2.2)
        self._spin_bg.setValue(0.05)
        self._spin_vib_min.setValue(0.15)
        self._spin_vib_range.setValue(0.85)
        self._spin_size.setValue(1.8)
        self._spin_opacity.setValue(0.70)
        self._spin_events.setValue(min(100_000, self._max_sample_events))

    def _preset_publication(self) -> None:
        self._spin_detail.setValue(3.0)
        self._spin_smooth.setValue(3.2)
        self._spin_bg.setValue(0.08)
        self._spin_vib_min.setValue(0.20)
        self._spin_vib_range.setValue(0.80)
        self._spin_size.setValue(1.5)
        self._spin_opacity.setValue(0.90)
        self._spin_events.setValue(self._max_sample_events)

    def _preset_fast(self) -> None:
        self._spin_detail.setValue(1.0)
        self._spin_smooth.setValue(1.5)
        self._spin_bg.setValue(0.04)
        self._spin_vib_min.setValue(0.15)
        self._spin_vib_range.setValue(0.85)
        self._spin_size.setValue(2.2)
        self._spin_opacity.setValue(0.50)
        self._spin_events.setValue(min(50_000, self._max_sample_events))

    # ── Public API ────────────────────────────────────────────────────

    def get_config(self) -> PseudocolorConfig:
        return PseudocolorConfig(
            colormap=self._cmap_combo.currentData() or "jet",
            max_events=self._spin_events.value(),
            population_detail=self._spin_detail.value(),
            population_smoothing=self._spin_smooth.value(),
            background_suppression=self._spin_bg.value(),
            vibrancy_min=self._spin_vib_min.value(),
            vibrancy_range=self._spin_vib_range.value(),
            point_size=self._spin_size.value(),
            opacity=self._spin_opacity.value(),
        )

    def set_config(self, config: PseudocolorConfig) -> None:
        for i in range(self._cmap_combo.count()):
            if self._cmap_combo.itemData(i) == config.colormap:
                self._cmap_combo.setCurrentIndex(i)
                break
        self._spin_events.setValue(min(config.max_events, self._max_sample_events))
        self._spin_detail.setValue(config.population_detail)
        self._spin_smooth.setValue(config.population_smoothing)
        self._spin_bg.setValue(config.background_suppression)
        self._spin_vib_min.setValue(config.vibrancy_min)
        self._spin_vib_range.setValue(config.vibrancy_range)
        self._spin_size.setValue(config.point_size)
        self._spin_opacity.setValue(config.opacity)
