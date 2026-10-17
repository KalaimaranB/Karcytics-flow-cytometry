"""The selected population's gating path, one live plot per gate.

Each plot is a real ``FlowCanvas`` showing the gate's *parent* population on
the gate's axes, the gate and its siblings drawn over it, and the selected
population backgated on top. The canvases carry the gate coordinator, so a
gate dragged here is edited, re-counted and propagated exactly as on the
Gating tab.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from karcytics_sdk.plugin.components import BioCaptionLabel, SubtitleLabel
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from ....analysis.fcs_io import get_channel_marker_label
from ....analysis.sample_lens.edges import gate_axes
from ...graph.flow_canvas import DisplayMode, FlowCanvas
from ._style import card

if TYPE_CHECKING:
    import pandas as pd

    from ....analysis.experiment import Sample
    from ....analysis.gating import GateNode
    from ....analysis.state import FlowState

PLOT_W, PLOT_H = 320, 290


def gate_path(node: GateNode) -> list[GateNode]:
    """The gated nodes from the root down to ``node`` (logic nodes have no plot)."""
    path: list[GateNode] = []
    current: GateNode | None = node
    while current is not None and not current.is_root:
        if current.gate is not None:
            path.append(current)
        current = current.parents[0] if current.parents else None
    return path[::-1]


class _PathPlot(QWidget):
    """One step of the path: a caption over a canvas."""

    def __init__(self, state: FlowState, controller: Any) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.caption = BioCaptionLabel("")
        layout.addWidget(self.caption)
        self.canvas = FlowCanvas(state=state, controller=controller)
        self.canvas.setFixedSize(PLOT_W, PLOT_H)
        layout.addWidget(self.canvas)


class GatingPathStrip(QWidget):
    """A horizontal strip of the selected population's gating path."""

    def __init__(self, state: FlowState, controller: Any, axis_manager: Any) -> None:
        super().__init__()
        self._state = state
        self._controller = controller
        self._axis_manager = axis_manager
        self._plots: list[_PathPlot] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)
        self._title = SubtitleLabel("Gating path")
        outer.addWidget(self._title)
        self._hint = BioCaptionLabel("")
        outer.addWidget(self._hint)

        frame = card("lens_path_card", "BG_DARKEST")
        frame_layout = QVBoxLayout(frame)
        frame_layout.setContentsMargins(8, 8, 8, 8)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("background: transparent;")
        row_widget = QWidget()
        self._row = QHBoxLayout(row_widget)
        self._row.setContentsMargins(0, 0, 0, 0)
        self._row.setSpacing(12)
        self._row.addStretch()
        scroll.setWidget(row_widget)
        scroll.setFixedHeight(PLOT_H + 48)
        frame_layout.addWidget(scroll)
        outer.addWidget(frame)

    def _plot(self, i: int) -> _PathPlot:
        while len(self._plots) <= i:  # canvases are reused, never rebuilt per selection
            plot = _PathPlot(self._state, self._controller)
            self._row.insertWidget(len(self._plots), plot)
            self._plots.append(plot)
        return self._plots[i]

    def show_population(
        self, sample: Sample | None, events: pd.DataFrame | None, node: GateNode | None, color: str
    ) -> None:
        path = gate_path(node) if node is not None else []
        for plot in self._plots[len(path) :]:
            plot.hide()
        if sample is None or events is None or node is None or not path:
            self._title.setText("Gating path")
            self._hint.setText("Pick a population in the hierarchy to see every gate above it.")
            return

        self._title.setText(f"Gating path · {node.name}")
        self._hint.setText(
            f"Each plot is the parent population on that gate's axes; {node.name} is highlighted. "
            "Drag a gate here to edit it — every sample in its group follows."
        )
        selected = node.mask(events)
        for i, step in enumerate(path):
            plot = self._plot(i)
            self._show_step(plot, sample, events, step, selected, color)
            plot.show()

    def _show_step(
        self,
        plot: _PathPlot,
        sample: Sample,
        events: pd.DataFrame,
        step: GateNode,
        selected: Any,
        color: str,
    ) -> None:
        assert step.gate is not None
        parent = step.parent_mask(events)
        params = [param for param, _ in gate_axes(step.gate)]
        x = params[0]
        y = params[1] if len(params) > 1 else x
        fcs = sample.fcs_data
        x_label = get_channel_marker_label(fcs, x) if fcs else x
        y_label = get_channel_marker_label(fcs, y) if fcs else y
        parent_name = step.parents[0].name if step.parents else "All Events"
        plot.caption.setText(f"{parent_name}  →  {step.name}")

        gates, nodes = self._controller.get_gates_for_display(
            sample.sample_id, step.parents[0].node_id if step.parents else None
        )
        canvas = plot.canvas
        canvas.begin_update()
        canvas.set_sample_id(sample.sample_id)
        canvas.set_display_mode(DisplayMode.PSEUDOCOLOR if y != x else DisplayMode.HISTOGRAM)
        canvas.set_axes(x, y, x_label, y_label)
        canvas.set_scales(
            self._axis_manager.get_scale(x, sample.sample_id),
            self._axis_manager.get_scale(y, sample.sample_id),
        )
        canvas.set_backgate(selected[parent], color)
        canvas.set_data(events.loc[parent])
        canvas.end_update()  # one redraw with axes, scales, data and backgate together
        canvas.set_gates(gates, nodes)
        canvas.select_gate(step.node_id)
