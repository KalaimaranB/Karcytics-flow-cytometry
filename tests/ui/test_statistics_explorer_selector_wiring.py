"""Smoke test: StatisticsExplorer wires correctly to the shared
SampleAndPopulationSelector (Phase 3 refactor) instead of its own duplicated
sample/population checklist.
"""

import pytest

from karcytics_plugins.flow_cytometry.analysis.experiment import Sample
from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.analysis.statistics import StatType
from karcytics_plugins.flow_cytometry.ui.widgets.statistics_explorer import StatisticsExplorer


@pytest.fixture
def flow_state_with_samples():
    state = FlowState()
    for sid in ("s1", "s2"):
        sample = Sample(sample_id=sid, display_name=sid)
        sample.gate_tree.add_child(None, name="Lymphocytes")
        state.data.experiment.samples[sid] = sample
    return state


@pytest.mark.ui
def test_refresh_samples_updates_selector(qtbot, flow_state_with_samples):
    widget = StatisticsExplorer(flow_state_with_samples)
    qtbot.addWidget(widget)

    new_sample = Sample(sample_id="s3", display_name="s3")
    flow_state_with_samples.data.experiment.samples["s3"] = new_sample
    widget.refresh_samples()

    assert "s3" in widget._selector.get_checked_sample_ids()


@pytest.mark.ui
def test_compute_drops_sample_columns_with_no_checked_population(qtbot):
    """A population unique to one sample (e.g. only ever gated on Sample C)
    shouldn't produce an all-"-" placeholder column for every other sample —
    the table's columns should track which samples the checked populations
    actually apply to. The grid always shows every experiment sample as a
    column now (there's no separate sample checklist to gate that), so this
    guards `get_checked_sample_ids()`'s derive-from-populations behavior.
    """
    state = FlowState()
    for sid in ("s1", "s2", "s3"):
        state.data.experiment.samples[sid] = Sample(sample_id=sid, display_name=sid)
    state.data.experiment.samples["s1"].gate_tree.add_child(None, name="B-cells")

    widget = StatisticsExplorer(state)
    qtbot.addWidget(widget)
    widget.refresh_samples()

    widget._selector.population_selector.check_all(False)
    widget._selector.population_selector._toggle_cell("s1", "B-cells")

    for stat, cb in widget._stat_checkboxes.items():
        cb.setChecked(stat == StatType.PERCENT_TOTAL)

    widget._on_compute()

    assert widget._current_sample_ids == ["s1"]
