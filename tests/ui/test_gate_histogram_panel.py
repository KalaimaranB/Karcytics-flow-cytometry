"""Tests for GateHistogramPanel — which gate it highlights, and when it renders."""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from PyQt6.QtCore import QTimer

from karcytics_plugins.flow_cytometry.analysis import events
from karcytics_plugins.flow_cytometry.analysis.constants import (
    GATE_DRAWING_COLOR,
    GATE_SELECTED_COLOR,
)
from karcytics_plugins.flow_cytometry.analysis.gating import QuadrantGate, RectangleGate
from karcytics_plugins.flow_cytometry.ui.widgets import gate_histogram_panel
from karcytics_plugins.flow_cytometry.ui.widgets.gate_histogram_panel import GateHistogramPanel

pytestmark = pytest.mark.ui

SAMPLE_ID = "test_sample_1"


class _FakeWorker:
    def __init__(self):
        self._finished_cbs = []
        self.finished = Mock()
        self.finished.connect = self._finished_cbs.append
        self.error = Mock()

    def emit_finished(self, results):
        for cb in list(self._finished_cbs):
            cb(results)


def _synchronous_scheduler():
    """Runs the compute stage inline; delivers the result on the next event-loop turn."""
    scheduler = Mock()

    def _submit(analyzer, state=None):
        worker = _FakeWorker()
        QTimer.singleShot(0, lambda: worker.emit_finished(analyzer.run(state)))
        return worker

    scheduler.submit.side_effect = _submit
    return scheduler


@pytest.fixture
def panel(qtbot, flow_state):
    flow_state.view.active_x_param = "FSC-A"
    flow_state.view.active_y_param = "SSC-A"
    widget = GateHistogramPanel(
        flow_state,
        flow_state.axis_manager,
        flow_state.population_service,
        task_scheduler=_synchronous_scheduler(),
    )
    qtbot.addWidget(widget)
    # Most tests drive _render() directly and inspect what each canvas is asked to draw.
    widget.isVisible = Mock(return_value=True)
    widget._x_canvas.show_histogram = Mock()
    widget._y_canvas.show_histogram = Mock()
    widget.set_context(SAMPLE_ID, None, None)
    return widget


def _rendered(panel):
    """Render now; return ((x_state, x_boundary), (y_state, y_boundary))."""
    panel._render()
    return (
        panel._x_canvas.show_histogram.call_args.args,
        panel._y_canvas.show_histogram.call_args.args,
    )


def _add_gate(flow_state, gate, name="Cells"):
    root = flow_state.data.experiment.samples[SAMPLE_ID].gate_tree
    return gate.create_nodes(root, name)[0]


def _rectangle():
    return RectangleGate("FSC-A", "SSC-A", x_min=10, x_max=20, y_min=1, y_max=2)


def test_at_rest_draws_plain_histograms_of_each_axis(panel):
    (x_state, x_boundary), (y_state, y_boundary) = _rendered(panel)

    assert (x_state.x_param, y_state.x_param) == ("FSC-A", "SSC-A")
    assert list(x_state.current_data.columns) == ["FSC-A", "SSC-A"]
    assert x_state.highlight_gate is None and y_state.highlight_gate is None
    assert x_boundary is None and y_boundary is None


def test_selected_child_gate_is_highlighted_as_a_copy(panel, flow_state):
    gate = _rectangle()
    node = _add_gate(flow_state, gate)
    panel.set_context(SAMPLE_ID, None, node.node_id)

    (x_state, x_boundary), (_y_state, y_boundary) = _rendered(panel)

    assert x_state.highlight_gate is not gate  # read on the compute thread
    assert x_state.highlight_gate.x_max == gate.x_max
    assert x_boundary == (10, 20, GATE_SELECTED_COLOR)
    assert y_boundary == (1, 2, GATE_SELECTED_COLOR)


def test_selected_node_that_is_the_displayed_population_is_not_highlighted(panel, flow_state):
    node = _add_gate(flow_state, _rectangle())
    panel.set_context(SAMPLE_ID, node.node_id, node.node_id)

    (x_state, x_boundary), _ = _rendered(panel)

    assert x_state.highlight_gate is None
    assert x_boundary is None


def test_gate_drawn_on_other_axes_is_not_highlighted(panel, flow_state):
    node = _add_gate(flow_state, RectangleGate("FITC-A", "APC-A", x_min=1, x_max=2))
    panel.set_context(SAMPLE_ID, None, node.node_id)

    (x_state, x_boundary), _ = _rendered(panel)

    assert x_state.highlight_gate is None
    assert x_boundary is None


def test_gate_being_drawn_takes_over_then_hands_back(panel, flow_state):
    node = _add_gate(flow_state, _rectangle())
    panel.set_context(SAMPLE_ID, None, node.node_id)

    drawing = RectangleGate("FSC-A", "SSC-A", x_min=30, x_max=40, y_min=3, y_max=4)
    panel._on_gate_preview({"gate": drawing})
    (x_state, x_boundary), _ = _rendered(panel)
    assert x_state.highlight_gate.x_min == 30
    assert x_boundary == (30, 40, GATE_DRAWING_COLOR)

    panel._on_gate_preview({"gate": None})  # committed or cancelled
    (x_state, x_boundary), _ = _rendered(panel)
    assert x_state.highlight_gate.x_min == 10
    assert x_boundary == (10, 20, GATE_SELECTED_COLOR)


def test_quadrant_shows_its_divider_but_no_overlay(panel):
    panel._on_gate_preview({"gate": QuadrantGate("FSC-A", "SSC-A", x_mid=100, y_mid=7)})

    (x_state, x_boundary), (_y_state, y_boundary) = _rendered(panel)

    assert x_state.highlight_gate is None  # a quadrant gate contains every event
    assert x_boundary == (100, 100, GATE_DRAWING_COLOR)
    assert y_boundary == (7, 7, GATE_DRAWING_COLOR)


def test_population_is_capped_and_reused_across_preview_frames(panel, flow_state):
    flow_state.view.render_config.pseudocolor.max_events = 100
    panel._population_service = Mock(wraps=flow_state.population_service)
    panel.refresh()

    (x_state, _), _ = _rendered(panel)
    assert len(x_state.current_data) == 100

    panel._on_gate_preview({"gate": _rectangle()})
    _rendered(panel)
    assert panel._population_service.get_gated_events.call_count == 1

    panel._on_model_changed({})  # e.g. an upstream gate moved
    _rendered(panel)
    assert panel._population_service.get_gated_events.call_count == 2


def test_no_sample_shows_a_placeholder_instead_of_the_plots(panel):
    assert panel._placeholder.isHidden()
    assert not panel._x_canvas.isHidden() and not panel._y_canvas.isHidden()

    panel._x_canvas.show_histogram.reset_mock()
    panel.set_context(None, None, None)
    panel._render()

    assert not panel._placeholder.isHidden()
    assert "Select a sample" in panel._placeholder.text()
    assert panel._x_canvas.isHidden() and panel._y_canvas.isHidden()
    panel._x_canvas.show_histogram.assert_not_called()


def test_hidden_panel_defers_rendering_until_shown(panel):
    panel.isVisible = Mock(return_value=False)
    panel._x_canvas.show_histogram.reset_mock()

    panel._render()

    panel._x_canvas.show_histogram.assert_not_called()
    assert panel._stale


def test_cleanup_unsubscribes_everything_and_silences_late_events(panel):
    bus = gate_histogram_panel.CentralEventBus
    bus.unsubscribe.reset_mock()

    panel.cleanup()
    panel.cleanup()  # idempotent

    unsubscribed = [call.args for call in bus.unsubscribe.call_args_list]
    assert unsubscribed == panel._subscriptions
    assert (events.GATE_PREVIEW, panel._subscriptions[0][1]) in unsubscribed

    # The bus delivers queued events after teardown; they must be no-ops.
    panel._x_canvas.show_histogram.reset_mock()
    panel._on_gate_preview({"gate": _rectangle()})
    panel._on_model_changed({})
    panel._render()
    assert not panel._refresh_timer.isActive()
    panel._x_canvas.show_histogram.assert_not_called()


def test_renders_the_gated_overlay_end_to_end(qtbot, flow_state):
    """The real pipeline: compute stage → histogram strategy → axes."""
    flow_state.view.active_x_param = "FSC-A"
    flow_state.view.active_y_param = "SSC-A"
    events_df = flow_state.data.experiment.samples[SAMPLE_ID].fcs_data.events
    gate = RectangleGate(
        "FSC-A",
        "SSC-A",
        x_min=events_df["FSC-A"].quantile(0.25),
        x_max=events_df["FSC-A"].quantile(0.75),
        y_min=events_df["SSC-A"].min(),
        y_max=events_df["SSC-A"].max(),
    )
    node = _add_gate(flow_state, gate)
    panel = GateHistogramPanel(
        flow_state,
        flow_state.axis_manager,
        flow_state.population_service,
        task_scheduler=_synchronous_scheduler(),
    )
    qtbot.addWidget(panel)
    panel.show()

    with qtbot.waitSignal(panel._x_canvas.data_layer_finished, timeout=3000):
        panel.set_context(SAMPLE_ID, None, node.node_id)

    ax = panel._x_canvas._ax
    assert ax.get_xlabel() == "FSC-A"
    # Population + gated subset (stepfilled polygons) and the gate's shaded span.
    assert len(ax.patches) >= 3
