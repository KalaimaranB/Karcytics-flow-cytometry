"""PhenoGraph: shared-neighbour graph + Leiden (scikit-network, BSD)."""

import numpy as np
from scipy import sparse


def test_scikit_network_leiden_splits_two_cliques():
    from sknetwork.clustering import Leiden

    block = np.ones((5, 5)) - np.eye(5)
    graph = sparse.csr_matrix(np.block([[block, np.zeros((5, 5))], [np.zeros((5, 5)), block]]))
    graph[4, 5] = graph[5, 4] = 0.1  # a weak bridge

    labels = Leiden(random_state=0).fit_predict(graph)
    assert len(set(labels[:5])) == 1 and len(set(labels[5:])) == 1
    assert labels[0] != labels[5]


# ── PhenoGraph on the Sample Lens fixture's planted cell types ────────────────

import time  # noqa: E402

import pytest  # noqa: E402
from sklearn.metrics import adjusted_rand_score  # noqa: E402

from karcytics_plugins.flow_cytometry.analysis.clustering import phenograph  # noqa: E402
from karcytics_plugins.flow_cytometry.analysis.clustering.phenograph import (  # noqa: E402
    fit_phenograph,
    recluster,
)
from tests.fixtures.lens import make_sample  # noqa: E402


@pytest.fixture(scope="module")
def planted():
    _sample, events, truth = make_sample("s1")
    x = events.to_numpy() / 1000
    return x, truth, fit_phenograph(x, resolution=0.3)


def _majority_type(truth, clusters):
    return {c: np.bincount(truth[clusters == c] + 1).argmax() - 1 for c in set(clusters) if c >= 0}


def test_clusters_recover_the_planted_cell_types(planted):
    _x, truth, result = planted
    assert adjusted_rand_score(truth, result.clusters) > 0.95  # noqa: PLR2004
    sizes = np.bincount(result.clusters[result.clusters >= 0])
    assert list(sizes) == sorted(sizes, reverse=True)  # 0 is the largest


def test_a_higher_resolution_gives_more_clusters(planted):
    *_, result = planted
    counts = [recluster(result.base, r).n_clusters for r in (0.3, 1.0, 2.0)]
    assert counts == sorted(counts) and counts[0] < counts[-1]


def test_a_seed_makes_a_run_reproducible(planted):
    x, _truth, result = planted
    again = fit_phenograph(x, resolution=0.3)
    assert again is not None
    np.testing.assert_array_equal(again.clusters, result.clusters)
    high = [recluster(result.base, 2.0).clusters for _ in range(2)]
    np.testing.assert_array_equal(*high)


def test_pieces_of_one_population_are_connected_and_distinct_ones_are_not(planted):
    _x, truth, result = planted
    split = recluster(result.base, 2.0)  # over-split: several clusters per cell type
    kind = _majority_type(truth, split.clusters)
    within = [
        s for (a, b), s in zip(split.edges, split.connectivity, strict=True) if kind[a] == kind[b]
    ]
    between = [
        s for (a, b), s in zip(split.edges, split.connectivity, strict=True) if kind[a] != kind[b]
    ]
    assert within, "a planted type should split into linked pieces at resolution 2"
    assert max(between, default=0.0) < min(within)


def test_small_clusters_become_outliers(planted):
    *_, result = planted
    tiny = recluster(result.base, 2.0, min_size=10**4)
    assert (tiny.clusters == -1).all() and tiny.n_clusters == 0


def test_events_beyond_the_graph_take_their_neighbours_cluster(planted, monkeypatch):
    x, truth, _ = planted
    monkeypatch.setattr(phenograph, "GRAPH_MAX", 2000)
    result = fit_phenograph(x, resolution=0.3)
    assert result is not None
    assert result.base.graph.shape == (2000, 2000)
    assert result.base.hosts.shape == (len(x) - 2000, phenograph.VOTE)
    assert result.clusters.shape == (len(x),)
    assert adjusted_rand_score(truth, result.clusters) > 0.9  # noqa: PLR2004


def test_a_cancelled_run_returns_nothing(planted):
    x, *_ = planted
    assert fit_phenograph(x, cancelled=lambda: True) is None


def test_too_few_events_for_the_neighbours_is_an_error():
    with pytest.raises(ValueError, match="more than 30 events"):
        fit_phenograph(np.zeros((20, 3)))


def test_majority_vote_ignores_outliers_and_breaks_ties_to_the_larger_cluster():
    votes = np.array([[2, 2, 1, -1, -1], [1, 0, -1, -1, -1], [-1] * 5])
    assert phenograph._majority(votes).tolist() == [2, 0, -1]


def test_the_cluster_graph_layout_is_finite(planted):
    *_, result = planted
    split = recluster(result.base, 2.0)
    assert split.layout.shape == (split.n_clusters, 2)
    assert np.isfinite(split.layout).all()
    points = phenograph.graph_embedding(split.layout, split.clusters)
    assert points.shape == (len(split.clusters), 2) and np.isfinite(points).all()


def test_more_events_than_the_graph_holds_cluster_in_under_a_minute():
    x = np.random.default_rng(0).normal(size=(300_000, 8))
    start = time.perf_counter()
    result = fit_phenograph(x)
    assert result is not None and (result.clusters >= 0).mean() > 0.99  # noqa: PLR2004
    assert time.perf_counter() - start < 60  # noqa: PLR2004
