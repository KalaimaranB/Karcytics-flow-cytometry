"""What each clustering method is called and how its results read.

A run (a dict in ``umap_results``) names its method in ``run["method"]``;
runs saved before there was a choice are UMAP + HDBSCAN.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RecutSetting:
    """The setting that changes how finely a run is cut, after the run."""

    key: str  # the run's key for it ("k", "resolution")
    label: str  # "Metaclusters (k)", "Resolution"
    short: str  # in labels: "k=5", "res=1.0"
    minimum: float
    maximum: float
    step: float
    decimals: int
    instant: bool  # True: re-cut on the spot; False: a background job (seconds)
    help: str

    def text(self, value: Any) -> str:
        """The setting in a label, like "k=5" or "res=1.0"."""
        shown = f"{float(value):.{self.decimals}f}" if self.decimals else str(int(value))
        return f"{self.short}={shown}"


K_SETTING = RecutSetting(
    "k",
    "Metaclusters (k)",
    "k",
    2,
    40,
    1,
    0,
    True,
    "FlowSOM groups its nodes into k metaclusters. Too high splits a population in two "
    "(the lens ignores splits with the same phenotype); too low merges two.",
)
RESOLUTION_SETTING = RecutSetting(
    "resolution",
    "Resolution",
    "res",
    0.1,
    5.0,
    0.1,
    1,
    False,
    "How finely PhenoGraph divides its graph into clusters. Higher gives more, smaller "
    "clusters; lower merges them. Re-clustering takes a few seconds.",
)


@dataclass(frozen=True)
class ClusteringMethod:
    key: str
    name: str
    cluster_noun: str  # what one cluster is called in sentences ("cluster", "metacluster")
    has_noise: bool  # some events can be left out of every cluster (label -1)
    recut: RecutSetting | None  # what changes the cut after the run (None: it can't be)
    over_splits: bool  # may split one population into several clusters by design
    export_parent: str  # the population that holds a run's exported clusters
    short: str  # prefix of a cluster's default name ("UMAP Cluster 3", "Metacluster 3")
    tag_prefix: str = ""  # how plots label a cluster: "" gives "3", "M" gives "M3"

    @property
    def recuttable(self) -> bool:
        return self.recut is not None

    def setting_text(self, run: dict[str, Any]) -> str:
        """The run's cut in a label ("k=5", "res=1.0"); empty when it has none."""
        if self.recut is None or run.get(self.recut.key) is None:
            return ""
        return self.recut.text(run[self.recut.key])

    def cluster_name(self, cluster: int) -> str:
        """Default name of an exported cluster ("UMAP Cluster 3", "Metacluster 3")."""
        return f"{self.short} {cluster}"

    def tag(self, cluster: int) -> str:
        """How plots label a cluster ("3", "M3")."""
        return f"{self.tag_prefix}{cluster}"

    def cluster_label(self, cluster: int) -> str:
        """A cluster in a sentence ("cluster 3", "metacluster M3")."""
        return f"{self.cluster_noun} {self.tag(cluster)}"

    def clusters_label(self, clusters: tuple[int, ...]) -> str:
        """One or more clusters in a sentence ("metaclusters M1, M8 and M9")."""
        if len(clusters) == 1:
            return self.cluster_label(clusters[0])
        tags = [self.tag(c) for c in clusters]
        return f"{self.cluster_noun}s {', '.join(tags[:-1])} and {tags[-1]}"

    def map_caption(self, run: dict[str, Any]) -> str:
        """Caption for the run's map coloured by cluster."""
        if self.key == FLOWSOM.key:
            return f"Coloured by metacluster (FlowSOM, k = {run.get('k', '?')})"
        if self.key == PHENOGRAPH.key:
            return f"Coloured by cluster (PhenoGraph, resolution {run.get('resolution', '?')})"
        return "Coloured by cluster (HDBSCAN)"


UMAP_HDBSCAN = ClusteringMethod(
    key="umap_hdbscan",
    name="UMAP + HDBSCAN",
    cluster_noun="cluster",
    has_noise=True,
    recut=None,
    over_splits=False,
    export_parent="UMAP Reduction",
    short="UMAP Cluster",
)
FLOWSOM = ClusteringMethod(
    key="flowsom",
    name="FlowSOM",
    cluster_noun="metacluster",
    has_noise=False,
    recut=K_SETTING,
    over_splits=True,
    export_parent="FlowSOM",
    short="Metacluster",
    tag_prefix="M",
)
PHENOGRAPH = ClusteringMethod(
    key="phenograph",
    name="PhenoGraph",
    cluster_noun="cluster",
    has_noise=True,  # clusters under the minimum size are outliers (-1)
    recut=RESOLUTION_SETTING,
    over_splits=True,
    export_parent="PhenoGraph",
    short="PhenoGraph Cluster",
    tag_prefix="C",
)
METHODS = {m.key: m for m in (UMAP_HDBSCAN, FLOWSOM, PHENOGRAPH)}


def method_of(run: dict[str, Any]) -> ClusteringMethod:
    return METHODS.get(run.get("method") or UMAP_HDBSCAN.key, UMAP_HDBSCAN)
