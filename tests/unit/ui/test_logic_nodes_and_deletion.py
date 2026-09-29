"""Tests for logic node addition behavior and right-click deletion with child warnings."""

from unittest.mock import MagicMock, patch

import pytest
from karcytics_sdk.plugin import CentralEventBus

from karcytics_plugins.flow_cytometry.analysis import events
from karcytics_plugins.flow_cytometry.analysis.gating import RectangleGate
from karcytics_plugins.flow_cytometry.analysis.gating.gate_node import GateNode
from karcytics_plugins.flow_cytometry.analysis.population_service import PopulationService
from karcytics_plugins.flow_cytometry.analysis.services.gate_mutation_service import (
    GateMutationService,
)
from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.ui.widgets.node_canvas.canvas_view import NodeCanvas


@pytest.fixture
def mock_flow_state():
    state = FlowState()
    state.axis_manager = MagicMock()
    # Create a mock sample with a root GateNode
    sample = MagicMock()
    sample.sample_id = "sample-1"
    sample.gate_tree = GateNode(name="All Events", parents=[], gate=None)
    state.data.experiment.samples["sample-1"] = sample
    return state


def test_add_logic_node_publishes_logic_node_created(mock_flow_state):
    """Verify add_logic_node publishes LOGIC_NODE_CREATED instead of GATE_CREATED."""
    pop_service = PopulationService(mock_flow_state)
    mutation_service = GateMutationService(
        mock_flow_state, MagicMock(), MagicMock(), MagicMock(), pop_service
    )

    with patch.object(CentralEventBus, "publish") as mock_publish:
        node_id = mutation_service.add_logic_node("sample-1", "AND", "Test AND")
        assert node_id is not None

        # Verify LOGIC_NODE_CREATED was fired and GATE_CREATED was not fired
        published_topics = [call.args[0] for call in mock_publish.call_args_list]
        assert events.LOGIC_NODE_CREATED in published_topics
        assert events.GATE_CREATED not in published_topics


def test_remove_population_cleans_logic_node_and_references(mock_flow_state):
    """Verify remove_population unhooks logic nodes from gate_tree.children and parent refs."""
    sample = mock_flow_state.data.experiment.samples["sample-1"]
    pop_service = PopulationService(mock_flow_state)

    # Add a normal gate child
    gate1 = RectangleGate(
        "FSC-A", "SSC-A", x_min=100, x_max=200, y_min=100, y_max=200, gate_id="g1"
    )
    node1 = sample.gate_tree.add_child(gate1, "Gate 1")

    # Add a logic node
    logic_node = GateNode(
        name="AND Logic", logic_operator="AND", parents=[node1], is_logic_node=True
    )
    sample.gate_tree.children.append(logic_node)
    node1.children.append(logic_node)

    assert logic_node in sample.gate_tree.children
    assert logic_node in node1.children

    # Remove the logic node
    success = pop_service.remove_population("sample-1", logic_node.node_id)
    assert success is True
    assert logic_node not in sample.gate_tree.children
    assert logic_node not in node1.children


def test_remove_population_with_child_populations(mock_flow_state):
    """Verify remove_population removes parent and all child nodes."""
    sample = mock_flow_state.data.experiment.samples["sample-1"]
    pop_service = PopulationService(mock_flow_state)

    # Add Parent -> Child -> Grandchild
    gate1 = RectangleGate(
        "FSC-A", "SSC-A", x_min=100, x_max=200, y_min=100, y_max=200, gate_id="g1"
    )
    parent = sample.gate_tree.add_child(gate1, "Parent")

    gate2 = RectangleGate(
        "FSC-A", "SSC-A", x_min=120, x_max=180, y_min=120, y_max=180, gate_id="g2"
    )
    child = parent.add_child(gate2, "Child")

    gate3 = RectangleGate(
        "FSC-A", "SSC-A", x_min=130, x_max=170, y_min=130, y_max=170, gate_id="g3"
    )
    grandchild = child.add_child(gate3, "Grandchild")

    assert sample.gate_tree.find_node_by_id(parent.node_id) is not None
    assert sample.gate_tree.find_node_by_id(child.node_id) is not None
    assert sample.gate_tree.find_node_by_id(grandchild.node_id) is not None

    # Remove parent
    success = pop_service.remove_population("sample-1", parent.node_id)
    assert success is True

    # None of them should be in the tree anymore
    assert sample.gate_tree.find_node_by_id(parent.node_id) is None
    assert sample.gate_tree.find_node_by_id(child.node_id) is None
    assert sample.gate_tree.find_node_by_id(grandchild.node_id) is None


def test_node_canvas_confirm_delete_with_children(qtbot, mock_flow_state):
    """Verify NodeCanvas prompts warning when deleting a node with children."""
    sample = mock_flow_state.data.experiment.samples["sample-1"]
    gate1 = RectangleGate(
        "FSC-A", "SSC-A", x_min=100, x_max=200, y_min=100, y_max=200, gate_id="g1"
    )
    parent = sample.gate_tree.add_child(gate1, "Parent Node")
    gate2 = RectangleGate(
        "FSC-A", "SSC-A", x_min=120, x_max=180, y_min=120, y_max=180, gate_id="g2"
    )
    parent.add_child(gate2, "Child Node")

    canvas = NodeCanvas(mock_flow_state)
    qtbot.addWidget(canvas)
    canvas.set_sample("sample-1")

    removed_nodes = []
    canvas.node_removed.connect(lambda nid: removed_nodes.append(nid))

    # Test 1: User declines confirmation
    with patch("PyQt6.QtWidgets.QMessageBox.exec", return_value=1024):  # No / Reject
        canvas._confirm_and_delete_node(parent.node_id)
        assert len(removed_nodes) == 0

    # Test 2: User accepts confirmation
    from PyQt6.QtWidgets import QMessageBox

    with patch("PyQt6.QtWidgets.QMessageBox.exec", return_value=QMessageBox.StandardButton.Yes):
        canvas._confirm_and_delete_node(parent.node_id)
        assert removed_nodes == [parent.node_id]
