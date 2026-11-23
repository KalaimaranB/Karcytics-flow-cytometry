"""A UMAP + HDBSCAN run from the Population Analysis tab: the settings reach the run,
the run is stored with them, and the finished run shows read-only in the history.
"""

from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QSlider

from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.analysis.umap_analysis import UmapAnalysis
from karcytics_plugins.flow_cytometry.ui.services.umap_service import UmapService
from karcytics_plugins.flow_cytometry.ui.widgets import population_analysis_viewer
from karcytics_plugins.flow_cytometry.ui.widgets.cluster_plot_gallery import ClusterPlotGallery
from karcytics_plugins.flow_cytometry.ui.widgets.population_analysis_viewer import (
    PopulationAnalysisViewer,
)
from tests.fixtures.daemon import in_process_daemon
from tests.fixtures.lens import make_sample


class SyncUmapService(UmapService):
    """Runs UMAP on the calling thread, so the test sees the finished run."""

    def run_analysis(self, params, on_done, on_error_cb, on_progress=None):
        self.params = params
        analysis = UmapAnalysis(self._daemon)
        for name, value in vars(params).items():
            setattr(analysis, name, value)
        on_done(analysis.run(self._state))


@pytest.fixture
def viewer(qtbot, monkeypatch):
    monkeypatch.setattr(ClusterPlotGallery, "_request_tile", lambda *_a, **_k: None)
    # The animation's own quick UMAP isn't under test: report it failed, so the run goes on.
    monkeypatch.setattr(
        population_analysis_viewer, "_prepare_animation", lambda *_a: {"success": False}
    )
    state = FlowState()
    sample, _events, _truth = make_sample("s1", n=3000)
    state.data.experiment.add_sample(sample)
    widget = PopulationAnalysisViewer(state, SyncUmapService(state, MagicMock(), in_process_daemon))
    qtbot.addWidget(widget)
    return widget


@pytest.mark.ui
def test_a_umap_run_uses_the_sidebar_settings_and_is_stored_with_them(viewer, qtbot):
    setup = viewer._setup
    setup.findChild(QSlider, "UmapNeighborsSlider").setValue(12)
    setup._run_name_input.setText("Overview")
    viewer.start_analysis()

    qtbot.waitUntil(lambda: viewer.academy_snapshot().has_results, timeout=60_000)
    params = viewer._umap_service.params
    assert params.n_neighbors == 12
    assert params.n_events == 300  # 10% of 3,000
    (run,) = viewer._state.data.umap_results["s1::root"]
    assert run["name"] == "Overview"
    assert run["n_neighbors"] == 12
    snapshot = viewer.academy_snapshot()
    assert not snapshot.is_running
    assert not snapshot.new_run_selected  # the finished run is selected in the history
    assert setup._run_name_input.isReadOnly()  # shown as a stored run


@pytest.mark.ui
def test_a_run_without_a_name_is_refused_and_nothing_stays_running(viewer):
    viewer.start_analysis()
    assert viewer._run_details_lbl.text() == "Analysis Failed:\nPlease provide a name for this run."
    assert not viewer.academy_snapshot().is_running
