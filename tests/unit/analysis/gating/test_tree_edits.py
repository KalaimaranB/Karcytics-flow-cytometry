"""gating.tree_edits: naming, geometry edits, splits and removals on a gate tree."""

import pytest

from karcytics_plugins.flow_cytometry.analysis.experiment import Sample
from karcytics_plugins.flow_cytometry.analysis.gating import (
    EllipseGate,
    GateNode,
    PolygonGate,
    QuadrantGate,
    RangeGate,
    RectangleGate,
    tree_edits,
)


@pytest.fixture
def sample():
    return Sample(sample_id="s1", display_name="S1")


@pytest.fixture
def rect(sample):
    gate = RectangleGate("FSC-A", "SSC-A", x_min=10, x_max=100, gate_id="gate_123")
    return gate, sample.gate_tree.add_child(gate, name="Lymphocytes")


# ── unique_name ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("existing", "prefix", "expected"),
    [
        ([], "Gate", "Gate 1"),
        (["Gate 1"], "Gate", "Gate 2"),
        (["Gate 1", "Gate 3"], "Gate", "Gate 2"),
        (["Gate 1"], "Lymphocytes", "Lymphocytes 1"),
    ],
)
def test_unique_name_takes_the_first_free_number(sample, existing, prefix, expected):
    for name in existing:
        sample.gate_tree.add_child(RectangleGate("FSC-A", "SSC-A", x_min=0, x_max=10), name=name)
    assert tree_edits.unique_name(sample, prefix) == expected


def test_unique_name_without_a_sample():
    assert tree_edits.unique_name(None) == "Gate 1"


# ── modify_gate ──────────────────────────────────────────────────────────


def test_modify_gate_geometry(sample, rect):
    gate, node = rect
    assert tree_edits.modify_gate(sample, "gate_123", x_min=20, x_max=200) == [node]
    assert (gate.x_min, gate.x_max) == (20, 200)


def test_modify_gate_negates_every_node_sharing_the_gate(sample, rect):
    gate, node1 = rect
    node2 = sample.gate_tree.add_child(gate, name="Population B")

    tree_edits.modify_gate(sample, "gate_123", x_max=500, negated=True)

    assert gate.x_max == 500
    assert node1.negated and node2.negated


def test_modify_gate_unknown_gate_changes_nothing(sample, rect):
    assert tree_edits.modify_gate(sample, "no-such-gate", x_min=0) == []


def test_modify_gate_rejects_inverted_rectangle_atomically(sample, rect):
    """x_min >= x_max is rejected without applying the (valid) x_max either."""
    gate, _ = rect
    assert tree_edits.modify_gate(sample, "gate_123", x_min=500, x_max=50) == []
    assert (gate.x_min, gate.x_max) == (10, 100)


@pytest.mark.parametrize(
    ("gate", "edit", "attribute", "unchanged"),
    [
        (RangeGate("FSC-A", low=10, high=100, gate_id="g"), {"low": 200}, "low", 10),
        (
            EllipseGate("FSC-A", "SSC-A", center=(50, 50), width=10, height=10, gate_id="g"),
            {"width": 0},
            "width",
            10,
        ),
        (
            PolygonGate("FSC-A", "SSC-A", vertices=[(0, 0), (10, 0), (10, 10)], gate_id="g"),
            {"vertices": [(0, 0), (10, 0)]},
            "vertices",
            [(0, 0), (10, 0), (10, 10)],
        ),
    ],
)
def test_modify_gate_rejects_invalid_geometry(sample, gate, edit, attribute, unchanged):
    sample.gate_tree.add_child(gate, name="Pop")
    assert tree_edits.modify_gate(sample, "g", **edit) == []
    assert getattr(gate, attribute) == unchanged


def test_modify_quadrant_subgate_moves_the_shared_crosshair(sample):
    """A quadrant leaf's gate is a QuadrantSubGate: the edit lands on its parent QuadrantGate."""
    quadrant = QuadrantGate("FSC-A", "SSC-A", x_mid=50, y_mid=50, gate_id="quad_1")
    nodes = quadrant.create_nodes(sample.gate_tree)

    assert tree_edits.modify_gate(sample, nodes[0].gate.gate_id, x_mid=75, y_mid=25)

    assert (quadrant.x_mid, quadrant.y_mid) == (75, 25)
    assert all(node.gate.parent is quadrant for node in nodes)


# ── split_population ─────────────────────────────────────────────────────


def test_split_population_adds_an_inverted_sibling_on_the_same_gate(sample, rect):
    gate, node = rect
    sibling = tree_edits.split_population(sample, node.node_id)

    assert sibling.name == "Lymphocytes (Outside)"
    assert sample.gate_tree.children == [node, sibling]
    assert sibling.gate is gate
    assert sibling.negated and not node.negated


def test_split_population_of_a_negated_node(sample, rect):
    _, node = rect
    node.negated = True
    node.name = "Debris (Outside)"

    sibling = tree_edits.split_population(sample, node.node_id)

    assert sibling.name == "Debris (Outside) (Inside)"
    assert sibling.negated is False


@pytest.mark.parametrize("target", ["no-such-node", "root"])
def test_split_population_needs_a_gated_node(sample, rect, target):
    node_id = sample.gate_tree.node_id if target == "root" else target
    assert tree_edits.split_population(sample, node_id) is None


# ── remove_subtree ───────────────────────────────────────────────────────


def test_remove_subtree_drops_descendants_and_logic_node_references(sample, rect):
    _, node = rect
    child = node.add_child(RectangleGate("FSC-A", "SSC-A", x_min=20, x_max=30), "Child")
    other = sample.gate_tree.add_child(RectangleGate("FSC-A", "SSC-A", x_min=0, x_max=5), "Other")
    logic = GateNode(name="AND", parents=[child, other], is_logic_node=True)
    child.children.append(logic)
    other.children.append(logic)
    sample.gate_tree.children.append(logic)

    removed = tree_edits.remove_subtree(sample, node.node_id)

    # The AND node keeps its other parent, so it stays (now over Other alone).
    assert removed == {node.node_id, child.node_id}
    assert sample.gate_tree.children == [other, logic]
    assert logic.parents == [other]


def test_remove_subtree_refuses_the_root(sample):
    assert tree_edits.remove_subtree(sample, sample.gate_tree.node_id) == set()
