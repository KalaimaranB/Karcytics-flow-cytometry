"""A clustering method's own picture and its phenotype heatmap, drawn headless.

Both are `IPlotRenderer`s: `ClusterMapView` gathers plain data on the GUI
thread (`ClusterMapPicture`, the heatmap's levels, the theme's colours) and
these build the figures on a background thread.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import matplotlib as mpl
import numpy as np
from matplotlib import patheffects
from matplotlib.collections import LineCollection
from matplotlib.figure import Figure

from ...analysis.clustering import call
from ..graph.figure_renderer import IPlotRenderer
from .cluster_scatter_draw import cluster_rgb

MIN_SIZE, MAX_SIZE = 30.0, 520.0  # circle area range, points²
VIRIDIS_MIDPOINT = 0.5  # dark text below it, light above


def cluster_colors(n: int) -> list[tuple[float, ...]]:
    """The same per-cluster colours the scatter plots use."""
    return [(*cluster_rgb(i, 0), 1.0) for i in range(n)]


@dataclass(frozen=True)
class MapTheme:
    """The theme colours drawn into the figures (read on the GUI thread)."""

    background: str
    outline: str  # circle edges and the halo behind labels
    foreground: str
    secondary: str
    missing: str  # heatmap cells of markers that barely differ


@dataclass(frozen=True)
class MapLines:
    """The lines joining circles; widths and alphas are one value or one per line."""

    segments: np.ndarray  # (lines, 2, 2)
    widths: float | np.ndarray
    alphas: float | np.ndarray


@dataclass(frozen=True)
class MapLabel:
    text: str
    at: tuple[float, float]


@dataclass(frozen=True)
class ClusterMapPicture:
    """Everything one map shows.

    Circles are coloured by ``clusters`` (the shared palette), or by
    ``marker_values`` on a dimmest-to-brightest scale when a marker is chosen.
    """

    layout: np.ndarray  # (circles, 2)
    counts: np.ndarray  # cells per circle
    clusters: np.ndarray  # each circle's cluster
    lines: MapLines | None
    title: str
    marker: str | None = None  # the marker coloured by
    marker_values: np.ndarray | None = None
    labels: tuple[MapLabel, ...] = field(default_factory=tuple)  # drawn when coloured by cluster


def circle_sizes(counts: np.ndarray) -> np.ndarray:
    """Circle areas: area grows with the square root of the cell count."""
    return MIN_SIZE + (MAX_SIZE - MIN_SIZE) * np.sqrt(counts / max(counts.max(initial=0), 1))


class ClusterMapRenderer(IPlotRenderer):
    """kwargs: ``picture`` (`ClusterMapPicture`), ``theme`` (`MapTheme`)."""

    def render(self, **kwargs) -> Figure:
        picture: ClusterMapPicture = kwargs["picture"]
        theme: MapTheme = kwargs["theme"]
        fig = Figure(facecolor=theme.background, layout="constrained")
        ax = fig.add_subplot(111)
        ax.set_facecolor(theme.background)
        ax.set_axis_off()
        if picture.lines is not None and len(picture.lines.segments):
            lines = picture.lines
            ax.add_collection(
                LineCollection(
                    list(lines.segments),
                    colors=theme.secondary,
                    alpha=lines.alphas,
                    linewidths=lines.widths,
                    zorder=1,
                )
            )
        colors, norm = _circle_colors(picture)
        layout = picture.layout
        ax.scatter(
            layout[:, 0],
            layout[:, 1],
            s=circle_sizes(picture.counts),
            c=colors,
            edgecolors=theme.outline,
            linewidths=0.8,
            zorder=2,
        )
        if norm is not None:
            mappable = mpl.cm.ScalarMappable(cmap="viridis", norm=norm)
            cbar = fig.colorbar(mappable, ax=ax, fraction=0.04, pad=0.02)
            scale_label = f"{picture.marker}: dimmest to brightest"
            cbar.set_label(scale_label, color=theme.secondary, fontsize=8)
            cbar.ax.yaxis.set_tick_params(colors=theme.secondary, labelsize=7)
        else:
            halo = [patheffects.withStroke(linewidth=3, foreground=theme.outline)]
            for label in picture.labels:
                ax.annotate(
                    label.text,
                    label.at,
                    xytext=(0, 9),
                    textcoords="offset points",
                    ha="center",
                    color=theme.foreground,
                    fontsize=8,
                    fontweight="bold",
                    zorder=3,
                    path_effects=halo,
                )
        ax.set_title(picture.title, color=theme.foreground, fontsize=10, fontweight="bold")
        ax.set_aspect("equal", "datalim")
        return fig


def _circle_colors(
    picture: ClusterMapPicture,
) -> tuple[list | np.ndarray, mpl.colors.Normalize | None]:
    """Each circle's colour, and the marker scale (None when coloured by cluster).

    A marker's scale spans the circles' own range, dimmest to brightest, so
    differences show even when they are small.
    """
    if picture.marker_values is None:
        clusters = picture.clusters
        palette = cluster_colors(int(clusters.max()) + 1 if len(clusters) else 0)
        return [palette[c] for c in clusters], None
    values = picture.marker_values
    norm = mpl.colors.Normalize(float(values.min()), float(values.max()) or 1.0)
    return mpl.colormaps["viridis"](norm(values)), norm


class PhenotypeHeatmapRenderer(IPlotRenderer):
    """Clusters × markers, coloured by where each median sits in the marker's range.

    kwargs: ``rows`` (cluster names), ``markers``, ``levels`` (rows × markers,
    0..1; NaN for markers that barely differ, left blank), ``theme`` (`MapTheme`).
    """

    def render(self, **kwargs) -> Figure:
        theme: MapTheme = kwargs["theme"]
        rows, markers, levels = kwargs["rows"], kwargs["markers"], kwargs["levels"]
        fig = Figure(facecolor=theme.background, layout="constrained")
        ax = fig.add_subplot(111)
        cmap = mpl.colormaps["viridis"].with_extremes(bad=theme.missing)
        if levels.size:
            ax.imshow(levels, cmap=cmap, vmin=0, vmax=1, aspect="auto")
        for (r, c), v in np.ndenumerate(levels):
            if not np.isnan(v):
                text_color = "black" if v >= VIRIDIS_MIDPOINT else "white"
                ax.text(c, r, call(v), ha="center", va="center", fontsize=7, color=text_color)
        ax.set_xticks(range(len(markers)), markers, rotation=45, ha="right")
        ax.set_yticks(range(len(rows)), rows)
        ax.tick_params(colors=theme.secondary, labelsize=7, length=0)
        for spine in ax.spines.values():
            spine.set_visible(False)
        return fig
