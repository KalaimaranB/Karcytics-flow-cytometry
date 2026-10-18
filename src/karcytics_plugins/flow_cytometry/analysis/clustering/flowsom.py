"""FlowSOM: a self-organizing map of the events, its node tree, and metaclusters.

1. A SOM grid of nodes (10 × 10 by default) is trained on the events; each
   event belongs to its nearest node, so no event is left out as noise.
2. A minimum spanning tree links each node to the nodes most like it, and is
   laid out in 2-D for plotting (stress majorization of tree distances).
3. The node codes are clustered hierarchically (Ward) into *k* metaclusters.
   The hierarchy is kept, so *k* can be changed later with :func:`recut`.

The SOM is a batch SOM (every pass moves each node to the neighbourhood-
weighted mean of its events), not FlowSOM's online SOM. It is deterministic
for a seed and vectorized, with the same kind of result.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.sparse.csgraph import minimum_spanning_tree, shortest_path
from scipy.spatial.distance import cdist

TRAIN_MAX = 200_000  # events the SOM is trained on; every event is then mapped
CHUNK = 50_000  # events per nearest-node chunk (bounds memory)
START_RADIUS_QUANTILE = 0.67  # FlowSOM's starting neighbourhood (of grid distances)
END_RADIUS = 0.5  # grid units: by the last pass a node barely pulls its neighbours
LAYOUT_ITERATIONS = 300


@dataclass
class FlowsomResult:
    """One FlowSOM run. Node arrays are indexed by node, event arrays by event."""

    codes: np.ndarray  # (nodes, channels) each node's position in marker space
    grid: np.ndarray  # (nodes, 2) each node's SOM grid cell
    nodes: np.ndarray  # (events,) each event's node
    mst_edges: np.ndarray  # (nodes - 1, 2) the node tree
    layout: np.ndarray  # (nodes, 2) where each node is drawn
    linkage: np.ndarray  # Ward hierarchy of the codes, for recut
    node_metaclusters: np.ndarray  # (nodes,) each node's metacluster
    k: int

    @property
    def clusters(self) -> np.ndarray:
        """Each event's metacluster."""
        return self.node_metaclusters[self.nodes]


def fit_flowsom(  # noqa: PLR0913
    x: np.ndarray,
    *,
    xdim: int = 10,
    ydim: int = 10,
    k: int = 10,
    passes: int = 10,
    seed: int = 42,
    progress: Callable[[float], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> FlowsomResult | None:
    """Fit FlowSOM to ``x`` (events × channels, already transformed); None if cancelled."""
    x = np.asarray(x, dtype=np.float64)
    rng = np.random.default_rng(seed)
    grid = np.array([(i, j) for j in range(ydim) for i in range(xdim)], dtype=np.float64)
    n_nodes = len(grid)
    if len(x) < n_nodes:
        raise ValueError(f"FlowSOM needs at least {n_nodes} events for a {xdim}×{ydim} grid.")

    train = x[rng.choice(len(x), TRAIN_MAX, replace=False)] if len(x) > TRAIN_MAX else x
    codes = train[rng.choice(len(train), n_nodes, replace=False)].copy()
    grid_dist = cdist(grid, grid)
    start = max(float(np.quantile(grid_dist, START_RADIUS_QUANTILE)), END_RADIUS)
    for p, radius in enumerate(np.geomspace(start, END_RADIUS, passes)):
        if cancelled is not None and cancelled():
            return None
        codes = _batch_pass(train, codes, np.exp(-(grid_dist**2) / (2 * radius**2)))
        if progress is not None:
            progress(0.8 * (p + 1) / passes)

    nodes = nearest_nodes(x, codes)
    edges = _mst(codes)
    tree = linkage(codes, method="ward")
    if progress is not None:
        progress(0.9)
    return FlowsomResult(
        codes=codes,
        grid=grid.astype(np.int64),
        nodes=nodes,
        mst_edges=edges,
        layout=_tree_layout(edges, n_nodes),
        linkage=tree,
        node_metaclusters=recut(tree, k, nodes),
        k=k,
    )


def recut(tree: np.ndarray, k: int, nodes: np.ndarray | None = None) -> np.ndarray:
    """Each node's metacluster when the hierarchy is cut into ``k``.

    Metaclusters are numbered from 0, largest first (by events when ``nodes``
    is given, else by nodes), so the same cut always gets the same numbers.
    """
    raw = fcluster(tree, t=k, criterion="maxclust") - 1
    weight = np.bincount(nodes, minlength=len(raw)) if nodes is not None else np.ones(len(raw))
    sizes = np.bincount(raw, weights=weight)
    order = np.argsort(-sizes, kind="stable")
    rank = np.empty_like(order)
    rank[order] = np.arange(len(order))
    return rank[raw]


def nearest_nodes(x: np.ndarray, codes: np.ndarray) -> np.ndarray:
    """Each event's nearest node, in chunks."""
    sq = (codes**2).sum(axis=1)
    out = np.empty(len(x), dtype=np.int64)
    for lo in range(0, len(x), CHUNK):
        chunk = x[lo : lo + CHUNK]
        out[lo : lo + CHUNK] = np.argmin(sq - 2 * chunk @ codes.T, axis=1)
    return out


def _batch_pass(x: np.ndarray, codes: np.ndarray, kernel: np.ndarray) -> np.ndarray:
    """Move every node to the kernel-weighted mean of the events nearest it and its neighbours."""
    nodes = nearest_nodes(x, codes)
    counts = np.bincount(nodes, minlength=len(codes)).astype(np.float64)
    sums = np.zeros_like(codes)
    np.add.at(sums, nodes, x)
    weight = kernel @ counts
    moved = (kernel @ sums) / np.maximum(weight, 1e-12)[:, None]
    return np.where(weight[:, None] > 0, moved, codes)


def _mst(codes: np.ndarray) -> np.ndarray:
    dist = cdist(codes, codes)
    tree = minimum_spanning_tree(dist + 1e-12 * (dist == 0)).tocoo()  # 0 would mean "no edge"
    return np.column_stack([tree.row, tree.col]).astype(np.int64)


def _tree_layout(edges: np.ndarray, n_nodes: int) -> np.ndarray:
    """2-D node positions whose distances follow tree distances (SMACOF stress majorization)."""
    adjacency = np.zeros((n_nodes, n_nodes))
    adjacency[edges[:, 0], edges[:, 1]] = adjacency[edges[:, 1], edges[:, 0]] = 1.0
    target = shortest_path(adjacency, unweighted=True)

    # Classical MDS start, then majorize: deterministic and untangled.
    centring = np.eye(n_nodes) - 1.0 / n_nodes
    values, vectors = np.linalg.eigh(-0.5 * centring @ (target**2) @ centring)
    top = np.argsort(values)[::-1][:2]
    pos = vectors[:, top] * np.sqrt(np.maximum(values[top], 1e-9))

    weights = np.where(target > 0, 1.0 / np.maximum(target, 1e-9) ** 2, 0.0)
    v = -weights
    np.fill_diagonal(v, weights.sum(axis=1))
    v_inv = np.linalg.pinv(v)
    for _ in range(LAYOUT_ITERATIONS):
        dist = cdist(pos, pos)
        b = np.where(dist > 0, -weights * target / np.maximum(dist, 1e-9), 0.0)
        np.fill_diagonal(b, -b.sum(axis=1))
        pos = v_inv @ b @ pos
    return pos - pos.mean(axis=0)
