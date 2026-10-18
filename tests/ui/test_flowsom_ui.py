"""FlowSOM in the Population Analysis tab: settings, a run, its tree, and re-cutting k."""

from unittest.mock import MagicMock

import pytest

from karcytics_plugins.flow_cytometry.analysis.flowsom_analysis import FlowsomAnalysis
from karcytics_plugins.flow_cytometry.analysis.services.umap_service import UmapService
from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.ui.widgets.cluster_results_panel import ClusterResultsPanel
from karcytics_plugins.flow_cytometry.ui.widgets.population_analysis_viewer import (
    PopulationAnalysisViewer,
)
from tests.fixtures.lens import make_sample

MARKERS = ["CD3", "CD4", "CD8", "CD56"]


class SyncFlowsomService(UmapService):
    """Runs FlowSOM on the calling thread, so the test sees the finished run."""

    def run_flowsom(self, params, on_done, on_error_cb, on_progress=None):
        self.params = params
        analysis = FlowsomAnalysis()
        for name, value in vars(params).items():
            setattr(analysis, name, value)
        on_done(analysis.run(self._state))


@pytest.fixture
def viewer(qtbot, monkeypatch):
    # Gallery tiles render on worker threads; not what these tests are about.
    monkeypatch.setattr(ClusterResultsPanel, "_request_gallery_tile", lambda *_a, **_k: None)
    state = FlowState()
    sample, _events, _truth = make_sample("s1", n=3000)
    state.data.experiment.add_sample(sample)
    widget = PopulationAnalysisViewer(state, SyncFlowsomService(state, MagicMock()))
    qtbot.addWidget(widget)
    return widget


def choose_flowsom(viewer):
    viewer._algo_combo.setCurrentIndex(viewer._algo_combo.findData("flowsom"))


def run_flowsom(viewer, k=5):
    choose_flowsom(viewer)
    viewer._flowsom_params._spins["k"].setValue(k)
    for i in range(viewer._channel_list.count()):
        item = viewer._channel_list.item(i)
        item.setCheckState(
            item.checkState().Checked if item.text() in MARKERS else item.checkState().Unchecked
        )
    viewer._run_name_input.setText("Second opinion")
    viewer.start_analysis()


@pytest.mark.ui
def test_choosing_flowsom_shows_its_settings_and_uses_every_event(viewer):
    choose_flowsom(viewer)
    assert viewer._flowsom_params.isVisibleTo(viewer)
    assert not viewer._umap_params.isVisibleTo(viewer)
    assert viewer._n_events_slider.value() == 100  # noqa: PLR2004
    assert "3,000 events" in viewer._n_events_title_lbl.text()

    viewer._algo_combo.setCurrentIndex(viewer._algo_combo.findData("umap_hdbscan"))
    assert viewer._umap_params.isVisibleTo(viewer)
    assert viewer._n_events_slider.value() == 10  # noqa: PLR2004


@pytest.mark.ui
def test_the_slider_can_lower_the_events_to_compare_with_umap(viewer):
    choose_flowsom(viewer)
    viewer._n_events_slider.setValue(25)
    run_flowsom(viewer)
    assert viewer._umap_service.params.n_events == 750  # noqa: PLR2004


@pytest.mark.ui
def test_a_run_is_stored_and_opens_on_its_tree(viewer):
    run_flowsom(viewer)

    runs = viewer._state.data.umap_results["s1::root"]
    assert runs[-1]["method"] == "flowsom"
    assert runs[-1]["n_events"] == 3000  # noqa: PLR2004
    assert "FlowSOM k=5" in viewer._history_combo.currentText()
    panel = viewer._results_panel
    assert panel._tabs.tabText(0) == "FlowSOM Tree"
    assert panel._tree_view._legend.count() == 5  # noqa: PLR2004
    assert not viewer._replay_anim_btn.isVisibleTo(viewer)


@pytest.mark.ui
def test_changing_k_recuts_the_tree_and_the_statistics(viewer):
    run_flowsom(viewer, k=5)
    panel = viewer._results_panel

    panel._tree_view._k_spin.setValue(3)
    panel._tree_view._recut_timer.timeout.emit()

    run = viewer._state.data.umap_results["s1::root"][-1]
    assert run["k"] == 3  # noqa: PLR2004
    assert len(run["cluster_stats"]["data"]) == 3  # noqa: PLR2004
    assert panel._tree_view._legend.count() == 3  # noqa: PLR2004
    assert [panel._tabs.tabText(i) for i in range(panel._tabs.count())] == [
        "FlowSOM Tree",
        "Plot Gallery",
        "Interactive Map",
        "Population Statistics",
    ]
    assert "Metacluster 0" in [e.text() for _c, e in panel._cluster_ui_elements.values()]


@pytest.mark.ui
def test_reopening_a_run_from_history_shows_flowsom_and_its_settings(viewer):
    run_flowsom(viewer, k=7)
    viewer._history_combo.setCurrentIndex(0)  # [ New Run ]
    viewer._algo_combo.setCurrentIndex(viewer._algo_combo.findData("umap_hdbscan"))

    viewer._history_combo.setCurrentIndex(1)

    assert viewer._algo_combo.currentData() == "flowsom"
    assert viewer._flowsom_params.values()["k"] == 7  # noqa: PLR2004
    assert not viewer._flowsom_params._spins["k"].isEnabled()


@pytest.mark.ui
def test_course_4_flowsom_checks_follow_the_learner(viewer):
    from karcytics_plugins.flow_cytometry.tutorials.validators import (
        ClusteringMethodValidator,
        FlowsomColorValidator,
        FlowsomKValidator,
        FlowsomResultsReadyValidator,
        NewRunSelectedValidator,
        metaclusters_positive_for,
    )

    state = viewer._state
    state.view._population_analysis_viewer = viewer
    assert NewRunSelectedValidator().validate(state)
    assert not ClusteringMethodValidator("flowsom").validate(state)
    assert not FlowsomResultsReadyValidator().validate(state)

    run_flowsom(viewer, k=5)
    assert ClusteringMethodValidator("flowsom").validate(state)
    assert FlowsomResultsReadyValidator().validate(state)
    assert not NewRunSelectedValidator().validate(state)  # the run is showing

    tree = viewer._results_panel._tree_view
    seen = []
    colour = FlowsomColorValidator("CD56", on_found=seen.append)
    assert not colour.validate(state)
    tree._color_combo.setCurrentIndex(tree._color_combo.findText("Marker: CD56"))
    assert colour.validate(state)
    assert seen == [tree]
    assert metaclusters_positive_for(tree, "CD56")  # NK and NKT cells

    assert not FlowsomKValidator(3).validate(state)
    tree._k_spin.setValue(3)
    tree._recut_timer.timeout.emit()
    assert FlowsomKValidator(3).validate(state)
    assert "k=3" in viewer._history_combo.currentText()
