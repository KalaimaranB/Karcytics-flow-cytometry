"""Background render task for one Plot Gallery tile (`ClusterPlotGallery`).

Mirrors `ui/graph/render_task.py::RenderTask`'s shape: a self-contained
`AnalysisBase` whose `run()` builds a headless `Figure`, draws onto it, and
returns an RGBA byte buffer — dispatched via `task_scheduler.submit()` so the
gallery's N-per-sample scatter+colorbar plots render off the UI thread
instead of blocking the widget's constructor.
"""

from __future__ import annotations

from typing import Any

from karcytics_sdk.plugin import AnalysisBase
from karcytics_sdk.plugin.rendering.lock import MPL_RASTER_LOCK
from karcytics_sdk.plugin.theme_fallback import Colors

from .cluster_scatter_draw import ScatterSpec, draw_cluster_scatter


class ClusterPlotRenderTask(AnalysisBase):
    """Renders one UMAP scatter+colorbar tile to an RGBA image buffer."""

    def __init__(self, plugin_id: str = "flow_cytometry") -> None:
        super().__init__(plugin_id)
        self.config: dict = {}

    def configure(
        self, spec: ScatterSpec, width_px: int = 500, height_px: int = 400, dpi: int = 100
    ) -> None:
        self.config = {"spec": spec, "width_px": width_px, "height_px": height_px, "dpi": dpi}

    def run(self, state: Any | None = None) -> dict:
        """Execute the render — called by TaskScheduler on a background thread."""
        import matplotlib  # karcytics: allow KS360 - heavy library

        matplotlib.use("Agg")
        # karcytics: allow KS360 - heavy library
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.figure import Figure  # karcytics: allow KS360 - heavy library

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
            draw_cluster_scatter(fig, c["spec"])
            canvas = FigureCanvasAgg(fig)
            canvas.draw()
            width, height = canvas.get_width_height()
            image_data = bytes(canvas.buffer_rgba())
            fig.clf()

        return {"image_data": image_data, "width": width, "height": height}
