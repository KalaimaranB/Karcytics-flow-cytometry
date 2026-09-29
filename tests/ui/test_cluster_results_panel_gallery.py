"""Tests for `ClusterResultsPanel`'s Plot Gallery async rendering
(SDK_Abstraction_Performance_Plan.md Priority 1 UI #1).

The gallery used to build every tile's matplotlib Figure/scatter/colorbar
synchronously in the constructor. It now shows a placeholder per tile
immediately and dispatches each tile's render via `ClusterPlotRenderTask`
through `task_scheduler`, swapping in the rendered image once its task
completes — mirroring how `group_preview.py` already listens to the global
`task_scheduler.task_finished`/`task_error` signals rather than a per-worker
signal.
"""

from __future__ import annotations

import numpy as np
import pytest
from PyQt6.QtCore import QObject, QSize, QTimer, pyqtSignal

from karcytics_plugins.flow_cytometry.ui.widgets import cluster_results_panel as panel_module
from karcytics_plugins.flow_cytometry.ui.widgets.cluster_results_panel import (
    ClusterResultsPanel,
    CopyablePixmapLabel,
)


class _FakeGlobalScheduler(QObject):
    """Fakes the module-level `task_scheduler` singleton's global-signal shape.

    `submit()` runs the task synchronously but defers the finished/error
    signal emission via `QTimer.singleShot(0, ...)`, so a caller's
    `.connect()` made immediately after `submit()` returns (as
    `ClusterResultsPanel.__init__` does, once, for its whole lifetime) is
    already registered before the callback fires.
    """

    task_finished = pyqtSignal(str, dict)
    task_error = pyqtSignal(str, str)

    def __init__(self) -> None:
        super().__init__()
        self.submitted: list = []
        self._next_id = 0

    def submit(self, analyzer, state=None):
        self._next_id += 1
        task_id = str(self._next_id)
        self.submitted.append(analyzer)

        def _run_and_emit():
            try:
                results = analyzer.run(state)
            except Exception as exc:  # noqa: BLE001
                self.task_error.emit(task_id, str(exc))
            else:
                self.task_finished.emit(task_id, results)

        QTimer.singleShot(0, _run_and_emit)

        worker = QObject()
        worker.task_id = task_id  # type: ignore[attr-defined]
        return worker


@pytest.fixture
def fake_scheduler(monkeypatch):
    scheduler = _FakeGlobalScheduler()
    monkeypatch.setattr(panel_module, "task_scheduler", scheduler)
    return scheduler


def _gallery_results(n_channels=2):
    rng = np.random.default_rng(0)
    n = 50
    return {
        "embedding": rng.normal(size=(n, 2)),
        "intensities": rng.normal(size=(n, n_channels)),
        "channels": [f"CH{i}" for i in range(n_channels)],
    }


@pytest.mark.ui
def test_gallery_shows_a_placeholder_per_tile_before_any_render_completes(fake_scheduler, qtbot):
    panel = ClusterResultsPanel(_gallery_results(n_channels=2))
    qtbot.addWidget(panel)

    item_0 = panel._gallery_grid.itemAtPosition(0, 0)
    item_1 = panel._gallery_grid.itemAtPosition(0, 1)
    assert item_0 is not None and item_1 is not None
    assert item_0.widget().text() == "Rendering…"
    assert item_1.widget().text() == "Rendering…"


@pytest.mark.ui
def test_gallery_dispatches_one_render_task_per_tile(fake_scheduler, qtbot):
    panel = ClusterResultsPanel(_gallery_results(n_channels=3))
    qtbot.addWidget(panel)

    assert len(fake_scheduler.submitted) == 3


@pytest.mark.ui
def test_gallery_tiles_render_at_2x_supersample_resolution(fake_scheduler, qtbot):
    panel = ClusterResultsPanel(_gallery_results(n_channels=1))
    qtbot.addWidget(panel)

    (task,) = fake_scheduler.submitted
    assert task.config["width_px"] == 934
    assert task.config["height_px"] == 746


@pytest.mark.ui
def test_gallery_tile_becomes_a_fixed_size_pixmap_label_once_its_render_completes(
    fake_scheduler, qtbot
):
    panel = ClusterResultsPanel(_gallery_results(n_channels=1))
    qtbot.addWidget(panel)

    def _tile_is_rendered():
        item = panel._gallery_grid.itemAtPosition(0, 0)
        assert item is not None
        assert isinstance(item.widget(), CopyablePixmapLabel)

    qtbot.waitUntil(_tile_is_rendered, timeout=2000)

    label = panel._gallery_grid.itemAtPosition(0, 0).widget()
    pixmap = label.pixmap()
    assert pixmap is not None
    assert not pixmap.isNull()
    assert label.size().width() == 467
    assert label.size().height() == 373


@pytest.mark.ui
def test_rendered_tile_is_fixed_size_and_never_distorted(qtbot):
    """Guards against three regressions in a row, all from trying to make a
    tile dynamically expand to fill its grid cell: `setScaledContents`
    stretched width/height independently and distorted the plot;
    `Expanding` + resize-driven `KeepAspectRatio` rescaling fixed that but
    then hit `QGridLayout` giving different rows wildly inconsistent
    heights for otherwise-identical tiles. A fixed, deterministic size sidesteps
    all of it — no `QGridLayout` stretch heuristics are involved in sizing a
    tile at all.
    """
    from PyQt6.QtGui import QPixmap

    source = QPixmap(934, 746)
    source.fill()
    display_size = QSize(467, 373)

    label = CopyablePixmapLabel(source, display_size)
    qtbot.addWidget(label)

    assert label.size() == display_size
    displayed = label.pixmap()
    assert displayed is not None and not displayed.isNull()
    # KeepAspectRatio: same ~5:4 ratio as the source, so it should fit exactly.
    assert displayed.width() == 467
    assert displayed.height() == 373


@pytest.mark.ui
def test_a_raising_render_task_leaves_the_placeholder_in_place(fake_scheduler, qtbot, monkeypatch):
    def _boom(self, state=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(panel_module.ClusterPlotRenderTask, "run", _boom)

    panel = ClusterResultsPanel(_gallery_results(n_channels=1))
    qtbot.addWidget(panel)

    def _tile_was_popped():
        assert "1" not in panel._pending_gallery_tiles

    qtbot.waitUntil(_tile_was_popped, timeout=2000)

    item = panel._gallery_grid.itemAtPosition(0, 0)
    assert item is not None
    assert item.widget().text() == "Rendering…"


@pytest.mark.ui
def test_cluster_plot_params_produces_a_discrete_colorbar_spec(fake_scheduler, qtbot):
    results = _gallery_results(n_channels=1)
    results["clusters"] = np.array([0, 1, 2, 0, 1] * 10)
    panel = ClusterResultsPanel(results)
    qtbot.addWidget(panel)

    params = panel._cluster_plot_params()

    assert params is not None
    assert params["title"] == "Auto-Cluster ID"
    assert params["is_discrete"] is True
    assert params["min_c"] == 0
    assert params["max_c"] == 2
