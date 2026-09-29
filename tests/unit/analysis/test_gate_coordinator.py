import sys
import time

import pytest
from PyQt6.QtWidgets import QApplication

# Ensure QApplication exists for signal processing
from karcytics_plugins.flow_cytometry.analysis.axis_manager import AxisManager
from karcytics_plugins.flow_cytometry.analysis.gate_coordinator import GateCoordinator
from karcytics_plugins.flow_cytometry.analysis.gate_propagator import GatePropagator
from karcytics_plugins.flow_cytometry.analysis.population_service import PopulationService

app = QApplication.instance() or QApplication(sys.argv)

# Make debounce instantaneous for tests
GatePropagator.DEBOUNCE_MS = 0


@pytest.fixture
def gate_coordinator(flow_state):
    axis_manager = AxisManager(flow_state)
    pop_service = PopulationService(flow_state)
    from unittest.mock import MagicMock

    mock_scheduler = MagicMock()

    # Mock submit to just run the task synchronously
    def sync_submit(worker, state):
        res = worker.run(state)
        # Check if it's the StatisticsAnalysis worker
        from karcytics_plugins.flow_cytometry.analysis.statistics_analysis import (
            StatisticsAnalysis,
        )

        if isinstance(worker, StatisticsAnalysis):
            # The callback is connected to task_finished signal
            if hasattr(mock_scheduler, "task_finished"):
                mock_scheduler.task_finished.emit("test_task_1", res)
        else:
            # Call the finished signal manually since we aren't using the real scheduler
            controller.propagator._on_propagation_finished("test_task_1", res)
        return MagicMock(task_id="test_task_1")

    mock_scheduler.submit.side_effect = sync_submit
    mock_scheduler.task_finished = MagicMock()

    controller = GateCoordinator(
        flow_state, axis_manager, pop_service, task_scheduler=mock_scheduler
    )
    controller.sync_stats = True
    return controller


def wait_for_propagation(gate_coordinator):
    time.sleep(0.05)
    gate_coordinator.propagator.cleanup()


def test_add_rectangle_gate(gate_coordinator, flow_state, gate_rectangle_singlet):
    sample_id = "test_sample_1"

    # Add a gate
    node_id = gate_coordinator.add_gate(gate_rectangle_singlet, sample_id, name="Singlets")

    assert node_id is not None
    sample = flow_state.data.experiment.samples[sample_id]

    # Check tree
    node = sample.gate_tree.find_node_by_id(node_id)
    assert node is not None
    assert node.name == "Singlets"
    assert node.gate == gate_rectangle_singlet

    # Wait for background task to complete
    wait_for_propagation(gate_coordinator)

    # Check stats were computed
    assert "count" in node.statistics
    assert node.statistics["count"] > 0
    assert node.statistics["pct_parent"] <= 100.0


def test_add_quadrant_gate(gate_coordinator, flow_state, gate_quadrant_cd4_cd8):
    sample_id = "test_sample_1"

    gate_coordinator.add_gate(gate_quadrant_cd4_cd8, sample_id)
    wait_for_propagation(gate_coordinator)

    sample = flow_state.data.experiment.samples[sample_id]

    assert len(sample.gate_tree.children) == 4

    labels = [n.name for n in sample.gate_tree.children]
    assert labels == ["Q1", "Q2", "Q3", "Q4"]


def test_modify_gate(gate_coordinator, flow_state, gate_rectangle_singlet):
    sample_id = "test_sample_1"
    node_id = gate_coordinator.add_gate(gate_rectangle_singlet, sample_id, name="Singlets")

    wait_for_propagation(gate_coordinator)

    sample = flow_state.data.experiment.samples[sample_id]
    node = sample.gate_tree.find_node_by_id(node_id)

    orig_count = node.statistics.get("count", 0)

    # Modify gate to be much smaller
    success = gate_coordinator.modify_gate(
        gate_rectangle_singlet.gate_id,
        sample_id,
        x_min=100_000,
        x_max=110_000,
        y_min=80_000,
        y_max=90_000,
    )

    assert success is True
    assert gate_rectangle_singlet.x_min == 100_000

    wait_for_propagation(gate_coordinator)

    # Check stats updated
    new_count = node.statistics["count"]
    assert new_count < orig_count


def test_remove_population(gate_coordinator, flow_state, gate_rectangle_singlet):
    sample_id = "test_sample_1"
    node_id = gate_coordinator.add_gate(gate_rectangle_singlet, sample_id, name="Singlets")

    wait_for_propagation(gate_coordinator)

    success = gate_coordinator.remove_population(sample_id, node_id)
    assert success is True

    sample = flow_state.data.experiment.samples[sample_id]
    assert sample.gate_tree.find_node_by_id(node_id) is None


def test_rename_population(gate_coordinator, flow_state, gate_rectangle_singlet):
    sample_id = "test_sample_1"
    node_id = gate_coordinator.add_gate(gate_rectangle_singlet, sample_id, name="Singlets")

    success = gate_coordinator.rename_population(sample_id, node_id, "New Name")
    assert success is True

    wait_for_propagation(gate_coordinator)

    sample = flow_state.data.experiment.samples[sample_id]
    node = sample.gate_tree.find_node_by_id(node_id)
    assert node.name == "New Name"


def test_split_population(gate_coordinator, flow_state, gate_rectangle_singlet):
    sample_id = "test_sample_1"
    node_id = gate_coordinator.add_gate(gate_rectangle_singlet, sample_id, name="Singlets")

    wait_for_propagation(gate_coordinator)

    sibling_id = gate_coordinator.split_population(sample_id, node_id)
    assert sibling_id is not None

    wait_for_propagation(gate_coordinator)

    sample = flow_state.data.experiment.samples[sample_id]
    sibling = sample.gate_tree.find_node_by_id(sibling_id)

    assert sibling is not None
    assert sibling.negated is True
    assert sibling.name == "Singlets (Outside)"


def test_modify_gate_invalidates_the_node_mask_cache(
    gate_coordinator, flow_state, gate_rectangle_singlet
):
    """`GateNode._get_mask` caches per-events masks (Priority 1 analysis #1).
    `StatisticsAnalysis._walk_and_compute` doesn't exercise it for regular
    gate nodes (it calls `gate.contains()` directly), so this checks the
    cache itself via `apply_hierarchy` — the entry point every UI refresh
    path (render_window, graph_window, comparisons, population/UMAP views)
    actually calls.
    """
    sample_id = "test_sample_1"
    node_id = gate_coordinator.add_gate(gate_rectangle_singlet, sample_id, name="Singlets")
    wait_for_propagation(gate_coordinator)

    sample = flow_state.data.experiment.samples[sample_id]
    node = sample.gate_tree.find_node_by_id(node_id)
    events = sample.fcs_data.events

    orig_count = len(node.apply_hierarchy(events))

    success = gate_coordinator.modify_gate(
        gate_rectangle_singlet.gate_id,
        sample_id,
        x_min=100_000,
        x_max=110_000,
        y_min=80_000,
        y_max=90_000,
    )
    assert success is True
    wait_for_propagation(gate_coordinator)

    new_count = len(node.apply_hierarchy(events))
    assert new_count < orig_count


def test_modify_gate_does_not_recompute_an_unrelated_siblings_gate(
    gate_coordinator, flow_state, gate_rectangle_singlet, gate_rectangle_lymph, monkeypatch
):
    """End-to-end proof of Priority 1 analysis #3 (scoped recompute) through
    the real `GateCoordinator` → `gate_mutation_service` → `StatisticsAnalysis`
    → `DagEvaluator.evaluate_scoped` pipeline, not just the DagEvaluator unit
    tests: an edit to one gate must never even *call* an unrelated sibling's
    `.contains()`, let alone get a different answer from it.
    """
    sample_id = "test_sample_1"
    gate_coordinator.add_gate(gate_rectangle_singlet, sample_id, name="A")
    gate_coordinator.add_gate(gate_rectangle_lymph, sample_id, name="B")
    wait_for_propagation(gate_coordinator)

    calls = []
    original_contains = gate_rectangle_lymph.contains

    def spy_contains(events):
        calls.append(1)
        return original_contains(events)

    monkeypatch.setattr(gate_rectangle_lymph, "contains", spy_contains)

    gate_coordinator.modify_gate(
        gate_rectangle_singlet.gate_id,
        sample_id,
        x_min=100_000,
        x_max=110_000,
        y_min=80_000,
        y_max=90_000,
    )
    wait_for_propagation(gate_coordinator)

    assert calls == []


def test_remove_population_invalidates_a_sibling_logic_nodes_mask_cache(
    gate_coordinator, flow_state, gate_rectangle_singlet, gate_rectangle_lymph
):
    """`remove_population` rewires a logic node's `parents` list directly
    (`PopulationService._clean_references`) without going through
    `GateCoordinator.recompute_all_stats` — the one mutation path that
    doesn't, so its own cache invalidation is verified separately here.

    An OR node needs >=2 real parents (`LOGIC_GATE_MIN_PARENTS`); dropping
    to 1 makes it `is_incomplete`, which must yield an all-empty mask.
    That's a sharper signal than re-deriving "A alone" would be: a stale
    cache returns the old non-empty A-or-B mask outright instead.
    """
    sample_id = "test_sample_1"
    node_a_id = gate_coordinator.add_gate(gate_rectangle_singlet, sample_id, name="A")
    node_b_id = gate_coordinator.add_gate(gate_rectangle_lymph, sample_id, name="B")
    wait_for_propagation(gate_coordinator)

    sample = flow_state.data.experiment.samples[sample_id]

    or_id = gate_coordinator._mutation_service.add_logic_node(sample_id, "OR")
    or_node = sample.gate_tree.find_node_by_id(or_id)
    gate_coordinator.add_connection(sample_id, node_a_id, or_id)
    gate_coordinator.add_connection(sample_id, node_b_id, or_id)
    wait_for_propagation(gate_coordinator)

    events = sample.fcs_data.events
    orig_count = len(or_node.apply_hierarchy(events))  # populates the cache
    assert orig_count > 0

    success = gate_coordinator.remove_population(sample_id, node_b_id)
    assert success is True
    assert or_node.is_incomplete

    new_count = len(or_node.apply_hierarchy(events))
    assert new_count == 0
