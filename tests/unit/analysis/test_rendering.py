from unittest.mock import MagicMock

import numpy as np

from karcytics_plugins.flow_cytometry.analysis.scaling import AxisScale
from karcytics_plugins.flow_cytometry.analysis.transforms import TransformType
from karcytics_plugins.flow_cytometry.ui.graph.render_task import RenderTask


def test_render_task_execution(sample_data):
    task = RenderTask()
    x_scale = AxisScale(TransformType.LINEAR)
    y_scale = AxisScale(TransformType.LINEAR)

    task.configure(
        data=sample_data,
        x_param="FSC-A",
        y_param="SSC-A",
        x_scale=x_scale,
        y_scale=y_scale,
        x_range=(0, 1024),
        y_range=(0, 1024),
        width_px=100,
        height_px=100,
        plot_type="pseudocolor",
    )

    state = MagicMock()
    results = task.run(state)

    assert "image_data" in results
    assert results["width"] == 100
    assert results["height"] == 100


def test_rendering_math():
    from karcytics_plugins.flow_cytometry.analysis.rendering import (
        compute_pseudocolor_points,
        histogram_curve,
    )

    x = np.linspace(0, 100, 50)
    centers, counts = histogram_curve(x, 10, 0, 100)
    assert len(counts) == 10
    assert counts.sum() == 50
    assert centers[0] == 5.0

    y = np.linspace(0, 100, 50)
    # compute_pseudocolor_points returns (x, y, colors)
    xv, yv, c = compute_pseudocolor_points(x, y, (0, 100), (0, 100))
    assert len(xv) == 50
    assert len(c) == 50


def test_rendering_custom_params():
    from karcytics_plugins.flow_cytometry.analysis.rendering import (
        compute_pseudocolor_points,
    )

    # Dense cluster to ensure some values pass threshold
    np.random.seed(42)
    x = np.random.normal(50, 5, 1000)
    y = np.random.normal(50, 5, 1000)

    # Render with defaults
    xv_def, yv_def, c_def = compute_pseudocolor_points(x, y, (0, 100), (0, 100))

    # Render with custom aggressive threshold and vibrancy
    xv_cust, yv_cust, c_cust = compute_pseudocolor_points(
        x,
        y,
        (0, 100),
        (0, 100),
        density_threshold=0.3,
        vibrancy_min=0.5,
        vibrancy_range=1.0,
    )

    assert len(xv_cust) == 1000
    # Custom config should zero out more background points than defaults
    zeros_def = np.sum(c_def == 0.0)
    zeros_cust = np.sum(c_cust == 0.0)
    assert zeros_cust > zeros_def


def test_compute_pseudocolor_base_density_disabled_returns_none():
    from karcytics_plugins.flow_cytometry.analysis.rendering import compute_pseudocolor_base_density

    x = np.linspace(0, 100, 50)
    y = np.linspace(0, 100, 50)
    assert compute_pseudocolor_base_density(x, y, max_events=1000, enabled=False) is None


def test_compute_pseudocolor_base_density_empty_input_returns_none():
    from karcytics_plugins.flow_cytometry.analysis.rendering import compute_pseudocolor_base_density

    empty = np.array([])
    assert compute_pseudocolor_base_density(empty, empty, max_events=1000, enabled=True) is None


def test_compute_pseudocolor_base_density_subsamples_large_input():
    """This is the fix for a real segfault-adjacent bug: the Comparisons
    Pseudocolor Overlay plot type used to run this (potentially multi-second)
    computation while holding the process-wide MPL_RASTER_LOCK, starving the main
    gating canvas's paint retries for the whole duration. It must stay a
    plain, subsampled numpy computation independent of any lock.
    """
    from karcytics_plugins.flow_cytometry.analysis.rendering import compute_pseudocolor_base_density

    rng = np.random.default_rng(0)
    n = 5000
    x = rng.normal(50, 10, n)
    y = rng.normal(50, 10, n)

    result = compute_pseudocolor_base_density(x, y, max_events=1000, enabled=True)
    assert result is not None
    x_plot, y_plot, c_plot = result
    assert len(x_plot) <= n
    # Subsampling should have kept the result well under the full input size.
    assert len(x_plot) < n
    assert len(x_plot) == len(y_plot) == len(c_plot)


def _fitted_sizes(monkeypatch) -> list[int]:
    """Record how many events each gaussian_kde fit receives."""
    from karcytics_plugins.flow_cytometry.analysis import rendering

    sizes: list[int] = []
    real = rendering.gaussian_kde

    def spy(values, **kwargs):
        sizes.append(len(values))
        return real(values, **kwargs)

    monkeypatch.setattr(rendering, "gaussian_kde", spy)
    return sizes


def test_kde_curve_fits_a_capped_subsample(monkeypatch):
    from karcytics_plugins.flow_cytometry.analysis.constants import KDE_MAX_EVENTS
    from karcytics_plugins.flow_cytometry.analysis.rendering import kde_curve

    sizes = _fitted_sizes(monkeypatch)
    values = np.random.default_rng(0).normal(100, 10, 200_000)
    x_grid, density = kde_curve(values, 50, 150)

    assert sizes[0] < KDE_MAX_EVENTS * 1.05
    assert len(x_grid) == len(density) == 512
    # Still the right curve: the peak sits at the mean.
    assert abs(x_grid[np.argmax(density)] - 100) < 2


def test_kde_curve_gives_none_for_constant_values():
    from karcytics_plugins.flow_cytometry.analysis.rendering import kde_curve

    assert kde_curve(np.full(500, 3.0), 0, 10) is None


def test_main_histogram_kde_uses_the_cap(monkeypatch):
    from karcytics_plugins.flow_cytometry.analysis.constants import KDE_MAX_EVENTS
    from karcytics_plugins.flow_cytometry.ui.graph.renderers.histogram import HistogramStrategy

    sizes = _fitted_sizes(monkeypatch)
    values = np.random.default_rng(1).normal(0, 1, 100_000)
    data = HistogramStrategy().compute(values, smooth_kde=True, bins=100)

    assert sizes[0] < KDE_MAX_EVENTS * 1.05
    assert data.kde_vals is not None
    # Count mode: the curve's area matches the bars' total count.
    bin_width = (data.bin_edges[-1] - data.bin_edges[0]) / data.bins
    area = np.trapz(data.kde_vals, data.x_grid) / bin_width
    assert abs(area - len(values)) / len(values) < 0.02


def test_density_grid_and_contour_levels():
    from karcytics_plugins.flow_cytometry.analysis.rendering import contour_levels, density_grid

    rng = np.random.default_rng(2)
    x, y = rng.normal(5, 1, 5000), rng.normal(2, 1, 5000)
    X, Y, density = density_grid(x, y, (0, 10), (-3, 7), bins=50)

    assert X.shape == Y.shape == density.shape == (50, 50)
    levels = contour_levels(density, 10)
    assert len(levels) == 10
    assert levels[0] > 0
    assert levels[-1] == density.max()
    assert list(contour_levels(np.zeros((5, 5)), 10)) == [0.0, 1.0]
