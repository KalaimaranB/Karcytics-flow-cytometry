"""Protocols for domain service interfaces.

These protocols define the expected API for core analysis services.
UI and other boundary components should type-hint against these
protocols rather than concrete classes (Dependency Inversion).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    import pandas as pd

    from .experiment import Sample
    from .gating import Gate, GateNode


class IGateCoordinator(Protocol):
    """Protocol for the central gate operations facade."""

    def add_gate(
        self,
        gate: Gate,
        sample_id: str,
        name: str | None = None,
        parent_node_id: str | None = None,
    ) -> str | None: ...

    def remove_population(self, sample_id: str, node_id: str) -> bool: ...

    def add_logic_node(
        self, sample_id: str, operator: str, name: str | None = None
    ) -> str | None: ...

    def add_connection(self, sample_id: str, source_node_id: str, target_node_id: str) -> bool: ...

    def remove_connection(
        self, sample_id: str, source_node_id: str, target_node_id: str
    ) -> bool: ...

    def rename_population(self, sample_id: str, node_id: str, new_name: str) -> bool: ...

    def modify_gate(self, gate_id: str, sample_id: str, **kwargs: Any) -> bool: ...

    def split_population(self, sample_id: str, node_id: str) -> str | None: ...

    def copy_gates_to_group(self, source_sample_id: str) -> int: ...

    def get_gates_for_display(
        self, sample_id: str, parent_node_id: str | None = None
    ) -> tuple[list[Gate], list[GateNode]]: ...

    def recompute_all_stats(self, sample_id: str, sync: bool = False) -> None: ...

    def set_propagation_enabled(self, enabled: bool) -> None: ...


class IPopulationService(Protocol):
    """Protocol for population hierarchy traversal and querying."""

    def get_sample(self, sample_id: str) -> Sample | None: ...

    def get_root_node(self, sample_id: str) -> GateNode | None: ...

    def find_node(self, sample_id: str, node_id: str) -> GateNode | None: ...

    def find_nodes_by_gate(self, sample_id: str, gate_id: str) -> list[GateNode]: ...

    def get_gated_events(
        self, sample_id: str, node_id: str | None = None
    ) -> pd.DataFrame | None: ...

    def add_population(
        self,
        sample_id: str,
        gate: Gate,
        parent_id: str | None = None,
        name: str | None = None,
    ) -> GateNode | list[GateNode] | None: ...

    def remove_population(self, sample_id: str, node_id: str) -> bool: ...
