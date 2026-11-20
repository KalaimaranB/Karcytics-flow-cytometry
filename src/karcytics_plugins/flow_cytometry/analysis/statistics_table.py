"""The Statistics tab's results: picked statistics per population, across samples.

Rows are populations (matched by label across samples), columns are
(sample, statistic) pairs. Each cell keeps its number for charts and the text
the table shows. A population exported from a subsampled clustering run shows
its Count and % Total scaled back up, marked as an estimate.
"""

from __future__ import annotations

import csv
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from karcytics_sdk.plugin import get_logger

from .population_service import population_events
from .statistics import StatType, compute_statistic, format_statistic

logger = get_logger(__name__, "flow_cytometry")

_ESTIMATED_STATS = frozenset({StatType.COUNT, StatType.PERCENT_TOTAL})


@dataclass(frozen=True)
class PopulationPick:
    """One checked population: the sample, its gate node (None: all events), its label."""

    sample_id: str
    node_id: str | None
    label: str


@dataclass(frozen=True)
class StatisticsRequest:
    """What to compute: these statistics, of these populations, in these samples."""

    sample_ids: tuple[str, ...]
    populations: tuple[PopulationPick, ...]
    stats: tuple[StatType, ...]
    channel: str | None  # for the statistics that need one


@dataclass(frozen=True)
class StatCell:
    """One statistic of one population in one sample."""

    text: str  # "1,234", "12.50%"; "—" not gated in that sample, "0" empty, "Err" failed
    value: float = 0.0  # the number behind the text (0 when there is none)
    scale: float | None = None  # an estimate: scaled up by this from a subsample

    @property
    def shown(self) -> str:
        """The text with a "*" when the value is an estimate."""
        return f"{self.text}*" if self.scale else self.text


_NOT_GATED = StatCell("—")
_EMPTY = StatCell("0")
_FAILED = StatCell("Err")


@dataclass(frozen=True)
class StatisticsRow:
    population: str
    cells: dict[tuple[str, StatType], StatCell]  # (sample id, statistic) -> cell

    def cell(self, sample_id: str, stat: StatType) -> StatCell:
        return self.cells.get((sample_id, stat), _NOT_GATED)


@dataclass(frozen=True)
class StatisticsTable:
    request: StatisticsRequest
    sample_names: tuple[str, ...]  # display names, in ``request.sample_ids`` order
    rows: tuple[StatisticsRow, ...]

    @property
    def has_estimates(self) -> bool:
        return any(cell.scale for row in self.rows for cell in row.cells.values())

    def values(self, stat: StatType) -> tuple[np.ndarray, np.ndarray]:
        """``stat`` as (values, estimated): two populations × samples arrays."""
        cells = [[row.cell(sid, stat) for sid in self.request.sample_ids] for row in self.rows]
        values = np.array([[c.value for c in row] for row in cells], dtype=float)
        estimated = np.array([[bool(c.scale) for c in row] for row in cells], dtype=bool)
        shape = (len(self.rows), len(self.request.sample_ids))
        return values.reshape(shape), estimated.reshape(shape)

    def records(self) -> list[dict[str, str]]:
        """One dict per row, as exported: ``population`` then ``"<sample id>::<stat>"`` keys."""
        return [
            {
                "population": row.population,
                **{
                    f"{sid}::{stat.value}": row.cell(sid, stat).shown
                    for sid in self.request.sample_ids
                    for stat in self.request.stats
                },
            }
            for row in self.rows
        ]


def write_csv(path: str | Path, table: StatisticsTable) -> None:
    """Write the table's records to a CSV file."""
    records = table.records()
    fieldnames = list(records[0]) if records else ["population"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)


def compute_table(experiment: Any, request: StatisticsRequest) -> StatisticsTable:
    """Compute every requested statistic (reads the experiment; safe off the GUI thread)."""
    by_label: dict[str, dict[str, str | None]] = {}
    for pick in request.populations:
        by_label.setdefault(pick.label, {})[pick.sample_id] = pick.node_id
    rows = []
    for label, nodes in by_label.items():
        cells: dict[tuple[str, StatType], StatCell] = {}
        for sid in request.sample_ids:
            sample = experiment.samples.get(sid)
            if sid in nodes and sample is not None:
                for stat, cell in _population_cells(experiment, sample, nodes[sid], request):
                    cells[(sid, stat)] = cell
        rows.append(StatisticsRow(label, cells))
    names = tuple(_display_name(experiment, sid) for sid in request.sample_ids)
    return StatisticsTable(request, names, tuple(rows))


def _display_name(experiment: Any, sample_id: str) -> str:
    sample = experiment.samples.get(sample_id)
    return sample.display_name if sample is not None else sample_id


def _population_cells(
    experiment: Any, sample: Any, node_id: str | None, request: StatisticsRequest
) -> list[tuple[StatType, StatCell]]:
    node = sample.gate_tree.find_node_by_id(node_id) if node_id and sample.gate_tree else None
    events = population_events(experiment, sample, node)
    if events is None or len(events) == 0:
        return [(stat, _EMPTY) for stat in request.stats]
    parent, grandparent, total = _ancestor_counts(experiment, sample, node)
    # dag_evaluator keeps the estimation correction fresh on every gate change
    # (see its _propagate_estimation): read it, don't re-derive it.
    node_stats: dict = (node.statistics if node is not None else None) or {}
    scale_valid = bool(node_stats.get("is_estimated") and node_stats.get("is_scale_valid"))
    estimated = {
        StatType.COUNT: node_stats.get("estimated_count"),
        StatType.PERCENT_TOTAL: node_stats.get("estimated_pct_total"),
    }

    cells = []
    for stat in request.stats:
        try:
            if scale_valid and stat in _ESTIMATED_STATS:
                corrected = estimated[stat]
                if corrected is None:  # marked estimated without the estimate: show it failed
                    raise KeyError(f"no estimated {stat.value} on the node")
                value = float(corrected)
                cell = StatCell(
                    format_statistic(stat, value), value, node_stats.get("scale_factor", 1.0)
                )
            else:
                value = compute_statistic(
                    events,
                    request.channel if stat.needs_channel else None,
                    stat,
                    parent_count=parent,
                    grandparent_count=grandparent,
                    total_count=total,
                )
                cell = StatCell(format_statistic(stat, value), value)
        except Exception as exc:  # noqa: BLE001 - one failed cell must not lose the table
            logger.warning("Stat %s failed for %s/%s: %s", stat, sample.sample_id, node_id, exc)
            cell = _FAILED
        cells.append((stat, cell))
    return cells


def _ancestor_counts(experiment: Any, sample: Any, node: Any) -> tuple[int, int, int]:
    """Event counts of (parent, grandparent, all events) for a % statistic."""
    everything = population_events(experiment, sample)
    total = len(everything) if everything is not None else 0
    if node is None or not node.parents:
        return total, total, total

    def count(population: Any) -> int:
        if population is None or population.is_root:
            return total
        gated = population_events(experiment, sample, population)
        return len(gated) if gated is not None else 0

    parent = node.parents[0]
    return count(parent), count(parent.parents[0] if parent.parents else None), total


def picks_of(checked: Sequence[tuple[str, str | None, str]]) -> tuple[PopulationPick, ...]:
    """The population selector's (sample id, node id, label) triples as picks."""
    return tuple(PopulationPick(sid, nid, label) for sid, nid, label in checked)
