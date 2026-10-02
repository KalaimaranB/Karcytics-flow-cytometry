"""Service for high-level gating operations (cloning, propagation)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from karcytics_sdk.plugin import get_logger

from ..gating import GateNode, gate_from_dict

if TYPE_CHECKING:
    from ..experiment import Experiment, Sample
    from ..gating import Gate

logger = get_logger(__name__, "flow_cytometry")


class GatingService:
    """Handles cross-sample gate tree operations."""

    @staticmethod
    def get_gates_for_display(
        sample: Sample, parent_node_id: str | None = None
    ) -> tuple[list[Gate], list[GateNode]]:
        """Return the gates (and nodes) that should be drawn on the canvas."""
        if parent_node_id:
            parent = sample.gate_tree.find_node_by_id(parent_node_id)
            if parent is None:
                return ([], [])
        else:
            parent = sample.gate_tree

        gates = []
        nodes = []
        for child in parent.children:
            if child.gate is not None:
                gates.append(child.gate)
                nodes.append(child)

        return (gates, nodes)

    @staticmethod
    def clone_gate_tree(source_root: GateNode, target: Sample) -> None:
        """Deep-clone a gate tree onto a target sample."""
        target.gate_tree = GateNode()
        GatingService._clone_dag(source_root, target.gate_tree)

    @staticmethod
    def _clone_dag(source_root: GateNode, target_root: GateNode) -> None:
        """Clone every node reachable from source_root, then rewire parent/child
        edges to mirror the source DAG.

        A plain child-recursion misses AND/OR/NOT logic nodes: those have
        gate=None (so a naive "skip if gate is None" clone drops them and
        everything gated beneath them) and can have multiple parents wired
        in via drag-drop, which a simple add_child-per-parent walk can't
        represent. Instead, every reachable node is cloned exactly once and
        the parent/child lists are then rebuilt from the originals.
        """
        all_nodes = {node.node_id: node for node in source_root.iter_dag()}

        clones: dict[str, GateNode] = {source_root.node_id: target_root}
        for node_id, node in all_nodes.items():
            if node_id == source_root.node_id:
                continue
            cloned_gate = None
            if node.gate is not None:
                # Deep-copy the gate with a new ID to keep it independent
                cloned_gate_dict = node.gate.to_dict()
                cloned_gate_dict["gate_id"] = None  # force new ID
                cloned_gate = gate_from_dict(cloned_gate_dict)
            clones[node_id] = GateNode(
                gate=cloned_gate,
                name=node.name,
                negated=node.negated,
                logic_operator=node.logic_operator,
            )

        for node_id, node in all_nodes.items():
            clone = clones[node_id]
            clone.parents.extend(clones[p.node_id] for p in node.parents if p.node_id in clones)
            clone.children.extend(clones[c.node_id] for c in node.children if c.node_id in clones)

    @staticmethod
    def copy_gates_to_group(experiment: Experiment, source_sample_id: str) -> int:
        """Copy the gate tree from one sample to all others in its groups."""
        source = experiment.samples.get(source_sample_id)
        if source is None:
            return 0

        # Find all samples in the same groups
        targets: list[Sample] = []
        for group in experiment.groups.values():
            if source_sample_id in group.sample_ids:
                for sid in group.sample_ids:
                    if sid != source_sample_id:
                        s = experiment.samples.get(sid)
                        if s and s.fcs_data:
                            targets.append(s)

        # If not in any group, copy to all other samples
        if not targets:
            targets = [
                s
                for s in experiment.samples.values()
                if s.sample_id != source_sample_id and s.fcs_data
            ]

        count = 0
        for target in targets:
            GatingService.clone_gate_tree(source.gate_tree, target)
            count += 1

        return count
