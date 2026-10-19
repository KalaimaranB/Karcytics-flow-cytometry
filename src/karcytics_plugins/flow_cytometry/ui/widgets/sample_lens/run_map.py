"""The run's map twice: coloured by final population, and by cluster.

The map is the run's embedding: a UMAP, or for FlowSOM each event drawn
around its node in the tree (with the tree's lines behind), or for PhenoGraph
each event drawn around its cluster (with the cluster links behind).

Where the two colourings disagree, the gating probably has a mistake; the
findings are circled. Clicking a cluster emits ``cluster_clicked``.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any

import numpy as np
from karcytics_sdk.plugin.theme_fallback import Colors
from matplotlib.collections import LineCollection
from matplotlib.colors import to_rgba_array
from matplotlib.figure import Figure
from matplotlib.patches import Circle
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget

from ....analysis.clustering import method_of
from ....analysis.sample_lens import NOISE, Finding, RunScope
from ...graph._mpl_compat import LockedFigureCanvas
from ..cluster_scatter_draw import style_embedding_axes
from ._style import card, palette_color

if TYPE_CHECKING:
    from matplotlib.axes import Axes

_LABEL = {"missed": "missed", "merges": "merged", "cuts": "cut"}


NODE_RING = 0.6  # tree-edge lengths: a ring around one FlowSOM node


def _rings(scope: RunScope, cid: int, spread: float) -> list[tuple[np.ndarray, float]]:
    """Where to circle a cluster: around its cells, or (FlowSOM tree) around each of its nodes.

    A metacluster can sit on several branches, so one circle around all its
    cells would cover most of the tree. Its biggest node comes first.
    """
    run = scope.run
    if run.get("embedding_kind") == "tree" and run.get("node_metaclusters") is not None:
        members = np.flatnonzero(np.asarray(run["node_metaclusters"]) == cid)
        counts = np.bincount(np.asarray(run["nodes"]), minlength=len(run["layout"]))[members]
        layout = np.asarray(run["layout"])
        return [(layout[n], NODE_RING) for n in members[np.argsort(-counts)]]
    assert scope.clusters is not None
    points = scope.embedding[scope.clusters == cid]
    center = np.median(points, axis=0)
    radius = max(float(np.percentile(np.linalg.norm(points - center, axis=1), 90)), spread * 0.03)
    return [(center, radius)]


def _draw_tree(ax: Axes, run: dict[str, Any]) -> None:
    """A FlowSOM run's node tree or a PhenoGraph run's cluster links, behind its events.

    Nothing for a UMAP run. PhenoGraph's lines are as thick as the clusters are linked.
    """
    kind = run.get("embedding_kind")
    if kind not in ("tree", "graph") or run.get("layout") is None:
        return
    layout = np.asarray(run["layout"]).reshape(-1, 2)
    widths: Any = 0.8
    if kind == "tree":
        edges = np.asarray(run["mst_edges"])
    else:
        edges = np.asarray(run.get("cluster_edges", [])).reshape(-1, 2)
        strength = np.asarray(run.get("cluster_connectivity", []), dtype=float)
        widths = 0.5 + 3.0 * strength / max(float(strength.max()), 1e-12) if len(strength) else 0.8
    if len(edges):
        ax.add_collection(
            LineCollection(layout[edges], colors=Colors.FG_SECONDARY, alpha=0.35, linewidths=widths)
        )


def _scope_key(
    scope: RunScope | None,
    population_colors: dict[str, str],
    selected_path: str | None,
    findings: list[Finding],
    emphasis: tuple[int, ...],
) -> tuple:
    """Everything the map's picture depends on (a new scope object can draw the same)."""
    if scope is None:
        return (None,)
    digest = hashlib.blake2b(digest_size=16)
    for array in (scope.rows, scope.embedding, scope.clusters, *scope.masks.values()):
        if array is not None:
            digest.update(np.ascontiguousarray(array).tobytes())
    return (
        id(scope.run),
        tuple(scope.masks),
        digest.hexdigest(),
        tuple(sorted(population_colors.items())),
        selected_path,
        tuple(f.title for f in findings),
        emphasis,
    )


class RunMap(QWidget):
    cluster_clicked = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        frame = card("lens_map_card", "BG_DARK")
        frame_layout = QVBoxLayout(frame)
        frame_layout.setContentsMargins(6, 6, 6, 6)
        self._canvas = LockedFigureCanvas(Figure(layout="constrained"))
        self._canvas.mpl_connect("button_press_event", self._on_click)
        frame_layout.addWidget(self._canvas)
        layout.addWidget(frame)
        self._scope: RunScope | None = None
        self._cluster_ax: Axes | None = None
        self._shown: tuple | None = None  # what the figure shows, to skip a repeat

    def forget_drawn(self) -> None:
        """Make the next show_scope redraw (a theme change, say)."""
        self._shown = None

    def show_scope(
        self,
        scope: RunScope | None,
        population_colors: dict[str, str],
        selected_path: str | None,
        findings: list[Finding],
        emphasis: tuple[int, ...] = (),
    ) -> None:
        self._scope = scope
        shown = _scope_key(scope, population_colors, selected_path, findings, emphasis)
        if shown == self._shown:
            return  # redrawing tens of thousands of points to the same picture
        self._shown = shown
        fig = self._canvas.figure
        fig.clear()
        fig.set_facecolor(Colors.BG_DARK)
        self._cluster_ax = None
        if scope is None or scope.n == 0:
            fig.text(
                0.5,
                0.5,
                "The map needs a clustering run.\nBackgating above works without one.",
                ha="center",
                va="center",
                color=Colors.FG_SECONDARY,
                fontsize=10,
            )
            self._canvas.draw_idle()
            return

        gates_ax, clusters_ax = fig.subplots(1, 2)
        for ax in (gates_ax, clusters_ax):
            _draw_tree(ax, scope.run)
        self._draw_by_population(gates_ax, scope, population_colors, selected_path)
        if scope.clusters is not None:
            self._draw_by_cluster(clusters_ax, scope)
            self._cluster_ax = clusters_ax
            self._circle_findings((gates_ax, clusters_ax), scope, findings, emphasis)
        else:
            style_embedding_axes(clusters_ax, "No clusters in this run")
        self._canvas.draw_idle()

    def _draw_by_population(
        self,
        ax: Axes,
        scope: RunScope,
        colors: dict[str, str],
        selected: str | None,
    ) -> None:
        style_embedding_axes(ax, "Coloured by your final populations")
        point_colors = np.full(scope.n, Colors.BG_LIGHT, dtype=object)
        for path, mask in scope.masks.items():
            point_colors[mask] = colors.get(path, Colors.FG_SECONDARY)
        # Events in no final population go on top: a gate cutting an island shows as a grey slice.
        order = np.argsort(point_colors != Colors.BG_LIGHT, kind="stable")[::-1]
        emb = scope.embedding[order]
        rgba = to_rgba_array(list(point_colors[order]))
        rgba[:, 3] = 0.8
        if selected in scope.masks:  # fade the other populations, keep the ungated visible
            other = (point_colors[order] != Colors.BG_LIGHT) & ~scope.masks[selected][order]
            rgba[other, 3] = 0.15
        ax.scatter(emb[:, 0], emb[:, 1], c=rgba, s=2, linewidths=0, rasterized=True)
        handles = [
            ax.scatter([], [], c=colors.get(p.path, Colors.FG_SECONDARY), s=14, label=p.name)
            for p in scope.final_populations
        ]
        handles.append(ax.scatter([], [], c=Colors.BG_LIGHT, s=14, label="in no final population"))
        legend = ax.legend(
            handles=handles,
            fontsize=7,
            loc="upper right",  # fixed: "best" costs ~0.2 s a draw on this many points
            frameon=True,
            facecolor=Colors.BG_DARK,
            edgecolor=Colors.BORDER,
            framealpha=0.9,
        )
        for text in legend.get_texts():
            text.set_color(Colors.FG_SECONDARY)

    def _draw_by_cluster(self, ax: Axes, scope: RunScope) -> None:
        assert scope.clusters is not None
        method = method_of(scope.run)
        style_embedding_axes(ax, method.map_caption(scope.run))
        colors = np.array(
            [Colors.BG_LIGHT if c == NOISE else palette_color(int(c)) for c in scope.clusters],
            dtype=object,
        )
        ax.scatter(
            scope.embedding[:, 0],
            scope.embedding[:, 1],
            c=list(colors),
            s=2,
            alpha=0.8,
            linewidths=0,
            rasterized=True,
        )
        for cid in np.unique(scope.clusters):
            if cid == NOISE:
                continue
            cx, cy = np.median(scope.embedding[scope.clusters == cid], axis=0)
            ax.text(
                cx,
                cy,
                method.tag(int(cid)),
                color=Colors.FG_PRIMARY,
                fontsize=9,
                fontweight="bold",
                ha="center",
                va="center",
            )

    def _circle_findings(
        self,
        axes: tuple[Axes, Axes],
        scope: RunScope,
        findings: list[Finding],
        emphasis: tuple[int, ...],
    ) -> None:
        assert scope.clusters is not None
        spread = float(np.ptp(scope.embedding, axis=0).max()) or 1.0
        # One ring and one label per cluster: findings sharing a cluster used
        # to stack their labels on the same spot. The numbers match the cards.
        labels: dict[int, list[str]] = {}
        for number, finding in enumerate(findings, start=1):
            word = f"{number} {_LABEL[finding.kind.value]}"
            for cid in dict.fromkeys(finding.clusters):
                labels.setdefault(cid, []).append(word)
        for cid, words in labels.items():
            rings = _rings(scope, cid, spread)
            strong = cid in emphasis
            for ax in axes:
                for center, radius in rings:
                    ax.add_patch(
                        Circle(
                            tuple(center),
                            radius,
                            fill=False,
                            edgecolor=Colors.ACCENT_WARNING,
                            linewidth=2.4 if strong else 1.1,
                            linestyle="--",
                        )
                    )
            center, radius = rings[0]
            axes[0].annotate(
                " · ".join(words),
                (center[0], center[1] + radius),
                color=Colors.ACCENT_WARNING,
                fontsize=8,
                ha="center",
                va="bottom",
                fontweight="bold" if strong else "normal",
                bbox={
                    "boxstyle": "round,pad=0.2",
                    "fc": Colors.BG_DARK,
                    "ec": "none",
                    "alpha": 0.8,
                },
            )

    def _on_click(self, event: Any) -> None:
        scope = self._scope
        if scope is None or scope.clusters is None or event.inaxes is not self._cluster_ax:
            return
        if event.xdata is None or event.ydata is None:
            return
        dist = np.hypot(scope.embedding[:, 0] - event.xdata, scope.embedding[:, 1] - event.ydata)
        cid = int(scope.clusters[int(np.argmin(dist))])
        if cid != NOISE:
            self.cluster_clicked.emit(cid)
