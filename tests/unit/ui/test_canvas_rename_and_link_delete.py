"""Tests for canvas rename-population and delete-link (logic-node connections only)."""

from unittest.mock import MagicMock, patch

from karcytics_plugins.flow_cytometry.analysis.gating import RectangleGate
from karcytics_plugins.flow_cytometry.analysis.gating.gate_node import GateNode
from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.ui.widgets.node_canvas.canvas_view import NodeCanvas
from karcytics_plugins.flow_cytometry.ui.widgets.node_canvas.items.edge_item import EdgeItem
from karcytics_plugins.flow_cytometry.ui.widgets.node_canvas.items.node_item import NodeItem


def _mock_flow_state():
    state = FlowState()
    state.axis_manager = MagicMock()
    sample = MagicMock()
    sample.sample_id = "sample-1"
    sample.display_name = "Sample 1"
    sample.group_ids = []
    sample.gate_tree = GateNode(name="All Events", parents=[], gate=None)
    state.data.experiment.samples["sample-1"] = sample
    return state


def test_rename_available_for_logic_nodes(qtbot):
    """Logic nodes have user-set names too (e.g. "AND Logic"), so they're renamable
    just like regular populations — via a "Rename Node" entry.
    """
    item = NodeItem("logic-1", "AND")
    item.is_logic_node = True
    received = []
    item.rename_requested.connect(lambda nid: received.append(nid))

    mock_event = MagicMock()
    mock_event.screenPos.return_value = MagicMock()

    with (
        patch("PyQt6.QtWidgets.QMenu.exec") as mock_exec,
        patch("PyQt6.QtWidgets.QMenu.addAction") as mock_add_action,
    ):
        rename_action_mock = MagicMock(name="rename_action")
        delete_action_mock = MagicMock(name="delete_action")
        mock_add_action.side_effect = [rename_action_mock, delete_action_mock]
        mock_exec.return_value = rename_action_mock

        item.contextMenuEvent(mock_event)
        assert mock_add_action.call_count == 2
        assert received == ["logic-1"]


def test_link_submenus_only_appear_with_logic_links(qtbot):
    """No get_logic_links hook, or empty links, means no link submenus are built."""
    item = NodeItem("node-1", "Lymphocytes")
    mock_event = MagicMock()
    mock_event.screenPos.return_value = MagicMock()

    with (
        patch("PyQt6.QtWidgets.QMenu.exec") as mock_exec,
        patch("PyQt6.QtWidgets.QMenu.addAction") as mock_add_action,
        patch("PyQt6.QtWidgets.QMenu.addMenu") as mock_add_menu,
    ):
        rename_mock = MagicMock(name="rename")
        delete_mock = MagicMock(name="delete")
        mock_add_action.side_effect = [rename_mock, delete_mock]
        mock_exec.return_value = delete_mock

        item.contextMenuEvent(mock_event)
        mock_add_menu.assert_not_called()


def test_link_submenu_emits_link_delete_requested_for_picked_connection(qtbot):
    """Picking a connection from the incoming/outgoing submenu emits the right pair."""
    item = NodeItem("logic-1", "AND")
    item.is_logic_node = True
    item.get_logic_links = MagicMock(return_value=([("parent-1", "Parent A")], []))

    received = []
    item.link_delete_requested.connect(lambda src, tgt: received.append((src, tgt)))

    mock_event = MagicMock()
    mock_event.screenPos.return_value = MagicMock()

    with (
        patch("PyQt6.QtWidgets.QMenu.exec") as mock_exec,
        patch("PyQt6.QtWidgets.QMenu.addAction") as mock_add_action,
        patch("PyQt6.QtWidgets.QMenu.addMenu"),
    ):
        rename_action_mock = MagicMock(name="rename_action")
        delete_action_mock = MagicMock(name="delete_action")
        link_action_mock = MagicMock(name="link_action")
        # Top-level menu adds "Rename Node" then "Delete Node"; the submenu's
        # addAction for the one incoming link is a separate BioMenu instance,
        # but patch handles both since BioMenu inherits QMenu.addAction unmodified.
        mock_add_action.side_effect = [rename_action_mock, delete_action_mock, link_action_mock]
        mock_exec.return_value = link_action_mock

        item.contextMenuEvent(mock_event)
        assert received == [("parent-1", "logic-1")]


def test_edge_item_tags_logic_edge_by_target_node(qtbot):
    """EdgeItem.is_logic_edge mirrors the target node's is_logic_node flag."""
    logic_target = NodeItem("logic-1", "AND")
    logic_target.is_logic_node = True
    structural_target = NodeItem("node-1", "Lymphocytes")

    logic_edge = EdgeItem(NodeItem("src-1", "Source"), logic_target)
    structural_edge = EdgeItem(NodeItem("src-2", "Source"), structural_target)

    assert logic_edge.is_logic_edge is True
    assert structural_edge.is_logic_edge is False


def test_keypress_delete_ignores_structural_edges(qtbot):
    """Delete/Backspace on a selected structural edge does nothing (only logic edges
    are deletable this way) — regression test for the pre-existing orphaning gap.
    """
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QKeyEvent

    state = _mock_flow_state()
    canvas = NodeCanvas(state)
    qtbot.addWidget(canvas)

    structural_target = NodeItem("child-1", "Child")
    structural_edge = EdgeItem(NodeItem("parent-1", "Parent"), structural_target)
    canvas._scene.addItem(structural_edge)
    structural_edge.setSelected(True)

    removed = []
    canvas._manager.connection_removed.connect(lambda src, tgt: removed.append((src, tgt)))

    event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Delete, Qt.KeyboardModifier.NoModifier)
    canvas.keyPressEvent(event)

    assert removed == []


def test_confirm_and_rename_node_emits_with_scope_target_ids(qtbot):
    """_confirm_and_rename_node resolves scope via ScopeSelectionDialog and emits rename_requested."""
    state = _mock_flow_state()
    sample = state.data.experiment.samples["sample-1"]
    gate1 = RectangleGate(
        "FSC-A", "SSC-A", x_min=100, x_max=200, y_min=100, y_max=200, gate_id="g1"
    )
    node = sample.gate_tree.add_child(gate1, "Lymphocytes")

    canvas = NodeCanvas(state)
    qtbot.addWidget(canvas)
    canvas.set_sample("sample-1")

    received = []
    canvas.rename_requested.connect(
        lambda nid, new_name, target_ids: received.append((nid, new_name, target_ids))
    )

    from PyQt6.QtWidgets import QDialog, QInputDialog

    from karcytics_plugins.flow_cytometry.ui.widgets.scope_selection_dialog import (
        ScopeSelectionDialog,
    )

    with (
        patch.object(QInputDialog, "getText", return_value=("New Name", True)),
        patch.object(ScopeSelectionDialog, "exec", return_value=QDialog.DialogCode.Accepted),
        patch.object(ScopeSelectionDialog, "get_scope", return_value=("sample", None)),
    ):
        canvas._confirm_and_rename_node(node.node_id)

    assert received == [(node.node_id, "New Name", ["sample-1"])]


def test_confirm_and_delete_link_respects_default_no(qtbot):
    """The affected-samples warning defaults to No — declining it must not emit."""
    state = _mock_flow_state()
    sample = state.data.experiment.samples["sample-1"]
    logic_node = GateNode(name="AND", logic_operator="AND", parents=[], is_logic_node=True)
    sample.gate_tree.children.append(logic_node)
    logic_node.parents.append(sample.gate_tree)

    canvas = NodeCanvas(state)
    qtbot.addWidget(canvas)
    canvas.set_sample("sample-1")

    received = []
    canvas.link_delete_requested.connect(
        lambda src, tgt, target_ids: received.append((src, tgt, target_ids))
    )

    from PyQt6.QtWidgets import QDialog, QMessageBox

    from karcytics_plugins.flow_cytometry.ui.widgets.scope_selection_dialog import (
        ScopeSelectionDialog,
    )

    with (
        patch.object(ScopeSelectionDialog, "exec", return_value=QDialog.DialogCode.Accepted),
        patch.object(ScopeSelectionDialog, "get_scope", return_value=("sample", None)),
        patch.object(QMessageBox, "exec", return_value=QMessageBox.StandardButton.No),
    ):
        canvas._confirm_and_delete_link(sample.gate_tree.node_id, logic_node.node_id)

    assert received == []
