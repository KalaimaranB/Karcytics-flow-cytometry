"""The shared frame of a clustering method's own picture (FlowSOM tree, PhenoGraph graph).

A guide to reading it, a colour-by menu and the method's re-cut control above;
the picture (circles joined by lines) on the left; on the right a legend that
says what each cluster is (share of cells and +/− phenotype), a phenotype
heatmap, and what's under the mouse. Subclasses say what the circles and
lines are.
"""

from __future__ import annotations

from typing import Any

import matplotlib as mpl
import numpy as np
from karcytics_sdk.plugin.components import (
    BioComboBox,
    BioDoubleSpinBox,
    BioListWidget,
    BioSpinBox,
)
from karcytics_sdk.plugin.rendering.lock import MPL_RASTER_LOCK
from karcytics_sdk.plugin.rendering.mpl_canvas import LockedFigureCanvas
from karcytics_sdk.plugin.theme_fallback import Colors
from matplotlib import patheffects
from matplotlib.figure import Figure
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QListWidgetItem, QVBoxLayout, QWidget

from ...analysis.clustering import call, method_of, short_marker, summarize_clusters

MIN_SIZE, MAX_SIZE = 30.0, 520.0  # circle area range, points²
RECUT_DELAY_MS = 350
SIDE_WIDTH = 330


def cluster_colors(n: int) -> list[tuple[float, ...]]:
    """The same per-cluster colours the scatter plots use (tab20)."""
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


class ClusterMapView(QWidget):
    """Guide, colour-by and re-cut controls, the picture, legend, heatmap and hover."""

    GUIDE = ""
    LEGEND_TITLE = "Clusters"
    # objectNames, spelled out in each subclass (Academy steps target them by name)
    GUIDE_NAME = "ClusterGuide"
    COLOR_COMBO_NAME = "ClusterColorCombo"
    RECUT_NAME = "ClusterRecutSpin"
    BUSY_NAME = "ClusterBusyLabel"
    CANVAS_NAME = "ClusterCanvas"
    LEGEND_NAME = "ClusterLegend"
    HEATMAP_NAME = "ClusterHeatmap"
    HOVER_NAME = "ClusterHoverLabel"

    def __init__(self, run: dict[str, Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._run = run
        self._method = method_of(run)
        self._recut_timer = QTimer(self)
        self._recut_timer.setSingleShot(True)
        self._recut_timer.setInterval(RECUT_DELAY_MS)
        self._recut_timer.timeout.connect(lambda: self._emit_recut(self._recut_spin.value()))
        self._setup_ui()
        self.refresh()

    # ── What subclasses provide ────────────────────────────────────────

    def _emit_recut(self, value: float) -> None:
        raise NotImplementedError

    def _circles(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Each circle's position, cell count and cluster."""
        raise NotImplementedError

    def _circle_values(self, marker: int) -> np.ndarray:
        """Each circle's median ``marker`` value, for colouring by it."""
        raise NotImplementedError

    def _draw_lines(self, ax: Any, layout: np.ndarray) -> None:
        raise NotImplementedError

    def _title(self) -> str:
        raise NotImplementedError

    def _hover_text(self, circle: int) -> str:
        raise NotImplementedError

    # ── UI ────────────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        guide = QLabel(self.GUIDE)
        guide.setObjectName(self.GUIDE_NAME)
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
        self._canvas.setObjectName(self.CANVAS_NAME)
        self._canvas.setMinimumHeight(380)
        self._canvas.mpl_connect("motion_notify_event", self._on_hover)
        body.addWidget(self._canvas, stretch=3)
        body.addWidget(self._build_side())
        layout.addLayout(body, stretch=1)

    def _build_toolbar(self) -> QHBoxLayout:
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("Colour by:"))
        self._color_combo = BioComboBox()
        self._color_combo.setObjectName(self.COLOR_COMBO_NAME)
        self._color_combo.addItem(self._method.cluster_noun.capitalize(), None)
        for i, marker in enumerate(self._markers):
            self._color_combo.addItem(f"Marker: {marker}", i)
        self._color_combo.currentIndexChanged.connect(lambda _i: self._draw())
        toolbar.addWidget(self._color_combo)
        toolbar.addSpacing(16)
        setting = self._method.recut
        assert setting is not None  # only re-cuttable methods have their own view
        label = QLabel(f"{setting.label}:")
        label.setToolTip(setting.help)
        toolbar.addWidget(label)
        self._recut_spin: BioSpinBox | BioDoubleSpinBox
        if setting.decimals:
            self._recut_spin = BioDoubleSpinBox()
            self._recut_spin.setDecimals(setting.decimals)
            self._recut_spin.setSingleStep(setting.step)
            self._recut_spin.setRange(setting.minimum, setting.maximum)
        else:
            self._recut_spin = BioSpinBox()
            self._recut_spin.setRange(int(setting.minimum), int(setting.maximum))
        self._recut_spin.setObjectName(self.RECUT_NAME)
        self._recut_spin.setToolTip(setting.help)
        self._show_setting()
        self._recut_spin.valueChanged.connect(lambda _v: self._recut_timer.start())
        toolbar.addWidget(self._recut_spin)
        self._busy_lbl = QLabel("")
        self._busy_lbl.setObjectName(self.BUSY_NAME)
        self._busy_lbl.setStyleSheet(f"color: {Colors.FG_SECONDARY}; font-size: 11px;")
        toolbar.addWidget(self._busy_lbl)
        toolbar.addStretch()
        return toolbar

    def _build_side(self) -> QWidget:
        side = QVBoxLayout()
        legend_title = QLabel(self.LEGEND_TITLE)
        legend_title.setStyleSheet(f"color: {Colors.FG_PRIMARY}; font-weight: bold;")
        side.addWidget(legend_title)
        noun = self._method.cluster_noun
        hint = QLabel(
            f"Share of cells and phenotype. Per marker, the dimmest {noun} is − and the "
            "brightest +; lo is in between. Markers that barely differ are left out."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {Colors.FG_SECONDARY}; font-size: 10px;")
        side.addWidget(hint)
        self._legend = BioListWidget()
        self._legend.setObjectName(self.LEGEND_NAME)
        self._legend.setWordWrap(True)
        side.addWidget(self._legend, stretch=1)
        heat_title = QLabel("Phenotype heatmap")
        heat_title.setStyleSheet(f"color: {Colors.FG_PRIMARY}; font-weight: bold;")
        side.addWidget(heat_title)
        self._heat_figure = Figure(facecolor=Colors.BG_DARK)
        self._heat_canvas = LockedFigureCanvas(self._heat_figure)
        self._heat_canvas.setObjectName(self.HEATMAP_NAME)
        self._heat_canvas.setMinimumHeight(220)
        side.addWidget(self._heat_canvas, stretch=1)
        self._hover_lbl = QLabel("Hover a circle to see its cells.")
        self._hover_lbl.setObjectName(self.HOVER_NAME)
        self._hover_lbl.setWordWrap(True)
        self._hover_lbl.setTextFormat(Qt.TextFormat.RichText)
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

    def _name(self, cluster: int) -> str:
        return self._run.get("cluster_names", {}).get(str(cluster)) or self._method.tag(cluster)

    def _show_setting(self) -> None:
        setting = self._method.recut
        if setting is None or self._run.get(setting.key) is None:
            return
        value = float(self._run[setting.key])
        if isinstance(self._recut_spin, BioDoubleSpinBox):
            self._recut_spin.setValue(value)
        else:
            self._recut_spin.setValue(int(value))

    def show_error(self, text: str) -> None:
        """A re-cut failed: say so beside the control, which stays usable."""
        self._busy_lbl.setText(f"Failed: {text}")
        self._recut_spin.setEnabled(True)

    def set_busy(self, text: str) -> None:
        """Say a re-cut is running (empty: done); the control waits meanwhile."""
        self._busy_lbl.setText(text)
        self._recut_spin.setEnabled(not text)

    def refresh(self) -> None:
        """Redraw after the run changed (e.g. re-cut)."""
        self._recut_spin.blockSignals(True)
        self._show_setting()
        self._recut_spin.blockSignals(False)
        self._summaries = summarize_clusters(
            self._array("intensities"), self._array("clusters"), self._labels
        )
        self._fill_legend()
        self._draw()

    def _legend_note(self, cluster: int) -> str:  # noqa: ARG002 - a hook for subclasses
        return ""

    def _fill_legend(self) -> None:
        self._legend.clear()
        n = max((s.cluster for s in self._summaries), default=-1) + 1
        colors = cluster_colors(n)
        for summary in self._summaries:
            note = self._legend_note(summary.cluster)
            text = f"{self._name(summary.cluster)} · {summary.share:.0%} · {summary.phenotype}"
            text += f" · {note}" if note else ""
            item = QListWidgetItem(_dot(colors[summary.cluster]), text)
            item.setToolTip(text)
            self._legend.addItem(item)

    # ── Drawing ───────────────────────────────────────────────────────

    def _draw(self) -> None:
        # Agg is shared with the gallery's background renders: build under the lock.
        with MPL_RASTER_LOCK:
            self._draw_figure()
            self._draw_heatmap()
        self._canvas.draw_idle()
        self._heat_canvas.draw_idle()

    def _colors(self, clusters: np.ndarray) -> tuple[Any, Any]:
        """Each circle's colour, and the marker scale (None when colouring by cluster).

        A marker's scale spans the circles' own range, dimmest to brightest,
        so differences show even when they are small.
        """
        marker = self._color_combo.currentData()
        if marker is None:
            palette = cluster_colors(int(clusters.max()) + 1 if len(clusters) else 0)
            return [palette[c] for c in clusters], None
        values = self._circle_values(marker)
        norm = mpl.colors.Normalize(float(values.min()), float(values.max()) or 1.0)
        return mpl.colormaps["viridis"](norm(values)), norm

    def _draw_figure(self) -> None:
        self._figure.clear()
        ax = self._figure.add_subplot(111)
        ax.set_facecolor(Colors.BG_DARK)
        ax.set_axis_off()
        layout, counts, clusters = self._circles()
        self._draw_lines(ax, layout)
        sizes = MIN_SIZE + (MAX_SIZE - MIN_SIZE) * np.sqrt(counts / max(counts.max(), 1))
        colors, norm = self._colors(clusters)
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
            cbar.set_label(f"{marker}: dimmest to brightest", color=Colors.FG_SECONDARY, fontsize=8)
            cbar.ax.yaxis.set_tick_params(colors=Colors.FG_SECONDARY, labelsize=7)
        else:
            self._label_clusters(ax, layout, counts, clusters)
        ax.set_title(self._title(), color=Colors.FG_PRIMARY, fontsize=10, fontweight="bold")
        ax.set_aspect("equal", "datalim")
        self._figure.tight_layout()

    def _label_clusters(
        self, ax: Any, layout: np.ndarray, counts: np.ndarray, clusters: np.ndarray
    ) -> None:
        """Name each cluster at its biggest circle, so colours read without the legend."""
        for c in np.unique(clusters):
            members = np.flatnonzero(clusters == c)
            anchor = members[np.argmax(counts[members])]
            ax.annotate(
                self._name(int(c)),
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

    def _draw_heatmap(self) -> None:
        """Clusters × markers, coloured by where each median sits in the marker's range."""
        self._heat_figure.clear()
        ax = self._heat_figure.add_subplot(111)
        rows = [self._name(s.cluster) for s in self._summaries]
        levels = np.array([s.level for s in self._summaries])
        if self._summaries:  # markers that don't differ: blank, as in the legend
            levels[:, ~np.array(self._summaries[0].informative)] = np.nan
        cmap = mpl.colormaps["viridis"].with_extremes(bad=Colors.BG_MEDIUM)
        if levels.size:
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

    def _on_hover(self, event: Any) -> None:
        if event.inaxes is None or event.xdata is None:
            return
        layout, _counts, _clusters = self._circles()
        if not len(layout):
            return
        dist = np.hypot(layout[:, 0] - event.xdata, layout[:, 1] - event.ydata)
        circle = int(np.argmin(dist))
        if dist[circle] > self._hover_radius():
            return
        self._hover_lbl.setText(self._hover_text(circle))

    def _hover_radius(self) -> float:
        return 0.6

    def _phenotype(self, cluster: int) -> str:
        summary = next((s for s in self._summaries if s.cluster == cluster), None)
        return summary.phenotype if summary is not None else ""
