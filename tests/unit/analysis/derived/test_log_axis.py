"""Log axes for derived parameters, whose values mostly sit below 1.

The detector log floor (1.0) clamps every ratio < 1 onto one point — the
histogram collapses to a single bar and a Range gate between 0.3 and 0.9
can't tell 0.01 from 0.6.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from karcytics_plugins.flow_cytometry.analysis.axis_manager import AxisManager
from karcytics_plugins.flow_cytometry.analysis.constants import DERIVED_LOG_FLOOR
from karcytics_plugins.flow_cytometry.analysis.derived import DerivedParameter
from karcytics_plugins.flow_cytometry.analysis.derived.expression import parse_formula
from karcytics_plugins.flow_cytometry.analysis.derived.preview import compute_preview
from karcytics_plugins.flow_cytometry.analysis.gating.range import RangeGate
from karcytics_plugins.flow_cytometry.analysis.scaling import (
    AxisScale,
    compute_axis_limits,
    get_transform_kwargs,
)
from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.analysis.transforms import (
    TransformType,
    apply_transform,
    log_decade_tick_values,
)

RATIO_KEY = "derived:ratio001"
RATIOS = np.array([0.005, 0.01, 0.012, 0.3, 0.6, 0.65, 1.1])


def _derived_log_scale() -> AxisScale:
    return AxisScale(TransformType.LOG, log_floor=DERIVED_LOG_FLOOR)


class TestLogFloor:
    def test_detector_scale_unchanged(self):
        scale = AxisScale(TransformType.LOG)
        assert get_transform_kwargs(scale) == {"min_value": 1.0}
        out = apply_transform(
            np.array([0.5, 10.0]), scale.transform_type, **get_transform_kwargs(scale)
        )
        np.testing.assert_allclose(out, [0.0, 1 / 4.5])

    def test_derived_scale_keeps_sub_one_values_apart(self):
        scale = _derived_log_scale()
        out = apply_transform(RATIOS, scale.transform_type, **get_transform_kwargs(scale))
        assert len(np.unique(out)) == len(RATIOS)

    def test_axis_limits_cover_the_data(self):
        scale = _derived_log_scale()
        kwargs = get_transform_kwargs(scale)
        lo, hi = compute_axis_limits(RATIOS, scale, kwargs)
        shown = apply_transform(RATIOS, scale.transform_type, **kwargs)
        assert lo < shown.min() and shown.max() < hi

    def test_round_trips_through_dict_and_copy(self):
        scale = _derived_log_scale()
        assert AxisScale.from_dict(scale.to_dict()).log_floor == DERIVED_LOG_FLOOR
        assert scale.copy().log_floor == DERIVED_LOG_FLOOR
        assert AxisScale.from_dict({"transform_type": "log"}).log_floor == 1.0

    def test_rejects_non_positive_floor(self):
        with pytest.raises(ValueError, match="log_floor"):
            AxisScale(TransformType.LOG, log_floor=0.0)


class TestAxisManagerDefaults:
    def test_derived_axis_gets_derived_floor_and_detector_does_not(self):
        state = FlowState()
        state.data.experiment.derived_parameters = [
            DerivedParameter(RATIO_KEY, "B220/CD45", "[FITC-A] / [APC-A]")
        ]
        manager = AxisManager(state)
        derived = manager.get_scale(RATIO_KEY)
        assert derived.transform_type == TransformType.LOG
        assert derived.log_floor == DERIVED_LOG_FLOOR
        assert manager.get_scale("FITC-A").log_floor == 1.0


class TestRangeGateOnDerivedLogAxis:
    def test_separates_sub_one_ratios(self):
        gate = RangeGate(RATIO_KEY, low=0.3, high=0.9, x_scale=_derived_log_scale())
        inside = gate.contains(pd.DataFrame({RATIO_KEY: RATIOS}))
        assert inside.tolist() == [False, False, False, True, True, True, False]

    def test_floor_survives_serialization(self):
        gate = RangeGate(RATIO_KEY, low=0.3, high=0.9, x_scale=_derived_log_scale())
        assert gate.to_dict()["x_scale"]["log_floor"] == DERIVED_LOG_FLOOR


class TestDecadeTicks:
    def test_ratio_range(self):
        values, labels = log_decade_tick_values(0.0005, 2.0)
        np.testing.assert_allclose(values, [1e-3, 1e-2, 1e-1, 1.0])
        assert labels == ["$10^{-3}$", "$10^{-2}$", "$10^{-1}$", "$10^{0}$"]

    def test_detector_range(self):
        values, _ = log_decade_tick_values(1.0, 262144.0)
        np.testing.assert_allclose(values, [1, 10, 100, 1e3, 1e4, 1e5])

    @pytest.mark.parametrize(("lo", "hi"), [(1.0, 1.0), (-5.0, 0.0), (np.nan, 1.0), (2.0, 1.0)])
    def test_empty_for_degenerate_ranges(self, lo, hi):
        values, labels = log_decade_tick_values(lo, hi)
        assert len(values) == 0 and labels == []

    def test_caps_the_number_of_decades(self):
        values, _ = log_decade_tick_values(1e-30, 1e5)
        assert len(values) <= 13  # noqa: PLR2004


class TestPreviewReference:
    def _frames(self):
        rng = np.random.default_rng(0)
        b = pd.DataFrame({"A": rng.lognormal(np.log(0.6), 0.2, 500), "B": 1.0})
        t = pd.DataFrame({"A": rng.lognormal(np.log(0.01), 0.3, 500), "B": 1.0})
        return b, t, pd.concat([b, t], ignore_index=True)

    def test_populations_share_the_reference_axis(self):
        b, t, sample = self._frames()
        expr = parse_formula("[A] / [B]")
        kw = {"positive_denominators": True, "log_scale": True, "reference": sample}
        sb, st = compute_preview(expr, b, **kw), compute_preview(expr, t, **kw)
        np.testing.assert_array_equal(sb.edges, st.edges)
        assert sb.reference_counts is not None
        assert sb.reference_counts.sum() > sb.counts.sum()
        # B cells land right of T cells on the shared axis.
        centers = np.sqrt(sb.edges[:-1] * sb.edges[1:])
        assert np.average(centers, weights=sb.counts) > 10 * np.average(centers, weights=st.counts)

    def test_log_ticks_are_decades_in_axis_fractions(self):
        _, _, sample = self._frames()
        s = compute_preview(
            parse_formula("[A]"), sample, positive_denominators=True, log_scale=True
        )
        labels = [label for _, label in s.ticks]
        assert "0.01" in labels and "0.1" in labels
        assert all(0.0 <= frac <= 1.0 for frac, _ in s.ticks)

    def test_linear_ticks_are_round_numbers(self):
        df = pd.DataFrame({"A": np.linspace(0.0, 1.0, 200)})
        s = compute_preview(parse_formula("[A]"), df, positive_denominators=True, log_scale=False)
        assert 2 <= len(s.ticks) <= 6  # noqa: PLR2004
        assert all(float(label) * 10 % 1 == 0 for _, label in s.ticks)

    def test_no_reference_by_default(self):
        b, _, _ = self._frames()
        s = compute_preview(parse_formula("[A]"), b, positive_denominators=True, log_scale=True)
        assert s.reference_counts is None
