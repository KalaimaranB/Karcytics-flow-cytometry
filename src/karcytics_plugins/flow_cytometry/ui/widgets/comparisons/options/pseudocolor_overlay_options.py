"""Pseudocolor Overlay options panel — axis channel pickers, density-base
toggle, overlay opacity, and the full Pseudocolor density-rendering settings.

Generalizes the previous BackgatingOptionsPanel (never registered in
PLOT_REGISTRY). Like every other Comparisons plot type, per-population
colour is auto-assigned from the shared theme-aware palette (`Colors
.CHART_COLORS`, injected by comparisons_viewer.py) rather than a manual
per-row colour picker — no other plot type in this tab exposes one, so
adding it here would be a one-off UI pattern instead of reusing the
existing convention.

The base/context density layer's appearance (colormap, detail, smoothing,
etc.) is controlled by an embedded `PseudocolorSettingsPanel` — the exact
same widget the workspace tab's "⚙ Settings" dialog uses for the main
gating canvas's Pseudocolor render mode — so the two stay visually and
functionally in sync instead of maintaining two divergent settings surfaces.

Axis scaling (Linear/Log/Biexponential, manual range, Auto-Range, Logicle
T/W/M/A) is controlled by two embedded `AxisTransformPanel`s — the exact
same widget the workspace tab's "⚙ Transforms" dialog uses. Unlike the
workspace tab, these are *not* synced with `AxisManager`/`group
.channel_scales` — same self-contained-per-plot convention already used by
this tab's Histogram Overlay transform combo, rather than reacting to
channel-combo changes by reloading a different sample/group's live scale.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from karcytics_sdk.plugin.components import BioComboBox, BioHelpButton
from karcytics_sdk.plugin.theme_fallback import Colors
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QSlider, QVBoxLayout

from karcytics_plugins.flow_cytometry.analysis.config import PseudocolorConfig
from karcytics_plugins.flow_cytometry.analysis.constants import PSEUDOCOLOR_MAX_EVENTS
from karcytics_plugins.flow_cytometry.analysis.scaling import AxisScale, calculate_auto_range
from karcytics_plugins.flow_cytometry.ui.graph.components.transform_widgets import (
    AxisTransformPanel,
)
from karcytics_plugins.flow_cytometry.ui.graph.render_panels._utils import section_header
from karcytics_plugins.flow_cytometry.ui.graph.render_panels.pseudocolor_panel import (
    PseudocolorSettingsPanel,
)
from karcytics_plugins.flow_cytometry.ui.widgets.checkbox_style import checkbox_qss

from ..data_extractor import ComparisonsDataExtractor
from .base import IOptionsPanel

if TYPE_CHECKING:
    from karcytics_plugins.flow_cytometry.analysis.state import FlowState


class PseudocolorOverlayOptionsPanel(IOptionsPanel):
    """SRP: owns controls for pseudocolor-overlay axis selection and layer styling."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._channels: list[tuple[str, str]] = []
        self._state: FlowState | None = None
        self._active_sample_id: str | None = None
        self._extractor = ComparisonsDataExtractor()
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._build_axis_pickers(layout)

        # ── Axis transforms (shared with the workspace tab's "⚙ Transforms"
        # dialog) — Linear/Log/Biexponential scale, manual range/Auto-Range,
        # Logicle T/W/M/A. See module docstring for the AxisManager scope note.
        layout.addWidget(section_header("Axis Transforms"))
        self._x_transform_panel = AxisTransformPanel(
            "X", AxisScale(), self._make_auto_range_callback("x")
        )
        layout.addWidget(self._x_transform_panel)
        self._y_transform_panel = AxisTransformPanel(
            "Y", AxisScale(), self._make_auto_range_callback("y")
        )
        layout.addWidget(self._y_transform_panel)

        self._build_density_and_opacity_controls(layout)

        # ── Pseudocolor settings (shared with the workspace tab's "⚙
        # Settings" dialog) — governs the base/context density layer's
        # colormap and density-shaping appearance.
        layout.addWidget(section_header("Pseudocolor Settings"))
        self._pc_panel = PseudocolorSettingsPanel(
            PseudocolorConfig(), max_sample_events=PSEUDOCOLOR_MAX_EVENTS
        )
        layout.addWidget(self._pc_panel)

        self.apply_theme({})

    def _build_axis_pickers(self, layout: QVBoxLayout) -> None:
        x_row = QHBoxLayout()
        x_lbl = QLabel("X Axis Channel:")
        x_help = BioHelpButton()
        x_help.setHelpText(
            "The channel shown on the horizontal axis.\n\n"
            "Typically FSC-A (cell size) or a scatter parameter for a size/complexity view, "
            "or a fluorescence channel to check gate placement in expression space.",
            "X Axis",
        )
        self._x_combo = BioComboBox()
        x_row.addWidget(x_lbl)
        x_row.addWidget(x_help)
        x_row.addStretch()
        layout.addLayout(x_row)
        layout.addWidget(self._x_combo)

        y_row = QHBoxLayout()
        y_lbl = QLabel("Y Axis Channel:")
        y_help = BioHelpButton()
        y_help.setHelpText(
            "The channel shown on the vertical axis.\n\n"
            "Typically SSC-A (cell complexity/granularity) for a classic scatter view, "
            "or a second fluorescence channel for a bivariate expression view.",
            "Y Axis",
        )
        self._y_combo = BioComboBox()
        y_row.addWidget(y_lbl)
        y_row.addWidget(y_help)
        y_row.addStretch()
        layout.addLayout(y_row)
        layout.addWidget(self._y_combo)

    def _build_density_and_opacity_controls(self, layout: QVBoxLayout) -> None:
        density_row = QHBoxLayout()
        self._density_cb = QCheckBox("Density-shade base layer (pseudocolor)")
        self._density_cb.setChecked(True)
        density_help = BioHelpButton()
        density_help.setHelpText(
            "When checked, the base/context population (usually All Events) is "
            "rendered as a density-coloured pseudocolor cloud, matching the main "
            "gating canvas. When unchecked, it's a flat grey scatter — lighter to "
            "render for very large event counts.",
            "Density Base Layer",
        )
        density_row.addWidget(self._density_cb)
        density_row.addWidget(density_help)
        density_row.addStretch()
        layout.addLayout(density_row)

        opacity_row = QHBoxLayout()
        self._opacity_lbl = QLabel("Overlay Opacity:  70%")
        opacity_help = BioHelpButton()
        opacity_help.setHelpText(
            "Controls how transparent the coloured overlay populations appear. "
            "Lower opacity (30–50%) works well when overlays are dense; "
            "higher opacity (70–100%) is better for rare populations.",
            "Overlay Opacity",
        )
        opacity_row.addWidget(self._opacity_lbl)
        opacity_row.addWidget(opacity_help)
        opacity_row.addStretch()
        layout.addLayout(opacity_row)

        self._opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._opacity_slider.setRange(15, 100)
        self._opacity_slider.setValue(70)
        self._opacity_slider.valueChanged.connect(
            lambda v: self._opacity_lbl.setText(f"Overlay Opacity:  {v}%")
        )
        layout.addWidget(self._opacity_slider)

    def populate_channels(
        self, channels: list[tuple[str, str]], sample_id: str | None = None
    ) -> None:
        self._channels = channels
        self._active_sample_id = sample_id
        prev_x = self._x_combo.currentData()
        prev_y = self._y_combo.currentData()
        self._x_combo.blockSignals(True)
        self._y_combo.blockSignals(True)
        self._x_combo.clear()
        self._y_combo.clear()
        for label, key in channels:
            self._x_combo.addItem(label, key)
            self._y_combo.addItem(label, key)
        for combo, prev, default_idx in [
            (self._x_combo, prev_x, 0),
            (self._y_combo, prev_y, 1),
        ]:
            idx = combo.findData(prev) if prev else -1
            combo.setCurrentIndex(idx if idx >= 0 else min(default_idx, combo.count() - 1))
        self._x_combo.blockSignals(False)
        self._y_combo.blockSignals(False)

    def bind_state(self, state: FlowState) -> None:
        """Seed the embedded Pseudocolor Settings panel from the workspace
        tab's global render config, so the overlay starts out matching
        whatever the user already dialed in there. Also stashes ``state``
        so the Axis Transform panels' Auto-Range buttons can pull live
        channel data on demand (see `_make_auto_range_callback`).
        """
        self._state = state
        self._pc_panel.set_config(state.view.render_config.pseudocolor)

    def _make_auto_range_callback(self, axis: str):
        """Build the Auto-Range callback an AxisTransformPanel expects:
        given an outlier percentile, return a (min, max) display range
        computed from the active sample's current channel data.
        """

        def _callback(outlier_percentile: float | None) -> tuple[float, float] | None:
            if self._state is None or not self._active_sample_id:
                return None
            combo = self._x_combo if axis == "x" else self._y_combo
            channel = combo.currentData()
            if not channel:
                return None
            data = self._extractor.get_events_for_population(
                self._state, self._active_sample_id, None, channel
            )
            panel = self._x_transform_panel if axis == "x" else self._y_transform_panel
            return calculate_auto_range(data, panel.scale.transform_type, outlier_percentile or 0.1)

        return _callback

    def get_config(self) -> dict:
        return {
            "x_channel": self._x_combo.currentData(),
            "y_channel": self._y_combo.currentData(),
            "x_label": self._x_combo.currentText(),
            "y_label": self._y_combo.currentText(),
            "show_density_base": self._density_cb.isChecked(),
            "layer_opacity": self._opacity_slider.value() / 100.0,
            "pseudocolor_config": self._pc_panel.get_config().to_dict(),
            "x_scale": self._x_transform_panel.scale.to_dict(),
            "y_scale": self._y_transform_panel.scale.to_dict(),
        }

    def apply_theme(self, colors: dict) -> None:
        sec = Colors.FG_SECONDARY
        for lbl in self.findChildren(QLabel):
            lbl.setStyleSheet(f"color: {sec}; font-size: 11px;")
        self._opacity_lbl.setStyleSheet(f"color: {Colors.FG_PRIMARY}; font-size: 11px;")
        self._density_cb.setStyleSheet(checkbox_qss())
        if hasattr(self._pc_panel, "_apply_theme_styles"):
            self._pc_panel._apply_theme_styles()
        for panel in (self._x_transform_panel, self._y_transform_panel):
            if hasattr(panel, "_apply_theme_styles"):
                panel._apply_theme_styles()
