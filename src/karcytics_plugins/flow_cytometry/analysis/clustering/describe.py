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
class ClusterSummary:
    cluster: int
    share: float  # of all events in the run
    markers: tuple[str, ...]  # short marker names
    level: tuple[float, ...]  # per marker: 0 = dimmest cluster's median, 1 = brightest's
    informative: tuple[bool, ...]  # per marker: does it differ between clusters at all

    @property
    def phenotype(self) -> str:
        """e.g. "B220+ CD3− CD4− CD8lo" (uninformative markers left out)."""
        return " ".join(
            f"{m}{call(v)}"
            for m, v, keep in zip(self.markers, self.level, self.informative, strict=True)
            if keep
        )


def summarize_clusters(
    x: np.ndarray, clusters: np.ndarray, labels: list[str]
) -> list[ClusterSummary]:
    """One summary per cluster (noise, -1, left out), largest first."""
    ids = [int(c) for c in np.unique(clusters) if c >= 0]
    if not ids:
        return []
    medians = np.array([np.median(x[clusters == c], axis=0) for c in ids])
    low, high = medians.min(axis=0), medians.max(axis=0)
    spread = high - low
    levels = (medians - low) / np.maximum(spread, 1e-9)
    informative = tuple(bool(s >= MIN_SPREAD) for s in spread)
    markers = tuple(short_marker(label) for label in labels)
    out = [
        ClusterSummary(
            cid,
            float((clusters == cid).mean()),
            markers,
            tuple(float(v) for v in level),
            informative,
        )
        for cid, level in zip(ids, levels, strict=True)
    ]
    return sorted(out, key=lambda s: -s.share)
