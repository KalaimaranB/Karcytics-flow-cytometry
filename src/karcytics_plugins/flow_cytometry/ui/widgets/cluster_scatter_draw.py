"""Pure matplotlib drawing for a UMAP-embedding scatter plot with a colorbar.

Extracted out of `ClusterResultsPanel._create_plot` so the exact same drawing
code can run either on the Qt main thread (building a live, interactive
`Figure` for the Interactive Map tab) or headless on a background thread
(building an offscreen `Figure` for the Plot Gallery's `ClusterPlotRenderTask`,
see `cluster_plot_render_task.py`). Takes an already-constructed `Figure` and
never touches a Qt canvas itself, so it has no thread affinity of its own —
the caller's `Figure`/canvas choice is what determines which thread it's safe
to call on.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import matplotlib.colors as mcolors
import numpy as np
from karcytics_sdk.plugin.theme_fallback import Colors

if TYPE_CHECKING:
    from matplotlib.figure import Figure


def draw_cluster_scatter(  # noqa: PLR0913
    fig: Figure,
    embedding: np.ndarray,
    color_data: np.ndarray,
    title: str,
    cmap: str | mcolors.Colormap,
    norm=None,
    is_discrete: bool = False,
    min_c: int = 0,
    max_c: int = 0,
) -> None:
    """Draw a themed UMAP scatter + colorbar onto `fig` (adds its one subplot)."""
    ax = fig.add_subplot(111)
    ax.set_facecolor(Colors.BG_DARK)
    ax.tick_params(colors=Colors.FG_SECONDARY, labelsize=7)
    for spine in ("bottom", "left"):
        ax.spines[spine].set_color(Colors.BORDER)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)

    ax.set_title(title, color=Colors.FG_PRIMARY, fontsize=10, fontweight="bold", pad=8)
    ax.set_aspect("equal", "datalim")

    scatter = ax.scatter(
        embedding[:, 0],
        embedding[:, 1],
        c=color_data,
        cmap=cmap,
        norm=norm,
        s=1.0,
        alpha=0.75,
        edgecolors="none",
    )

    cbar = fig.colorbar(scatter, ax=ax, fraction=0.046, pad=0.04)
    cbar.ax.yaxis.set_tick_params(colors=Colors.FG_SECONDARY, labelsize=7)
    cbar.outline.set_color(Colors.BORDER)  # type: ignore

    if is_discrete:
        cbar.set_ticks(np.arange(min_c, max_c + 1))  # type: ignore
        cbar.set_label("Cluster ID", color=Colors.FG_SECONDARY, fontsize=8)
    else:
        cbar.set_label("Intensity", color=Colors.FG_SECONDARY, fontsize=8)

    fig.tight_layout()
