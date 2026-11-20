"""A clustering run's Population Statistics tables, drawn populations and export."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from karcytics_plugins.flow_cytometry.analysis.clustering.result_tables import (
    DRAWN_AWAY,
    ExportPicks,
    add_drawn_population,
    drawn_populations,
    export_populations,
    heatmap_table,
    stacked_profiles,
    statistics_table,
)
from karcytics_plugins.flow_cytometry.analysis.clustering.run_input import cluster_tables
from karcytics_plugins.flow_cytometry.analysis.experiment import Sample
from karcytics_plugins.flow_cytometry.analysis.state import FlowState

pytestmark = pytest.mark.unit


def _run(n_events: int = 10, parent_total_events: int | None = None) -> dict:
    """Two clusters (first half 0, second half 1) over two channels."""
    rng = np.random.default_rng(0)
    intensities = rng.uniform(0, 1, size=(n_events, 2))
    clusters = np.repeat([0, 1], [n_events // 2, n_events - n_events // 2])
    return {
        "embedding": rng.normal(size=(n_events, 2)),
        "intensities": intensities,
        "channels": ["FL1-A", "FL2-A"],
        "channel_labels": ["CD3", "CD4"],
        "clusters": clusters,
        **cluster_tables(intensities, clusters, ["FL1-A", "FL2-A"]),
        "indices": np.arange(100, 100 + n_events),
        "sample_id": "s1",
        "node_id": None,  # the sample's root
        "n_events": n_events,
        "parent_total_events": parent_total_events or n_events,
    }


@pytest.fixture
def experiment():
    state = FlowState()
    state.data.experiment.samples["s1"] = Sample(sample_id="s1", display_name="Sample 1")
    return state.data.experiment


def test_statistics_table_lists_clusters_then_drawn_populations():
    run = _run()
    run["custom_clusters"] = [
        {"name": "Empty", "mask": []},  # numbered, but holds nothing: not listed
        {"name": "Blob", "mask": [0, 1, 2]},
    ]

    stats = statistics_table(run)

    assert stats is not None
    assert list(stats["Cluster ID"]) == [0, 1, "Custom 2"]
    assert list(stats["Cell Count"]) == [5, 5, 3]
    assert stats["% of Total"].iloc[2] == pytest.approx(30.0)


def test_statistics_table_is_none_without_cluster_stats():
    run = _run()
    del run["cluster_stats"]
    assert statistics_table(run) is None


def test_heatmap_table_labels_markers_and_averages_drawn_populations():
    run = _run()
    run["custom_clusters"] = [{"name": "Blob", "mask": [0, 1]}]

    heatmap = heatmap_table(run)

    assert heatmap is not None
    assert list(heatmap.columns) == ["CD3", "CD4"]
    assert list(heatmap.index) == [0, 1, "Custom 1"]
    np.testing.assert_allclose(
        heatmap.loc["Custom 1"].to_numpy(dtype=float), run["intensities"][[0, 1]].mean(axis=0)
    )


def test_heatmap_table_from_drawn_populations_alone():
    run = _run()
    del run["marker_heatmap"]
    assert heatmap_table(run) is None
    run["custom_clusters"] = [{"name": "Blob", "mask": [3]}]

    heatmap = heatmap_table(run)

    assert heatmap is not None and list(heatmap.index) == ["Custom 1"]


def test_stacked_profiles_rows_sum_to_100_even_with_negative_values():
    heatmap = pd.DataFrame([[-1.0, 1.0], [2.0, 2.0], [0.0, 0.0]])
    profiles = stacked_profiles(heatmap)
    np.testing.assert_allclose(profiles[:2].sum(axis=1), [100.0, 100.0])
    np.testing.assert_allclose(profiles[1], [50.0, 50.0])
    assert np.isfinite(profiles).all()  # an all-zero row doesn't divide by zero


def test_drawing_a_population_takes_its_events_out_of_the_clusters():
    run = _run()
    mask = np.zeros(10, dtype=bool)
    mask[[0, 1, 2]] = True  # three events of cluster 0

    add_drawn_population(run, "Blob", [(0, 0), (1, 0), (1, 1)], mask)

    assert run["custom_clusters"] == [
        {"name": "Blob", "mask": [0, 1, 2], "verts": [(0, 0), (1, 0), (1, 1)]}
    ]
    assert (run["clusters"][:3] == DRAWN_AWAY).all()
    stats = statistics_table(run)
    assert stats is not None
    # Cluster 0 keeps 2 events, still out of all 10; the drawn population follows.
    assert list(stats["Cell Count"]) == [2, 5, 3]
    assert stats["% of Total"].iloc[0] == pytest.approx(20.0)
    assert [p.name for p in drawn_populations(run)] == ["Blob"]


def test_export_adds_picked_clusters_under_a_method_parent(experiment):
    run = _run()
    drawn = np.zeros(10, dtype=bool)
    drawn[[7, 8]] = True

    created = export_populations(
        run, experiment, ExportPicks(clusters={0: "T cells", 1: ""}, drawn=[(drawn, "")])
    )

    assert created == 3  # noqa: PLR2004
    root = experiment.samples["s1"].gate_tree
    parent = next(c for c in root.children if c.name == "UMAP Reduction")
    assert run["exported_node_id"] == parent.node_id  # double-clicking it reopens the run
    assert [c.name for c in parent.children] == ["T cells", "UMAP Cluster 1", "Custom Cluster"]
    # Each population keeps the parent's event indices for its own events.
    assert parent.children[0].gate.indices == {100, 101, 102, 103, 104}
    assert parent.children[2].gate.indices == {107, 108}


def test_export_marks_a_subsampled_run_as_estimated(experiment):
    """8 of 10 parent events were clustered: counts scale by 10/8."""
    run = _run(n_events=8, parent_total_events=10)

    export_populations(run, experiment, ExportPicks(clusters={0: ""}, drawn=[]))

    parent = experiment.samples["s1"].gate_tree.children[0]
    cluster_node = parent.children[0]
    assert cluster_node.is_estimated is True
    assert cluster_node.scale_factor == pytest.approx(10 / 8)
    assert parent.is_estimated is False  # the container isn't a reported population
    assert parent.scale_factor == 1.0


def test_export_of_a_full_run_is_not_estimated(experiment):
    run = _run()
    export_populations(run, experiment, ExportPicks(clusters={0: ""}, drawn=[]))
    cluster_node = experiment.samples["s1"].gate_tree.children[0].children[0]
    assert cluster_node.is_estimated is False
    assert cluster_node.scale_factor == 1.0


def test_export_without_its_sample_does_nothing(experiment):
    run = _run()
    run["sample_id"] = "gone"
    assert export_populations(run, experiment, ExportPicks(clusters={0: ""}, drawn=[])) is None
