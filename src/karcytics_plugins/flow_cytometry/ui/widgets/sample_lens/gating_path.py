"""The selected population's gating path, one live plot per gate.

Each plot is a real ``FlowCanvas`` showing the gate's *parent* population on
the gate's axes, the gate and its siblings drawn over it, and the selected
population backgated on top. The canvases carry the gate coordinator, so a
gate dragged here is edited, re-counted and propagated exactly as on the
Gating tab.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np
from karcytics_sdk.plugin.components import BioCaptionLabel, SubtitleLabel
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from ....analysis.fcs_io import get_channel_marker_label
from ....analysis.gating import GateNode
from ....analysis.sample_lens.edges import gate_axes
from ...graph.flow_canvas import DisplayMode, FlowCanvas
from ._style import card

if TYPE_CHECKING:
    import pandas as pd

    from ....analysis.experiment import Sample
    from ....analysis.gating import Gate
    from ....analysis.state import FlowState
    from .lens_model import Proposal

PLOT_W, PLOT_H = 320, 290


@dataclass
class PlotStep:
    """One plot: ``events`` on ``gate``'s axes, ``backgate`` rows highlighted."""

    caption: str
    events: pd.DataFrame
    gate: Gate
    backgate: np.ndarray
    color: str
    gates: list[Gate]  # overlays to draw (the canvas keeps those on its axes)
    nodes: list[GateNode]  # their nodes: a gate is drawn only with a node
    selected_node_id: str | None = None  # whose handles to show (None: not editable here)


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

    def show_steps(self, title: str, hint: str, sample: Sample, steps: list[PlotStep]) -> None:
        """Show one plot per step (extra canvases are hidden, never destroyed)."""
        self._title.setText(title)
        self._hint.setText(hint)
        for plot in self._plots[len(steps) :]:
            plot.hide()
        for i, step in enumerate(steps):
            plot = self._plot(i)
            self._draw(plot, sample, step)
            plot.show()

    def show_population(
        self, sample: Sample | None, events: pd.DataFrame | None, node: GateNode | None, color: str
    ) -> None:
        """``node``'s gating path, ``node`` backgated on every step."""
        path = gate_path(node) if node is not None else []
        if sample is None or events is None or node is None or not path:
            for plot in self._plots:
                plot.hide()
            self._title.setText("Gating path")
            self._hint.setText("Pick a population in the hierarchy to see every gate above it.")
            return
        selected = node.mask(events)
        steps = []
        for step_node in path:
            assert step_node.gate is not None
            parent = step_node.parent_mask(events)
            parent_node = step_node.parents[0] if step_node.parents else None
            gates, nodes = self._controller.get_gates_for_display(
                sample.sample_id, parent_node.node_id if parent_node else None
            )
            steps.append(
                PlotStep(
                    caption=f"{parent_node.name if parent_node else 'All Events'}  →  {step_node.name}",
                    events=events.loc[parent],
                    gate=step_node.gate,
                    backgate=selected[parent],
                    color=color,
                    gates=gates,
                    nodes=nodes,
                    selected_node_id=step_node.node_id,
                )
            )
        self.show_steps(
            f"Gating path · {node.name}",
            f"Each plot is the parent population on that gate's axes; {node.name} is highlighted. "
            "Drag a gate here to edit it — every sample in its group follows.",
            sample,
            steps,
        )

    def show_proposal(self, sample: Sample, proposal: Proposal, color: str) -> None:
        """Each proposed gate on the events left by the ones before it, cluster highlighted."""
        steps = []
        remaining = np.ones(len(proposal.events), dtype=bool)
        for i, proposed in enumerate(proposal.steps):
            preview = GateNode(gate=proposed.gate, name=f"Step {i + 1}")
            steps.append(
                PlotStep(
                    caption=f"Step {i + 1} · F1 {proposed.f1:.2f}",
                    events=proposal.events.loc[remaining],
                    gate=proposed.gate,
                    backgate=proposal.target[remaining],
                    color=color,
                    gates=[proposed.gate],
                    nodes=[preview],
                )
            )
            remaining &= proposed.gate.contains(proposal.events)
        self.show_steps(
            f"Proposed gates · cluster {proposal.cluster}",
            "The cluster is highlighted; each step keeps only the events inside the one before. "
            "Nothing changes until you add them.",
            sample,
            steps,
        )

    def _draw(self, plot: _PathPlot, sample: Sample, step: PlotStep) -> None:
        params = [param for param, _ in gate_axes(step.gate)]
        x = params[0]
        y = params[1] if len(params) > 1 else x
        fcs = sample.fcs_data
        plot.caption.setText(step.caption)
        canvas = plot.canvas
        canvas.begin_update()
        canvas.set_sample_id(sample.sample_id)
        canvas.set_display_mode(DisplayMode.PSEUDOCOLOR if y != x else DisplayMode.HISTOGRAM)
        canvas.set_axes(
            x,
            y,
            get_channel_marker_label(fcs, x) if fcs else x,
            get_channel_marker_label(fcs, y) if fcs else y,
        )
        canvas.set_scales(
            self._axis_manager.get_scale(x, sample.sample_id),
            self._axis_manager.get_scale(y, sample.sample_id),
        )
        canvas.set_backgate(step.backgate, step.color)
        canvas.set_data(step.events)
        canvas.end_update()  # one redraw with axes, scales, data and backgate together
        canvas.set_gates(step.gates, step.nodes)
        canvas.select_gate(step.selected_node_id)
