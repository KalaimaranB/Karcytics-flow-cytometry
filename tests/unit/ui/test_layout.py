from karcytics_plugins.flow_cytometry.analysis.gating.base import Gate
from karcytics_plugins.flow_cytometry.analysis.gating.gate_node import GateNode
from karcytics_plugins.flow_cytometry.ui.widgets.gate_hierarchy.node_tree_engine import (
    NodeTreeEngine,
)


class DummyGate(Gate):
    def __init__(self, gate_id=""):
        super().__init__(gate_id=gate_id, x_param="FSC-A")
        self.y_param = "SSC-A"

    def contains(self, events):
        pass

    def contains_vectorized(self, events):
        pass

    def copy(self):
        return DummyGate(self.gate_id)


def _build_tree():
    root = GateNode(node_id="root", name="All Events")
    child1 = root.add_child(DummyGate("child1"), name="Gate 1")
    child2 = root.add_child(DummyGate("child2"), name="Gate 2")
    grandchild = child1.add_child(DummyGate("grandchild"), name="Gate 1.1")
    return root, child1, child2, grandchild


def _rects_by_id(rects):
    return {r.node_id: r for r in rects}


def test_compute_returns_one_rect_per_node():
    root, child1, child2, grandchild = _build_tree()

    rects = NodeTreeEngine().compute(root)

    node_ids = {r.node_id for r in rects}
    assert node_ids == {"root", child1.node_id, child2.node_id, grandchild.node_id}


def test_depth_increases_y_and_matches_tree_depth():
    root, child1, child2, grandchild = _build_tree()

    by_id = _rects_by_id(NodeTreeEngine().compute(root))

    assert by_id["root"].depth == 0
    assert by_id[child1.node_id].depth == 1
    assert by_id[child2.node_id].depth == 1
    assert by_id[grandchild.node_id].depth == 2

    # Each deeper row must be drawn strictly below the previous one.
    assert by_id[child1.node_id].y > by_id["root"].y
    assert by_id[grandchild.node_id].y > by_id[child1.node_id].y


def test_siblings_do_not_overlap_horizontally():
    root, child1, child2, _grandchild = _build_tree()
    engine = NodeTreeEngine()

    by_id = _rects_by_id(engine.compute(root))
    r1, r2 = by_id[child1.node_id], by_id[child2.node_id]

    # Same depth, so any horizontal separation less than one node width
    # means the two boxes would be drawn on top of each other.
    assert abs(r1.x - r2.x) >= engine.node_width


def test_parent_ids_are_recorded_on_children():
    root, child1, child2, grandchild = _build_tree()

    by_id = _rects_by_id(NodeTreeEngine().compute(root))

    assert by_id[child1.node_id].parent_ids == ["root"]
    assert by_id[child2.node_id].parent_ids == ["root"]
    assert by_id[grandchild.node_id].parent_ids == [child1.node_id]


def test_layout_is_deterministic():
    root, *_ = _build_tree()
    engine = NodeTreeEngine()

    first = [(r.node_id, r.x, r.y) for r in engine.compute(root)]
    second = [(r.node_id, r.x, r.y) for r in engine.compute(root)]

    assert first == second


def test_empty_root_returns_empty_layout():
    assert NodeTreeEngine().compute(None) == []
