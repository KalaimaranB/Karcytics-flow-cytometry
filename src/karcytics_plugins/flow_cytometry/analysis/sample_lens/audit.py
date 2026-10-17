"""Gate audit: where a sample's final populations and its clusters disagree.

Three kinds of finding, all computed on a :class:`RunScope`:

* **missed** — a cluster that no final population holds most of.
* **merges** — a final population made of two or more sizeable clusters.
* **cuts** — a cluster that one population holds only part of, the rest
  falling just outside it: the gate edge runs through the cluster.

Clustering is a second opinion, not ground truth, so a finding is a prompt to
look, not a verdict.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np

from .scope import NOISE, RunScope

MIN_CLUSTER_SHARE = 0.005  # clusters smaller than this share of the run are ignored
MISSED_BELOW = 0.3  # a cluster less than this much inside final populations was missed
CUT_RANGE = (0.2, 0.85)  # one population holding this much of a cluster cuts through it
MERGE_MIN_SHARE = 0.1  # a cluster this big a part of a population counts as one of its parts


class FindingKind(Enum):
    MISSED = "missed"
    MERGES = "merges"
    CUTS = "cuts"


@dataclass(frozen=True)
class Finding:
    kind: FindingKind
    clusters: tuple[int, ...]
    population: str | None = None  # label path of the population involved, if any
    size: int = 0  # events in the cluster (missed / cuts)
    shares: tuple[float, ...] = ()  # see `detail`

    @property
    def title(self) -> str:
        name = self.population.rsplit(" / ", 1)[-1] if self.population else ""
        if self.kind is FindingKind.MISSED:
            return f"Cluster {self.clusters[0]} isn't in any population"
        if self.kind is FindingKind.MERGES:
            return f"'{name}' holds {len(self.clusters)} different clusters"
        return f"'{name}' cuts cluster {self.clusters[0]} in two"

    @property
    def detail(self) -> str:
        if self.kind is FindingKind.MISSED:
            return (
                f"{self.size:,} events form a distinct cluster, but only "
                f"{self.shares[0]:.0%} of them are in a final population."
            )
        if self.kind is FindingKind.MERGES:
            parts = " / ".join(
                f"cluster {c}: {s:.0%}" for c, s in zip(self.clusters, self.shares, strict=True)
            )
            return f"{parts}. Separate clusters usually mean separate populations."
        return (
            f"The gate holds {self.shares[0]:.0%} of cluster {self.clusters[0]}; the rest is "
            "outside it. The edge probably runs through the population, not around it."
        )


def audit(scope: RunScope) -> list[Finding]:
    """Every disagreement between ``scope``'s final populations and its clusters."""
    if scope.clusters is None or not scope.masks:
        return []
    clusters = [
        int(c)
        for c in np.unique(scope.clusters)
        if c != NOISE and (scope.clusters == c).mean() >= MIN_CLUSTER_SHARE
    ]
    return _cluster_findings(scope, clusters) + _merge_findings(scope, clusters)


def _cluster_findings(scope: RunScope, clusters: list[int]) -> list[Finding]:
    assert scope.clusters is not None
    findings = []
    for cid in clusters:
        in_cluster = scope.clusters == cid
        size = int(in_cluster.sum())
        share = {
            path: float((mask & in_cluster).sum()) / size for path, mask in scope.masks.items()
        }
        covered = float(np.any(list(scope.masks.values()), axis=0)[in_cluster].mean())
        best, best_share = max(share.items(), key=lambda kv: kv[1])
        if covered < MISSED_BELOW:
            findings.append(Finding(FindingKind.MISSED, (cid,), size=size, shares=(covered,)))
        elif CUT_RANGE[0] < best_share < CUT_RANGE[1]:
            findings.append(
                Finding(FindingKind.CUTS, (cid,), best, size=size, shares=(best_share,))
            )
    return findings


def _merge_findings(scope: RunScope, clusters: list[int]) -> list[Finding]:
    assert scope.clusters is not None
    findings = []
    for path, mask in scope.masks.items():
        total = int(mask.sum())
        if total == 0:
            continue
        parts = [(cid, float((mask & (scope.clusters == cid)).sum()) / total) for cid in clusters]
        major = [(cid, share) for cid, share in parts if share >= MERGE_MIN_SHARE]
        if len(major) >= 2:  # noqa: PLR2004
            findings.append(
                Finding(
                    FindingKind.MERGES,
                    tuple(c for c, _ in major),
                    path,
                    shares=tuple(s for _, s in major),
                )
            )
    return findings
