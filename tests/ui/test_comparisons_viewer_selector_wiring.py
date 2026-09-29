"""Smoke test: ComparisonsViewer wires correctly to the shared
SampleAndPopulationSelector (Phase 3 refactor), including switching between
multi-select and single-select (radio) population modes per plot type.
"""

import pytest

from karcytics_plugins.flow_cytometry.analysis.experiment import Sample
from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.ui.widgets.comparisons_viewer import ComparisonsViewer


@pytest.fixture
def flow_state_with_samples():
    state = FlowState()
    for sid in ("s1", "s2"):
        sample = Sample(sample_id=sid, display_name=sid)
        sample.gate_tree.add_child(None, name="Lymphocytes")
        state.data.experiment.samples[sid] = sample
    return state


@pytest.mark.ui
def test_plot_type_switch_toggles_multi_population_mode(qtbot, flow_state_with_samples):
    widget = ComparisonsViewer(flow_state_with_samples)
    qtbot.addWidget(widget)

    # Violin is single-pop mode: every checked sample defaults to "All Events" only.
    idx = widget._plot_type_combo.findText("🎻  Violin Plot")
    widget._plot_type_combo.setCurrentIndex(idx)
    checked = widget._selector.get_checked_populations()
    assert len(checked) == 2
    assert all(label == "All Events" for _sid, _nid, label in checked)
    assert widget._selector.population_selector._multi_select is False

    # Heatmap is multi-pop mode: grouped Shared/Sample-Specific selection.
    idx = widget._plot_type_combo.findText("🗺️  Channel Heatmap")
    widget._plot_type_combo.setCurrentIndex(idx)
    assert widget._selector.population_selector._multi_select is True
    checked = widget._selector.get_checked_populations()
    labels = {label for _sid, _nid, label in checked}
    assert "Lymphocytes" in labels
