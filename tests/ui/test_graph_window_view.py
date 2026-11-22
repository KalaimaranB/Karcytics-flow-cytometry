"""A graph window owns its plot's scales: zoom and auto-range requests, the full-quality render."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest
from karcytics_sdk.plugin import CentralEventBus
from karcytics_sdk.plugin.components import BioMenu
from PySide6.QtCore import QObject, QPoint

from karcytics_plugins.flow_cytometry.analysis import events
from karcytics_plugins.flow_cytometry.analysis.axis_manager import AxisManager
from karcytics_plugins.flow_cytometry.analysis.experiment import Sample
from karcytics_plugins.flow_cytometry.analysis.gating.rectangle import RectangleGate
from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.ui.graph.graph_window import GraphWindow
from karcytics_plugins.flow_cytometry.ui.services.bus_subscriptions import subscribe_while_alive

pytestmark = pytest.mark.ui


@pytest.fixture
def window(qtbot):
    state = FlowState()
    state.axis_manager = AxisManager(state)
    rng = np.random.default_rng(0)
    sample = Sample(sample_id="s", display_name="Sample S")
    sample.fcs_data = MagicMock()
    sample.fcs_data.channels = ["FSC-A", "SSC-A"]
    sample.fcs_data.markers = ["", ""]
    sample.fcs_data.events = pd.DataFrame(
        {"FSC-A": rng.uniform(1000, 200_000, 400), "SSC-A": rng.uniform(500, 100_000, 400)}
    )
    lymph = sample.gate_tree.add_child(RectangleGate("FSC-A", "SSC-A", x_min=5000), "Lymphocytes")
    state.data.experiment.samples["s"] = sample
    population = MagicMock()
    population.get_gated_events.return_value = sample.fcs_data.events
    win = GraphWindow(
        state,
        "s",
        node_id=lymph.node_id,
        axis_manager=state.axis_manager,
        population_service=population,
        controller=MagicMock(get_gates_for_display=MagicMock(return_value=([], []))),
    )
    qtbot.addWidget(win)
    win._axis_panel.set_current_x("FSC-A")
    win._axis_panel.set_current_y("SSC-A")
    win._do_axis_render()
    return win


@pytest.fixture
def range_events(qtbot):
    """AXIS_RANGE_CHANGED payloads published during the test."""
    received: list[dict] = []
    owner = QObject()
    subscribe_while_alive(owner, {events.AXIS_RANGE_CHANGED: received.append})
    yield received
    owner.deleteLater()


def _width(scale) -> float:
    return scale.max_val - scale.min_val


def test_a_wheel_zoom_narrows_the_windows_scales_and_says_so(window, range_events, qtbot):
    before = _width(window._x_scale)
    ax = window.canvas.ax
    centre = sum(ax.get_xlim()) / 2, sum(ax.get_ylim()) / 2

    window.canvas._zoom_handler.handle_scroll(
        SimpleNamespace(inaxes=ax, button="up", xdata=centre[0], ydata=centre[1])
    )

    assert _width(window._x_scale) < before
    assert window.canvas.x_scale.max_val == window._x_scale.max_val
    qtbot.waitUntil(
        lambda: any(e["x_scale"].max_val == window._x_scale.max_val for e in range_events)
    )


def test_without_a_window_a_zoom_request_changes_nothing(qtbot):
    from karcytics_plugins.flow_cytometry.ui.graph.flow_canvas import FlowCanvas

    canvas = FlowCanvas(state=FlowState())
    qtbot.addWidget(canvas)
    canvas.set_axes("FSC-A", "SSC-A")
    before = (canvas.x_scale.min_val, canvas.x_scale.max_val)
    with qtbot.waitSignal(canvas.scale_edit_requested):
        canvas._zoom_handler.handle_scroll(
            SimpleNamespace(inaxes=canvas.ax, button="up", xdata=0.5, ydata=0.5)
        )

    assert (canvas.x_scale.min_val, canvas.x_scale.max_val) == before  # the owner decides


def test_the_f_key_fits_both_ranges_to_the_data(window):
    window._x_scale.max_val = 10.0  # far too narrow

    window.canvas._on_key_press(SimpleNamespace(key="f"))

    assert (window._x_scale.min_val, window._x_scale.max_val) == window._calculate_auto_range("x")
    assert window.canvas.x_scale.max_val == window._x_scale.max_val


def test_render_full_quality_opens_the_same_plot_with_every_event(window, monkeypatch):
    def choose(menu, *_args):
        next(a for a in menu.actions() if "Render Full Quality" in a.text()).trigger()

    monkeypatch.setattr(BioMenu, "exec", choose)
    window.canvas.customContextMenuRequested.emit(QPoint(5, 5))

    (render,) = window._render_windows
    assert render.isVisible()
    assert (render.canvas.x_param, render.canvas.y_param) == ("FSC-A", "SSC-A")
    assert render.canvas.x_scale.max_val == window._x_scale.max_val
    assert render.canvas._max_events is None  # no subsampling
    assert render.windowTitle() == "Full Render — Sample S"
    render.close()


def test_the_breadcrumb_shows_the_gating_path(window):
    window.refresh_breadcrumb()

    assert window._toolbar._breadcrumb.text().endswith("Sample S  ›  ⊳ Lymphocytes")


def test_a_subscription_ends_with_its_owner(qtbot):
    received: list = []
    owner = QObject()
    subscribe_while_alive(owner, {"test.topic": received.append})
    CentralEventBus.publish("test.topic", 1)
    qtbot.waitUntil(lambda: received == [1])

    owner.deleteLater()
    qtbot.waitUntil(lambda: not _alive(owner))
    CentralEventBus.publish("test.topic", 2)
    qtbot.wait(50)

    assert received == [1]


def _alive(obj) -> bool:
    import shiboken6

    return shiboken6.isValid(obj)
