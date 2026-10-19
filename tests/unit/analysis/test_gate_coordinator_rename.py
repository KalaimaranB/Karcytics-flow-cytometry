"""GateCoordinator.rename_population's scope, and remove_connection_for_samples."""

from unittest.mock import MagicMock

import pytest

from karcytics_plugins.flow_cytometry.analysis.gate_coordinator import GateCoordinator
from karcytics_plugins.flow_cytometry.analysis.gating.gate_node import GateNode
from karcytics_plugins.flow_cytometry.analysis.population_service import PopulationService
from karcytics_plugins.flow_cytometry.analysis.state import FlowState

SHARED = "shared-node-1"


@pytest.fixture
def state():
    """Three samples whose trees hold the same node id, as after propagation."""
    state = FlowState()
    for sample_id in ("sample-a", "sample-b", "sample-c"):
        sample = MagicMock()
        sample.sample_id = sample_id
        root = GateNode(name="All Events", parents=[], gate=None)
        node = GateNode(node_id=SHARED, name="Lymphocytes", parents=[root])
        root.children.append(node)
        sample.gate_tree = root
        state.data.experiment.samples[sample_id] = sample
    return state


@pytest.fixture
def coordinator(state):
    return GateCoordinator(state, MagicMock(), PopulationService(state))


def _name(state, sample_id, node_id=SHARED):
    return state.data.experiment.samples[sample_id].gate_tree.find_node_by_id(node_id).name


def test_rename_population_scoped_to_target_sample_ids(coordinator, state):
    """Explicit target_sample_ids rename only the listed samples plus the origin."""
    assert coordinator.rename_population(
        "sample-a", SHARED, "Renamed", target_sample_ids=["sample-b"]
    )
    assert [_name(state, s) for s in ("sample-a", "sample-b", "sample-c")] == [
        "Renamed",
        "Renamed",
        "Lymphocytes",
    ]


def test_rename_population_defaults_to_propagation_targets(coordinator, state, monkeypatch):
    targets = MagicMock(return_value=[MagicMock(sample_id="sample-c")])
    monkeypatch.setattr(coordinator.propagator, "find_targets", targets)

    assert coordinator.rename_population("sample-a", SHARED, "Renamed")

    targets.assert_called_once_with("sample-a")
    assert [_name(state, s) for s in ("sample-a", "sample-b", "sample-c")] == [
        "Renamed",
        "Lymphocytes",
        "Renamed",
    ]


def test_rename_population_skips_a_target_without_the_node(coordinator, state):
    """A target sample lacking the node id (propagation drift) is skipped, not an error."""
    assert coordinator.rename_population(
        "sample-a", SHARED, "Renamed", target_sample_ids=["sample-b", "no-such-sample"]
    )
    assert _name(state, "sample-b") == "Renamed"


def test_remove_connection_for_samples_counts_only_the_removed_ones(coordinator, state):
    """Samples where the pair is missing are tolerated and not counted."""
    for sample_id in ("sample-a", "sample-c"):
        root = state.data.experiment.samples[sample_id].gate_tree
        source = root.find_node_by_id(SHARED)
        logic = GateNode(node_id="logic", name="AND", parents=[source], is_logic_node=True)
        source.children.append(logic)
        root.children.append(logic)

    removed = coordinator.remove_connection_for_samples(
        SHARED, "logic", ["sample-a", "sample-b", "sample-c"]
    )

    assert removed == 2
    for sample_id in ("sample-a", "sample-c"):
        logic = state.data.experiment.samples[sample_id].gate_tree.find_node_by_id("logic")
        assert all(p.node_id != SHARED for p in logic.parents)
