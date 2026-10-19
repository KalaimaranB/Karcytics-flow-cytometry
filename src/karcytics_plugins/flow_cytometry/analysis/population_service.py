"""Read access to samples' populations and their gated events.

Changes to the gate tree go through GateCoordinator instead.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from karcytics_sdk.plugin import get_logger

from .derived.sync import sync_sample

if TYPE_CHECKING:
    import pandas as pd

    from .experiment import Sample
    from .gating import GateNode
    from .state import FlowState

logger = get_logger(__name__, "flow_cytometry")


class PopulationService:
    """Looks up populations (GateNodes) and the events inside them."""

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
        # Safety net: no-op unless a load/compensation path forgot to re-sync
        # derived columns, in which case gates on them would KeyError.
        sync_sample(self._state.data.experiment, sample)
        events = sample.fcs_data.events
        if not node_id:
            return events

        node = self.find_node(sample_id, node_id)
        if not node:
            return events

        return node.apply_hierarchy(events)
