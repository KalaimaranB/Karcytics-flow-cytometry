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

import matplotlib as mpl
import numpy as np
from karcytics_sdk.plugin.components import BioComboBox, BioListWidget, BioSpinBox
from karcytics_sdk.plugin.rendering.lock import MPL_RASTER_LOCK
from karcytics_sdk.plugin.rendering.mpl_canvas import LockedFigureCanvas
from karcytics_sdk.plugin.theme_fallback import Colors
from matplotlib import patheffects
from matplotlib.collections import LineCollection
from matplotlib.figure import Figure
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QListWidgetItem, QVBoxLayout, QWidget

from ...analysis.clustering import call, short_marker, summarize_clusters

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
K_HELP = (
    "Metaclusters (k): how many populations FlowSOM splits the nodes into. Too high splits "
    "one population in two; too low merges two. Changing it is instant."
)
MIN_SIZE, MAX_SIZE = 30.0, 520.0  # circle area range, points²
RECUT_DELAY_MS = 350
K_RANGE = (2, 40)
SIDE_WIDTH = 330


def metacluster_colors(n: int) -> list[tuple[float, ...]]:
    """The same per-metacluster colours the scatter plots use (tab20)."""
    cmap = mpl.colormaps["tab20"]
    return [cmap(i % 20) for i in range(n)]


def _dot(rgba: tuple[float, ...], size: int = 12) -> QIcon:
    """A coloured dot (row colours are overridden by the list's stylesheet; icons aren't)."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor.fromRgbF(*rgba))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(1, 1, size - 2, size - 2)
    painter.end()
    return QIcon(pixmap)


class FlowsomTreeView(QWidget):
    """The tree, a legend of metaclusters, and the k control for one FlowSOM run."""

    k_changed = Signal(int)

    def __init__(self, run: dict[str, Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._run = run
        self._recut_timer = QTimer(self)
        self._recut_timer.setSingleShot(True)
        self._recut_timer.setInterval(RECUT_DELAY_MS)
        self._recut_timer.timeout.connect(lambda: self.k_changed.emit(self._k_spin.value()))
        self._setup_ui()
        self.refresh()

    # ── UI ────────────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        guide = QLabel(GUIDE)
        guide.setObjectName("FlowsomTreeGuide")
        guide.setWordWrap(True)
        guide.setStyleSheet(
            f"color: {Colors.FG_SECONDARY}; background: {Colors.BG_MEDIUM}; "
            f"border: 1px solid {Colors.BORDER}; border-radius: 4px; padding: 8px; font-size: 11px;"
        )
        layout.addWidget(guide)
        layout.addLayout(self._build_toolbar())

        body = QHBoxLayout()
        self._figure = Figure(facecolor=Colors.BG_DARK)
        self._canvas = LockedFigureCanvas(self._figure)
        self._canvas.setObjectName("FlowsomTreeCanvas")
        self._canvas.setMinimumHeight(380)
        self._canvas.mpl_connect("motion_notify_event", self._on_hover)
        body.addWidget(self._canvas, stretch=3)
        body.addWidget(self._build_side())
        layout.addLayout(body, stretch=1)

    def _build_toolbar(self) -> QHBoxLayout:
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("Colour by:"))
        self._color_combo = BioComboBox()
        self._color_combo.setObjectName("FlowsomColorCombo")
        self._color_combo.addItem("Metacluster", None)
        for i, marker in enumerate(self._markers):
            self._color_combo.addItem(f"Marker: {marker}", i)
        self._color_combo.currentIndexChanged.connect(lambda _i: self._draw())
        toolbar.addWidget(self._color_combo)
        toolbar.addSpacing(16)
        k_label = QLabel("Metaclusters (k):")
        k_label.setToolTip(K_HELP)
        toolbar.addWidget(k_label)
        self._k_spin = BioSpinBox()
        self._k_spin.setObjectName("FlowsomKSpin")
        self._k_spin.setRange(*K_RANGE)
        self._k_spin.setToolTip(K_HELP)
        self._k_spin.setValue(int(self._run.get("k", 10)))
        self._k_spin.valueChanged.connect(lambda _v: self._recut_timer.start())
        toolbar.addWidget(self._k_spin)
        toolbar.addStretch()
        return toolbar

    def _build_side(self) -> QWidget:
        side = QVBoxLayout()
        legend_title = QLabel("Metaclusters")
        legend_title.setStyleSheet(f"color: {Colors.FG_PRIMARY}; font-weight: bold;")
        side.addWidget(legend_title)
        hint = QLabel(
            "Share of cells and phenotype. Per marker, the dimmest metacluster is − and the "
            "brightest +; lo is in between. Markers that barely differ are left out."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {Colors.FG_SECONDARY}; font-size: 10px;")
        side.addWidget(hint)
        self._legend = BioListWidget()
        self._legend.setObjectName("FlowsomLegend")
        self._legend.setWordWrap(True)
        side.addWidget(self._legend, stretch=1)
        heat_title = QLabel("Phenotype heatmap")
        heat_title.setStyleSheet(f"color: {Colors.FG_PRIMARY}; font-weight: bold;")
        side.addWidget(heat_title)
        self._heat_figure = Figure(facecolor=Colors.BG_DARK)
        self._heat_canvas = LockedFigureCanvas(self._heat_figure)
        self._heat_canvas.setObjectName("FlowsomHeatmap")
        self._heat_canvas.setMinimumHeight(220)
        side.addWidget(self._heat_canvas, stretch=1)
        self._hover_lbl = QLabel("Hover a circle to see its cells.")
        self._hover_lbl.setObjectName("FlowsomHoverLabel")
        self._hover_lbl.setWordWrap(True)
        self._hover_lbl.setStyleSheet(f"color: {Colors.FG_SECONDARY}; font-size: 11px;")
        side.addWidget(self._hover_lbl)
        side_widget = QWidget()
        side_widget.setLayout(side)
        side_widget.setFixedWidth(SIDE_WIDTH)
        return side_widget

    # ── Data ──────────────────────────────────────────────────────────

    @property
    def _labels(self) -> list[str]:
        return list(self._run.get("channel_labels") or self._run.get("channels", []))

    @property
    def _markers(self) -> list[str]:
        return [short_marker(label) for label in self._labels]

    def _array(self, key: str) -> np.ndarray:
        return np.asarray(self._run[key])

    def refresh(self) -> None:
        """Redraw after the run changed (e.g. re-cut)."""
        nodes = self._array("nodes")
        self._counts = np.bincount(nodes, minlength=len(self._array("layout")))
        self._k_spin.blockSignals(True)
        self._k_spin.setValue(int(self._run.get("k", self._k_spin.value())))
        self._k_spin.blockSignals(False)
        self._summaries = summarize_clusters(
            self._array("intensities"), self._array("clusters"), self._labels
        )
        self._fill_legend()
        self._draw()

    def _fill_legend(self) -> None:
        self._legend.clear()
        names = self._run.get("cluster_names", {})
        colors = metacluster_colors(int(self._array("node_metaclusters").max()) + 1)
        for summary in self._summaries:
            name = names.get(str(summary.cluster)) or f"M{summary.cluster}"
            text = f"{name} · {summary.share:.0%} · {summary.phenotype}"
            item = QListWidgetItem(_dot(colors[summary.cluster]), text)
            item.setToolTip(text)
            self._legend.addItem(item)

    def _node_colors(self) -> tuple[Any, Any]:
        """Each node's colour, and the marker scale (None when colouring by metacluster).

        A marker's scale spans its nodes' own range, dimmest to brightest node,
        so differences between nodes show even when they are small.
        """
        marker = self._color_combo.currentData()
        if marker is None:
            meta = self._array("node_metaclusters")
            palette = metacluster_colors(int(meta.max()) + 1)
            return [palette[m] for m in meta], None
        codes = self._array("codes")[:, marker]
        norm = mpl.colors.Normalize(float(codes.min()), float(codes.max()) or 1.0)
        return mpl.colormaps["viridis"](norm(codes)), norm

    def _draw(self) -> None:
        # Agg is shared with the gallery's background renders: build under the lock.
        with MPL_RASTER_LOCK:
            self._draw_figure()
            self._draw_heatmap()
        self._canvas.draw_idle()
        self._heat_canvas.draw_idle()

    def _draw_heatmap(self) -> None:
        """Metaclusters × markers, coloured by where each median sits in the marker's range."""
        self._heat_figure.clear()
        ax = self._heat_figure.add_subplot(111)
        names = self._run.get("cluster_names", {})
        rows = [names.get(str(s.cluster)) or f"M{s.cluster}" for s in self._summaries]
        levels = np.array([s.level for s in self._summaries])
        if self._summaries:  # markers that don't differ: blank, as in the legend
            levels[:, ~np.array(self._summaries[0].informative)] = np.nan
        cmap = mpl.colormaps["viridis"].with_extremes(bad=Colors.BG_MEDIUM)
        ax.imshow(levels, cmap=cmap, vmin=0, vmax=1, aspect="auto")
        for (r, c), v in np.ndenumerate(levels):
            if np.isnan(v):
                continue
            ax.text(
                c,
                r,
                call(v),
                ha="center",
                va="center",
                fontsize=7,
                color="black" if v >= 0.5 else "white",  # noqa: PLR2004 (viridis midpoint)
            )
        ax.set_xticks(range(len(self._markers)), self._markers, rotation=45, ha="right")
        ax.set_yticks(range(len(rows)), rows)
        ax.tick_params(colors=Colors.FG_SECONDARY, labelsize=7, length=0)
        for spine in ax.spines.values():
            spine.set_visible(False)
        self._heat_figure.tight_layout()

    def _draw_figure(self) -> None:
        self._figure.clear()
        ax = self._figure.add_subplot(111)
        ax.set_facecolor(Colors.BG_DARK)
        ax.set_axis_off()
        layout = self._array("layout")
        edges = self._array("mst_edges")
        ax.add_collection(
            LineCollection(
                layout[edges], colors=Colors.FG_SECONDARY, alpha=0.55, linewidths=1.2, zorder=1
            )
        )
        sizes = MIN_SIZE + (MAX_SIZE - MIN_SIZE) * np.sqrt(
            self._counts / max(self._counts.max(), 1)
        )
        colors, norm = self._node_colors()
        ax.scatter(
            layout[:, 0],
            layout[:, 1],
            s=sizes,
            c=colors,
            edgecolors=Colors.BG_DARKEST,
            linewidths=0.8,
            zorder=2,
        )
        if norm is not None:
            marker = self._markers[self._color_combo.currentData()]
            mappable = mpl.cm.ScalarMappable(cmap="viridis", norm=norm)
            cbar = self._figure.colorbar(mappable, ax=ax, fraction=0.04, pad=0.02)
            cbar.set_label(
                f"{marker}: dimmest to brightest node", color=Colors.FG_SECONDARY, fontsize=8
            )
            cbar.ax.yaxis.set_tick_params(colors=Colors.FG_SECONDARY, labelsize=7)
        else:
            self._label_metaclusters(ax, layout)
        ax.set_title(
            f"FlowSOM tree: {len(layout)} nodes, k = {self._run.get('k')} metaclusters",
            color=Colors.FG_PRIMARY,
            fontsize=10,
            fontweight="bold",
        )
        ax.set_aspect("equal", "datalim")
        self._figure.tight_layout()

    def _label_metaclusters(self, ax: Any, layout: np.ndarray) -> None:
        """Name each metacluster at its biggest node, so colours read without the legend."""
        meta = self._array("node_metaclusters")
        names = self._run.get("cluster_names", {})
        for m in np.unique(meta):
            members = np.flatnonzero(meta == m)
            anchor = members[np.argmax(self._counts[members])]
            ax.annotate(
                names.get(str(m)) or f"M{m}",
                layout[anchor],
                xytext=(0, 9),
                textcoords="offset points",
                ha="center",
                color=Colors.FG_PRIMARY,
                fontsize=8,
                fontweight="bold",
                zorder=3,
                path_effects=[patheffects.withStroke(linewidth=3, foreground=Colors.BG_DARKEST)],
            )

    def _on_hover(self, event: Any) -> None:
        if event.inaxes is None or event.xdata is None:
            return
        layout = self._array("layout")
        dist = np.hypot(layout[:, 0] - event.xdata, layout[:, 1] - event.ydata)
        node = int(np.argmin(dist))
        if dist[node] > 0.6:  # noqa: PLR2004 (tree-edge lengths)
            return
        meta = int(self._array("node_metaclusters")[node])
        total = max(int(self._counts.sum()), 1)
        summary = next((s for s in self._summaries if s.cluster == meta), None)
        phenotype = summary.phenotype if summary is not None else ""
        name = self._run.get("cluster_names", {}).get(str(meta)) or f"M{meta}"
        self._hover_lbl.setText(
            f"<b>Node {node}</b> · {name}<br>{self._counts[node]:,} cells "
            f"({self._counts[node] / total:.1%})<br>{phenotype}"
        )
        self._hover_lbl.setTextFormat(Qt.TextFormat.RichText)
