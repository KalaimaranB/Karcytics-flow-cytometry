"""Edits to a sample's gate tree.

Pure model changes: no events, no statistics, no event bus. GateCoordinator
calls these, then recomputes statistics and tells the rest of the plugin.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from karcytics_sdk.plugin import get_logger

from ..constants import POLYGON_MIN_VERTICES
from .ellipse import EllipseGate
from .gate_factory import gate_from_dict
from .gate_node import GateNode
from .polygon import PolygonGate
from .quadrant import QuadrantSubGate
from .range import RangeGate
from .rectangle import RectangleGate

if TYPE_CHECKING:
    from ..experiment import Experiment, Sample
    from .base import Gate

logger = get_logger(__name__, "flow_cytometry")


def unique_name(sample: Sample | None, prefix: str = "Gate") -> str:
    """The first of '<prefix> 1', '<prefix> 2', ... that no population in `sample` uses."""
    existing = {n.name for n in sample.gate_tree.iter_dag() if not n.is_root} if sample else set()
    counter = 1
    while f"{prefix} {counter}" in existing:
        counter += 1
    return f"{prefix} {counter}"


def gates_for_display(
    sample: Sample, parent_node_id: str | None = None
) -> tuple[list[Gate], list[GateNode]]:
    """The gates (and their nodes) drawn on a plot of `parent_node_id`'s population."""
    parent = (
        sample.gate_tree.find_node_by_id(parent_node_id) if parent_node_id else sample.gate_tree
    )
    if parent is None:
        return ([], [])
    nodes = [child for child in parent.children if child.gate is not None]
    return ([n.gate for n in nodes if n.gate is not None], nodes)


def modify_gate(sample: Sample, gate_id: str, **kwargs: Any) -> list[GateNode]:
    """Change a gate's geometry (and `negated` on its nodes).

    Returns the nodes sharing the gate, or [] when the gate is missing or the
    edit would leave it invalid; a rejected edit changes nothing.
    """
    nodes = sample.gate_tree.find_nodes_by_gate(gate_id)
    gate = nodes[0].gate if nodes else None
    if gate is None:
        return []

    # QuadrantGate.create_nodes() only ever creates QuadrantSubGate-
    # wrapping nodes — there is no node wrapping the bare parent
    # QuadrantGate — so the geometry that actually needs mutating
    # (x_mid/y_mid) lives on gate.parent, shared by all 4 quadrant
    # nodes. Redirecting here (rather than changing which gate_id is
    # looked up) means every quadrant sub-node's crosshair updates from
    # a single mutation, with no extra fan-out.
    if isinstance(gate, QuadrantSubGate):
        gate = gate.parent

    node_kwargs = {"negated": kwargs.pop("negated")} if "negated" in kwargs else {}
    candidate = {key: value for key, value in kwargs.items() if hasattr(gate, key)}
    error = _geometry_error(gate, candidate)
    if error:
        logger.warning("Gate modification rejected for %s: %s", gate_id, error)
        return []

    for key, value in candidate.items():
        setattr(gate, key, value)
    for node in nodes:
        for key, value in node_kwargs.items():
            setattr(node, key, value)
    return nodes


def _geometry_error(gate: Gate, candidate: dict[str, Any]) -> str | None:
    """Why applying `candidate` to `gate` would leave it invalid, or None.

    Checked against the merged (current + candidate) state before anything is
    mutated, so a rejected edit never partially applies.
    """
    merged = {**gate.__dict__, **candidate}
    if isinstance(gate, RectangleGate):
        if merged["x_min"] >= merged["x_max"]:
            return "x_min must be < x_max"
        if merged["y_min"] >= merged["y_max"]:
            return "y_min must be < y_max"
    elif isinstance(gate, RangeGate):
        if merged["low"] >= merged["high"]:
            return "low must be < high"
    elif isinstance(gate, EllipseGate):
        if merged["width"] <= 0 or merged["height"] <= 0:
            return "width/height must be > 0"
    elif isinstance(gate, PolygonGate):
        if len(merged["vertices"]) < POLYGON_MIN_VERTICES:
            return "polygon requires at least 3 vertices"
    # QuadrantGate: x_mid/y_mid have no invariant beyond being finite.
    return None


def split_population(sample: Sample, node_id: str) -> GateNode | None:
    """Add a sibling of `node_id` that holds the events its gate excludes (or includes).

    One gate geometry then drives two complementary populations.
    """
    node = sample.gate_tree.find_node_by_id(node_id)
    if node is None or node.gate is None or not node.parents:
        return None

    # Wired to *all* of the node's parents (not just parents[0]) so
    # multi-parent nodes keep every parent relationship after the split.
    sibling = GateNode(
        gate=node.gate,
        name=f"{node.name} (Inside)" if node.negated else f"{node.name} (Outside)",
        negated=not node.negated,
        logic_operator=node.logic_operator,
        parents=list(node.parents),
    )
    for parent in node.parents:
        parent.children.append(sibling)
    return sibling


def remove_subtree(sample: Sample, node_id: str) -> set[str]:
    """Remove a population and everything below it; returns the ids no longer in the tree."""
    root = sample.gate_tree
    node = root.find_node_by_id(node_id)
    if node is None or node.is_root:
        return set()

    subtree = {n.node_id for n in node.iter_dag()}
    for parent in list(node.parents):
        parent.remove_child(node.node_id)
    node.parents.clear()
    # A logic node also hangs off root.children, whatever its parents.
    root.remove_child(node.node_id)
    # A logic node below `node` survives when it is still reachable another
    # way; drop its references to the nodes that did go.
    survivors = list(root.iter_dag())
    removed = subtree - {n.node_id for n in survivors}
    for survivor in survivors:
        survivor.parents = [p for p in survivor.parents if p.node_id not in removed]

    # The parents lists just changed, so cached masks below them are stale
    # (GateCoordinator.recompute_all_stats covers every other edit).
    root.invalidate_mask_cache()
    return removed


def clone_gate_tree(source_root: GateNode, target: Sample) -> None:
    """Replace `target`'s gate tree with an independent copy of `source_root`.

    Every reachable node is cloned exactly once and the parent/child lists
    are rebuilt from the originals. A plain child recursion would drop
    AND/OR/NOT logic nodes (gate=None) and everything below them, and could
    not represent their multiple parents.
    """
    target.gate_tree = GateNode()
    clones: dict[str, GateNode] = {source_root.node_id: target.gate_tree}
    originals = list(source_root.iter_dag())
    for node in originals:
        if node is source_root:
            continue
        gate = None
        if node.gate is not None:
            gate_dict = node.gate.to_dict()
            gate_dict["gate_id"] = None  # a new id keeps the copy independent
            gate = gate_from_dict(gate_dict)
        clones[node.node_id] = GateNode(
            gate=gate, name=node.name, negated=node.negated, logic_operator=node.logic_operator
        )
    for node in originals:
        clone = clones[node.node_id]
        clone.parents.extend(clones[p.node_id] for p in node.parents if p.node_id in clones)
        clone.children.extend(clones[c.node_id] for c in node.children if c.node_id in clones)


def copy_gates_to_group(experiment: Experiment, source_sample_id: str) -> list[Sample]:
    """Copy one sample's gate tree to the other loaded samples in its groups.

    A sample in no group copies to every other loaded sample. Returns the
    samples that received the copy.
    """
    source = experiment.samples.get(source_sample_id)
    if source is None:
        return []

    def loaded_others(sample_ids) -> list[Sample]:
        return [
            s
            for sid in sample_ids
            if sid != source_sample_id and (s := experiment.samples.get(sid)) and s.fcs_data
        ]

    in_groups = {
        sid
        for group in experiment.groups.values()
        if source_sample_id in group.sample_ids
        for sid in group.sample_ids
    }
    targets = loaded_others(sorted(in_groups)) or loaded_others(experiment.samples)
    for target in targets:
        clone_gate_tree(source.gate_tree, target)
    return targets
