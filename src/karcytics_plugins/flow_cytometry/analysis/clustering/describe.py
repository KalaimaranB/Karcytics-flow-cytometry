"""Plain-language descriptions of clusters: how big, and which markers set them apart."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

STANDS_OUT = 0.5  # a marker stands out when the cluster's median is this many IQRs off
MAX_MARKERS = 3


@dataclass(frozen=True)
class ClusterSummary:
    cluster: int
    share: float  # of all events in the run
    up: tuple[str, ...]  # markers brighter than in the rest of the run
    down: tuple[str, ...]  # markers dimmer than in the rest of the run

    @property
    def signature(self) -> str:
        """e.g. "CD4↑ CD8↓"; empty when nothing stands out."""
        return " ".join([f"{m}↑" for m in self.up] + [f"{m}↓" for m in self.down])


def summarize_clusters(
    x: np.ndarray, clusters: np.ndarray, labels: list[str]
) -> list[ClusterSummary]:
    """One summary per cluster (noise, -1, left out), largest first.

    A marker is listed when the cluster's median differs from the whole run's
    median by more than half the run's interquartile range; the strongest few
    are kept.
    """
    overall = np.median(x, axis=0)
    q1, q3 = np.percentile(x, [25, 75], axis=0)
    spread = np.maximum(q3 - q1, 1e-9)
    out = []
    for cid in np.unique(clusters):
        if cid < 0:
            continue
        inside = clusters == cid
        effect = (np.median(x[inside], axis=0) - overall) / spread
        strongest = [i for i in np.argsort(-np.abs(effect)) if abs(effect[i]) > STANDS_OUT]
        strongest = strongest[:MAX_MARKERS]
        out.append(
            ClusterSummary(
                cluster=int(cid),
                share=float(inside.mean()),
                up=tuple(labels[i] for i in strongest if effect[i] > 0),
                down=tuple(labels[i] for i in strongest if effect[i] < 0),
            )
        )
    return sorted(out, key=lambda s: -s.share)
