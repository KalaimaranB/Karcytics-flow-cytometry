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

from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import Enum

import numpy as np

from ..clustering import UMAP_HDBSCAN, ClusteringMethod, ClusterSummary, method_of
from ..clustering.describe import summarize_clusters
from ..population_matching import PATH_SEP
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
    method: ClusteringMethod = UMAP_HDBSCAN  # names the clusters
    phenotypes: tuple[str, ...] = ()  # per cluster, when the run can describe them

    def _label(self, i: int) -> str:
        label = self.method.cluster_label(self.clusters[i])
        if i < len(self.phenotypes) and self.phenotypes[i]:
            label += f" ({self.phenotypes[i]})"
        return label

    @property
    def title(self) -> str:
        name = self.population.rsplit(PATH_SEP, 1)[-1] if self.population else ""
        which = self.method.clusters_label(self.clusters)
        noun = self.method.cluster_noun
        if self.kind is FindingKind.MISSED:
            verb = "isn't" if len(self.clusters) == 1 else "aren't"
            return f"{which[0].upper()}{which[1:]} {verb} in any population"
        if self.kind is FindingKind.MERGES:
            return f"'{name}' holds {len(self.clusters)} different {noun}s"
        if len(self.clusters) > 1:
            return f"'{name}' cuts through {which}"
        return f"'{name}' cuts {which} in two"

    @property
    def detail(self) -> str:
        noun = self.method.cluster_noun
        if self.kind is FindingKind.MISSED:
            phenotype = f" ({self.phenotypes[0]})" if any(self.phenotypes) else ""
            return (
                f"{self.size:,} events form a distinct {noun}{phenotype}, but only "
                f"{self.shares[0]:.0%} of them are in a final population."
            )
        if self.kind is FindingKind.MERGES:
            parts = " / ".join(f"{self._label(i)}: {s:.0%}" for i, s in enumerate(self.shares))
            why = "different phenotypes" if any(self.phenotypes) else f"separate {noun}s"
            return f"{parts}. {why[0].upper()}{why[1:]} usually mean separate populations."
        return (
            f"Of the {noun}'s cells that reach this gate, it keeps {self.shares[0]:.0%}; the "
            "rest fall just outside. The edge probably runs through the population, not "
            "around it."
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
    method = method_of(scope.run)
    summaries = _summaries(scope) if method.over_splits else {}
    cuts_ok = _same_phenotype_split(scope, summaries) if summaries else None
    findings = _cluster_findings(scope, clusters, cuts_ok) + _merge_findings(
        scope, clusters, summaries
    )
    findings = [
        replace(
            f,
            method=method,
            phenotypes=tuple(summaries[c].phenotype if c in summaries else "" for c in f.clusters),
        )
        for f in findings
    ]
    return _group_same_phenotype(findings) if summaries else findings


def _group_same_phenotype(findings: list[Finding]) -> list[Finding]:
    """One missed / cut finding per population and phenotype, not one per metacluster.

    At a high k one population is split into several metaclusters, each of
    which would otherwise repeat the same finding.
    """
    groups: dict[tuple, list[Finding]] = {}
    for f in findings:
        key = (f.kind, f.population, f.phenotypes) if f.kind is not FindingKind.MERGES else (f,)
        groups.setdefault(key, []).append(f)
    out = []
    for group in groups.values():
        first = group[0]
        if len(group) == 1:
            out.append(first)
            continue
        size = sum(f.size for f in group)
        share = sum(f.shares[0] * f.size for f in group) / max(size, 1)
        out.append(
            replace(
                first,
                clusters=tuple(c for f in group for c in f.clusters),
                size=size,
                shares=(share,),
                phenotypes=first.phenotypes[:1],
            )
        )
    return out


def _summaries(scope: RunScope) -> dict[int, ClusterSummary]:
    """Each cluster's phenotype, from the run's own events (all of them, not just scope's)."""
    x, clusters = scope.run.get("intensities"), scope.run.get("clusters")
    labels = scope.run.get("channel_labels") or scope.run.get("channels") or []
    if x is None or clusters is None or len(labels) != np.shape(x)[1]:
        return {}
    return {s.cluster: s for s in summarize_clusters(np.asarray(x), np.asarray(clusters), labels)}


def _same_phenotype_split(
    scope: RunScope, summaries: dict[int, ClusterSummary]
) -> Callable[[np.ndarray, np.ndarray], bool] | None:
    """For a method that can lump populations together: is a split of a cluster a real cut?

    A gate that keeps one part of a metacluster and drops the rest is only
    cutting a population when both parts have the same phenotype; when they
    clearly differ, the gate is separating two populations the metacluster
    lumped together.
    """
    x = scope.x
    if x is None:
        return None
    scale = next(iter(summaries.values())).scale

    def same(kept: np.ndarray, lost: np.ndarray) -> bool:
        if not kept.any() or not lost.any():
            return True
        return not scale.clearly_different(scale.level(x[kept]), scale.level(x[lost]))

    return same


def _cluster_findings(
    scope: RunScope,
    clusters: list[int],
    is_cut: Callable[[np.ndarray, np.ndarray], bool] | None = None,
) -> list[Finding]:
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
            inside = in_cluster & scope.masks[best]
            if is_cut is not None and not is_cut(inside, in_cluster & ~inside):
                continue
            culprit, kept = _where_lost(scope, best, in_cluster)
            findings.append(Finding(FindingKind.CUTS, (cid,), culprit, size=size, shares=(kept,)))
    return findings


def _where_lost(scope: RunScope, final_path: str, in_cluster: np.ndarray) -> tuple[str, float]:
    """The gate on ``final_path`` that drops the most of a cluster, and the share it keeps.

    The final population is only where the survivors end up; the edge that
    cuts the cluster can be any gate above it (within the run's scope).
    """
    parts = final_path.split(PATH_SEP)
    chain = [PATH_SEP.join(parts[: i + 1]) for i in range(len(parts))]
    reaching = in_cluster
    worst, worst_kept, worst_lost = final_path, 1.0, -1
    for path in chain:
        mask = scope.steps.get(path)
        if mask is None:  # above the run's population: every run event is inside it
            continue
        kept = reaching & mask
        lost = int(reaching.sum() - kept.sum())
        if lost > worst_lost:
            worst, worst_lost = path, lost
            worst_kept = float(kept.sum()) / max(int(reaching.sum()), 1)
        reaching = kept
    return worst, worst_kept


def _merge_findings(
    scope: RunScope, clusters: list[int], summaries: dict[int, ClusterSummary]
) -> list[Finding]:
    """Populations holding several sizeable clusters.

    With ``summaries`` (a method that can over-split, like FlowSOM at a high k),
    parts that aren't clearly different are counted as one, so over-split
    copies of one population aren't flagged.
    """
    assert scope.clusters is not None
    findings = []
    for path, mask in scope.masks.items():
        total = int(mask.sum())
        if total == 0:
            continue
        parts = [(cid, float((mask & (scope.clusters == cid)).sum()) / total) for cid in clusters]
        major = [(cid, share) for cid, share in parts if share >= MERGE_MIN_SHARE]
        if summaries:
            major = _distinct(major, summaries)
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


def _distinct(
    parts: list[tuple[int, float]], summaries: dict[int, ClusterSummary]
) -> list[tuple[int, float]]:
    """Group parts that aren't clearly different; each group is its biggest part, summed."""
    groups: list[tuple[int, float]] = []
    for cid, share in sorted(parts, key=lambda p: -p[1]):
        for i, (rep, total) in enumerate(groups):
            if (
                cid in summaries
                and rep in summaries
                and not summaries[cid].scale.clearly_different(
                    summaries[cid].level, summaries[rep].level
                )
            ):
                groups[i] = (rep, total + share)
                break
        else:
            groups.append((cid, share))
    return groups
