"""Histogram Overlay options panel."""

from __future__ import annotations

from karcytics_sdk.plugin.components import BioComboBox, BioHelpButton
from karcytics_sdk.plugin.theme_fallback import Colors
from PyQt6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from karcytics_plugins.flow_cytometry.ui.widgets.checkbox_style import checkbox_qss

from .base import IOptionsPanel


class HistogramOverlayOptionsPanel(IOptionsPanel):
    """SRP: owns Qt controls for Histogram Overlay plot settings only."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:  # noqa: PLR0915
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # ── Layout mode ───────────────────────────────────────────────
        layout_row = QHBoxLayout()
        layout_lbl = QLabel("Layout:")
        layout_help = BioHelpButton()
        layout_help.setHelpText(
            "Overlay: all populations drawn on one shared axis, alpha-blended.\n\n"
            "Ridge: each population gets its own row, stacked vertically with "
            "a shared X-axis — like the classic flow cytometry ridge plot.",
            "Layout",
        )
        layout_row.addWidget(layout_lbl)
        layout_row.addWidget(layout_help)
        layout_row.addStretch()
        layout.addLayout(layout_row)

        self._layout_combo = BioComboBox()
        self._layout_combo.setObjectName("HistogramLayoutCombo")
        self._layout_combo.addItem("Ridge (waterfall)", "ridge")
        self._layout_combo.addItem("Overlay (all on one axis)", "overlay")
        self._layout_combo.currentIndexChanged.connect(self._on_layout_changed)
        layout.addWidget(self._layout_combo)

        # ── Ridge spacing (only shown in ridge mode) ───────────────────
        self._ridge_spacing_widget = QWidget()
        rs_layout = QFormLayout(self._ridge_spacing_widget)
        rs_layout.setContentsMargins(0, 0, 0, 0)
        rs_layout.setSpacing(6)

        rs_lbl = QLabel("Ridge overlap:")
        rs_help = BioHelpButton()
        rs_help.setHelpText(
            "Controls how much the ridge panels overlap vertically.\n"
            "0 = no overlap (panels are fully separated).\n"
            "1 = maximum overlap (panels nearly touch the one above).",
            "Ridge Overlap",
        )
        rs_row = QHBoxLayout()
        rs_row.addWidget(rs_lbl)
        rs_row.addWidget(rs_help)
        rs_row.addStretch()

        self._ridge_overlap_spin = QDoubleSpinBox()
        self._ridge_overlap_spin.setRange(0.0, 0.95)
        self._ridge_overlap_spin.setSingleStep(0.05)
        self._ridge_overlap_spin.setDecimals(2)
        self._ridge_overlap_spin.setValue(0.60)

        rs_layout.addRow(rs_row)
        rs_layout.addRow(self._ridge_overlap_spin)
        layout.addWidget(self._ridge_spacing_widget)

        # ── X-axis transform ──────────────────────────────────────────
        xt_row = QHBoxLayout()
        xt_lbl = QLabel("X-axis scale:")
        xt_help = BioHelpButton()
        xt_help.setHelpText(
            "Linear: raw values on the X-axis.\n"
            "Log₁₀: logarithmic scale — best for wide-dynamic-range fluorescence data.\n"
            "Biexponential: symmetric log that handles negative values from compensation.",
            "X-Axis Scale",
        )
        xt_row.addWidget(xt_lbl)
        xt_row.addWidget(xt_help)
        xt_row.addStretch()
        layout.addLayout(xt_row)

        self._x_transform_combo = BioComboBox()
        self._x_transform_combo.addItem("Linear", "linear")
        self._x_transform_combo.addItem("Log₁₀", "log")
        self._x_transform_combo.addItem("Biexponential", "biex")
        layout.addWidget(self._x_transform_combo)

        # ── Smooth KDE ────────────────────────────────────────────────
        kde_row = QHBoxLayout()
        self._smooth_kde_cb = QCheckBox("Smooth curve (KDE)")
        self._smooth_kde_cb.setChecked(True)
        kde_help = BioHelpButton()
        kde_help.setHelpText(
            "Draws a smooth kernel density estimate instead of raw histogram bars.\n"
            "Recommended for clean, publication-ready overlays.",
            "Smooth KDE",
        )
        kde_row.addWidget(self._smooth_kde_cb)
        kde_row.addWidget(kde_help)
        kde_row.addStretch()
        layout.addLayout(kde_row)

        # ── Normalise to peak ──────────────────────────────────────────
        norm_row = QHBoxLayout()
        self._normalize_cb = QCheckBox("Normalise to peak")
        self._normalize_cb.setChecked(True)
        norm_help = BioHelpButton()
        norm_help.setHelpText(
            "Scales each population's curve so its peak equals 1.0.\n"
            "Ensures small populations are visible alongside large ones.\n"
            "Turn off to compare absolute event counts.",
            "Normalise to Peak",
        )
        norm_row.addWidget(self._normalize_cb)
        norm_row.addWidget(norm_help)
        norm_row.addStretch()
        layout.addLayout(norm_row)

        # ── Bins (only relevant when KDE is off) ──────────────────────
        bins_form = QFormLayout()
        bins_form.setSpacing(4)
        bins_lbl = QLabel("Histogram bins:")
        bins_lbl.setToolTip("Number of bins when 'Smooth curve' is disabled.")
        self._bins_spin = QSpinBox()
        self._bins_spin.setRange(32, 512)
        self._bins_spin.setSingleStep(32)
        self._bins_spin.setValue(256)
        bins_form.addRow(bins_lbl, self._bins_spin)
        layout.addLayout(bins_form)

        # ── Line width ────────────────────────────────────────────────
        lw_form = QFormLayout()
        lw_form.setSpacing(4)
        lw_lbl = QLabel("Line width:")
        self._lw_spin = QDoubleSpinBox()
        self._lw_spin.setRange(0.5, 5.0)
        self._lw_spin.setSingleStep(0.5)
        self._lw_spin.setDecimals(1)
        self._lw_spin.setValue(1.5)
        lw_form.addRow(lw_lbl, self._lw_spin)
        layout.addLayout(lw_form)

        # ── Show legend (overlay mode) ────────────────────────────────
        leg_row = QHBoxLayout()
        self._legend_cb = QCheckBox("Show legend (overlay mode)")
        self._legend_cb.setChecked(True)
        leg_row.addWidget(self._legend_cb)
        leg_row.addStretch()
        layout.addLayout(leg_row)

        self.apply_theme({})

    # ── Slots ─────────────────────────────────────────────────────────

    def _on_layout_changed(self, _index: int) -> None:
        is_ridge = self._layout_combo.currentData() == "ridge"
        self._ridge_spacing_widget.setVisible(is_ridge)
        self._legend_cb.setEnabled(not is_ridge)

    # ── IOptionsPanel API ──────────────────────────────────────────────

    def get_config(self) -> dict:
        return {
            "layout": self._layout_combo.currentData() or "ridge",
            "smooth_kde": self._smooth_kde_cb.isChecked(),
            "normalize_to_peak": self._normalize_cb.isChecked(),
            "bins": self._bins_spin.value(),
            "ridge_overlap": self._ridge_overlap_spin.value(),
            "x_transform": self._x_transform_combo.currentData() or "linear",
            "show_legend": self._legend_cb.isChecked(),
            "line_width": self._lw_spin.value(),
        }

    def apply_theme(self, colors: dict) -> None:
        fg = Colors.FG_PRIMARY
        sec = Colors.FG_SECONDARY
        spin_style = (
            f"QSpinBox, QDoubleSpinBox {{"
            f" background: {Colors.BG_MEDIUM}; color: {fg};"
            f" border: 1px solid {Colors.BORDER}; border-radius: 3px; padding: 2px 6px; }}"
        )
        for cb in (self._smooth_kde_cb, self._normalize_cb, self._legend_cb):
            cb.setStyleSheet(checkbox_qss())
        for lbl in self.findChildren(QLabel):
            lbl.setStyleSheet(f"color: {sec}; font-size: 11px;")
        for spin in self.findChildren(QSpinBox):
            spin.setStyleSheet(spin_style)
        for dspin in self.findChildren(QDoubleSpinBox):
            dspin.setStyleSheet(spin_style)
