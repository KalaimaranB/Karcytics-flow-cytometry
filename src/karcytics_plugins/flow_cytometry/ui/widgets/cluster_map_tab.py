"""A clustering run's Interactive Map: its embedding, a hover card, and drawn populations.

The map is an SDK `LayeredMatplotlibCanvas`: picking the points to draw and
building the hover index run off the GUI thread, and drawing waits for the
shared raster lock without blocking the GUI while gallery tiles hold it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from karcytics_sdk.plugin.components import BioComboBox, SecondaryButton
from karcytics_sdk.plugin.dialogs import get_text, show_info
from karcytics_sdk.plugin.rendering.mpl_canvas import LayeredMatplotlibCanvas
from karcytics_sdk.plugin.rendering.pipeline import RasterizeStage, RenderComputeStage, RenderData
from karcytics_sdk.plugin.theme_fallback import Colors, theme_manager
from matplotlib.figure import Figure
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ...analysis.clustering import ClusteringMethod
from ...analysis.clustering.result_tables import (
    DrawnPopulation,
    add_drawn_population,
    drawn_populations,
    marker_labels,
    run_array,
)
from .cluster_scatter_draw import (
    ScatterSpec,
    cluster_spec,
    draw_scatter,
    marker_spec,
    style_embedding_axes,
    thinned,
)

_NEIGHBOURS = 50  # events averaged into the hover card
_HOVER_REACH = 0.05  # of the visible span: farther from every event, no card
_CARD_OFFSET_PX = 15
_BAR_WIDTH_PX = 120
_BAR_HEIGHT_PX = 10


@dataclass(frozen=True)
class _MapRequest:
    """What one redraw shows (built on the GUI thread)."""

    spec: ScatterSpec
    outlines: list[Any]  # drawn populations' vertices


@dataclass
class _MapData(RenderData):
    spec: ScatterSpec  # thinned to what is drawn
    outlines: list[Any]
    neighbours: Any = field(repr=False)  # scipy KDTree over every event
    marker_scale: np.ndarray  # 99th percentile per marker: a full hover bar


class _MapComputeStage(RenderComputeStage):
    """Thins the points and builds the hover index (once), off the GUI thread."""

    def __init__(self, embedding: np.ndarray, intensities: np.ndarray) -> None:
        super().__init__("flow_cytometry")
        self._embedding = embedding
        self._intensities = intensities
        self._neighbours: Any = None
        self._marker_scale: np.ndarray | None = None

    def compute(self, state: Any | None) -> _MapData:
        request = state
        assert isinstance(request, _MapRequest)  # see ClusterMapTab._redraw
        if self._neighbours is None or self._marker_scale is None:
            import scipy.spatial  # karcytics: allow KS360 - heavy library, loaded on first map

            # Two overlapping first renders may both build these; either result is the same.
            self._neighbours = scipy.spatial.KDTree(self._embedding)
            self._marker_scale = np.percentile(self._intensities, 99, axis=0)
        return _MapData(
            thinned(request.spec), request.outlines, self._neighbours, self._marker_scale
        )


class _MapRasterizeStage(RasterizeStage):
    """Draws the scatter, its colorbar and the drawn outlines (GUI thread, lock held)."""

    def __init__(self, colorbar_ax: Any) -> None:
        self._colorbar_ax = colorbar_ax
        self.latest: _MapData | None = None

    def rasterize(self, target: Any, data: Any) -> None:
        from matplotlib.patches import Polygon  # karcytics: allow KS360 - heavy library

        map_data: _MapData = data
        target.figure.patch.set_facecolor(Colors.BG_DARK)
        self._colorbar_ax.clear()
        draw_scatter(target, map_data.spec, self._colorbar_ax)
        for verts in map_data.outlines:
            target.add_patch(
                Polygon(
                    verts,
                    closed=True,
                    fill=False,
                    edgecolor=Colors.ACCENT_PRIMARY,
                    linewidth=2,
                    linestyle="--",
                )
            )
        target.figure.sca(target)  # the canvas redraws onto gca(): keep it the map, not the bar
        self.latest = map_data


class ClusterMapTab(QWidget):
    """The map with its colour picker, Draw Custom Population and a hover card."""

    population_drawn = Signal()  # the run now has one more drawn population

    def __init__(
        self, run: dict[str, Any], method: ClusteringMethod, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._run = run
        self._method = method
        self._drawn: list[DrawnPopulation] = drawn_populations(run)
        self._selector: Any = None

        self._combo = BioComboBox()
        self._combo.setObjectName("UmapInteractiveMapCombo")
        self._combo.addItem("Auto-Cluster ID", "clusters")
        for channel in run.get("channels", []):
            self._combo.addItem(f"Marker: {channel}", channel)
        draw_button = SecondaryButton("✏️ Draw Custom Population")
        draw_button.clicked.connect(self._start_drawing)
        toolbar = QHBoxLayout()
        toolbar.addWidget(self._combo)
        toolbar.addWidget(draw_button)
        toolbar.addStretch()

        figure = Figure(facecolor=Colors.BG_DARK, figsize=(5, 4))
        self._ax = figure.add_axes((0.08, 0.08, 0.76, 0.84))
        colorbar_ax = figure.add_axes((0.87, 0.08, 0.03, 0.84))
        # Themed and blank until the first render lands, not a white flash.
        style_embedding_axes(self._ax, "Rendering…")
        colorbar_ax.set_facecolor(Colors.BG_DARK)
        colorbar_ax.set_xticks([])
        colorbar_ax.set_yticks([])
        figure.sca(self._ax)
        self._canvas = LayeredMatplotlibCanvas(figure, plugin_id="flow_cytometry")
        self._canvas.setObjectName("UmapInteractiveMapCanvas")
        self._canvas.setMinimumHeight(350)
        self._canvas.set_compute_stage(
            _MapComputeStage(run_array(run, "embedding"), run_array(run, "intensities"))
        )
        self._raster = _MapRasterizeStage(colorbar_ax)
        self._canvas.set_rasterize_stage(self._raster)
        self._canvas.mpl_connect("motion_notify_event", self._on_hover)

        self._info = QLabel()
        theme_manager.apply_style(self._info, "color: {FG_SECONDARY};")
        self._card = HoverStatsCard(marker_labels(run), self._canvas)

        layout = QVBoxLayout(self)
        layout.addLayout(toolbar)
        layout.addWidget(self._canvas, stretch=1)
        layout.addWidget(self._info)

        self._combo.currentIndexChanged.connect(self._redraw)
        self._redraw()

    @property
    def color_label(self) -> str:
        """What the map is coloured by, as the picker shows it."""
        return self._combo.currentText()

    def _redraw(self) -> None:
        key = self._combo.currentData()
        spec = (
            cluster_spec(self._run, self._method)
            if key == "clusters"
            else marker_spec(self._run, key, self._combo.currentText())
        )
        if spec is None:
            return
        outlines = [
            drawn["verts"] for drawn in self._run.get("custom_clusters", []) if "verts" in drawn
        ]
        self._canvas.request_data_redraw(
            _MapRequest(spec, outlines),  # type: ignore[arg-type]  # the SDK types this PluginState; our compute stage reads a _MapRequest
            debounce_ms=0,
        )
        self._info.setText(f"Displaying: {self.color_label} | Total events: {len(spec.embedding)}")

    def _apply_theme_styles(self) -> None:
        self._redraw()  # the theme's colours are drawn into the figure

    # ── Hover card ───────────────────────────────────────────────────────

    def _on_hover(self, event: Any) -> None:
        data = self._raster.latest
        if not event.inaxes or event.inaxes is not self._ax or data is None:
            self._card.hide()
            return
        distances, nearest = data.neighbours.query([event.xdata, event.ydata], k=_NEIGHBOURS)
        x0, x1 = self._ax.get_xlim()
        y0, y1 = self._ax.get_ylim()
        if distances[0] > max(abs(x1 - x0), abs(y1 - y0)) * _HOVER_REACH:
            self._card.hide()
            return
        expression = run_array(self._run, "intensities")[nearest].mean(axis=0)
        self._card.show_stats(self._hover_title(nearest), expression, data.marker_scale)
        if event.guiEvent is not None:
            self._place_card(event.guiEvent.pos())

    def _hover_title(self, nearest: np.ndarray) -> str:
        closest = nearest[0]
        for drawn in reversed(self._drawn):
            if drawn.mask[closest]:
                return f"Custom: {drawn.name}"
        if "clusters" not in self._run:
            return f"Local Neighborhood (n={_NEIGHBOURS})"
        ids, counts = np.unique(run_array(self._run, "clusters")[nearest], return_counts=True)
        dominant = int(ids[np.argmax(counts)])
        name = self._run.get("cluster_names", {}).get(
            str(dominant), self._method.cluster_name(dominant)
        )
        return f"Dominant: {name}"

    def _place_card(self, pos: Any) -> None:
        x = pos.x() + _CARD_OFFSET_PX
        if x + self._card.width() > self._canvas.width():
            x = pos.x() - self._card.width() - _CARD_OFFSET_PX
        self._card.move(x, pos.y() + _CARD_OFFSET_PX)
        if not self._card.isVisible():
            self._card.show()
            self._card.raise_()

    # ── Drawing a population ─────────────────────────────────────────────

    def _start_drawing(self) -> None:
        from matplotlib.widgets import PolygonSelector  # karcytics: allow KS360 - heavy library

        show_info(
            self,
            "Draw Cluster",
            "Click on the UMAP plot to draw a polygon.\n"
            "Double-click or press Enter to complete the shape.",
        )
        self._selector = PolygonSelector(
            self._ax,
            self._on_polygon_drawn,  # type: ignore[arg-type]  # the stub types onselect as two-argument; PolygonSelector passes the vertices
            useblit=True,
            props={"color": Colors.ACCENT_PRIMARY, "linestyle": "-", "linewidth": 2, "alpha": 0.8},
        )

    def _on_polygon_drawn(self, verts: list[tuple[float, float]]) -> None:
        from matplotlib.path import Path  # karcytics: allow KS360 - heavy library

        if self._selector is not None:
            self._selector.disconnect_events()
            self._selector.set_visible(False)
            self._selector = None
        mask = Path(verts).contains_points(run_array(self._run, "embedding"))
        if not mask.any():
            return
        suggested = f"Custom Cluster {len(self._run.get('custom_clusters', [])) + 1}"
        name = get_text(
            self, "Name Population", "Enter a name for this custom population:", suggested
        )
        if not name or not name.strip():
            return
        add_drawn_population(self._run, name.strip(), verts, mask)
        self._drawn = drawn_populations(self._run)
        self._redraw()  # its outline, and the clusters it took events from
        self.population_drawn.emit()


class HoverStatsCard(QFrame):
    """A floating card of the mean marker expression around the pointer."""

    def __init__(self, markers: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setObjectName("hover_stats")
        theme_manager.apply_style(
            self,
            "#hover_stats { background-color: {BG_DARKEST}; border: 1px solid {BORDER};"
            " border-radius: 6px; }"
            " QLabel { color: {FG_SECONDARY}; font-size: 11px; }"
            " QLabel#hover_title { color: {FG_PRIMARY}; font-weight: bold; font-size: 12px; }"
            " QFrame#hover_track { background-color: {BG_LIGHT}; border-radius: 3px; }"
            " QFrame#hover_bar { background-color: {ACCENT_PRIMARY}; border-radius: 3px; }",
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        self._title = QLabel("Local Neighborhood")
        self._title.setObjectName("hover_title")
        layout.addWidget(self._title)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(6)
        self._bars: list[QFrame] = []
        for row, marker in enumerate(markers):
            grid.addWidget(QLabel(marker), row, 0)
            track = QFrame()
            track.setObjectName("hover_track")
            track.setFixedSize(_BAR_WIDTH_PX, _BAR_HEIGHT_PX)
            bar = QFrame(track)
            bar.setObjectName("hover_bar")
            bar.setFixedSize(0, _BAR_HEIGHT_PX)
            grid.addWidget(track, row, 1)
            self._bars.append(bar)
        layout.addLayout(grid)
        self.hide()

    def show_stats(self, title: str, expression: np.ndarray, scale: np.ndarray) -> None:
        """Set the title, and each marker's bar to its share of ``scale``."""
        self._title.setText(title)
        for bar, value, full in zip(self._bars, expression, scale, strict=False):
            fraction = min(1.0, max(0.0, value / full)) if full > 0 else 0.0
            bar.setFixedSize(int(fraction * _BAR_WIDTH_PX), _BAR_HEIGHT_PX)
