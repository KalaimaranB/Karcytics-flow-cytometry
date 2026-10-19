"""Read access to samples' populations and their gated events.

Changes to the gate tree go through GateCoordinator instead.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from karcytics_sdk.plugin import get_logger

from .derived.sync import sync_sample

if TYPE_CHECKING:
    import pandas as pd

    from .experiment import Experiment, Sample
    from .gating import GateNode
    from .state import FlowState

logger = get_logger(__name__, "flow_cytometry")


def population_events(
    experiment: Experiment, sample: Sample | None, node: GateNode | None = None
) -> pd.DataFrame | None:
    """The events in `node`'s population: the sample's events with every gate down to it applied.

    The whole sample when `node` is None; None when the sample has no events.
    This is the one way outside analysis/ to read a sample's events.
    """
    if sample is None or sample.fcs_data is None or sample.fcs_data.events is None:
        return None
    # Safety net: no-op unless a load/compensation path forgot to re-sync
    # derived columns, in which case gates on them would KeyError.
    sync_sample(experiment, sample)
    events = sample.fcs_data.events
    return events if node is None else node.apply_hierarchy(events)


def uncompensated_events(sample: Sample | None) -> pd.DataFrame | None:
    """The sample's events as acquired, before any compensation (None without data)."""
    fcs = sample.fcs_data if sample is not None else None
    if fcs is None or fcs.events is None:
        return None
    return fcs.raw_events if fcs.raw_events is not None else fcs.events


def channel_values(
    experiment: Experiment, sample: Sample | None, channel: str, node: GateNode | None = None
) -> np.ndarray | None:
    """One channel of a population's events as float64, or None when it has no such channel."""
    events = population_events(experiment, sample, node)
    if events is None or channel not in events:
        return None
    return events[channel].to_numpy(dtype=np.float64)


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
        """A population's events (the whole sample when the node is unknown or None)."""
        node = self.find_node(sample_id, node_id) if node_id else None
        return population_events(self._state.data.experiment, self.get_sample(sample_id), node)
