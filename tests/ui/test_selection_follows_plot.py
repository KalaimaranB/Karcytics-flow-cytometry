"""With nothing selected, the properties panel (and its Group Preview) describe the plot."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from karcytics_plugins.flow_cytometry.ui.main_panel import FlowCytometryPanel
from tests.fixtures.workspace import build_rich_state


def _panel(active_graph):
    state = build_rich_state()
    return SimpleNamespace(
        state=state,
        _gate_hierarchy=MagicMock(),
        _properties_panel=MagicMock(),
        _graph_manager=SimpleNamespace(get_active_graph=lambda: active_graph),
        status_message=MagicMock(),
    )


def _select(panel, sample_id, node_id):
    FlowCytometryPanel._on_gate_selected_from_controller(panel, sample_id, node_id)
    return panel._properties_panel.show_sample_properties.call_args.args


def test_deselecting_on_a_gated_plot_keeps_that_population():
    panel = _panel(SimpleNamespace(sample_id="s0", node_id="lymph"))
    assert _select(panel, "s0", None) == ("s0", "lymph")


def test_deselecting_on_the_all_events_plot_shows_the_sample():
    panel = _panel(SimpleNamespace(sample_id="s0", node_id=None))
    assert _select(panel, "s0", None) == ("s0", None)


def test_a_plot_of_another_sample_is_ignored():
    panel = _panel(SimpleNamespace(sample_id="s1", node_id="lymph"))
    assert _select(panel, "s0", None) == ("s0", None)


def test_a_selected_gate_wins():
    panel = _panel(SimpleNamespace(sample_id="s0", node_id="lymph"))
    assert _select(panel, "s0", "cd4") == ("s0", "cd4")
