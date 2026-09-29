"""Population service for managing gate hierarchies and gated data.

Provides a clean interface for querying and manipulating the population tree
without direct coupling to Sample or Experiment objects where possible.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from karcytics_sdk.plugin import get_logger

if TYPE_CHECKING:
    import pandas as pd

    from .experiment import Sample
    from .gating import Gate, GateNode
    from .state import FlowState

logger = get_logger(__name__, "flow_cytometry")


class PopulationService:
    """Service for managing populations (GateNodes) across the experiment."""

    def __init__(self, state: FlowState):
        self._state = state

    def get_sample(self, sample_id: str) -> Sample | None:
        """Look up a sample by ID."""
        return self._state.data.experiment.samples.get(sample_id)

    def get_root_node(self, sample_id: str) -> GateNode | None:
        """Get the root of the gate tree for a sample."""
        sample = self.get_sample(sample_id)
        return sample.gate_tree if sample else None

    def find_node(self, sample_id: str, node_id: str) -> GateNode | None:
        """Find a specific population node in a sample's tree."""
        root = self.get_root_node(sample_id)
        if not root:
            return None
        return root.find_node_by_id(node_id)

    def find_nodes_by_gate(self, sample_id: str, gate_id: str) -> list[GateNode]:
        """Find all nodes in a sample sharing a physical gate."""
        root = self.get_root_node(sample_id)
        if not root:
            return []
        return root.find_nodes_by_gate(gate_id)

    def get_gated_events(self, sample_id: str, node_id: str | None = None) -> pd.DataFrame | None:
        """Get the events for a population, applying all parent gates."""
        sample = self.get_sample(sample_id)
        if not sample or not sample.has_data:
            return None

        assert sample.fcs_data is not None
        events = sample.fcs_data.events
        if not node_id:
            return events

        node = self.find_node(sample_id, node_id)
        if not node:
            return events

        return node.apply_hierarchy(events)

    def add_population(
        self,
        sample_id: str,
        gate: Gate,
        parent_id: str | None = None,
        name: str | None = None,
    ) -> GateNode | list[GateNode] | None:
        """Add a new population to a sample's gating hierarchy."""
        sample = self.get_sample(sample_id)
        if not sample:
            return None

        parent = self.find_node(sample_id, parent_id) if parent_id else sample.gate_tree
        if not parent:
            logger.warning(f"Parent node {parent_id} not found in sample {sample_id}")
            return None

        # Delegate the node creation logic to the gate itself.
        # This resolves OCP violations by allowing gates (like QuadrantGate)
        # to determine how many nodes they spawn.
        nodes = gate.create_nodes(parent, name)

        # For backward compatibility with the expected return types
        if len(nodes) == 1:
            return nodes[0]
        return nodes

    def remove_population(self, sample_id: str, node_id: str) -> bool:
        """Remove a population and all its children from a sample."""
        sample = self.get_sample(sample_id)
        if not sample or not sample.gate_tree:
            return False

        node = self.find_node(sample_id, node_id)
        if not node or node.is_root:  # Cannot remove root
            return False

        # Collect all node IDs in this subtree (the node itself + all descendants)
        deleted_ids = set()

        def _collect_ids(cur: GateNode):
            deleted_ids.add(cur.node_id)
            for ch in cur.children:
                _collect_ids(ch)

        _collect_ids(node)

        # 1. Unhook from all direct parents
        for p in list(node.parents):
            p.remove_child(node.node_id)
            if p in node.parents:
                node.parents.remove(p)

        # 2. Also remove from root.children in case it's a logic node or attached directly to root
        sample.gate_tree.remove_child(node.node_id)

        # 3. Clean any remaining references in other nodes' parents across the entire tree
        def _clean_references(cur: GateNode):
            cur.parents = [p for p in cur.parents if p.node_id not in deleted_ids]
            for ch in cur.children:
                _clean_references(ch)

        _clean_references(sample.gate_tree)

        # The only structural mutation that doesn't also go through
        # GateCoordinator.recompute_all_stats (see there for why this
        # invalidates GateNode's mask cache too) — a surviving logic node
        # that had `node` as one of its parents just had its `parents`
        # list rewritten above, so its cached mask (if any) is now stale.
        sample.gate_tree.invalidate_mask_cache()
        return True
