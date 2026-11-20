"""The Statistics tab's channel and chart-statistic pickers."""

from pathlib import Path

import pandas as pd
import pytest

from karcytics_plugins.flow_cytometry.analysis.experiment import Sample
from karcytics_plugins.flow_cytometry.analysis.fcs_io import FCSData
from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.analysis.statistics import StatType
from karcytics_plugins.flow_cytometry.analysis.statistics_table import (
    StatisticsRequest,
    compute_table,
)
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
    widget.refresh_channels()

    assert widget._channel_combo.count() == 3
    assert widget._channel_combo.itemData(0) == "FSC-A"


@pytest.mark.ui
def test_refresh_channel_combo_empties_when_nothing_checked(widget):
    widget.refresh_channels()
    widget._selector.population_selector.check_all(False)

    widget.refresh_channels()

    assert widget._channel_combo.count() == 0


@pytest.mark.ui
def test_computed_results_fill_the_chart_statistic_picker(widget):
    request = StatisticsRequest((), (), (StatType.COUNT, StatType.PERCENT_TOTAL), None)

    widget.show_table(compute_table(widget._state.data.experiment, request))

    assert widget._chart_stat_combo.count() == 2  # noqa: PLR2004
    assert widget._chart_stat_combo.itemData(0) == StatType.COUNT
