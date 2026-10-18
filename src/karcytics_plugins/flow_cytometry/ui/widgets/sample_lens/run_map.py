"""The run's UMAP twice: coloured by final population, and by cluster.

Where the two colourings disagree, the gating probably has a mistake; the
findings are circled. Clicking a cluster emits ``cluster_clicked``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np
from karcytics_sdk.plugin.theme_fallback import Colors
from matplotlib.colors import to_rgba_array
from matplotlib.figure import Figure
from matplotlib.patches import Circle
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget

from ....analysis.sample_lens import NOISE, Finding, RunScope
from ...graph._mpl_compat import LockedFigureCanvas
from ..cluster_scatter_draw import style_embedding_axes
from ._style import card, palette_color

if TYPE_CHECKING:
    from matplotlib.axes import Axes

_LABEL = {"missed": "missed", "merges": "merged", "cuts": "cut"}


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

    def show_scope(
        self,
        scope: RunScope | None,
        population_colors: dict[str, str],
        selected_path: str | None,
        findings: list[Finding],
        emphasis: tuple[int, ...] = (),
    ) -> None:
        self._scope = scope
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
        legend = ax.legend(handles=handles, fontsize=7, loc="best", frameon=False)
        for text in legend.get_texts():
            text.set_color(Colors.FG_SECONDARY)

    def _draw_by_cluster(self, ax: Axes, scope: RunScope) -> None:
        assert scope.clusters is not None
        style_embedding_axes(ax, "Coloured by cluster (HDBSCAN)")
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
                str(cid),
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
        for finding in findings:
            for cid in finding.clusters:
                points = scope.embedding[scope.clusters == cid]
                center = np.median(points, axis=0)
                radius = max(
                    float(np.percentile(np.linalg.norm(points - center, axis=1), 90)), spread * 0.03
                )
                strong = cid in emphasis
                for ax in axes:
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
                axes[0].annotate(
                    _LABEL[finding.kind.value],
                    (center[0], center[1] + radius),
                    color=Colors.ACCENT_WARNING,
                    fontsize=8,
                    ha="center",
                    va="bottom",
                    fontweight="bold" if strong else "normal",
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
