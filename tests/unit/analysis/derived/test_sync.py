"""Tests for keeping derived columns in step with definitions and event tables."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from karcytics_plugins.flow_cytometry.analysis.derived import (
    DerivedParameter,
    strip_derived_columns,
    sync_fcs_data,
)
from karcytics_plugins.flow_cytometry.analysis.fcs_io import (
    FCSData,
    get_channel_marker_label,
    get_fluorescence_channels,
)

RATIO = DerivedParameter(
    param_id="derived:ratio001", name="B220/CD45", formula="[FITC-A] / [APC-A]"
)
SUM = DerivedParameter(param_id="derived:sum00002", name="Sum", formula="[FITC-A] + [APC-A]")


def _fcs(fitc=(10.0, 4.0, 6.0), apc=(2.0, 4.0, 0.0)) -> FCSData:
    events = pd.DataFrame({"FSC-A": [1.0, 2.0, 3.0], "FITC-A": list(fitc), "APC-A": list(apc)})
    return FCSData(
        file_path=Path("s.fcs"),
        channels=["FSC-A", "FITC-A", "APC-A"],
        markers=["", "B220", "CD45"],
        events=events,
        raw_events=events.copy(),
    )


def test_no_definitions_is_a_true_noop():
    fcs = _fcs()
    before = fcs.events
    result = sync_fcs_data(fcs, [])
    assert not result.changed
    assert fcs.events is before
    assert fcs.channels == ["FSC-A", "FITC-A", "APC-A"]


def test_adds_column_channel_and_label():
    fcs = _fcs()
    result = sync_fcs_data(fcs, [RATIO])
    assert result.changed
    np.testing.assert_array_equal(fcs.events[RATIO.param_id], [5.0, 1.0, np.nan])
    assert fcs.channels[-1] == RATIO.param_id
    assert get_channel_marker_label(fcs, RATIO.param_id) == "ƒ B220/CD45"
    # real channel labels are untouched
    assert get_channel_marker_label(fcs, "FITC-A") == "B220 (FITC-A)"


def test_raw_events_never_touched():
    fcs = _fcs()
    sync_fcs_data(fcs, [RATIO])
    assert RATIO.param_id not in fcs.raw_events.columns


def test_second_sync_is_noop_and_keeps_frame_identity():
    fcs = _fcs()
    sync_fcs_data(fcs, [RATIO])
    frame = fcs.events
    assert not sync_fcs_data(fcs, [RATIO]).changed
    assert fcs.events is frame


def test_new_frame_swapped_not_mutated():
    fcs = _fcs()
    original = fcs.events
    sync_fcs_data(fcs, [RATIO])
    assert fcs.events is not original
    assert RATIO.param_id not in original.columns


def test_replaced_events_are_recomputed_even_if_they_carry_stale_copies():
    """Compensation paths that copy `events` would drag old derived values along."""
    fcs = _fcs()
    sync_fcs_data(fcs, [RATIO])
    stale = fcs.events.copy()
    stale["FITC-A"] = stale["FITC-A"] * 10  # e.g. compensation changed the inputs
    fcs.events = stale
    assert sync_fcs_data(fcs, [RATIO]).changed
    np.testing.assert_array_equal(fcs.events[RATIO.param_id], [50.0, 10.0, np.nan])


def test_rebuilt_from_raw_events_gets_column_back():
    fcs = _fcs()
    sync_fcs_data(fcs, [RATIO])
    fcs.events = fcs.raw_events.copy()
    sync_fcs_data(fcs, [RATIO])
    assert RATIO.param_id in fcs.events.columns


def test_formula_change_recomputes_only_that_column():
    fcs = _fcs()
    ratio = DerivedParameter(RATIO.param_id, RATIO.name, RATIO.formula)
    sync_fcs_data(fcs, [ratio, SUM])
    ratio.formula = "[APC-A] / [FITC-A]"
    assert sync_fcs_data(fcs, [ratio, SUM]).changed
    np.testing.assert_allclose(fcs.events[ratio.param_id], [0.2, 1.0, 0.0])
    np.testing.assert_array_equal(fcs.events[SUM.param_id], [12.0, 8.0, 6.0])


def test_policy_change_recomputes():
    fcs = _fcs(fitc=(1.0, 1.0, 1.0), apc=(1.0, -1.0, 1.0))
    ratio = DerivedParameter(RATIO.param_id, RATIO.name, RATIO.formula)
    sync_fcs_data(fcs, [ratio])
    assert np.isnan(fcs.events[ratio.param_id].iloc[1])
    ratio.positive_denominators = False
    sync_fcs_data(fcs, [ratio])
    assert fcs.events[ratio.param_id].iloc[1] == -1.0


def test_removed_definition_drops_column_and_channel():
    fcs = _fcs()
    sync_fcs_data(fcs, [RATIO, SUM])
    sync_fcs_data(fcs, [SUM])
    assert RATIO.param_id not in fcs.events.columns
    assert RATIO.param_id not in fcs.channels
    assert RATIO.param_id not in fcs.derived_labels


def test_order_follows_definitions_after_real_channels():
    fcs = _fcs()
    sync_fcs_data(fcs, [SUM, RATIO])
    assert list(fcs.events.columns) == ["FSC-A", "FITC-A", "APC-A", SUM.param_id, RATIO.param_id]
    assert fcs.channels == ["FSC-A", "FITC-A", "APC-A", SUM.param_id, RATIO.param_id]


def test_missing_input_channel_yields_nan_column_not_keyerror():
    fcs = _fcs()
    missing = DerivedParameter("derived:missing1", "PE ratio", "[PE-A] / [APC-A]")
    result = sync_fcs_data(fcs, [missing])
    assert result.missing == {"derived:missing1": ["PE-A"]}
    assert fcs.events["derived:missing1"].isna().all()


def test_invalid_formula_does_not_break_sync():
    fcs = _fcs()
    broken = DerivedParameter("derived:broken01", "Broken", "[FITC-A] +")
    result = sync_fcs_data(fcs, [broken, RATIO])
    assert "derived:broken01" in result.errors
    assert fcs.events["derived:broken01"].isna().all()
    assert fcs.events[RATIO.param_id].iloc[0] == 5.0


def test_none_events_is_safe():
    fcs = FCSData(file_path=Path("x.fcs"))
    assert not sync_fcs_data(fcs, [RATIO]).changed


def test_derived_excluded_from_fluorescence_channels():
    fcs = _fcs()
    sync_fcs_data(fcs, [RATIO])
    assert get_fluorescence_channels(fcs) == ["FITC-A", "APC-A"]


def test_strip_derived_columns():
    fcs = _fcs()
    sync_fcs_data(fcs, [RATIO])
    assert list(strip_derived_columns(fcs.events).columns) == ["FSC-A", "FITC-A", "APC-A"]
    plain = pd.DataFrame({"A": [1]})
    assert strip_derived_columns(plain) is plain


@pytest.mark.parametrize("transform", ["biexponential", "bogus"])
def test_model_coerces_unsupported_transform_to_linear(transform):
    d = DerivedParameter("derived:x0000001", "X", "[A]", preferred_transform=transform)
    assert d.preferred_transform == "linear"


def test_model_round_trip():
    d = DerivedParameter("derived:x0000001", "X", "[A] / [B]", "log", False)
    again = DerivedParameter.from_dict(d.to_dict())
    assert again.to_dict() == d.to_dict()
    assert again.expression.channels == ("A", "B")
