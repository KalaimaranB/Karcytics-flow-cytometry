"""The selected population's gating path, one live plot per gate.

Each plot is a real ``FlowCanvas`` showing the gate's *parent* population on
the gate's axes, the gate and its siblings drawn over it, and the selected
population backgated on top. The canvases carry the gate coordinator, so a
gate dragged here is edited, re-counted and propagated exactly as on the
Gating tab.

Plots are scaled as the Gating tab scales them (``fit_scale``), widened so the
whole gate is in view, and keep that range while the same population stays
selected, so an edit never moves the plot under the mouse. A plot whose
inputs haven't changed isn't redrawn, and nothing is redrawn mid-drag.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np
from karcytics_sdk.plugin.components import (
    BioCaptionLabel,
    BioComboBox,
    BioSpinBox,
    SecondaryButton,
    SubtitleLabel,
)
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QStandardItemModel
from PySide6.QtWidgets import (
    QCheckBox,
    QGridLayout,
    QHBoxLayout,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ....analysis._utils import project_to_display, project_to_raw
from ....analysis.fcs_io import get_channel_marker_label
from ....analysis.gating import GateNode
from ....analysis.sample_lens.edges import gate_axes, gate_extent
from ....analysis.scaling import AxisScale, fit_scale
from ...graph.flow_canvas import DisplayMode, FlowCanvas
from ._style import card

if TYPE_CHECKING:
    import pandas as pd

    from ....analysis.experiment import Sample
    from ....analysis.gating import Gate
    from ....analysis.state import FlowState
    from .lens_model import Proposal

PLOT_H = 290
PLOT_W_MIN, PLOT_W_MAX = 250, 340  # plots share the strip's width within these
FOCUS_W_MAX = 900  # in focus mode plots grow to fill the width, up to this
ASPECT = PLOT_H / PLOT_W_MAX  # height per width, kept when focus mode grows a plot
MAX_COLUMNS = 8  # "plots per row"; 0 means all in one row
CAPTION_H = 30  # a plot's caption row, above its canvas
PLOT_SPACING = 12
# Room for tick labels and axis titles on a small plot (figure fractions).
PLOT_MARGINS = {"left": 0.21, "bottom": 0.17, "right": 0.96, "top": 0.95}
VIEW_PAD = 0.04  # share of the display range kept clear around a gate
RETRY_MS = 300  # wait this long to redraw when a gate is being dragged
RESIZE_GAP_MS = 15  # between resizing one plot and the next, so each paints on its own
LOADING_TEXT = "Loading plot…"


SCATTER = ("SSC-A", "FSC-A")  # what a 1-D gate can be plotted against as a dot plot
VIEWS_2D = {
    "pseudocolor": DisplayMode.PSEUDOCOLOR,
    "dot": DisplayMode.DOT_PLOT,
    "contour": DisplayMode.CONTOUR,
}
VIEW_LABELS = {"pseudocolor": "Pseudocolor", "dot": "Dot plot", "contour": "Contour"}
HISTOGRAM = "histogram"
NO_HISTOGRAM = (
    "A 2-D gate can't be drawn on a histogram: one axis would drop half of what it selects."
)


def view_options(gate: Gate, channels: pd.Index) -> list[tuple[str, str, bool]]:
    """(key, label, enabled) for each way this gate's plot can be shown.

    A 1-D (range) gate keeps its meaning on any plot with its channel on X:
    histogram, or a dot plot against a scatter channel. A 2-D gate needs both
    of its axes, so it gets the 2-D modes and a disabled histogram.
    """
    axes = gate_axes(gate)
    if len(axes) == 1:
        return [(HISTOGRAM, "Histogram", True)] + [
            (f"vs:{ch}", f"Dot plot vs {ch}", True)
            for ch in SCATTER
            if ch in channels and ch != axes[0][0]
        ]
    return [(key, VIEW_LABELS[key], True) for key in VIEWS_2D] + [(HISTOGRAM, "Histogram", False)]


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
    kept: bool | None = None  # a proposal step: ticked or not (None: no tick box)


def gate_path(node: GateNode) -> list[GateNode]:
    """The gated nodes from the root down to ``node`` (logic nodes have no plot)."""
    path: list[GateNode] = []
    current: GateNode | None = node
    while current is not None and not current.is_root:
        if current.gate is not None:
            path.append(current)
        current = current.parents[0] if current.parents else None
    return path[::-1]


def _digest(*arrays: np.ndarray) -> str:
    h = hashlib.blake2b(digest_size=16)
    for array in arrays:
        h.update(np.ascontiguousarray(array).tobytes())
    return h.hexdigest()


def _gates_key(gates: list[Gate], nodes: list[GateNode]) -> tuple:
    """What the gate overlays show: each gate's shape and each node's name."""
    return (
        tuple(json.dumps(g.to_dict(), sort_keys=True, default=str) for g in gates),
        tuple((n.node_id, n.name) for n in nodes),
    )


def _scale_key(scale: AxisScale) -> tuple:
    return (
        scale.transform_type,
        scale.min_val,
        scale.max_val,
        scale.logicle_t,
        scale.logicle_w,
        scale.logicle_a,
    )


def _widen(scale: AxisScale, lo: float, hi: float) -> tuple[float, float]:
    """``scale``'s range, widened in display space to hold ``lo``..``hi`` with a margin."""
    assert scale.min_val is not None and scale.max_val is not None
    d_min, d_max, d_lo, d_hi = project_to_display(
        np.array([scale.min_val, scale.max_val, lo, hi], dtype=np.float64), scale
    )
    pad = VIEW_PAD * (d_max - d_min)
    raw = project_to_raw(np.array([min(d_min, d_lo - pad), max(d_max, d_hi + pad)]), scale)
    return float(raw[0]), float(raw[1])


class _PathPlot(QWidget):
    """One step of the path: a caption over a canvas."""

    def __init__(self, state: FlowState, controller: Any) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(6)
        self.toggle = QCheckBox()
        self.toggle.setObjectName("SampleLensStepToggle")
        self.toggle.setToolTip("Untick to leave this gate out of the proposal")
        self.toggle.hide()
        top.addWidget(self.toggle)
        self.caption = BioCaptionLabel("")
        top.addWidget(self.caption, 1)
        self.view = BioComboBox()
        self.view.setObjectName("SampleLensPlotView")
        self.view.setToolTip("How to show this plot. Gates stay editable in every view.")
        top.addWidget(self.view)
        layout.addLayout(top)
        self.canvas = FlowCanvas(state=state, controller=controller)
        self.canvas.setFixedSize(PLOT_W_MAX, PLOT_H)
        self.canvas.set_margins(**PLOT_MARGINS)
        self.canvas.set_wheel_zoom(False)  # the wheel scrolls the strip
        self.canvas.set_compact_ticks(True)
        # Clicking a sibling gate makes it editable on this plot alone; the
        # app-wide selection would take every other plot's handles.
        self.canvas.set_local_selection(True)
        self.canvas.set_loading_text(LOADING_TEXT)
        layout.addWidget(self.canvas)
        self.target: tuple[int, int] | None = None  # a size waiting its turn (see _resize_next)
        self.drawn: tuple | None = None  # what the canvas last drew, to skip repeats
        self.gates_drawn: tuple | None = None  # the same, for the gates drawn over it
        # Whose gate this plot shows, to keep a click's selection across redraws.
        self.step_key: tuple | None = None
        self.options: list[tuple[str, str, bool]] = []  # the view combo's items
        self.last: tuple | None = None  # (sample, sample events, step): to redraw on a view change

    def show_options(self, options: list[tuple[str, str, bool]], current: str) -> None:
        """Fill the view combo (only when the options change) and show ``current``."""
        self.view.blockSignals(True)
        if options != self.options:
            self.options = options
            self.view.clear()
            model = self.view.model()
            assert isinstance(model, QStandardItemModel)  # QComboBox's own
            for i, (key, label, enabled) in enumerate(options):
                self.view.addItem(label, key)
                if not enabled:
                    item = model.item(i)
                    item.setEnabled(False)
                    item.setToolTip(NO_HISTOGRAM)
        self.view.setCurrentIndex(max(0, self.view.findData(current)))
        self.view.blockSignals(False)

    def needs_size(self, width: int, height: int) -> bool:
        return (self.canvas.width(), self.canvas.height()) != (width, height)

    def set_size(self, width: int, height: int) -> None:
        self.target = None
        if self.needs_size(width, height):
            self.canvas.setFixedSize(width, height)


class GatingPathStrip(QWidget):
    """A horizontal strip of the selected population's gating path."""

    step_toggled = Signal(int, bool)  # a proposal step ticked or unticked
    focus_changed = Signal(bool)  # focus mode: the plots get the whole tab

    def __init__(self, state: FlowState, controller: Any, axis_manager: Any) -> None:
        super().__init__()
        self._state = state
        self._controller = controller
        self._axis_manager = axis_manager
        self._plots: list[_PathPlot] = []
        self._ranges: dict[tuple[str, str], tuple[float, float]] = {}  # (gate id, channel)
        self._range_owner: tuple | None = None  # whose path the cached ranges belong to
        self._pending: tuple | None = None  # a redraw put off while a gate is dragged
        self._views: dict[str, str] = {}  # gate id -> chosen view, kept across selections
        self._focus = False
        self._resizing = False  # a _resize_next is scheduled

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)
        outer.addLayout(self._build_header())
        self._hint = BioCaptionLabel("")
        outer.addWidget(self._hint)

        frame = card("lens_path_card", "BG_DARKEST")
        frame_layout = QVBoxLayout(frame)
        frame_layout.setContentsMargins(8, 8, 8, 8)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll.setStyleSheet("background: transparent;")
        grid_widget = QWidget()
        self._grid = QGridLayout(grid_widget)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(PLOT_SPACING)
        self._grid.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self._scroll.setWidget(grid_widget)
        frame_layout.addWidget(self._scroll)
        outer.addWidget(frame, 1)
        self._apply_height()

    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        self._title = SubtitleLabel("Gating path")
        row.addWidget(self._title)
        row.addStretch()
        row.addWidget(BioCaptionLabel("Plots per row:"))
        self._columns = BioSpinBox()
        self._columns.setObjectName("SampleLensColumnsSpin")
        self._columns.setRange(0, MAX_COLUMNS)
        self._columns.setSpecialValueText("All")  # 0: every plot in one row
        self._columns.setToolTip("How many plots per row. 'All' keeps the path on one row.")
        self._columns.valueChanged.connect(lambda _v: self._relayout())
        row.addWidget(self._columns)
        self._focus_btn = SecondaryButton("Focus")
        self._focus_btn.setObjectName("SampleLensFocusButton")
        self._focus_btn.setCheckable(True)
        self._focus_btn.setToolTip(
            "Give the plots the whole tab: hides the sidebar, the maps and Across samples "
            "(Esc to leave)."
        )
        self._focus_btn.toggled.connect(self.set_focus)
        row.addWidget(self._focus_btn)
        return row

    # ── Layout ─────────────────────────────────────────────────────────

    @property
    def focused(self) -> bool:
        return self._focus

    def set_focus(self, on: bool) -> None:
        """Focus mode: plots fill the width (and grow) and the strip takes the tab's height."""
        if on == self._focus:
            return
        self._focus = on
        self._focus_btn.blockSignals(True)
        self._focus_btn.setChecked(on)
        self._focus_btn.setText("Exit focus" if on else "Focus")
        self._focus_btn.blockSignals(False)
        self._apply_height()
        self.focus_changed.emit(on)
        self._relayout()

    def set_columns(self, columns: int) -> None:
        self._columns.setValue(columns)

    def _apply_height(self) -> None:
        if self._focus:  # take whatever the tab gives; scroll inside
            self._scroll.setMinimumHeight(0)
            self._scroll.setMaximumHeight(16_777_215)
            self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        else:  # one row's height; more rows scroll
            self._scroll.setFixedHeight(PLOT_H + CAPTION_H + 18)
            policy = (
                Qt.ScrollBarPolicy.ScrollBarAsNeeded
                if self._columns.value()
                else Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            )
            self._scroll.setVerticalScrollBarPolicy(policy)

    def resizeEvent(self, event: Any) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self._fit_sizes()

    def _shown(self) -> list[_PathPlot]:
        return [p for p in self._plots if not p.isHidden()]

    def _per_row(self, count: int) -> int:
        return min(self._columns.value() or count, count) or 1

    def _relayout(self) -> None:
        """Place the shown plots in rows of ``Plots per row``, then size them."""
        per_row = self._per_row(len(self._shown()))
        for i, plot in enumerate(self._plots):
            self._grid.addWidget(plot, i // per_row, i % per_row)  # re-adding moves it
        self._apply_height()
        self._fit_sizes()

    def _fit_sizes(self) -> None:
        """Share the width between a row's plots; scroll only past PLOT_W_MIN each.

        Outside focus mode plots keep the strip's height (PLOT_H) and stop at
        PLOT_W_MAX; in focus mode they grow, keeping their shape.
        """
        shown = self._shown()
        if not shown:
            return
        per_row = self._per_row(len(shown))
        scrollbar = self._scroll.verticalScrollBar().sizeHint().width()
        free = self._scroll.viewport().width() - scrollbar - PLOT_SPACING * (per_row - 1)
        widest = FOCUS_W_MAX if self._focus else PLOT_W_MAX
        width = max(PLOT_W_MIN, min(widest, free // per_row))
        height = round(width * ASPECT) if self._focus else PLOT_H
        for plot in shown:
            if plot.needs_size(width, height):
                plot.target = (width, height)
                plot.canvas.set_loading(True)
            else:
                plot.target = None
        if not self._resizing and any(p.target for p in shown):
            self._resizing = True
            QTimer.singleShot(0, self._resize_next)

    def _resize_next(self) -> None:
        """Resize one waiting plot, then come back for the next.

        A resized plot redraws all its points (~0.15 s); resizing them all at
        once froze the tab for the whole batch with nothing painted. One per
        turn of the event loop shows each as it's ready, the rest keep their
        "Loading plot…" pill until their turn.
        """
        plot = next((p for p in self._shown() if p.target), None)
        if plot is None:
            self._resizing = False
            return
        assert plot.target is not None
        plot.set_size(*plot.target)
        plot.canvas.set_loading(False)
        QTimer.singleShot(RESIZE_GAP_MS, self._resize_next)

    def _plot(self, i: int) -> _PathPlot:
        while len(self._plots) <= i:  # canvases are reused, never rebuilt per selection
            plot = _PathPlot(self._state, self._controller)
            index = len(self._plots)
            plot.toggle.toggled.connect(lambda on, i=index: self.step_toggled.emit(i, on))
            plot.view.currentIndexChanged.connect(lambda _i, i=index: self._on_view_chosen(i))
            self._plots.append(plot)
            self._relayout()
        return self._plots[i]

    def _on_view_chosen(self, index: int) -> None:
        plot = self._plots[index]
        if plot.last is None:
            return
        sample, sample_events, step = plot.last
        self._views[step.gate.gate_id] = plot.view.currentData()
        self._draw(plot, sample, sample_events, step)

    def forget_drawn(self) -> None:
        """Make the next show redraw every plot (a theme change, say)."""
        for plot in self._plots:
            plot.drawn = plot.gates_drawn = None

    # ── Showing a path ─────────────────────────────────────────────────

    def show_steps(
        self,
        title: str,
        hint: str,
        sample: Sample,
        sample_events: pd.DataFrame,
        steps: list[PlotStep],
    ) -> None:
        """Show one plot per step (extra canvases are hidden, never destroyed)."""
        if any(p.canvas.is_interacting for p in self._plots if not p.isHidden()):
            # Redrawing now would pull the gate from under the mouse: retry after the drag.
            first_wait = self._pending is None
            self._pending = (title, hint, sample, sample_events, steps)
            if first_wait:
                QTimer.singleShot(RETRY_MS, self._show_pending)
            return
        self._pending = None
        self._title.setText(title)
        self._hint.setText(hint)
        for plot in self._plots[len(steps) :]:
            plot.hide()
        for i, step in enumerate(steps):
            plot = self._plot(i)
            plot.show()
            self._draw(plot, sample, sample_events, step)
        self._relayout()

    def _show_pending(self) -> None:
        if self._pending is not None:
            pending, self._pending = self._pending, None
            self.show_steps(*pending)

    def show_population(
        self, sample: Sample | None, events: pd.DataFrame | None, node: GateNode | None, color: str
    ) -> None:
        """``node``'s gating path, ``node`` backgated on every step."""
        path = gate_path(node) if node is not None else []
        if sample is None or events is None or node is None or not path:
            for plot in self._plots:
                plot.hide()
            self._title.setText("Gating path")
            self._hint.setText("Pick a population on the left to see every gate above it.")
            return
        self._own_ranges((sample.sample_id, node.node_id))
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
            events,
            steps,
        )

    def show_proposal(
        self, sample: Sample, sample_events: pd.DataFrame, proposal: Proposal, color: str
    ) -> None:
        """Each proposed gate on the events left by the ones before it, cluster highlighted."""
        self._own_ranges((sample.sample_id, "proposal", proposal.clusters))
        steps = []
        for i, (proposed, (before, scores)) in enumerate(
            zip(proposal.steps, proposal.walk(), strict=True)
        ):
            preview = GateNode(gate=proposed.gate, name=f"Step {i + 1}")
            steps.append(
                PlotStep(
                    caption=f"Step {i + 1} · "
                    + (f"F1 {scores[0]:.2f}" if scores is not None else "left out"),
                    events=proposal.events.loc[before],
                    gate=proposed.gate,
                    backgate=proposal.target[before],
                    color=color,
                    gates=[proposed.gate],
                    nodes=[preview],
                    kept=scores is not None,
                )
            )
        self.show_steps(
            f"Proposed gates · {proposal.label}",
            "The cluster is highlighted; each step keeps only the events inside the ticked steps "
            "before it. Untick a step to leave its gate out. Nothing changes until you add them.",
            sample,
            sample_events,
            steps,
        )

    # ── Drawing ────────────────────────────────────────────────────────

    def _own_ranges(self, owner: tuple) -> None:
        """Keep plot ranges while the same path is shown; start afresh for another."""
        if owner != self._range_owner:
            self._range_owner = owner
            self._ranges.clear()

    def _scale(
        self, sample: Sample, sample_events: pd.DataFrame, step: PlotStep, channel: str
    ) -> AxisScale:
        """As the Gating tab scales it, widened to hold the gate (range kept while shown)."""
        scale = fit_scale(
            self._axis_manager.get_scale(channel, sample.sample_id),
            channel,
            sample_events,
            step.events,
        )
        if scale.min_val is None or scale.max_val is None:
            return scale
        key = (step.gate.gate_id, channel)
        if key not in self._ranges:
            lo, hi = gate_extent(step.gate).get(channel, (scale.min_val, scale.max_val))
            self._ranges[key] = _widen(scale, lo, hi)
        scale.min_val, scale.max_val = self._ranges[key]
        return scale

    def _draw(
        self, plot: _PathPlot, sample: Sample, sample_events: pd.DataFrame, step: PlotStep
    ) -> None:
        plot.last = (sample, sample_events, step)
        options = view_options(step.gate, step.events.columns)
        usable = [key for key, _, enabled in options if enabled]
        view = self._views.get(step.gate.gate_id, usable[0])
        view = view if view in usable else usable[0]
        plot.show_options(options, view)
        params = [param for param, _ in gate_axes(step.gate)]
        x = params[0]
        if len(params) > 1:
            y, mode = params[1], VIEWS_2D[view]
        elif view.startswith("vs:"):
            y, mode = view[3:], DisplayMode.PSEUDOCOLOR
        else:
            y, mode = x, DisplayMode.HISTOGRAM
        x_scale = self._scale(sample, sample_events, step, x)
        y_scale = self._scale(sample, sample_events, step, y)
        plot.caption.setText(step.caption)
        canvas = plot.canvas

        drawn = (
            sample.sample_id,
            x,
            y,
            _scale_key(x_scale),
            _scale_key(y_scale),
            step.color,
            mode,
            _digest(step.events.index.to_numpy(), np.packbits(step.backgate)),
        )
        if drawn != plot.drawn:  # parent events, highlight or axes changed
            plot.drawn = drawn
            fcs = sample.fcs_data
            canvas.begin_update()
            canvas.set_sample_id(sample.sample_id)
            canvas.set_display_mode(mode)
            canvas.set_axes(
                x,
                y,
                get_channel_marker_label(fcs, x) if fcs else x,
                get_channel_marker_label(fcs, y) if fcs else y,
            )
            canvas.set_scales(x_scale, y_scale)
            canvas.set_backgate(step.backgate, step.color)
            canvas.set_data(step.events)
            canvas.end_update()  # one redraw with axes, scales, data and backgate together
        gates_key = (drawn, _gates_key(step.gates, step.nodes))
        if gates_key != plot.gates_drawn:  # each set_gates redraws the whole figure
            plot.gates_drawn = gates_key
            canvas.set_gates(step.gates, step.nodes)
        plot.toggle.setVisible(step.kept is not None)
        if step.kept is not None:
            plot.toggle.blockSignals(True)  # showing the state isn't a toggle
            plot.toggle.setChecked(step.kept)
            plot.toggle.blockSignals(False)
        # Select the step's own gate, unless a click picked another gate of this
        # same step (kept across the redraw an edit causes).
        step_key = (sample.sample_id, step.gate.gate_id, step.selected_node_id)
        shown = {node.node_id for node in step.nodes}
        if step_key != plot.step_key or canvas._selected_gate_id not in shown:
            plot.step_key = step_key
            canvas.select_gate(step.selected_node_id)
