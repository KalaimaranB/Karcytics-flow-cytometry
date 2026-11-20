"""The clustering results panel: its statistics tab, Interactive Map and export."""

from __future__ import annotations

import numpy as np
import pytest
from karcytics_sdk.plugin.components import BioTableWidget
from PySide6.QtWidgets import QMessageBox, QPushButton

from karcytics_plugins.flow_cytometry.analysis.clustering.run_input import cluster_tables
from karcytics_plugins.flow_cytometry.analysis.experiment import Sample
from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.ui.widgets import cluster_map_tab as map_module
from karcytics_plugins.flow_cytometry.ui.widgets.cluster_map_tab import ClusterMapTab
from karcytics_plugins.flow_cytometry.ui.widgets.cluster_plot_gallery import ClusterPlotGallery
from karcytics_plugins.flow_cytometry.ui.widgets.cluster_results_panel import (
    STATISTICS_TAB,
    ClusterResultsPanel,
)
from karcytics_plugins.flow_cytometry.ui.widgets.cluster_scatter_draw import cluster_rgb
from karcytics_plugins.flow_cytometry.ui.widgets.cluster_statistics_tab import (
    ClusterStatisticsTab,
)
from karcytics_plugins.flow_cytometry.ui.widgets.copyable import CopyableCanvas

N_EVENTS = 40


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    monkeypatch.setattr(ClusterPlotGallery, "_request_tile", lambda *_a, **_k: None)
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))


@pytest.fixture
def state():
    state = FlowState()
    state.data.experiment.samples["s1"] = Sample(sample_id="s1", display_name="Sample 1")
    return state


def _run() -> dict:
    """Two well-separated clusters: ids 0 (left, x < 0) and 1 (right)."""
    rng = np.random.default_rng(0)
    clusters = np.repeat([0, 1], N_EVENTS // 2)
    embedding = rng.normal(scale=0.3, size=(N_EVENTS, 2))
    embedding[:, 0] += np.where(clusters == 0, -3.0, 3.0)
    intensities = rng.uniform(size=(N_EVENTS, 2))
    return {
        "embedding": embedding,
        "intensities": intensities,
        "channels": ["FL1-A", "FL2-A"],
        "channel_labels": ["CD3", "CD4"],
        "clusters": clusters,
        **cluster_tables(intensities, clusters, ["CD3", "CD4"]),
        "indices": np.arange(N_EVENTS),
        "sample_id": "s1",
        "node_id": None,
        "n_events": N_EVENTS,
        "parent_total_events": N_EVENTS,
    }


def _panel(qtbot, state, run=None) -> ClusterResultsPanel:
    panel = ClusterResultsPanel(run or _run(), state=state)
    qtbot.addWidget(panel)
    return panel


def _statistics(panel: ClusterResultsPanel) -> ClusterStatisticsTab:
    tabs = panel._tabs
    tab = tabs.widget([tabs.tabText(i) for i in range(tabs.count())].index(STATISTICS_TAB))
    assert isinstance(tab, ClusterStatisticsTab)
    return tab


@pytest.mark.ui
def test_a_clustered_run_shows_gallery_map_and_statistics(qtbot, state):
    panel = _panel(qtbot, state)

    tabs = panel._tabs
    assert [tabs.tabText(i) for i in range(tabs.count())] == [
        "Plot Gallery",
        "Interactive Map",
        STATISTICS_TAB,
    ]
    snapshot = panel.academy_snapshot()
    assert snapshot.color_label == "Auto-Cluster ID"
    assert snapshot.cluster_rows == {0: (True, "UMAP Cluster 0"), 1: (True, "UMAP Cluster 1")}


@pytest.mark.ui
def test_a_run_without_clusters_shows_only_the_gallery(qtbot, state):
    run = _run()
    del run["clusters"]
    panel = _panel(qtbot, state, run)

    assert panel._tabs.count() == 1
    assert panel.academy_snapshot().color_label is None


@pytest.mark.ui
def test_the_expression_chart_renders_in_the_background(qtbot, state):
    panel = _panel(qtbot, state)
    statistics = _statistics(panel)

    qtbot.waitUntil(lambda: statistics.findChild(CopyableCanvas) is not None, timeout=5000)


@pytest.mark.ui
def test_table_swatches_match_the_map_once_ids_start_below_zero(qtbot, state):
    """Noise or drawn-away events (-1) shift the map's palette; the table follows it."""
    run = _run()
    run["clusters"][0] = -1
    run.update(cluster_tables(run["intensities"], run["clusters"], ["CD3", "CD4"]))
    panel = _panel(qtbot, state, run)
    statistics = _statistics(panel)

    table = statistics.findChildren(BioTableWidget)[0]
    row_of_cluster_0 = [table.item(r, 0).text() for r in range(table.rowCount())].index("0")
    swatch = table.item(row_of_cluster_0, 0).background().color()
    r, g, b = cluster_rgb(0, lowest=-1)
    assert (swatch.red(), swatch.green(), swatch.blue()) == (
        int(r * 255),
        int(g * 255),
        int(b * 255),
    )


@pytest.mark.ui
def test_create_populations_exports_the_ticked_clusters_with_their_names(qtbot, state):
    panel = _panel(qtbot, state)
    statistics = _statistics(panel)
    statistics._export._cluster_rows[0][1].setText("T cells")
    statistics._export._cluster_rows[1][0].setChecked(False)

    statistics.findChild(QPushButton, "CreatePopulationsButton").click()

    root = state.data.experiment.samples["s1"].gate_tree
    (parent,) = root.children
    assert [child.name for child in parent.children] == ["T cells"]
    assert panel.run["exported_node_id"] == parent.node_id


@pytest.mark.ui
def test_drawing_a_population_adds_it_to_the_statistics(qtbot, state, monkeypatch):
    monkeypatch.setattr(map_module, "get_text", lambda *_a, **_k: "Left blob")
    panel = _panel(qtbot, state)
    modified: list[bool] = []
    panel.results_modified.connect(lambda: modified.append(True))
    map_tab = panel._tabs.widget(1)
    assert isinstance(map_tab, ClusterMapTab)

    map_tab._on_polygon_drawn([(-5.0, -5.0), (-1.0, -5.0), (-1.0, 5.0), (-5.0, 5.0)])

    assert [d["name"] for d in panel.run["custom_clusters"]] == ["Left blob"]
    assert (panel.run["clusters"][: N_EVENTS // 2] == -1).all()
    statistics = _statistics(panel)
    assert list(statistics.cluster_rows()) == [1]  # cluster 0 lost every event to the drawing
    assert [box.text() for _m, box, _e in statistics._export._drawn_rows] == ["Custom 1"]
    assert modified == [True]
