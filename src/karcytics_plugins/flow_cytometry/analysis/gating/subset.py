"""SubsetGate for explicit index-based populations (e.g., UMAP clusters)."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd

from .base import Gate


class SubsetGate(Gate):
    """A gate defined explicitly by a list of event indices.

    This is used for populations that are generated via non-linear algorithms
    like UMAP or clustering, where a 2D geometric boundary cannot be drawn.
    """

    def __init__(
        self,
        indices: Sequence[int],
        gate_id: str | None = None,
    ) -> None:
        # subset gates don't truly have x/y params, but we pass dummy values to satisfy the base class
        super().__init__(x_param="Subset", y_param=None, adaptive=False, gate_id=gate_id)
        # Convert to a set for O(1) lookup during contains()
        self.indices = set(indices)
        # An immutable copy for serialization: a tuple can be shared by every
        # undo snapshot of this gate instead of being copied into each one
        # (see workspace_document.detached) — these can run to 100k+ ids.
        self._indices_list: tuple[int, ...] = tuple(indices)

    def copy(self) -> SubsetGate:
        """Create a deep copy of this gate."""
        return SubsetGate(indices=self._indices_list, gate_id=self.gate_id)

    def contains(self, events: pd.DataFrame) -> np.ndarray:
        """Test which events fall inside this subset.

        Args:
            events: DataFrame of events.

        Returns:
            Boolean array of shape ``(n_events,)``.
        """
        # events.index contains the original event IDs.
        return events.index.isin(self.indices)

    def to_dict(self) -> dict:
        """Serialize the gate to a JSON-compatible dictionary."""
        d = super().to_dict()
        d["indices"] = self._indices_list
        return d

    @classmethod
    def from_dict(cls, data: dict) -> SubsetGate:
        """Reconstruct a SubsetGate instance from a serialized dictionary."""
        return cls(
            indices=data.get("indices", []),
            gate_id=data.get("gate_id"),
        )
