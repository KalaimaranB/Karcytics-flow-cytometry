"""Background render task for one `ClusterResultsPanel` Plot Gallery tile.

Mirrors `ui/graph/render_task.py::RenderTask`'s shape: a self-contained
`AnalysisBase` whose `run()` builds a headless `Figure`, draws onto it, and
returns an RGBA byte buffer — dispatched via `task_scheduler.submit()` so the
gallery's N-per-sample scatter+colorbar plots render off the UI thread
instead of blocking the widget's constructor (SDK_Abstraction_Performance_Plan.md
Priority 1 UI #1).
"""

from __future__ import annotations

from typing import Any

import matplotlib.colors as mcolors
import numpy as np
from karcytics_sdk.plugin import AnalysisBase
from karcytics_sdk.plugin.rendering.lock import MPL_RASTER_LOCK

from .cluster_scatter_draw import draw_cluster_scatter


class ClusterPlotRenderTask(AnalysisBase):
    """Renders one UMAP scatter+colorbar tile to an RGBA image buffer."""

    def __init__(self, plugin_id: str = "flow_cytometry") -> None:
        super().__init__(plugin_id)
        self.config: dict = {}

    def configure(  # noqa: PLR0913
        self,
        embedding: np.ndarray,
        color_data: np.ndarray,
        title: str,
        cmap: str | mcolors.Colormap,
        norm=None,
        is_discrete: bool = False,
        min_c: int = 0,
        max_c: int = 0,
        width_px: int = 500,
        height_px: int = 400,
        dpi: int = 100,
    ) -> None:
        self.config = {
            "embedding": embedding,
            "color_data": color_data,
            "title": title,
            "cmap": cmap,
            "norm": norm,
            "is_discrete": is_discrete,
            "min_c": min_c,
            "max_c": max_c,
            "width_px": width_px,
            "height_px": height_px,
            "dpi": dpi,
        }

    def run(self, state: Any | None = None) -> dict:
        """Execute the render — called by TaskScheduler on a background thread."""
        import matplotlib

        matplotlib.use("Agg")
        from karcytics_sdk.plugin.theme_fallback import Colors
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.figure import Figure

        c = self.config
        if not c:
            return {"error": "Not configured"}

        # Figure creation, drawing, and buffer extraction are serialized behind
        # MPL_RASTER_LOCK because matplotlib's Agg C backend is not thread-safe
        # (see render_task.py's identical comment — concurrent calls can SIGBUS).
        with MPL_RASTER_LOCK:
            fig = Figure(
                facecolor=Colors.BG_DARK,
                figsize=(c["width_px"] / c["dpi"], c["height_px"] / c["dpi"]),
                dpi=c["dpi"],
            )
            draw_cluster_scatter(
                fig,
                c["embedding"],
                c["color_data"],
                c["title"],
                c["cmap"],
                c["norm"],
                c["is_discrete"],
                c["min_c"],
                c["max_c"],
            )
            canvas = FigureCanvasAgg(fig)
            canvas.draw()
            width, height = canvas.get_width_height()
            image_data = bytes(canvas.buffer_rgba())
            fig.clf()

        return {"image_data": image_data, "width": width, "height": height}
