"""After undo/redo replaces the model, every view must re-resolve by id."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest
from PyQt6.QtWidgets import QApplication

from karcytics_plugins.flow_cytometry.analysis.gating import RectangleGate
from karcytics_plugins.flow_cytometry.analysis.population_service import PopulationService
from karcytics_plugins.flow_cytometry.analysis.store import FlowStore
from tests.fixtures.workspace import FakeBus, build_rich_state


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


@pytest.fixture
def env(qapp, qtbot):
    from karcytics_plugins.flow_cytometry.ui.graph.graph_manager import GraphManager

    state = build_rich_state()
    store = FlowStore(state, FakeBus().publish)
    store.reset()
    controller = MagicMock()
    controller.get_gates_for_display.return_value = ([], [])
    manager = GraphManager(state, None, MagicMock(), controller)
    qtbot.addWidget(manager)
    return state, store, manager, controller


def _undo(store):
    store.restore(store.history.undo())


def test_graph_on_a_gate_that_undo_removes_is_closed(env):
    state, store, manager, _ = env
    node = state.data.experiment.samples["s0"].gate_tree.add_child(
        RectangleGate("FSC-A", "SSC-A", x_min=0.0, x_max=9.0, y_min=0.0, y_max=9.0), name="New"
    )
    store.commit("Add Gate")
    manager.open_graph_for_sample("s0", node.node_id)
    manager.open_graph_for_sample("s0")
    assert manager.get_open_graph("s0", node.node_id) is not None

    _undo(store)
    manager.reconcile_with_state()
    assert manager.get_open_graph("s0", node.node_id) is None
    assert manager.get_open_graph("s0") is not None


def test_graph_on_a_sample_that_undo_removes_is_closed(env):
    state, store, manager, _ = env
    from karcytics_plugins.flow_cytometry.analysis.experiment import Sample
    from tests.fixtures.workspace import make_fcs

    state.data.experiment.add_sample(
        Sample(sample_id="s9", display_name="S9", fcs_data=make_fcs("s9"))
    )
    store.commit("Add Samples")
    manager.open_graph_for_sample("s9")
    _undo(store)
    manager.reconcile_with_state()
    assert manager.get_open_graph("s9") is None


def test_surviving_graphs_reload_their_gates_from_the_new_model(env):
    state, store, manager, controller = env
    lymph = state.data.experiment.samples["s0"].gate_tree.children[0]
    manager.open_graph_for_sample("s0", lymph.node_id)
    PopulationService(state).remove_population("s0", lymph.children[0].node_id)
    store.commit("Delete Gate")

    controller.get_gates_for_display.reset_mock()
    _undo(store)
    manager.reconcile_with_state()

    graph = manager.get_open_graph("s0", lymph.node_id)
    assert graph is not None
    controller.get_gates_for_display.assert_called_with("s0", lymph.node_id)


def test_undo_cancels_a_half_finished_gate_drag(env):
    _, _, manager, _ = env
    manager.open_graph_for_sample("s0")
    graph = manager.get_open_graph("s0")
    graph.canvas._fsm.cancel = MagicMock(wraps=graph.canvas._fsm.cancel)
    manager.cancel_active_drawing()
    graph.canvas._fsm.cancel.assert_called_once()


def test_panel_restore_handler_recomputes_stats_and_cancels_propagation(qapp, qtbot, monkeypatch):
    from karcytics_plugins.flow_cytometry.ui.main_panel import FlowCytometryPanel

    panel = FlowCytometryPanel(plugin_id="flow_restore_test")
    qtbot.addWidget(panel)
    rich = build_rich_state()
    panel.state.data.experiment = rich.data.experiment
    recompute = MagicMock()
    cancel = MagicMock()
    monkeypatch.setattr(panel._gate_controller, "recompute_all_stats", recompute)
    monkeypatch.setattr(panel._gate_propagator, "cancel_pending", cancel)

    panel._on_state_restored({})

    cancel.assert_called_once()
    assert sorted(c.args[0] for c in recompute.call_args_list) == ["s0", "s1", "s2"]
