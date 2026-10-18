"""What each clustering method is called and how its results read.

A run (a dict in ``umap_results``) names its method in ``run["method"]``;
runs saved before there was a choice are UMAP + HDBSCAN.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ClusteringMethod:
    key: str
    name: str
    cluster_noun: str  # what one cluster is called in sentences ("cluster", "metacluster")
    has_noise: bool  # some events can be left out of every cluster (label -1)
    recuttable: bool  # the number of clusters can be changed after the run
    export_parent: str  # the population that holds a run's exported clusters
    short: str  # prefix of a cluster's default name ("UMAP Cluster 3", "Metacluster 3")

    def cluster_name(self, cluster: int) -> str:
        return f"{self.short} {cluster}"

    def map_caption(self, run: dict[str, Any]) -> str:
        """Caption for the run's map coloured by cluster."""
        if self.key == FLOWSOM.key:
            return f"Coloured by metacluster (FlowSOM, k = {run.get('k', '?')})"
        return "Coloured by cluster (HDBSCAN)"


UMAP_HDBSCAN = ClusteringMethod(
    "umap_hdbscan", "UMAP + HDBSCAN", "cluster", True, False, "UMAP Reduction", "UMAP Cluster"
)
FLOWSOM = ClusteringMethod(
    "flowsom", "FlowSOM", "metacluster", False, True, "FlowSOM", "Metacluster"
)
METHODS = {m.key: m for m in (UMAP_HDBSCAN, FLOWSOM)}


def method_of(run: dict[str, Any]) -> ClusteringMethod:
    return METHODS.get(run.get("method") or UMAP_HDBSCAN.key, UMAP_HDBSCAN)
