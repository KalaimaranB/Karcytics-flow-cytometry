"""A UMAP run lined up with its sample's events and gated populations.

A run covers a random subsample (``run["indices"]``, event row labels) of one
population (``run["node_id"]``, None = All Events). Everything the lens says
about a run is about those events only, so this module turns a run into
arrays that share one row order: the embedding, the cluster labels, and a
mask per *final* population under the run's node.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np

from ..population_matching import PATH_SEP, populations

if TYPE_CHECKING:
    import pandas as pd

    from ..experiment import Sample
    from ..gating import GateNode

NOISE = -1  # HDBSCAN's label for events in no cluster


@dataclass(frozen=True)
class LensPopulation:
    path: str  # full label path, e.g. "Lymphocytes / T cells / CD4+"
    node: GateNode

    @property
    def name(self) -> str:
        return self.path.rsplit(PATH_SEP, 1)[-1]


@dataclass
class RunScope:
    """One UMAP run, aligned with the events it was computed on."""

    run: dict[str, Any]
    rows: np.ndarray  # positions (iloc) of the run's events in the sample's events
    embedding: np.ndarray  # (n, 2)
    clusters: np.ndarray | None  # (n,) HDBSCAN labels, None if the run had no clustering
    final_populations: list[LensPopulation]  # the leaves under the run's node
    masks: dict[str, np.ndarray]  # path -> (n,) membership of each final population
    # path -> (n,) membership of every population under the run's node, final
    # or not: lets a finding name the gate on a path where cells are lost.
    steps: dict[str, np.ndarray] = field(default_factory=dict)

    @property
    def n(self) -> int:
        return len(self.rows)

    @property
    def has_clusters(self) -> bool:
        return self.clusters is not None


def is_cluster_population(node: GateNode) -> bool:
    """True for a population exported from a UMAP run (or under one).

    Those come from the clustering itself, so judging the gates against the
    clusters would just compare the clusters with themselves.
    """
    stack = [node]
    while stack:
        current = stack.pop()
        if current.is_umap_parent:
            return True
        stack.extend(current.parents)
    return False


def _descends_from(node: GateNode, ancestor_id: str | None) -> bool:
    if ancestor_id is None:
        return True
    stack = list(node.parents)
    while stack:
        current = stack.pop()
        if current.node_id == ancestor_id:
            return True
        stack.extend(current.parents)
    return False


def final_populations(sample: Sample, under_node_id: str | None = None) -> list[LensPopulation]:
    """The populations a gating strategy ends in: leaves, minus cluster exports.

    Logic nodes (AND/OR/NOT) only recombine gates, so they are neither final
    populations nor children that stop their gates from being final.
    """
    found = []
    for path, node in populations(sample):
        gate_children = [c for c in node.children if not c.is_incomplete and not c.is_logic_node]
        if node.is_logic_node or gate_children or is_cluster_population(node):
            continue
        if _descends_from(node, under_node_id):
            found.append(LensPopulation(path, node))
    return found


def build_scope(sample: Sample, run: dict[str, Any], events: pd.DataFrame) -> RunScope:
    """Line ``run`` up with ``events`` (the sample's root events, derived columns synced)."""
    positions = events.index.get_indexer(np.asarray(run["indices"]))
    kept = positions >= 0  # rows dropped since the run (e.g. a reload) can't be judged
    rows = positions[kept]

    embedding = np.asarray(run["embedding"], dtype=np.float64)[kept]
    clusters = run.get("clusters")
    clusters = np.asarray(clusters)[kept] if clusters is not None else None

    under = run.get("node_id")
    finals = final_populations(sample, under)
    steps = {
        path: node.mask(events)[rows]
        for path, node in populations(sample)
        if not is_cluster_population(node) and _descends_from(node, under)
    }
    masks = {pop.path: steps[pop.path] for pop in finals}
    return RunScope(run, rows, embedding, clusters, finals, masks, steps)
