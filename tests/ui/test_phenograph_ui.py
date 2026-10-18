"""PhenoGraph in the Population Analysis tab: settings, a run, its cluster graph, re-clustering."""

from unittest.mock import MagicMock

import pytest

from karcytics_plugins.flow_cytometry.analysis import phenograph_analysis
from karcytics_plugins.flow_cytometry.analysis.phenograph_analysis import (
    PhenographAnalysis,
    PhenographReclusterAnalysis,
)
from karcytics_plugins.flow_cytometry.analysis.services.umap_service import UmapService
from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.ui.widgets.cluster_results_panel import ClusterResultsPanel
from karcytics_plugins.flow_cytometry.ui.widgets.population_analysis_viewer import (
    PopulationAnalysisViewer,
)
from tests.fixtures.lens import make_sample
from tests.fixtures.phenograph import in_process_compute

MARKERS = ["CD3", "CD4", "CD8", "CD56"]


class SyncPhenographService(UmapService):
    """Runs PhenoGraph on the calling thread (and in-process), so the test sees the result."""

    def run_phenograph(self, params, on_done, on_error_cb, on_progress=None):
        self.params = params
        analysis = PhenographAnalysis()
        for name, value in vars(params).items():
            setattr(analysis, name, value)
        on_done(analysis.run(self._state))

    def recluster_phenograph(self, run, resolution, on_done, on_error_cb):
        self.reclustered = resolution
        on_done(PhenographReclusterAnalysis(run, resolution).run())


@pytest.fixture
def viewer(qtbot, monkeypatch):
    # Gallery tiles render on worker threads; not what these tests are about.
    monkeypatch.setattr(ClusterResultsPanel, "_request_gallery_tile", lambda *_a, **_k: None)
    monkeypatch.setattr(phenograph_analysis, "compute", in_process_compute)
    state = FlowState()
    sample, _events, _truth = make_sample("s1", n=3000)
    state.data.experiment.add_sample(sample)
    widget = PopulationAnalysisViewer(state, SyncPhenographService(state, MagicMock()))
    qtbot.addWidget(widget)
    return widget


def choose_phenograph(viewer):
    viewer._algo_combo.setCurrentIndex(viewer._algo_combo.findData("phenograph"))


def run_phenograph(viewer, resolution=0.1):
    choose_phenograph(viewer)
    viewer._phenograph_params._spins["resolution"].setValue(resolution)
    for i in range(viewer._channel_list.count()):
        item = viewer._channel_list.item(i)
        item.setCheckState(
            item.checkState().Checked if item.text() in MARKERS else item.checkState().Unchecked
        )
    viewer._run_name_input.setText("Third opinion")
    viewer.start_analysis()


@pytest.mark.ui
def test_choosing_phenograph_shows_its_settings_and_uses_every_event(viewer):
    choose_phenograph(viewer)
    assert viewer._phenograph_params.isVisibleTo(viewer)
    assert not viewer._umap_params.isVisibleTo(viewer)
    assert not viewer._flowsom_params.isVisibleTo(viewer)
    assert viewer._n_events_slider.value() == 100  # noqa: PLR2004
    values = viewer._phenograph_params.values()
    assert values == {"n_neighbors": 30, "resolution": 1.0, "min_cluster_size": 10}


@pytest.mark.ui
def test_a_run_is_stored_and_opens_on_its_cluster_graph(viewer):
    run_phenograph(viewer)
    params = viewer._umap_service.params
    assert params.resolution == 0.1  # noqa: PLR2004
    assert params.n_neighbors == 30  # noqa: PLR2004

    runs = viewer._state.data.umap_results["s1::root"]
    assert len(runs) == 1 and runs[0]["method"] == "phenograph"
    panel = viewer._results_panel
    assert panel._tabs.tabText(0) == "Cluster Graph"
    graph = panel._graph_view
    n_clusters = int(runs[0]["clusters"].max()) + 1
    assert graph._legend.count() == n_clusters
    assert "PhenoGraph res=0.1" in viewer._history_combo.currentText()


@pytest.mark.ui
def test_a_new_resolution_reclusters_and_refreshes_everything(viewer):
    run_phenograph(viewer)
    panel = viewer._results_panel
    run = viewer._state.data.umap_results["s1::root"][0]
    before = int(run["clusters"].max()) + 1

    panel._graph_view._recut_spin.setValue(2.0)
    panel._graph_view._recut_timer.timeout.emit()

    assert viewer._umap_service.reclustered == 2.0  # noqa: PLR2004
    assert run["resolution"] == 2.0  # noqa: PLR2004
    after = int(run["clusters"].max()) + 1
    assert after > before
    assert panel._graph_view._legend.count() == after
    assert len(panel._graph_view._counts) == after
    assert panel._graph_view._busy_lbl.text() == ""
    assert panel._graph_view._recut_spin.isEnabled()
    assert "res=2.0" in viewer._history_combo.currentText()


@pytest.mark.ui
def test_a_failed_recluster_says_so_and_keeps_the_run(viewer):
    run_phenograph(viewer)
    panel = viewer._results_panel
    run = viewer._state.data.umap_results["s1::root"][0]
    clusters = run["clusters"].copy()
    panel.apply_recluster({"error": "daemon gone"})
    assert "daemon gone" in panel._graph_view._busy_lbl.text()
    assert (run["clusters"] == clusters).all()


@pytest.mark.ui
def test_past_phenograph_runs_show_their_own_settings_not_umaps(viewer):
    run_phenograph(viewer)
    umap_neighbours = viewer._n_neigh_slider.value()
    viewer._history_combo.setCurrentIndex(1)
    assert viewer._phenograph_params._spins["resolution"].value() == 0.1  # noqa: PLR2004
    assert viewer._n_neigh_slider.value() == umap_neighbours  # PhenoGraph's 30 isn't UMAP's


@pytest.mark.ui
def test_a_cluster_with_no_links_stands_apart_in_the_legend(viewer):
    run_phenograph(viewer, resolution=0.1)  # the planted cell types: separate islands
    graph = viewer._results_panel._graph_view
    apart = [c for c in range(len(graph._counts)) if graph.stands_apart(c)]
    assert apart
    texts = [graph._legend.item(i).text() for i in range(graph._legend.count())]
    assert any("stands apart" in t for t in texts)
    assert "standing apart" in graph._title()
