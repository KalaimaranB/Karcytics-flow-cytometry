"""Do other clustering runs of the same cells report the same finding?

A finding that several methods report (UMAP + HDBSCAN, FlowSOM, PhenoGraph)
is about the gates; one that a single method reports may be about the method.

Cluster numbers mean nothing across runs, so findings are matched by what
they say:

* a cut or a merge: the same kind of finding on the same gate;
* a missed cluster: another run also misses a cluster made of mostly the
  same events (of the events both runs used).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .audit import Finding, FindingKind
from .scope import RunScope

SAME_CELLS = 0.5  # share of a missed cluster's events the other run's must hold


@dataclass(frozen=True)
class OtherRun:
    """Another run of the same population, already audited."""

    label: str  # "FlowSOM k=5", "PhenoGraph res=1.0"
    scope: RunScope
    findings: list[Finding]


@dataclass(frozen=True)
class Agreement:
    found_by: tuple[str, ...]  # the other runs that report it
    compared: int  # how many other runs there were

    @property
    def text(self) -> str:
        """The line under a finding ("Also found by FlowSOM k=5"); empty with nothing to compare."""
        if not self.compared:
            return ""
        if self.found_by:
            return "Also found by " + ", ".join(self.found_by)
        return "Only this run finds it"


def agreements(scope: RunScope, findings: list[Finding], others: list[OtherRun]) -> list[Agreement]:
    """Per finding (in order), which other runs report the same thing."""
    return [
        Agreement(
            tuple(o.label for o in others if any(_same(scope, f, o.scope, g) for g in o.findings)),
            len(others),
        )
        for f in findings
    ]


def _same(scope: RunScope, finding: Finding, other: RunScope, theirs: Finding) -> bool:
    if finding.kind is not theirs.kind:
        return False
    if finding.kind is not FindingKind.MISSED:
        return finding.population == theirs.population
    mine = _events(scope, finding)
    shared = np.intersect1d(mine, other.rows)  # events both runs used
    if not len(shared):
        return False
    return len(np.intersect1d(shared, _events(other, theirs))) / len(shared) > SAME_CELLS


def _events(scope: RunScope, finding: Finding) -> np.ndarray:
    """The sample-event positions of a finding's clusters."""
    assert scope.clusters is not None
    return scope.rows[np.isin(scope.clusters, finding.clusters)]
