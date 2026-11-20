"""The Plot Gallery: a placeholder per tile at once, each tile rendered in the background."""

from __future__ import annotations

import numpy as np
import pytest
import shiboken6
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QLabel

from karcytics_plugins.flow_cytometry.analysis.clustering import UMAP_HDBSCAN
from karcytics_plugins.flow_cytometry.ui.widgets import cluster_plot_gallery as gallery_module
from karcytics_plugins.flow_cytometry.ui.widgets.cluster_plot_gallery import (
    TILE_SIZE,
    ClusterPlotGallery,
)
from karcytics_plugins.flow_cytometry.ui.widgets.copyable import CopyablePixmapLabel


class _FakeScheduler(QObject):
    """Runs each task on the next event-loop turn and broadcasts its result."""

    task_finished = Signal(str, object)
    task_error = Signal(str, str)
    task_progress = Signal(str, int)

    def __init__(self) -> None:
        super().__init__()
        self.submitted: list = []

    def submit(self, analyzer, state=None):
        self.submitted.append(analyzer)
        task_id = str(len(self.submitted))

        def run_and_emit():
            try:
                results = analyzer.run(state)
            except Exception as exc:  # noqa: BLE001 - reported like the real scheduler does
                self.task_error.emit(task_id, str(exc))
            else:
                self.task_finished.emit(task_id, results)

        QTimer.singleShot(0, run_and_emit)
        worker = QObject()
        worker.task_id = task_id  # type: ignore[attr-defined]  # as AnalysisWorker carries it
        return worker


@pytest.fixture
def scheduler(monkeypatch):
    fake = _FakeScheduler()
    monkeypatch.setattr(gallery_module, "task_scheduler", fake)
    return fake


def _run(n_channels: int = 2, clusters: bool = False) -> dict:
    rng = np.random.default_rng(0)
    run = {
        "embedding": rng.normal(size=(50, 2)),
        "intensities": rng.uniform(size=(50, n_channels)),
        "channels": [f"CH{i}" for i in range(n_channels)],
        "channel_labels": [f"CD{i}" for i in range(n_channels)],
    }
    if clusters:
        run["clusters"] = np.array([0, 1, 2, 0, 1] * 10)
    return run


def _tile(gallery: ClusterPlotGallery, row: int, column: int) -> QLabel:
    tile = gallery.tile_at(row, column)
    assert isinstance(tile, QLabel)
    return tile


def _gallery(qtbot, run: dict) -> ClusterPlotGallery:
    gallery = ClusterPlotGallery(run, UMAP_HDBSCAN)
    qtbot.addWidget(gallery)
    return gallery


@pytest.mark.ui
def test_every_tile_shows_a_placeholder_before_it_renders(scheduler, qtbot):
    gallery = _gallery(qtbot, _run(n_channels=3))

    assert len(scheduler.submitted) == 3  # noqa: PLR2004
    for cell in ((0, 0), (0, 1), (1, 0)):
        assert _tile(gallery, *cell).text() == "Rendering…"


@pytest.mark.ui
def test_the_cluster_tile_comes_first_then_one_per_marker_by_label(scheduler, qtbot):
    _gallery(qtbot, _run(n_channels=2, clusters=True))

    titles = [task.config["spec"].title for task in scheduler.submitted]
    assert titles == ["Auto-Cluster ID", "CD0", "CD1"]
    assert scheduler.submitted[0].config["spec"].id_range == (0, 2)


@pytest.mark.ui
def test_tiles_render_at_twice_their_display_size(scheduler, qtbot):
    _gallery(qtbot, _run(n_channels=1))

    (task,) = scheduler.submitted
    assert (task.config["width_px"], task.config["height_px"]) == (
        TILE_SIZE.width() * 2,
        TILE_SIZE.height() * 2,
    )


@pytest.mark.ui
def test_a_rendered_tile_replaces_its_placeholder_at_the_fixed_size(scheduler, qtbot):
    gallery = _gallery(qtbot, _run(n_channels=1))

    qtbot.waitUntil(lambda: isinstance(gallery.tile_at(0, 0), CopyablePixmapLabel), timeout=2000)

    tile = _tile(gallery, 0, 0)
    assert not tile.pixmap().isNull()
    assert tile.size() == TILE_SIZE


@pytest.mark.ui
def test_a_failed_render_leaves_the_placeholder(scheduler, qtbot, monkeypatch):
    def boom(self, state=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(gallery_module.ClusterPlotRenderTask, "run", boom)
    errors: list[str] = []
    monkeypatch.setattr(gallery_module, "_log_failure", errors.append)
    gallery = _gallery(qtbot, _run(n_channels=1))

    qtbot.waitUntil(lambda: errors == ["boom"], timeout=2000)
    assert _tile(gallery, 0, 0).text() == "Rendering…"


@pytest.mark.ui
def test_a_tile_finishing_after_the_gallery_closed_is_ignored(scheduler, qtbot):
    gallery = ClusterPlotGallery(_run(n_channels=1), UMAP_HDBSCAN)
    shiboken6.delete(gallery)  # gone before its task reports back
    finished: list[str] = []
    scheduler.task_finished.connect(lambda task_id, _r: finished.append(task_id))

    qtbot.waitUntil(lambda: finished == ["1"], timeout=2000)  # no crash on the deleted gallery
