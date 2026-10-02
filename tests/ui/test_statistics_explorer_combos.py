"""Tests for `StatisticsExplorer`'s channel and chart-stat combo repopulation,
migrated to the shared `repopulate_combo` helper (SDK_Abstraction_Performance_Plan.md
Priority 1 UI #4).
"""

from pathlib import Path

import pandas as pd
import pytest

from karcytics_plugins.flow_cytometry.analysis.experiment import Sample
from karcytics_plugins.flow_cytometry.analysis.fcs_io import FCSData
from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.analysis.statistics import StatType
from karcytics_plugins.flow_cytometry.ui.widgets.statistics_explorer import StatisticsExplorer


def _sample_with_channels(sample_id, channels):
    sample = Sample(sample_id=sample_id, display_name=sample_id)
    events = pd.DataFrame({ch: [0.0, 1.0] for ch in channels})
    sample.fcs_data = FCSData(
        file_path=Path("sample.fcs"), channels=channels, markers=[""] * len(channels), events=events
    )
    return sample


@pytest.fixture
def widget(qtbot):
    state = FlowState()
    state.data.experiment.samples["s1"] = _sample_with_channels("s1", ["FSC-A", "SSC-A", "FITC-A"])
    w = StatisticsExplorer(state)
    qtbot.addWidget(w)
    w.refresh_samples()
    return w


@pytest.mark.ui
def test_refresh_channel_combo_populates_from_first_checked_sample(widget):
    widget._refresh_channel_combo()

    assert widget._channel_combo.count() == 3
    assert widget._channel_combo.itemData(0) == "FSC-A"


@pytest.mark.ui
def test_refresh_channel_combo_empties_when_nothing_checked(widget):
    widget._refresh_channel_combo()
    widget._selector.population_selector.check_all(False)

    widget._refresh_channel_combo()

    assert widget._channel_combo.count() == 0


def _prime_compute_state(widget, stats):
    """Set the `_current_*` bookkeeping `_on_compute()` normally sets right
    before starting the background worker — `_on_compute_success` reads
    these for `_populate_table`, so a direct unit-level call needs them too.
    """
    widget._current_sample_ids = []
    widget._current_pop_pairs = []
    widget._current_stats = stats
    widget._current_channel = None


@pytest.mark.ui
def test_on_compute_success_populates_chart_stat_combo(widget):
    _prime_compute_state(widget, [StatType.COUNT, StatType.PERCENT_TOTAL])

    widget._on_compute_success([])

    assert widget._chart_stat_combo.count() == 2
    assert widget._chart_stat_combo.itemData(0) == StatType.COUNT
