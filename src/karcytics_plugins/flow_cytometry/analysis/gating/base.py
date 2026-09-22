"""Base Gate class for flow cytometry gating."""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
from karcytics_sdk.plugin import get_logger

if TYPE_CHECKING:
    from .gate_node import GateNode

logger = get_logger(__name__, "flow_cytometry")


class Gate(ABC):
    """Abstract base for all gate types.

    Every gate operates on two parameters (x_param, y_param) for 2-D gates
    or one parameter for 1-D gates (y_param is None).

    Attributes:
        gate_id:   Unique identifier for serialization and cloning.
        x_param:   Channel/parameter name for the X axis.
        y_param:   Channel/parameter name for the Y axis (None for 1-D).
        adaptive:  If True, the gate supports automatic repositioning.
    """

    def __init__(
        self,
        x_param: str,
        y_param: str | None = None,
        *,
        adaptive: bool = False,
        gate_id: str | None = None,
    ) -> None:
        self.gate_id = gate_id or str(uuid.uuid4())
        self.x_param = x_param
        self.y_param = y_param
        self.adaptive = adaptive

    @abstractmethod
    def copy(self) -> Gate:
        """Create a deep copy of this gate."""

    @abstractmethod
    def contains(self, _events: pd.DataFrame) -> np.ndarray:
        """Test which events fall inside this gate.

        Args:
            events: DataFrame with columns matching ``x_param``
                    (and ``y_param`` if 2-D).

        Returns:
            Boolean array of shape ``(n_events,)``.
        """

    def apply(self, _events: pd.DataFrame) -> pd.DataFrame:
        """Return the subset of events inside this gate.

        Args:
            events: Full event DataFrame.

        Returns:
            Filtered DataFrame containing only gated events.
        """
        mask = self.contains(_events)
        return _events.loc[mask]

    def adapt(self, _events: pd.DataFrame) -> None:
        """Re-position the gate to fit a new dataset.

        Default implementation is a no-op.  Subclasses that support
        adaptive repositioning override this method with density-based
        optimization.

        Args:
            events: The new dataset to adapt to.
        """
        if self.adaptive:
            logger.debug(
                "Adaptive gate — adapt() not yet implemented for %s",
                type(self).__name__,
            )

    def to_dict(self) -> dict:
        """Serialize the gate to a JSON-compatible dictionary."""
        return {
            "type": type(self).__name__,
            "gate_id": self.gate_id,
            "x_param": self.x_param,
            "y_param": self.y_param,
            "adaptive": self.adaptive,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Gate:
        """Reconstruct a Gate instance from a serialized dictionary.

        Args:
            data: Dictionary containing the serialized gate attributes.

        Returns:
            An instantiated subclass of Gate.
        """
        # Base implementation handles common fields. Subclasses should override
        # to handle their specific parameters.
        return cls(
            x_param=data["x_param"],
            y_param=data.get("y_param"),
            adaptive=data.get("adaptive", False),
            gate_id=data.get("gate_id"),
        )

    def create_nodes(self, parent_node: GateNode, name: str | None = None) -> list[GateNode]:
        """Create and attach GateNodes for this gate to a parent node.

        Most gates create a single node, but some (like QuadrantGate) create multiple.

        Args:
            parent_node: The node to attach the new nodes to.
            name: Optional human-readable name for the population.

        Returns:
            list[GateNode]: The created nodes.
        """
        # Note: To avoid circular imports, GateNode is imported here
        from .gate_node import GateNode

        node_name = name or (self.gate_id[:8] if self.gate_id else "Unknown")
        child = GateNode(gate=self, name=node_name, parents=[parent_node])
        parent_node.children.append(child)
        return [child]

    def __repr__(self) -> str:
        return f"<{type(self).__name__} on {self.x_param}/{self.y_param}>"
