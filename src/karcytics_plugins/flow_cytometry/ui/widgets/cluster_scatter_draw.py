"""Matplotlib drawing for a run's embedding scatter, coloured by cluster or by a marker.

No Qt: the Plot Gallery draws these headless on a background thread
(`ClusterPlotRenderTask`) and the Interactive Map draws them on its canvas, so
both show a run the same way.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

import matplotlib as mpl
import matplotlib.colors as mcolors
import numpy as np
from karcytics_sdk.plugin.theme_fallback import Colors

from ...analysis.clustering import FLOWSOM, PHENOGRAPH, ClusteringMethod
from ...analysis.clustering.result_tables import run_array

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.figure import Figure


MAX_DRAWN = 150_000  # points per scatter; more only slows drawing (FlowSOM runs use every event)


def cluster_rgb(cluster_id: int, lowest: int) -> tuple[float, float, float]:
    """A cluster's colour, the same in every plot and table of one run.

    ``lowest`` is the run's lowest cluster id (-1 once events are noise or
    drawn away), so ids map onto the palette from its first colour.
    """
    r, g, b, _a = mpl.colormaps["tab20"]((cluster_id - lowest) % 20)
    return (r, g, b)


@dataclass(frozen=True)
class ScatterSpec:
    """One embedding scatter: what to plot and how to colour it."""

    embedding: np.ndarray  # (n, 2)
    color_data: np.ndarray  # (n,) cluster ids or 0..1 intensities
    title: str
    cmap: str | mcolors.Colormap
    norm: mcolors.Normalize
    colorbar_label: str
    id_range: tuple[int, int] | None = None  # cluster ids (one colorbar tick each); None: a marker


def cluster_spec(run: dict[str, Any], method: ClusteringMethod) -> ScatterSpec | None:
    """The run's embedding coloured by cluster id, or None if it has no clusters."""
    if "clusters" not in run:
        return None
    clusters = run_array(run, "clusters")
    lowest, highest = int(clusters.min()), int(clusters.max())
    cmap = mcolors.ListedColormap([cluster_rgb(i, lowest) for i in range(lowest, highest + 1)])
    return ScatterSpec(
        embedding=run_array(run, "embedding"),
        color_data=clusters,
        title={FLOWSOM: "Metacluster", PHENOGRAPH: "PhenoGraph Cluster"}.get(
            method, "Auto-Cluster ID"
        ),
        cmap=cmap,
        norm=mcolors.BoundaryNorm(np.arange(lowest, highest + 2) - 0.5, cmap.N),
        colorbar_label="Metacluster" if method is FLOWSOM else "Cluster ID",
        id_range=(lowest, highest),
    )


def marker_spec(run: dict[str, Any], channel: str, title: str) -> ScatterSpec:
    """The run's embedding coloured by one marker's scaled (0..1) intensity."""
    return ScatterSpec(
        embedding=run_array(run, "embedding"),
        color_data=run_array(run, "intensities")[:, list(run["channels"]).index(channel)],
        title=title,
        cmap="viridis",
        norm=mcolors.Normalize(vmin=0, vmax=1),
        colorbar_label="Intensity",
    )


def thinned(spec: ScatterSpec) -> ScatterSpec:
    """At most ``MAX_DRAWN`` of the spec's points, picked the same way every time."""
    if len(spec.embedding) <= MAX_DRAWN:
        return spec
    shown = np.random.default_rng(0).choice(len(spec.embedding), MAX_DRAWN, replace=False)
    return replace(spec, embedding=spec.embedding[shown], color_data=spec.color_data[shown])


def style_embedding_axes(ax: Axes, title: str) -> None:
    """Theme an axes for a UMAP embedding: dark face, bottom/left spines, equal aspect."""
    ax.set_facecolor(Colors.BG_DARK)
    ax.tick_params(colors=Colors.FG_SECONDARY, labelsize=7)
    for spine in ("bottom", "left"):
        ax.spines[spine].set_color(Colors.BORDER)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    ax.set_title(title, color=Colors.FG_PRIMARY, fontsize=10, fontweight="bold", pad=8)
    ax.set_aspect("equal", "datalim")


def draw_scatter(ax: Axes, spec: ScatterSpec, colorbar_ax: Axes | None = None) -> None:
    """Draw ``spec`` (already thinned) onto ``ax``, its colorbar into ``colorbar_ax``.

    Without ``colorbar_ax`` the colorbar takes room from ``ax``.
    """
    style_embedding_axes(ax, spec.title)
    scatter = ax.scatter(
        spec.embedding[:, 0],
        spec.embedding[:, 1],
        c=spec.color_data,
        cmap=spec.cmap,
        norm=spec.norm,
        s=1.0,
        alpha=0.75,
        edgecolors="none",
    )
    if colorbar_ax is None:
        cbar = ax.figure.colorbar(scatter, ax=ax, fraction=0.046, pad=0.04)
    else:
        cbar = ax.figure.colorbar(scatter, cax=colorbar_ax)
    cbar.ax.yaxis.set_tick_params(colors=Colors.FG_SECONDARY, labelsize=7)
    cbar.outline.set_color(Colors.BORDER)  # type: ignore[operator]  # a Spine, typed loosely
    if spec.id_range is not None:
        cbar.set_ticks(list(range(spec.id_range[0], spec.id_range[1] + 1)))
    cbar.set_label(spec.colorbar_label, color=Colors.FG_SECONDARY, fontsize=8)


def draw_cluster_scatter(fig: Figure, spec: ScatterSpec) -> None:
    """Draw ``spec`` as ``fig``'s one plot, colorbar beside it (a gallery tile)."""
    draw_scatter(fig.add_subplot(111), thinned(spec))
    fig.tight_layout()
