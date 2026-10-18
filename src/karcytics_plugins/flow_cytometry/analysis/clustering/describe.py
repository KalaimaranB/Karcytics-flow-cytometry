"""Plain-language descriptions of clusters: how big, and their phenotype.

Each marker is called from the clusters' own medians, the way a scientist
reads a heatmap: the dimmest cluster sets "−", the brightest "+", and a
cluster in the middle third of that span is "lo" (dim). So every cluster
reads like a gated population ("B220+ CD3− CD4− CD8lo").

A marker whose medians barely differ between clusters says nothing about
them (it is on every cell, or on none) and is left out of the phenotype.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np

_CHANNEL_SUFFIX = re.compile(r"\s*\([^()]*\)$")
MIN_SPREAD = 0.1  # transformed units (0-1): less between dimmest and brightest is no signal
LO, HI = 1 / 3, 2 / 3  # level thresholds: below LO "−", from HI "+", between "lo"


def short_marker(label: str) -> str:
    """Drop the channel: "CD4 (PE-A)" becomes "CD4"; a label without a marker is kept."""
    return _CHANNEL_SUFFIX.sub("", label) or label


def call(level: float) -> str:
    """The +/lo/− call for a level (0 = dimmest cluster, 1 = brightest)."""
    if level >= HI:
        return "+"
    return "lo" if level >= LO else "−"


@dataclass(frozen=True)
class MarkerScale:
    """Per marker, the span from the dimmest cluster's median to the brightest's."""

    markers: tuple[str, ...]  # short marker names
    low: np.ndarray
    spread: np.ndarray

    @classmethod
    def from_clusters(cls, x: np.ndarray, clusters: np.ndarray, labels: list[str]) -> MarkerScale:
        ids = [c for c in np.unique(clusters) if c >= 0]
        medians = np.array([np.median(x[clusters == c], axis=0) for c in ids])
        low = medians.min(axis=0)
        return cls(tuple(short_marker(lb) for lb in labels), low, medians.max(axis=0) - low)

    @property
    def informative(self) -> tuple[bool, ...]:
        """Does each marker differ between clusters at all."""
        return tuple(bool(s >= MIN_SPREAD) for s in self.spread)

    def level(self, cells: np.ndarray) -> tuple[float, ...]:
        """Where these cells' median sits on each marker's span (0 dimmest, 1 brightest)."""
        level = (np.median(cells, axis=0) - self.low) / np.maximum(self.spread, 1e-9)
        return tuple(float(v) for v in level)

    def phenotype(self, level: tuple[float, ...]) -> str:
        """e.g. "B220+ CD3− CD4− CD8lo" (uninformative markers left out)."""
        return " ".join(
            f"{m}{call(v)}"
            for m, v, keep in zip(self.markers, level, self.informative, strict=True)
            if keep
        )

    def clearly_different(self, a: tuple[float, ...], b: tuple[float, ...]) -> bool:
        """Some marker is + for one and − for the other (lo against either doesn't count)."""
        return any(
            keep and {call(u), call(v)} == {"+", "−"}
            for u, v, keep in zip(a, b, self.informative, strict=True)
        )


@dataclass(frozen=True)
class ClusterSummary:
    cluster: int
    share: float  # of all events in the run
    scale: MarkerScale
    level: tuple[float, ...]  # per marker, on the scale

    @property
    def markers(self) -> tuple[str, ...]:
        return self.scale.markers

    @property
    def informative(self) -> tuple[bool, ...]:
        return self.scale.informative

    @property
    def phenotype(self) -> str:
        return self.scale.phenotype(self.level)


def summarize_clusters(
    x: np.ndarray, clusters: np.ndarray, labels: list[str]
) -> list[ClusterSummary]:
    """One summary per cluster (noise, -1, left out), largest first."""
    if not (clusters >= 0).any():
        return []
    scale = MarkerScale.from_clusters(x, clusters, labels)
    out = [
        ClusterSummary(int(c), float((clusters == c).mean()), scale, scale.level(x[clusters == c]))
        for c in np.unique(clusters)
        if c >= 0
    ]
    return sorted(out, key=lambda s: -s.share)
