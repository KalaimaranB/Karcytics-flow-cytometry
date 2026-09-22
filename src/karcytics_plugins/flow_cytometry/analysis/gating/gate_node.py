"""GateNode class for hierarchical gating."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from karcytics_sdk.plugin import get_logger

from ..constants import LOGIC_GATE_MIN_PARENTS
from .base import Gate

logger = get_logger(__name__, "flow_cytometry")


@dataclass
class GateNode:
    """A node in the hierarchical gating tree.

    Each node wraps a :class:`Gate` and maintains parent-child
    relationships and population identity.
    """

    node_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = "All Events"
    negated: bool = False
    gate: Gate | None = None
    children: list[GateNode] = field(default_factory=list)
    parents: list[GateNode] = field(default_factory=list, repr=False)
    logic_operator: str = "AND"
    statistics: dict = field(default_factory=dict)
    creation_view: dict = field(default_factory=dict)
    is_umap_parent: bool = False  # True for synthetic nodes holding UMAP cluster populations
    is_logic_node: bool = False  # True for AND/OR/NOT nodes, explicit so an unwired
    # logic node (parents=[]) is never confused with the sentinel root below.

    @property
    def is_root(self) -> bool:
        """True only for the single 'All Events' root node — not for logic nodes.

        A freshly-created, unwired logic node also has gate=None and no
        parents yet, so structural inference alone can't tell it apart from
        the sentinel root — hence the explicit `is_logic_node` flag.
        """
        return self.gate is None and not self.parents and not self.is_logic_node

    @property
    def is_incomplete(self) -> bool:
        """True for a logic node that doesn't yet have enough wired parents
        to be evaluated. Always False for non-logic nodes.
        """
        if not self.is_logic_node:
            return False
        real_parents = [p for p in self.parents if not p.is_root]
        if self.logic_operator == "NOT":
            return len(real_parents) < 1
        return len(real_parents) < LOGIC_GATE_MIN_PARENTS

    def add_child(self, gate: Gate, name: str | None = None) -> GateNode:
        """Create and attach a child gate node.

        Args:
            gate: The Gate instance to wrap in the child node.
            name: Optional human-readable name for the population. If None,
                  uses the first 8 characters of the gate_id.

        Returns:
            GateNode: The newly created and attached child node.
        """
        node_name = name or (gate.gate_id[:8] if gate else "Unknown")
        child = GateNode(gate=gate, name=node_name, parents=[self])
        self.children.append(child)
        return child

    def remove_child(self, node_id: str) -> bool:
        """Remove a child population by node ID.

        Args:
            node_id: The unique identifier of the child node to remove.

        Returns:
            bool: True if the child was found and removed, False otherwise.
        """
        for i, child in enumerate(self.children):
            if child.node_id == node_id:
                self.children.pop(i)
                return True
        return False

    def find_node_by_id(self, node_id: str) -> GateNode | None:
        """Recursively search for a population node by its node ID.

        Args:
            node_id: The unique identifier to search for in this node and its descendants.

        Returns:
            GateNode or None: The matching node if found, otherwise None.
        """
        if self.node_id == node_id:
            return self
        for child in self.children:
            found = child.find_node_by_id(node_id)
            if found:
                return found
        return None

    def find_nodes_by_gate(self, gate_id: str) -> list[GateNode]:
        """Find all population nodes that use a specific gate instance.

        Args:
            gate_id: The unique identifier of the Gate instance to search for.

        Returns:
            list[GateNode]: A list of nodes that wrap the specified gate.
        """
        matches = []
        if self.gate and self.gate.gate_id == gate_id:
            matches.append(self)
        for child in self.children:
            matches.extend(child.find_nodes_by_gate(gate_id))
        return matches

    def _combine_parent_masks(self, parent_masks: list[np.ndarray], total_count: int) -> np.ndarray:
        if not parent_masks:
            return np.ones(total_count, dtype=bool)

        if self.logic_operator == "AND":
            mask = parent_masks[0].copy()
            for pm in parent_masks[1:]:
                mask &= pm
            return mask
        if self.logic_operator == "OR":
            mask = parent_masks[0].copy()
            for pm in parent_masks[1:]:
                mask |= pm
            return mask
        if self.logic_operator == "NOT":
            if len(parent_masks) == 1:
                return ~parent_masks[0]
            mask = parent_masks[0].copy()
            for pm in parent_masks[1:]:
                mask &= ~pm
            return mask

        return np.ones(total_count, dtype=bool)

    def _get_mask(self, events: pd.DataFrame) -> np.ndarray:
        if self.is_incomplete:
            # Unwired/under-wired logic node — has no valid population yet.
            # Without this, an empty parent list falls through to
            # `_combine_parent_masks`' "no parents" branch, which returns an
            # all-True mask (correct for the sentinel root, wrong here).
            return np.zeros(len(events), dtype=bool)

        parent_masks = [p._get_mask(events) for p in self.parents]
        mask = self._combine_parent_masks(parent_masks, len(events))

        if self.gate is not None:
            gate_mask = self.gate.contains(events)
            if self.negated:
                gate_mask = ~gate_mask
            mask &= gate_mask

        return mask

    def apply_hierarchy(self, events: pd.DataFrame) -> pd.DataFrame:
        """Apply the DAG hierarchy of gates up to this node.

        Args:
            events: The un-gated (root) DataFrame of events.

        Returns:
            pd.DataFrame: A subset of events that fall within this hierarchical path.
        """
        mask = self._get_mask(events)
        return events.loc[mask]

    def adapt_all(self, events: pd.DataFrame) -> None:
        """Recursively adapt all adaptive gates in the tree.

        Args:
            events: The un-gated (root) DataFrame of events to use for adaptation.
        """
        if self.gate and getattr(self.gate, "adaptive", False):
            parent_events = events
            if self.parents:
                dummy = GateNode(parents=self.parents, logic_operator=self.logic_operator)
                parent_events = dummy.apply_hierarchy(events)
            self.gate.adapt(parent_events)

        subset = self.gate.apply(events) if self.gate else events
        for child in self.children:
            child.adapt_all(subset)

    @staticmethod
    def from_dict(data: dict) -> GateNode | None:
        """Reconstruct a population DAG from a serialized dictionary."""
        from .gate_factory import gate_from_dict

        # Flat DAG format
        if "nodes" in data:
            nodes_by_id = {}
            root = None

            # First pass: create all nodes
            for n_data in data["nodes"]:
                gate_data = n_data.get("gate")
                gate = gate_from_dict(gate_data) if gate_data else None
                is_umap_parent = n_data.get("is_umap_parent", False) or (
                    n_data.get("name") == "UMAP Reduction"
                )
                is_root_flag = n_data.get("is_root", False)
                # Legacy saves predate the `is_logic_node` flag — infer it from the
                # same signal used to create the node (no gate, not the sentinel
                # root, not a UMAP cluster-population node).
                is_logic_node = n_data.get(
                    "is_logic_node", gate is None and not is_root_flag and not is_umap_parent
                )
                node = GateNode(
                    gate=gate,
                    name=n_data.get("name", "Unknown"),
                    node_id=n_data.get("node_id"),
                    negated=n_data.get("negated", False),
                    logic_operator=n_data.get("logic_operator", "AND"),
                    is_logic_node=is_logic_node,
                )
                node.creation_view = n_data.get("creation_view", {})
                node.is_umap_parent = is_umap_parent
                nodes_by_id[node.node_id] = node
                if is_root_flag:
                    root = node

            # Second pass: wire them up
            for n_data in data["nodes"]:
                node = nodes_by_id[n_data["node_id"]]
                for p_id in n_data.get("parents", []):
                    if p_id in nodes_by_id:
                        p_node = nodes_by_id[p_id]
                        node.parents.append(p_node)
                        p_node.children.append(node)

            return root

        raise ValueError("Invalid serialized DAG format")

    def to_dict(self) -> dict:
        """Serialize the full population DAG as a flat list of nodes."""
        nodes = []
        visited = set()

        def _collect(n: GateNode):
            if n.node_id in visited:
                return
            visited.add(n.node_id)
            nodes.append(
                {
                    "node_id": n.node_id,
                    "name": n.name,
                    "negated": n.negated,
                    "logic_operator": n.logic_operator,
                    "gate": n.gate.to_dict() if n.gate else None,
                    "parents": [p.node_id for p in n.parents],
                    "is_root": n.is_root,
                    "creation_view": n.creation_view,
                    "is_umap_parent": getattr(n, "is_umap_parent", False),
                    "is_logic_node": getattr(n, "is_logic_node", False),
                }
            )
            for c in n.children:
                _collect(c)

        _collect(self)
        return {"type": "dag", "nodes": nodes}
