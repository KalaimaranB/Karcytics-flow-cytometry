"""GateNode.iter_dag — the single DAG walk shared by stats, cloning and lookups."""

from karcytics_plugins.flow_cytometry.analysis.compute.dag_evaluator import DagEvaluator
from karcytics_plugins.flow_cytometry.analysis.gating.gate_node import GateNode


def _diamond() -> tuple[GateNode, GateNode]:
    """Root -> a, b ; a, b -> AND (shared, multi-parent) -> leaf."""
    root = GateNode(name="All Events")
    a = GateNode(name="A", parents=[root])
    b = GateNode(name="B", parents=[root])
    root.children += [a, b]
    logic = GateNode(name="AND", parents=[a, b], is_logic_node=True)
    a.children.append(logic)
    b.children.append(logic)
    leaf = GateNode(name="Leaf", parents=[logic])
    logic.children.append(leaf)
    return root, logic


def test_shared_descendants_visited_once():
    root, _ = _diamond()
    names = [n.name for n in root.iter_dag()]
    assert sorted(names) == ["A", "AND", "All Events", "B", "Leaf"]


def test_order_is_depth_first_stack_order():
    root, _ = _diamond()
    # Same order the pre-refactor stack walks produced: last child first.
    assert [n.name for n in root.iter_dag()] == ["All Events", "B", "AND", "Leaf", "A"]


def test_dag_evaluator_collects_same_nodes():
    root, _ = _diamond()
    assert DagEvaluator._collect_nodes(root) == list(root.iter_dag())


def test_subtree_walk_starts_at_node():
    _, logic = _diamond()
    assert [n.name for n in logic.iter_dag()] == ["AND", "Leaf"]
