"""Tests for PipelineRibbon's sample combo refresh.

`refresh_samples()` used to restore the selected sample via an *unblocked*
`setCurrentIndex()` (only the clear/addItem loop was inside blockSignals),
then unconditionally called `_on_combo_changed()` again right after — so a
refresh that actually changed the selection emitted `sample_selected` twice
per call: once via the signal, once via the explicit trailing call.
Migrating to the shared `repopulate_combo` helper (Priority 1 UI #4) fixed
this as a side effect by keeping signals blocked through the restore too.
"""

import pytest

from karcytics_plugins.flow_cytometry.analysis.experiment import Sample
from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.ui.ribbons.pipeline_ribbon import PipelineRibbon


@pytest.fixture
def ribbon(qtbot):
    state = FlowState()
    state.data.experiment.samples["s1"] = Sample(sample_id="s1", display_name="Sample 1")
    state.data.experiment.samples["s2"] = Sample(sample_id="s2", display_name="Sample 2")
    state.view.current_sample_id = "s2"

    widget = PipelineRibbon(state)
    qtbot.addWidget(widget)
    return widget


@pytest.mark.ui
def test_refresh_samples_populates_combo_from_state(ribbon):
    ribbon.refresh_samples()

    assert ribbon._sample_combo.count() == 2
    assert ribbon._sample_combo.itemData(0) == "s1"
    assert ribbon._sample_combo.itemData(1) == "s2"


@pytest.mark.ui
def test_refresh_samples_selects_current_sample_from_state(ribbon):
    ribbon.refresh_samples()
    assert ribbon._sample_combo.currentData() == "s2"


@pytest.mark.ui
def test_refresh_samples_emits_sample_selected_exactly_once(ribbon):
    """Previously, restoring the selection happened *after* `blockSignals(False)`,
    so `setCurrentIndex` could fire `_on_combo_changed` via the signal *and*
    the explicit trailing call right after it — up to two `sample_selected`
    emissions for one `refresh_samples()` call. `repopulate_combo` keeps
    signals blocked through the restore, so only the explicit trailing call
    (still made unconditionally, same as before) fires it.
    """
    emitted = []
    ribbon.sample_selected.connect(emitted.append)

    ribbon.refresh_samples()

    assert emitted == ["s2"]
