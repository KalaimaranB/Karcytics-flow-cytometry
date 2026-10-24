"""With nothing selected, the properties panel (and its Group Preview) describe the plot."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from karcytics_plugins.flow_cytometry.ui.controllers.gating_controller import GatingController
from karcytics_plugins.flow_cytometry.ui.workspace_views import WorkspaceViews
from tests.fixtures.workspace import build_rich_state


def _controller(active_graph):
    views = {name: MagicMock() for name in WorkspaceViews.__dataclass_fields__}
    views["graph_manager"] = SimpleNamespace(get_active_graph=lambda: active_graph)
    gating_views = WorkspaceViews(**views)
    controller = GatingController(
        build_rich_state(), MagicMock(), gating_views, MagicMock(), MagicMock(), MagicMock()
    )
    return controller, gating_views


def _select(built, sample_id, node_id):
    controller, views = built
    controller.on_gate_selected_from_controller(sample_id, node_id)
    return views.properties_panel.show_sample_properties.call_args.args


def test_deselecting_on_a_gated_plot_keeps_that_population():
    panel = _controller(SimpleNamespace(sample_id="s0", node_id="lymph"))
    assert _select(panel, "s0", None) == ("s0", "lymph")


def test_deselecting_on_the_all_events_plot_shows_the_sample():
    panel = _controller(SimpleNamespace(sample_id="s0", node_id=None))
    assert _select(panel, "s0", None) == ("s0", None)


def test_a_plot_of_another_sample_is_ignored():
    panel = _controller(SimpleNamespace(sample_id="s1", node_id="lymph"))
    assert _select(panel, "s0", None) == ("s0", None)


def test_a_selected_gate_wins():
    panel = _controller(SimpleNamespace(sample_id="s0", node_id="lymph"))
    assert _select(panel, "s0", "cd4") == ("s0", "cd4")


def test_double_clicking_an_exported_clustering_reopens_its_run():
    state = build_rich_state()
    sample_id, sample = next(iter(state.data.experiment.samples.items()))
    umap_node = next(n for n in sample.gate_tree.iter_dag() if n.is_umap_parent)
    lymph_id = umap_node.parents[0].node_id
    state.data.umap_results[f"{sample_id}::{lymph_id}"] = [
        {"name": "first"},
        {"name": "exported", "exported_node_id": umap_node.node_id},
    ]
    views = WorkspaceViews(**{name: MagicMock() for name in WorkspaceViews.__dataclass_fields__})
    views.gate_hierarchy.active_sample_id = sample_id
    controller = GatingController(state, MagicMock(), views, MagicMock(), MagicMock(), MagicMock())

    controller.on_gate_double_clicked(umap_node.node_id)

    views.population_analysis_viewer.show_run.assert_called_once_with(sample_id, lymph_id, 1)
