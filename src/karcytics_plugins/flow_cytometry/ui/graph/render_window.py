"""Render window: one plot with every event at full resolution, to look at and export.

Opened from a gating plot's right-click menu. The main plots subsample to
stay responsive; this draws the whole population on a grid twice as fine,
with the same axes, scales, display mode and gates.
"""

from __future__ import annotations

from functools import partial

from karcytics_sdk.plugin.theme_fallback import theme_manager
from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QMainWindow, QToolBar

from karcytics_plugins.flow_cytometry.analysis.gating import Gate, GateNode
from karcytics_plugins.flow_cytometry.analysis.population_service import population_events
from karcytics_plugins.flow_cytometry.analysis.scaling import AxisScale
from karcytics_plugins.flow_cytometry.analysis.state import FlowState

from .canvas.modes import DisplayMode
from .canvas.plot_export import FORMATS, copy_plot, save_plot
from .flow_canvas import FlowCanvas

EXPORT_DPI = 300  # publication quality, for the raster formats


class RenderWindow(QMainWindow):
    """A full-quality render of one population's plot."""

    def __init__(  # noqa: PLR0913 - the plot it reopens: sample, population, axes, scales
        self,
        state: FlowState,
        sample_id: str,
        node_id: str | None,
        axes: tuple[str, str],
        scales: tuple[AxisScale, AxisScale],
        display_mode: DisplayMode | None = None,
        gates: list[Gate] | None = None,
        gate_nodes: list[GateNode] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        sample = state.data.experiment.samples.get(sample_id)
        name = sample.display_name if sample is not None else sample_id
        self.setWindowTitle(f"Full Render — {name}")
        self.setMinimumSize(800, 700)

        self.canvas = FlowCanvas(state, parent=self)  # no controller: gates are shown, not edited
        self.canvas.set_full_quality()
        self.setCentralWidget(self.canvas)
        self._add_toolbar()

        node = sample.gate_tree.find_node_by_id(node_id) if sample and node_id else None
        events = population_events(state.data.experiment, sample, node)
        if events is None:
            return
        self.canvas.begin_update()
        self.canvas.set_axes(*axes)
        self.canvas.set_scales(*scales)
        if display_mode is not None:
            self.canvas.set_display_mode(display_mode, redraw=False)
        if gates:
            self.canvas.set_gates(gates, gate_nodes)
        self.canvas.end_update()
        self.canvas.set_data(events)

    def _add_toolbar(self) -> None:
        toolbar = QToolBar("Render Actions")
        toolbar.setIconSize(QSize(18, 18))
        toolbar.setMovable(False)
        theme_manager.apply_style(
            toolbar,
            "QToolBar { background: {BG_DARK}; border-bottom: 1px solid {BORDER};"
            " padding: 4px; spacing: 8px; }"
            "QToolButton { color: {FG_PRIMARY}; font-size: 11px; font-weight: 600;"
            " border-radius: 4px; padding: 4px 8px; }"
            "QToolButton:hover { background: {BG_MEDIUM}; color: {ACCENT_PRIMARY}; }",
        )
        figure = self.canvas.figure
        toolbar.addAction("📋 Copy to Clipboard", partial(copy_plot, figure))
        for fmt in FORMATS:
            dpi = EXPORT_DPI if fmt == "png" else None
            toolbar.addAction(f"💾 Save {fmt.upper()}…", partial(save_plot, self, figure, fmt, dpi))
        toolbar.addSeparator()
        toolbar.addAction("✕ Close", self.close)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, toolbar)
