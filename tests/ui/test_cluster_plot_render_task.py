"""Headless tests for `ClusterPlotRenderTask.run()` (no Qt widget, no task_scheduler).

Mirrors `test_subplots.py::test_thumbnail_rendering_resolution`'s convention of
calling an `AnalysisBase.run()` directly to verify the pure compute/render
result, independent of how it's dispatched.
"""

import matplotlib.colors as mcolors
import numpy as np
import pytest

from karcytics_plugins.flow_cytometry.ui.widgets.cluster_plot_render_task import (
    ClusterPlotRenderTask,
)


def _embedding_and_colors(n=200):
    rng = np.random.default_rng(0)
    embedding = rng.normal(size=(n, 2))
    color_data = rng.normal(size=n)
    return embedding, color_data


@pytest.mark.ui
def test_run_returns_an_rgba_image_buffer_of_the_configured_size():
    embedding, color_data = _embedding_and_colors()
    task = ClusterPlotRenderTask()
    task.configure(
        embedding=embedding,
        color_data=color_data,
        title="FITC-A",
        cmap="viridis",
        norm=mcolors.Normalize(vmin=0, vmax=1),
        width_px=200,
        height_px=160,
        dpi=100,
    )

    result = task.run(None)

    assert "image_data" in result
    assert isinstance(result["image_data"], bytes)
    assert result["width"] == 200
    assert result["height"] == 160
    # RGBA = 4 bytes/pixel
    assert len(result["image_data"]) == 200 * 160 * 4


@pytest.mark.ui
def test_run_draws_a_discrete_cluster_id_colorbar():
    embedding, _ = _embedding_and_colors()
    clusters = np.array([0, 1, 2] * (len(embedding) // 3) + [0] * (len(embedding) % 3))
    cmap = mcolors.ListedColormap(["red", "green", "blue"])
    norm = mcolors.BoundaryNorm(np.arange(-0.5, 3.5, 1), cmap.N)

    task = ClusterPlotRenderTask()
    task.configure(
        embedding=embedding,
        color_data=clusters,
        title="Auto-Cluster ID",
        cmap=cmap,
        norm=norm,
        is_discrete=True,
        min_c=0,
        max_c=2,
    )

    result = task.run(None)

    assert isinstance(result["image_data"], bytes)
    assert len(result["image_data"]) > 0


@pytest.mark.ui
def test_run_returns_an_error_when_not_configured():
    task = ClusterPlotRenderTask()

    result = task.run(None)

    assert result == {"error": "Not configured"}
