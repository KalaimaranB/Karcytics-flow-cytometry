"""Tests for `PopulationAnalysisViewer`'s sample/gate/history combo
repopulation, migrated to the shared `repopulate_combo` helper
(SDK_Abstraction_Performance_Plan.md Priority 1 UI #4).
"""

from unittest.mock import MagicMock

import pytest

from karcytics_plugins.flow_cytometry.analysis.experiment import Sample
from karcytics_plugins.flow_cytometry.analysis.services.umap_service import UmapService
from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.ui.widgets.population_analysis_viewer import (
    PopulationAnalysisViewer,
)


@pytest.fixture
def viewer(qtbot):
    state = FlowState()
    for sid in ("s1", "s2"):
        state.data.experiment.samples[sid] = Sample(sample_id=sid, display_name=f"Sample {sid}")
    umap_service = UmapService(state, MagicMock())
    widget = PopulationAnalysisViewer(state, umap_service)
    qtbot.addWidget(widget)
    return widget


@pytest.mark.ui
def test_refresh_samples_populates_sample_combo(viewer):
    assert viewer._sample_combo.count() == 2
    assert viewer._sample_combo.itemData(0) == "s1"


@pytest.mark.ui
def test_refresh_samples_restores_a_still_valid_prior_selection(viewer):
    viewer._sample_combo.setCurrentIndex(1)  # "s2"

    viewer.refresh_samples()

    assert viewer._sample_combo.currentData() == "s2"


@pytest.mark.ui
def test_refresh_samples_does_not_emit_signals_while_rebuilding(viewer):
    fired = []
    viewer._sample_combo.currentIndexChanged.connect(lambda idx: fired.append(idx))

    viewer.refresh_samples()

    assert fired == []


@pytest.mark.ui
def test_refresh_gates_always_has_all_events_first(viewer):
    assert viewer._gate_combo.itemText(0) == "⬡  All Events (no gate)"
    assert viewer._gate_combo.itemData(0) is None


@pytest.mark.ui
def test_refresh_gates_lists_named_nodes_in_the_selected_samples_tree(viewer):
    sample = viewer._state.data.experiment.samples["s1"]
    node = sample.gate_tree.add_child(None, name="Lymphocytes")

    viewer._refresh_gates()

    assert viewer._gate_combo.count() == 2
    assert viewer._gate_combo.itemData(1) == node.node_id


@pytest.mark.ui
def test_refresh_gates_restores_a_still_valid_prior_selection(viewer):
    sample = viewer._state.data.experiment.samples["s1"]
    node = sample.gate_tree.add_child(None, name="Lymphocytes")
    viewer._refresh_gates()
    viewer._gate_combo.setCurrentIndex(1)

    viewer._refresh_gates()

    assert viewer._gate_combo.currentData() == node.node_id


@pytest.mark.ui
def test_refresh_gates_does_not_emit_signals_while_rebuilding(viewer):
    fired = []
    viewer._gate_combo.currentIndexChanged.connect(lambda idx: fired.append(idx))

    viewer._refresh_gates()

    assert fired == []


@pytest.mark.ui
def test_refresh_history_always_has_new_run_first(viewer):
    assert viewer._history_combo.itemText(0) == "[ New Run ]"
    assert viewer._history_combo.itemData(0) is None


@pytest.mark.ui
def test_refresh_history_lists_runs_for_the_current_sample_and_gate(viewer):
    sample_id = viewer._sample_combo.currentData()
    key = f"{sample_id}::root"
    viewer._state.data.umap_results[key] = [{"name": "First run"}]

    viewer.refresh_history()

    assert viewer._history_combo.count() == 2
    assert viewer._history_combo.itemText(1) == "1. First run"


@pytest.mark.ui
def test_refresh_history_does_not_emit_signals_while_rebuilding(viewer):
    fired = []
    viewer._history_combo.currentIndexChanged.connect(lambda idx: fired.append(idx))

    viewer.refresh_history()

    assert fired == []
