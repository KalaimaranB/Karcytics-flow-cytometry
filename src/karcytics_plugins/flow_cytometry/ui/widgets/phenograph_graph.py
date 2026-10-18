"""Cluster Graph — PhenoGraph's clusters and how strongly they are linked.

One circle per cluster, sized by its cell count. A line joins two clusters
whose cells are neighbours of each other; the thicker the line, the bigger
the share of the smaller cluster's links that go to the other. Thick lines
mean one population cut along a gradient; a circle with no lines is a group
that stands apart, often rare and worth a look.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from karcytics_sdk.plugin.theme_fallback import Colors
from matplotlib.collections import LineCollection
from PySide6.QtCore import Signal

from .cluster_map_view import ClusterMapView

GUIDE = (
    "<b>How to read this.</b> Each circle is a <b>cluster</b> (bigger circle, more cells). "
    "A line joins two clusters whose cells are each other's neighbours: the thicker the line, "
    "the more they are linked. Positions only keep linked clusters close. "
    "<b>1.</b> Clusters joined by thick lines are usually one population split along a "
    "gradient. <b>2.</b> A circle with no lines <b>stands apart</b>: a distinct group, often "
    "rare and worth a look. <b>3.</b> Colour by each marker and read the phenotypes on the "
    "right to name the groups."
)
LINE_WIDTH = (0.6, 6.0)  # weakest to strongest link shown, points
STANDS_APART = "stands apart"


class PhenographGraphView(ClusterMapView):
    """The cluster graph, a legend of clusters, and the resolution control for one run."""

    GUIDE = GUIDE
    LEGEND_TITLE = "Clusters"
    GUIDE_NAME = "PhenographGraphGuide"
    COLOR_COMBO_NAME = "PhenographColorCombo"
    RECUT_NAME = "PhenographResolutionSpin"
    BUSY_NAME = "PhenographBusyLabel"
    CANVAS_NAME = "PhenographGraphCanvas"
    LEGEND_NAME = "PhenographLegend"
    HEATMAP_NAME = "PhenographHeatmap"
    HOVER_NAME = "PhenographHoverLabel"

    resolution_changed = Signal(float)

    def _emit_recut(self, value: float) -> None:
        self.resolution_changed.emit(round(float(value), 2))

    def refresh(self) -> None:
        clusters = self._array("clusters")
        n = len(self._array("layout").reshape(-1, 2))
        kept = clusters[clusters >= 0]
        self._counts = np.bincount(kept, minlength=n)[:n]
        x = self._array("intensities")
        self._medians = np.array(
            [
                np.median(x[clusters == c], axis=0) if self._counts[c] else np.zeros(x.shape[1])
                for c in range(n)
            ]
        ).reshape(n, x.shape[1])
        edges = self._array("cluster_edges").reshape(-1, 2)
        self._links: dict[int, list[tuple[int, float]]] = {c: [] for c in range(n)}
        for (a, b), strength in zip(edges, self._array("cluster_connectivity"), strict=True):
            self._links[int(a)].append((int(b), float(strength)))
            self._links[int(b)].append((int(a), float(strength)))
        super().refresh()

    def stands_apart(self, cluster: int) -> bool:
        """No link to any other cluster: a distinct group."""
        return not self._links.get(cluster)

    def _legend_note(self, cluster: int) -> str:
        return STANDS_APART if self.stands_apart(cluster) else ""

    def _circles(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        layout = self._array("layout").reshape(-1, 2)
        return layout, self._counts, np.arange(len(layout))

    def _circle_values(self, marker: int) -> np.ndarray:
        return self._medians[:, marker]

    def _draw_lines(self, ax: Any, layout: np.ndarray) -> None:
        edges = self._array("cluster_edges").reshape(-1, 2)
        if not len(edges):
            return
        strength = self._array("cluster_connectivity")
        share = strength / max(float(strength.max()), 1e-12)
        ax.add_collection(
            LineCollection(
                layout[edges],
                colors=Colors.FG_SECONDARY,
                alpha=0.35 + 0.45 * share,
                linewidths=LINE_WIDTH[0] + (LINE_WIDTH[1] - LINE_WIDTH[0]) * share,
                zorder=1,
            )
        )

    def _title(self) -> str:
        n = len(self._counts)
        apart = sum(self.stands_apart(c) for c in range(n))
        tail = f", {apart} standing apart" if apart else ""
        return f"PhenoGraph: {n} clusters at resolution {self._run.get('resolution')}{tail}"

    def _hover_radius(self) -> float:
        return 0.5

    def _hover_text(self, circle: int) -> str:
        total = max(int(self._counts.sum()), 1)
        links = sorted(self._links.get(circle, []), key=lambda link: -link[1])
        if links:
            linked = ", ".join(f"{self._name(c)} ({s:.0%})" for c, s in links[:3])
            relation = f"Linked to {linked} of its links"
        else:
            relation = "No links: it stands apart from every other cluster."
        return (
            f"<b>{self._name(circle)}</b> · {self._counts[circle]:,} cells "
            f"({self._counts[circle] / total:.1%})<br>{self._phenotype(circle)}<br>{relation}"
        )
