import numpy as np
import pytest

from karcytics_plugins.flow_cytometry.analysis.scaling import (
    calculate_auto_range,
    detect_logicle_top,
    estimate_logicle_params,
)
from karcytics_plugins.flow_cytometry.analysis.transforms import TransformType


@pytest.mark.unit
class TestLinearAutoRange:
    def test_linear_floor_anchored_at_zero(self):
        """Positive data should have a floor of 0 on a linear scale."""
        data = np.random.uniform(1000, 200000, 1000)
        vmin, vmax = calculate_auto_range(data, TransformType.LINEAR)
        assert vmin == 0.0

    def test_linear_ceiling_is_dynamic(self):
        """Ceiling should adapt to data range with headroom, not stay fixed at 262144."""
        data = np.random.uniform(0, 100000, 1000)
        vmin, vmax = calculate_auto_range(data, TransformType.LINEAR)
        # 100k + 5% headroom = 105k
        assert vmax >= 100000.0
        assert vmax < 110000.0

    def test_linear_snaps_to_18bit_range(self):
        """If data is close to 18-bit max, it should snap to exactly 262144 for clean axis."""
        data = np.random.uniform(0, 250000, 1000)
        vmin, vmax = calculate_auto_range(data, TransformType.LINEAR)
        assert vmax == 262144.0

    def test_linear_negative_compensation_floor(self):
        """If p0.05 is negative, the floor should extend to encompass the negative data."""
        data = np.concatenate(
            [
                np.random.uniform(-5000, 200000, 9500),
                np.random.uniform(-10000, -5000, 500),
            ]
        )
        vmin, vmax = calculate_auto_range(data, TransformType.LINEAR)
        assert vmin < 0.0
        assert vmin <= float(np.percentile(data, 0.1))


@pytest.mark.unit
class TestBiexponentialAutoRange:
    def test_biex_positive_only_min_is_positive(self):
        """For positive-only data, the min should be negative to provide space around zero (FlowJo style)."""
        data = np.random.uniform(10000, 200000, 1000)
        vmin, vmax = calculate_auto_range(data, TransformType.BIEXPONENTIAL)
        assert vmin <= -100.0

    def test_biex_with_negatives_min_extends_below(self):
        """For data with genuine negatives, the min should extend below the lowest negative percentile."""
        data = np.concatenate(
            [
                np.random.uniform(-5000, 200000, 9500),
                np.random.uniform(-20000, -10000, 500),
            ]
        )
        vmin, vmax = calculate_auto_range(data, TransformType.BIEXPONENTIAL)
        p_lo = float(np.percentile(data, 0.5))
        assert vmin < 0.0
        assert vmin < p_lo

    def test_biex_max_adapts_to_data(self):
        """The ceiling should dynamically exceed 262144 if a large portion of the data goes higher."""
        data = np.random.uniform(10000, 500000, 1000)
        vmin, vmax = calculate_auto_range(data, TransformType.BIEXPONENTIAL)
        assert vmax > 262144.0
        assert vmax > 500000.0


@pytest.mark.unit
class TestLogicleTopDetection:
    def test_detect_logicle_top_standard_18bit(self):
        """Data within standard bounds gets a T of 262144."""
        data = np.random.uniform(0, 250000, 1000)
        t = detect_logicle_top(data)
        assert t == 262144.0

    def test_detect_logicle_top_saturation_headroom(self):
        """A small overshoot above 262144 (e.g., from compensation) should not jump to 1M."""
        data = np.random.uniform(0, 300000, 1000)  # Exceeds 262144 slightly
        t = detect_logicle_top(data)
        assert t == 262144.0

    def test_detect_logicle_top_20bit_instrument(self):
        """Data legitimately exceeding the 18-bit range goes to the 20-bit bucket (1M)."""
        data = np.random.uniform(0, 800000, 1000)
        t = detect_logicle_top(data)
        assert t == 1048576.0


@pytest.mark.unit
class TestLogicleParamsEstimation:
    def test_estimate_logicle_params_positive_data(self):
        """Positive data gets a default W of 0.5 (half decade)."""
        data = np.random.uniform(100, 200000, 1000)
        w, a = estimate_logicle_params(data)
        assert w == 0.5
        assert a == 0.0

    def test_estimate_logicle_params_with_negatives(self):
        """Data with negatives computes W based on flowCore equation."""
        data = np.concatenate(
            [
                np.random.uniform(-5000, 200000, 9500),
                np.random.uniform(-20000, -10000, 500),
            ]
        )
        w, a = estimate_logicle_params(data)
        assert w > 0.5
        assert w < 2.5
        assert isinstance(a, float)


def test_fit_scale_ranges_on_the_sample_and_shapes_on_the_parent():
    import pandas as pd

    from karcytics_plugins.flow_cytometry.analysis.scaling import AxisScale, fit_scale

    rng = np.random.default_rng(0)
    sample = pd.DataFrame(
        {"CD3": np.concatenate([rng.normal(0, 300, 5000), rng.normal(5e4, 5e3, 5000)])}
    )
    parent = sample[sample["CD3"] > 1000]  # a gated subset with no negative tail
    fitted = fit_scale(AxisScale(TransformType.BIEXPONENTIAL), "CD3", sample, parent)

    assert fitted.min_val < 0 and fitted.max_val > 4e4  # noqa: PLR2004 - the whole sample's range
    assert fitted.logicle_w == pytest.approx(0.5)  # no negative tail in the parent

    kept = AxisScale(TransformType.BIEXPONENTIAL, min_val=-10.0, max_val=10.0)
    assert (fit_scale(kept, "CD3", sample, parent).min_val, kept.min_val) == (-10.0, -10.0)
