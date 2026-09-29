"""Tests for GateMutationService.rename_population's scope parameter and
remove_connection's cross-sample looping via GateCoordinator.
"""

from unittest.mock import MagicMock, call

import pytest

from karcytics_plugins.flow_cytometry.analysis.gate_coordinator import GateCoordinator
from karcytics_plugins.flow_cytometry.analysis.gating.gate_node import GateNode
from karcytics_plugins.flow_cytometry.analysis.population_service import PopulationService
from karcytics_plugins.flow_cytometry.analysis.services.gate_mutation_service import (
    GateMutationService,
)
from karcytics_plugins.flow_cytometry.analysis.state import FlowState


@pytest.fixture
def three_sample_state():
    """Three samples, each with a population sharing the same node_id (simulating
    propagation having previously copied one sample's tree into the others).
    """
    state = FlowState()
    shared_node_id = "shared-node-1"
    for sample_id in ("sample-a", "sample-b", "sample-c"):
        sample = MagicMock()
        sample.sample_id = sample_id
        root = GateNode(name="All Events", parents=[], gate=None)
        node = GateNode(node_id=shared_node_id, name="Lymphocytes", parents=[root])
        root.children.append(node)
        sample.gate_tree = root
        state.data.experiment.samples[sample_id] = sample
    return state


@pytest.fixture
def mutation_service(three_sample_state):
    pop_service = PopulationService(three_sample_state)
    coordinator = MagicMock()
    return GateMutationService(
        three_sample_state, coordinator, MagicMock(), MagicMock(), pop_service
    )


def _node_name(state, sample_id, node_id):
    return state.data.experiment.samples[sample_id].gate_tree.find_node_by_id(node_id).name


def test_rename_population_scoped_to_target_sample_ids(mutation_service, three_sample_state):
    """Explicit target_sample_ids should rename only the listed samples plus the origin."""
    success = mutation_service.rename_population(
        "sample-a", "shared-node-1", "Renamed", target_sample_ids=["sample-b"]
    )
    assert success is True
    assert _node_name(three_sample_state, "sample-a", "shared-node-1") == "Renamed"
    assert _node_name(three_sample_state, "sample-b", "shared-node-1") == "Renamed"
    assert _node_name(three_sample_state, "sample-c", "shared-node-1") == "Lymphocytes"


def test_rename_population_defaults_to_propagator_targets(mutation_service, three_sample_state):
    """With no explicit scope, behavior is unchanged: fall back to propagator._find_targets."""
    target_sample = MagicMock(sample_id="sample-c")
    mutation_service._coordinator.propagator._find_targets.return_value = [target_sample]

    success = mutation_service.rename_population("sample-a", "shared-node-1", "Renamed")
    assert success is True

    mutation_service._coordinator.propagator._find_targets.assert_called_once_with(
        "sample-a", three_sample_state
    )
    assert _node_name(three_sample_state, "sample-a", "shared-node-1") == "Renamed"
    assert _node_name(three_sample_state, "sample-c", "shared-node-1") == "Renamed"
    # sample-b was not among the resolved propagation targets
    assert _node_name(three_sample_state, "sample-b", "shared-node-1") == "Lymphocytes"


def test_rename_population_missing_node_in_target_sample_is_skipped(
    mutation_service, three_sample_state
):
    """A target sample lacking the node_id (propagation drift) is silently skipped, not an error."""
    success = mutation_service.rename_population(
        "sample-a", "shared-node-1", "Renamed", target_sample_ids=["sample-b", "no-such-sample"]
    )
    assert success is True
    assert _node_name(three_sample_state, "sample-a", "shared-node-1") == "Renamed"
    assert _node_name(three_sample_state, "sample-b", "shared-node-1") == "Renamed"


def test_remove_connection_for_samples_counts_successes_and_skips_drifted_samples():
    """GateCoordinator.remove_connection_for_samples loops remove_connection per sample
    and returns how many actually succeeded, tolerating samples where the pair is missing.
    """
    coordinator = GateCoordinator.__new__(GateCoordinator)
    coordinator._mutation_service = MagicMock()
    coordinator._mutation_service.remove_connection.side_effect = [True, False, True]

    removed = coordinator.remove_connection_for_samples(
        "src-node", "tgt-node", ["sample-a", "sample-b", "sample-c"]
    )

    assert removed == 2
    assert coordinator._mutation_service.remove_connection.call_args_list == [
        call("sample-a", "src-node", "tgt-node"),
        call("sample-b", "src-node", "tgt-node"),
        call("sample-c", "src-node", "tgt-node"),
    ]
