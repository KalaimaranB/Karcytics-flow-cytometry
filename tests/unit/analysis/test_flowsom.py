"""FlowSOM on the Sample Lens fixture's planted cell types."""

import time

import numpy as np
import pytest
from sklearn.metrics import adjusted_rand_score

from karcytics_plugins.flow_cytometry.analysis.clustering import (
    FLOWSOM,
    UMAP_HDBSCAN,
    fit_flowsom,
    method_of,
    recut,
)
from tests.fixtures.lens import make_sample


@pytest.fixture(scope="module")
def planted():
    _sample, events, truth = make_sample("s1")
    x = events.to_numpy() / 1000
    return x, truth, fit_flowsom(x, k=5)


def test_metaclusters_recover_the_planted_cell_types(planted):
    _x, truth, result = planted
    assert adjusted_rand_score(truth, result.clusters) > 0.95  # noqa: PLR2004


def test_every_event_has_a_node_and_no_event_is_noise(planted):
    x, _truth, result = planted
    assert result.nodes.shape == (len(x),)
    assert result.clusters.min() >= 0
    assert result.codes.shape == (100, x.shape[1])


def test_the_tree_spans_every_node(planted):
    *_, result = planted
    assert result.mst_edges.shape == (99, 2)
    assert set(result.mst_edges.ravel()) == set(range(100))
    assert result.layout.shape == (100, 2)
    assert np.isfinite(result.layout).all()


def test_a_seed_makes_a_run_reproducible(planted):
    x, _truth, result = planted
    again = fit_flowsom(x, k=5)
    assert again is not None
    np.testing.assert_array_equal(again.nodes, result.nodes)
    np.testing.assert_array_equal(again.clusters, result.clusters)


@pytest.mark.parametrize("k", [2, 5, 12])
def test_recut_gives_k_metaclusters_numbered_largest_first(planted, k):
    *_, result = planted
    labels = recut(result.linkage, k, result.nodes)
    assert sorted(set(labels)) == list(range(k))
    sizes = np.bincount(labels[result.nodes])
    assert list(sizes) == sorted(sizes, reverse=True)


def test_a_cancelled_run_returns_nothing(planted):
    x, *_ = planted
    assert fit_flowsom(x, cancelled=lambda: True) is None


def test_too_few_events_for_the_grid_is_an_error():
    with pytest.raises(ValueError, match="at least 100 events"):
        fit_flowsom(np.zeros((50, 3)))


def test_a_million_events_fit_in_seconds():
    x = np.random.default_rng(0).normal(size=(1_000_000, 12))
    start = time.perf_counter()
    fit_flowsom(x)
    assert time.perf_counter() - start < 30  # noqa: PLR2004


def test_runs_saved_before_the_choice_are_umap_hdbscan():
    assert method_of({}) is UMAP_HDBSCAN
    assert method_of({"method": "flowsom"}) is FLOWSOM
    assert FLOWSOM.map_caption({"k": 7}).endswith("k = 7)")
