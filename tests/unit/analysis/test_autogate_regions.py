"""Density regions, search scales and a deterministic display transform."""

import numpy as np

from karcytics_plugins.flow_cytometry.analysis._utils import project_to_display
from karcytics_plugins.flow_cytometry.analysis.autogate.population import search_scale
from karcytics_plugins.flow_cytometry.analysis.autogate.regions import density_regions
from karcytics_plugins.flow_cytometry.analysis.scaling import AxisScale
from karcytics_plugins.flow_cytometry.analysis.transforms import TransformType


def _blob(rng, centre, sd, n):
    return rng.normal(centre, sd, (n, 2))


def test_one_population_is_one_region_at_any_size():
    rng = np.random.default_rng(0)
    for n in (800, 5000, 20_000):
        xy = _blob(rng, (0, 0), 1, n)
        found = density_regions(xy[:, 0], xy[:, 1], 0.3)
        assert found is not None and len(found.regions) == 1, n


def test_separate_groups_stay_apart_and_a_speck_between_them_does_not_join_them():
    rng = np.random.default_rng(1)
    xy = np.vstack(
        (
            _blob(rng, (0, 0), 1, 9000),
            _blob(rng, (9, 0), 0.7, 1000),
            _blob(rng, (4.5, 0), 0.3, 40),  # a few events in the gap
        )
    )
    found = density_regions(xy[:, 0], xy[:, 1], 0.3)
    assert found is not None
    big = [r for r in found.regions if r.weight > 0.05]
    assert len(big) == 2
    assert abs(big[0].peak[0]) < 1 and abs(big[1].peak[0] - 9) < 1


def test_an_outline_follows_a_lopsided_population():
    rng = np.random.default_rng(2)
    arm = np.column_stack((rng.uniform(0, 8, 6000), rng.normal(0, 0.4, 6000)))
    leg = np.column_stack((rng.normal(0, 0.4, 6000), rng.uniform(0, 8, 6000)))
    xy = np.vstack((arm, leg))  # an L
    found = density_regions(xy[:, 0], xy[:, 1], 0.3)
    shape = found.joined(list(found.regions))
    from matplotlib.path import Path

    path = Path(shape)
    assert path.contains_points(xy).mean() > 0.9
    assert not path.contains_point((6, 6))  # the empty corner of the L stays out


def test_side_scatter_crowded_on_linear_is_searched_on_biexponential():
    rng = np.random.default_rng(3)
    ssc = rng.lognormal(8, 0.6, 10_000)  # most low, a long tail
    assert search_scale(ssc, AxisScale()).transform_type == TransformType.BIEXPONENTIAL
    fsc = rng.normal(70_000, 15_000, 10_000)
    linear = AxisScale()
    assert search_scale(fsc, linear) is linear
    biexp = AxisScale(transform_type=TransformType.BIEXPONENTIAL)
    assert search_scale(ssc, biexp) is biexp  # the app's own non-linear choice stands


def test_the_biexponential_display_is_the_same_every_time():
    values = np.random.default_rng(4).normal(500, 300, 5000)
    scale = AxisScale(transform_type=TransformType.BIEXPONENTIAL)
    assert np.array_equal(project_to_display(values, scale), project_to_display(values, scale))
