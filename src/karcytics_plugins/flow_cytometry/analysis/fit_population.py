"""Which events of a control a spillover estimate is fitted on.

An estimate is cleaner on the real cells than on everything the cytometer
recorded (debris, aggregates), so a fit can be restricted to a gate the
user drew. Only scatter gates qualify: a gate on a fluorescence axis is
positioned in compensated space, so deriving the compensation from it is
circular — and it can cut away the bright events the fit needs.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .experiment import Sample
from .gating.gate_node import GateNode
from .population_service import uncompensated_events

_SCATTER_PREFIXES = ("FSC", "SSC")
_PATH_SEPARATOR = " › "


@dataclass(frozen=True)
class FitEvents:
    """The uncompensated events of one control that a fit uses."""

    events: pd.DataFrame
    total: int  # events in the whole sample
    gated: bool  # ``events`` is the requested gate's population, not everything

    def describe(self, gate: str | None) -> str:
        if self.gated:
            return f"{len(self.events):,} of {self.total:,} (in '{gate}')"
        if gate is not None:
            return f"{self.total:,} — all events: no '{gate}' gate on this sample"
        return f"{self.total:,} — all events"


def population_gates(sample: Sample, scatter_only: bool = False) -> dict[str, GateNode]:
    """The sample's populations by path (``Cells › Singlets``), in tree order.

    With ``scatter_only``, just the gates that use scatter all the way up:
    a gate qualifies only if every gate above it does too.
    """
    found: dict[str, GateNode] = {}
    seen: set[str] = set()

    def _walk(node: GateNode, prefix: str) -> None:
        for child in node.children:
            if child.node_id in seen or child.is_incomplete:
                continue
            if scatter_only and (child.is_logic_node or not _on_scatter(child)):
                continue
            seen.add(child.node_id)
            path = prefix + child.name
            found.setdefault(path, child)
            _walk(child, path + _PATH_SEPARATOR)

    _walk(sample.gate_tree, "")
    return found


def scatter_gates(sample: Sample) -> dict[str, GateNode]:
    """The populations a spillover fit may be restricted to (see the module docstring)."""
    return population_gates(sample, scatter_only=True)


def population_rows(sample: Sample, population: str | None) -> pd.Index | None:
    """Row labels of the events in ``population``; None if the sample has no
    data or no such population (or ``population`` is None: everything).
    """
    fcs = sample.fcs_data
    node = population_gates(sample).get(population) if population is not None else None
    if fcs is None or fcs.events is None or node is None:
        return None
    # Gates are evaluated on the working events; row labels match the raw ones.
    return node.apply_hierarchy(fcs.events).index


def fit_events(sample: Sample, gate: str | None = None) -> FitEvents | None:
    """``sample``'s uncompensated events, restricted to ``gate`` if it has it.

    None if the sample has no data. A sample without the gate is used whole
    (``gated`` False) rather than dropped: a noisier fit beats a missing one.
    """
    fcs = sample.fcs_data
    raw = uncompensated_events(sample)
    if fcs is None or fcs.events is None or raw is None:
        return None
    node = scatter_gates(sample).get(gate) if gate is not None else None
    if node is None:
        return FitEvents(raw, len(raw), gated=False)
    # The gate is evaluated on the working events; scatter is the same in both.
    return FitEvents(raw.loc[node.apply_hierarchy(fcs.events).index], len(raw), gated=True)


def _on_scatter(node: GateNode) -> bool:
    gate = node.gate
    params = [p for p in (gate.x_param, gate.y_param) if p] if gate is not None else []
    return bool(params) and all(p.startswith(_SCATTER_PREFIXES) for p in params)
