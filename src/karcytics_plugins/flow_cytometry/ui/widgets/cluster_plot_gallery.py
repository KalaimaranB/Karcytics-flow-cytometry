"""A clustering run's Plot Gallery: its embedding coloured by cluster, then by each marker.

Every tile renders off the GUI thread (`ClusterPlotRenderTask`); a placeholder
holds its place in the grid until the image arrives.
"""

from __future__ import annotations

from functools import partial
from typing import Any

import shiboken6
from karcytics_sdk.plugin import get_logger, submit_task
from karcytics_sdk.plugin.components import BioCaptionLabel, BioScrollArea
from karcytics_sdk.plugin.runtime_services import task_scheduler
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QGridLayout, QWidget

from ...analysis.clustering import ClusteringMethod
from ...analysis.clustering.result_tables import marker_labels
from .cluster_plot_render_task import ClusterPlotRenderTask
from .cluster_scatter_draw import ScatterSpec, cluster_spec, marker_spec
from .copyable import CopyablePixmapLabel

logger = get_logger(__name__, "flow_cytometry")

_COLUMNS = 2
# Tiles show at one fixed size (CopyablePixmapLabel says why), rendered at
# _SUPERSAMPLE x that so the downscale stays sharp.
TILE_SIZE = QSize(467, 373)
_SUPERSAMPLE = 2


class ClusterPlotGallery(BioScrollArea):
    """A grid of the run's embedding scatters."""

    def __init__(
        self,
        run: dict[str, Any],
        method: ClusteringMethod,
        state: Any | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._state = state  # handed to the task scheduler with each tile
        container = QWidget()
        self._grid = QGridLayout(container)
        self._grid.setSpacing(16)
        self.setWidget(container)

        if run.get("embedding") is None or run.get("intensities") is None:
            return
        specs = [spec] if (spec := cluster_spec(run, method)) is not None else []
        specs += [
            marker_spec(run, channel, label)
            for channel, label in zip(run["channels"], marker_labels(run), strict=False)
        ]
        for i, spec in enumerate(specs):
            self._request_tile(divmod(i, _COLUMNS), spec)

    def tile_at(self, row: int, column: int) -> QWidget | None:
        """The placeholder or rendered tile in one grid cell."""
        item = self._grid.itemAtPosition(row, column)
        return item.widget() if item is not None else None

    def _request_tile(self, cell: tuple[int, int], spec: ScatterSpec) -> None:
        """Show a placeholder now and render the tile in the background."""
        placeholder = BioCaptionLabel("Rendering…")
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder.setFixedSize(TILE_SIZE)
        self._grid.addWidget(placeholder, *cell)

        task = ClusterPlotRenderTask()
        task.configure(
            spec,
            width_px=TILE_SIZE.width() * _SUPERSAMPLE,
            height_px=TILE_SIZE.height() * _SUPERSAMPLE,
        )
        submit_task(
            task,
            self._state,
            on_finished=partial(self._show_tile, cell),
            on_error=_log_failure,
            scheduler=task_scheduler,
        )

    def _show_tile(self, cell: tuple[int, int], results: dict) -> None:
        if not shiboken6.isValid(self):
            return  # closed while the tile rendered
        if "error" in results:
            _log_failure(results["error"])
            return
        buffer = results.get("image_data")
        if not buffer:
            return
        image = QImage(buffer, results["width"], results["height"], QImage.Format.Format_RGBA8888)
        if (old := self.tile_at(*cell)) is not None:
            self._grid.removeWidget(old)
            old.deleteLater()
        tile = CopyablePixmapLabel(QPixmap.fromImage(image.copy()), TILE_SIZE)
        self._grid.addWidget(tile, *cell)


def _log_failure(message: str) -> None:
    logger.warning(f"Plot gallery tile failed to render: {message}")
