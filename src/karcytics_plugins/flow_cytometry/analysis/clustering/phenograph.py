"""PhenoGraph: clusters as communities of a shared-neighbour graph (Levine et al. 2015).

1. Each event's *k* nearest events in marker space (pynndescent).
2. Two neighbouring events are linked by how many neighbours they share
   (Jaccard: shared ÷ combined), so a link inside a population is strong and a
   link across a gap is weak.
3. Leiden (scikit-network, BSD) finds communities in that graph; the
   resolution sets how fine they are. Events in a community smaller than
   ``min_size`` are outliers (-1).

On top of the clusters: how strongly each pair is connected in the graph
(the PAGA idea). A strong connection means one population split along a
gradient; a cluster with no strong connection is a distinct group.

The graph is built on at most ``GRAPH_MAX`` events (memory grows fast past
that: ~4 GB at a million). Every other event takes the cluster most of its
``VOTE`` nearest graph events have, as FlowSOM maps events it didn't train on.
The graph is kept, so a new resolution only re-runs Leiden and the vote.

The ``phenograph`` package isn't used: it requires leidenalg and python-igraph,
which are GPL.
"""

from __future__ import annotations

import ctypes
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from numba import njit
from scipy import sparse
from scipy.sparse.csgraph import shortest_path

from .layout import jitter_around, stress_layout

GRAPH_MAX = 250_000  # events in the graph; the rest are assigned by their neighbours
VOTE = 5  # graph neighbours an event outside the graph takes its cluster from
CHUNK = 50_000  # events per Jaccard chunk, between progress and cancel checks
MIN_CONNECTIVITY = 0.02  # weaker cluster links are left out of the cluster graph
SPREAD = 0.35  # the biggest cluster's circle radius, in layout units

# scikit-network's Leiden refinement draws from the C library's rand(), which
# its random_state doesn't seed. Seeding it (and holding a lock, as rand() is
# shared) is what makes a seeded run reproducible.
_RAND_LOCK = threading.Lock()


@dataclass
class PhenographGraph:
    """The costly part of a run, kept to re-cluster at another resolution."""

    graph: sparse.csr_matrix  # (graph events, graph events) symmetric Jaccard weights
    n_events: int
    sample: np.ndarray | None = None  # which events are in the graph (None: all of them)
    hosts: np.ndarray | None = None  # (other events, VOTE) their nearest graph events

    def spread(self, graph_labels: np.ndarray) -> np.ndarray:
        """Per-event labels from the graph events' (others by majority of their hosts)."""
        if self.sample is None or self.hosts is None:
            return graph_labels
        out = np.empty(self.n_events, dtype=np.int64)
        out[self.sample] = graph_labels
        others = np.ones(self.n_events, dtype=bool)
        others[self.sample] = False
        out[others] = _majority(graph_labels[self.hosts])
        return out


@dataclass
class PhenographResult:
    """One PhenoGraph run: per-event clusters and the cluster graph."""

    base: PhenographGraph
    clusters: np.ndarray  # (events,) cluster, -1 for outliers; 0 is the largest
    resolution: float
    edges: np.ndarray  # (m, 2) linked cluster pairs
    connectivity: np.ndarray  # (m,) 0-1: share of the smaller cluster's links to the other
    layout: np.ndarray  # (clusters, 2) where each cluster is drawn

    @property
    def n_clusters(self) -> int:
        return len(self.layout)


def fit_phenograph(  # noqa: PLR0913
    x: np.ndarray,
    *,
    k: int = 30,
    resolution: float = 1.0,
    min_size: int = 10,
    seed: int = 42,
    progress: Callable[[float], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> PhenographResult | None:
    """Cluster ``x`` (events × channels, already transformed); None if cancelled."""
    base = build_graph(x, k, seed, progress=progress, cancelled=cancelled)
    if base is None:
        return None
    result = recluster(base, resolution, seed=seed, min_size=min_size)
    if progress is not None:
        progress(0.95)
    return result


def build_graph(  # noqa: PLR0913
    x: np.ndarray,
    k: int,
    seed: int,
    *,
    progress: Callable[[float], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> PhenographGraph | None:
    """The shared-neighbour graph (on up to GRAPH_MAX events); None if cancelled."""
    from pynndescent import NNDescent

    x = np.asarray(x, dtype=np.float32)
    n = len(x)
    if n <= k:
        raise ValueError(f"PhenoGraph needs more than {k} events for {k} neighbours.")
    sample = None
    if n > GRAPH_MAX:
        sample = np.sort(np.random.default_rng(seed).choice(n, GRAPH_MAX, replace=False))
    in_graph = x if sample is None else x[sample]

    index = NNDescent(in_graph, n_neighbors=k + 1, random_state=seed)
    neighbours = _drop_self(index.neighbor_graph[0], k)
    if progress is not None:
        progress(0.4)
    graph = _jaccard(neighbours, progress=progress, cancelled=cancelled)
    if graph is None:
        return None

    hosts = None
    if sample is not None:
        others = np.ones(n, dtype=bool)
        others[sample] = False
        hosts = index.query(x[others], k=VOTE)[0].astype(np.int64)
    if progress is not None:
        progress(0.85)
    return PhenographGraph(graph, n, sample, hosts)


def recluster(
    base: PhenographGraph, resolution: float, *, seed: int = 42, min_size: int = 10
) -> PhenographResult:
    """Leiden at ``resolution`` on a built graph, plus the cluster graph."""
    from sknetwork.clustering import Leiden

    with _RAND_LOCK:
        _seed_c_rand(seed)
        raw = Leiden(resolution=resolution, random_state=seed).fit_predict(base.graph)
    graph_labels = _rank(raw, min_size)
    edges, connectivity = cluster_connectivity(base.graph, graph_labels)
    n_clusters = int(graph_labels.max()) + 1 if (graph_labels >= 0).any() else 0
    return PhenographResult(
        base=base,
        clusters=base.spread(graph_labels),
        resolution=resolution,
        edges=edges,
        connectivity=connectivity,
        layout=cluster_layout(n_clusters, edges, connectivity),
    )


def cluster_connectivity(
    graph: sparse.csr_matrix, clusters: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Linked cluster pairs and how strongly: the share of the smaller cluster's links to the other.

    A cluster split off a bigger one keeps many of its links to it; a distinct
    group links almost only to itself. Outliers are left out.
    """
    kept = clusters >= 0
    n_clusters = int(clusters[kept].max()) + 1 if kept.any() else 0
    if n_clusters < 2:  # noqa: PLR2004
        return np.zeros((0, 2), dtype=np.int64), np.zeros(0)
    ids = np.flatnonzero(kept)
    member = sparse.csr_matrix(
        (np.ones(len(ids)), (ids, clusters[ids])), shape=(len(clusters), n_clusters)
    )
    between = (member.T @ graph @ member).toarray()  # summed link weight, cluster × cluster
    total = between.sum(axis=1)  # each cluster's links, itself included
    a, b = np.triu_indices(n_clusters, 1)
    strength = between[a, b] / np.maximum(np.minimum(total[a], total[b]), 1e-12)
    keep = strength >= MIN_CONNECTIVITY
    return np.column_stack([a[keep], b[keep]]).astype(np.int64), strength[keep]


def cluster_layout(n_clusters: int, edges: np.ndarray, connectivity: np.ndarray) -> np.ndarray:
    """2-D cluster positions: strongly connected clusters close, unconnected ones apart."""
    if n_clusters == 0:
        return np.zeros((0, 2))
    lengths = sparse.csr_matrix(
        (1.0 / np.maximum(connectivity, MIN_CONNECTIVITY), (edges[:, 0], edges[:, 1])),
        shape=(n_clusters, n_clusters),
    )
    target = shortest_path(lengths, directed=False)
    finite = target[np.isfinite(target)]
    far = 1.5 * finite.max() if finite.size and finite.max() > 0 else 1.0
    target[~np.isfinite(target)] = far  # separate components: well apart
    layout = stress_layout(target)
    scale = np.abs(layout).max()
    return layout / scale * 4 if scale > 0 else layout


def graph_embedding(layout: np.ndarray, clusters: np.ndarray, seed: int = 0) -> np.ndarray:
    """A 2-D point per event, inside its cluster's circle; outliers at the centre."""
    if len(layout) == 0:
        return np.zeros((len(clusters), 2))
    points = jitter_around(layout, np.maximum(clusters, 0), seed, spread=SPREAD)
    points[clusters < 0] = 0.0
    return points


def _jaccard(
    neighbours: np.ndarray,
    *,
    progress: Callable[[float], None] | None,
    cancelled: Callable[[], bool] | None,
) -> sparse.csr_matrix | None:
    n, k = neighbours.shape
    neighbours = np.sort(neighbours, axis=1)  # sorted rows: shared counts by merging
    shared = np.empty((n, k), dtype=np.float32)
    for lo in range(0, n, CHUNK):
        if cancelled is not None and cancelled():
            return None
        hi = min(lo + CHUNK, n)
        _count_shared(neighbours, lo, hi, shared)
        if progress is not None:
            progress(0.4 + 0.3 * hi / n)
    weights = (shared / (2 * k - shared)).ravel()
    rows = np.repeat(np.arange(n), k)
    graph = sparse.csr_matrix((weights, (rows, neighbours.ravel())), shape=(n, n))
    graph = ((graph + graph.T) * 0.5).tocsr()
    graph.eliminate_zeros()
    return graph


@njit(cache=True, nogil=True)
def _count_shared(neighbours: np.ndarray, lo: int, hi: int, out: np.ndarray) -> None:
    """For rows lo..hi: how many neighbours each row shares with each of its neighbours.

    Rows must be sorted, so each count is one merge of two k-long lists.
    """
    k = neighbours.shape[1]
    for i in range(lo, hi):
        for slot in range(k):
            j = neighbours[i, slot]
            a = b = shared = 0
            while a < k and b < k:
                if neighbours[i, a] == neighbours[j, b]:
                    shared += 1
                    a += 1
                    b += 1
                elif neighbours[i, a] < neighbours[j, b]:
                    a += 1
                else:
                    b += 1
            out[i, slot] = shared


def _majority(votes: np.ndarray) -> np.ndarray:
    """Each row's most common cluster, ignoring outliers; ties go to the larger cluster."""
    n_clusters = int(votes.max()) + 1 if votes.size and votes.max() >= 0 else 0
    if n_clusters == 0:
        return np.full(len(votes), -1, dtype=np.int64)
    counts = np.zeros((len(votes), n_clusters), dtype=np.int64)
    rows = np.repeat(np.arange(len(votes)), votes.shape[1])
    flat = votes.ravel()
    np.add.at(counts, (rows[flat >= 0], flat[flat >= 0]), 1)
    best = counts.argmax(axis=1)  # first maximum: the lowest number, the larger cluster
    return np.where(counts.max(axis=1) > 0, best, -1)


def _seed_c_rand(seed: int) -> None:
    """srand(seed) in the C runtime the compiled Leiden core uses."""
    try:
        libc = ctypes.CDLL("ucrtbase") if sys.platform == "win32" else ctypes.CDLL(None)
        libc.srand(ctypes.c_uint(seed & 0xFFFFFFFF))
    except (OSError, AttributeError):  # no C runtime to seed: runs may differ slightly
        pass


def _drop_self(found: np.ndarray, k: int) -> np.ndarray:
    """Each row's k neighbours without the event itself (usually, not always, first)."""
    is_self = found == np.arange(len(found))[:, None]
    order = np.argsort(is_self, axis=1, kind="stable")  # self (True) moves to the end
    return np.take_along_axis(found, order, axis=1)[:, :k]


def _rank(raw: np.ndarray, min_size: int) -> np.ndarray:
    """Clusters numbered from 0, largest first; those under ``min_size`` become -1."""
    sizes = np.bincount(raw)
    order = np.argsort(-sizes, kind="stable")
    rank = np.full(len(sizes), -1, dtype=np.int64)
    big = order[sizes[order] >= min_size]
    rank[big] = np.arange(len(big))
    return rank[raw]
