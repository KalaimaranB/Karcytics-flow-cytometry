"""FlowSOM Tree — the standard FlowSOM picture, with a guide to reading it.

One circle per SOM node (a small group of very similar cells), sized by its
cell count; lines link each node to the nodes most like it (the minimum
spanning tree), so a branch is a family of related cells. Colour shows each
node's metacluster or how bright a marker is. Beside it, a legend says what
each metacluster is in plain words (size and the markers that set it apart),
and a k control re-cuts the metaclusters.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from karcytics_sdk.plugin.theme_fallback import Colors
from matplotlib.collections import LineCollection
from PySide6.QtCore import Signal

from .cluster_map_view import RECUT_DELAY_MS, SIDE_WIDTH, ClusterMapView, cluster_colors

GUIDE = (
    "<b>How to read this.</b> Each circle is a <b>node</b>, a small group of very similar "
    "cells (bigger circle, more cells). Lines join each node to the nodes most like it, so a "
    "branch is a family of related cells; positions and line lengths mean nothing. "
    "<b>1.</b> Colour by each marker to see which branches are bright for it. "
    "<b>2.</b> Name each <b>metacluster</b> from its phenotype on the right "
    "(e.g. CD3+ CD4+ is CD4 T cells). "
    "<b>3.</b> Check k: one branch split into several colours means k is probably too high; "
    "one colour across unrelated branches, too low."
)
K_RANGE = (2, 40)
metacluster_colors = cluster_colors

__all__ = ["K_RANGE", "RECUT_DELAY_MS", "SIDE_WIDTH", "FlowsomTreeView", "metacluster_colors"]


class FlowsomTreeView(ClusterMapView):
    """The tree, a legend of metaclusters, and the k control for one FlowSOM run."""

    GUIDE = GUIDE
    LEGEND_TITLE = "Metaclusters"
    GUIDE_NAME = "FlowsomTreeGuide"
    COLOR_COMBO_NAME = "FlowsomColorCombo"
    RECUT_NAME = "FlowsomKSpin"
    BUSY_NAME = "FlowsomBusyLabel"
    CANVAS_NAME = "FlowsomTreeCanvas"
    LEGEND_NAME = "FlowsomLegend"
    HEATMAP_NAME = "FlowsomHeatmap"
    HOVER_NAME = "FlowsomHoverLabel"

    k_changed = Signal(int)

    @property
    def _k_spin(self) -> Any:
        return self._recut_spin

    def _emit_recut(self, value: float) -> None:
        self.k_changed.emit(int(value))

    def refresh(self) -> None:
        self._counts = np.bincount(self._array("nodes"), minlength=len(self._array("layout")))
        super().refresh()

    def _circles(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        return self._array("layout"), self._counts, self._array("node_metaclusters")

    def _circle_values(self, marker: int) -> np.ndarray:
        return self._array("codes")[:, marker]

    def _draw_lines(self, ax: Any, layout: np.ndarray) -> None:
        edges = self._array("mst_edges")
        ax.add_collection(
            LineCollection(
                layout[edges], colors=Colors.FG_SECONDARY, alpha=0.55, linewidths=1.2, zorder=1
            )
        )

    def _title(self) -> str:
        n = len(self._array("layout"))
        return f"FlowSOM tree: {n} nodes, k = {self._run.get('k')} metaclusters"

    def _hover_text(self, circle: int) -> str:
        meta = int(self._array("node_metaclusters")[circle])
        total = max(int(self._counts.sum()), 1)
        return (
            f"<b>Node {circle}</b> · {self._name(meta)}<br>{self._counts[circle]:,} cells "
            f"({self._counts[circle] / total:.1%})<br>{self._phenotype(meta)}"
        )
