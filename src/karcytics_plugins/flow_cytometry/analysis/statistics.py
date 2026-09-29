"""Statistical computations for flow cytometry populations.

Provides a unified interface for computing standard flow cytometry
statistics (Mean, Median, MFI, CV, %Parent, etc.) on gated populations.

All functions operate on pandas DataFrames — no GUI dependencies.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

import numpy as np
import pandas as pd
from karcytics_sdk.plugin import get_logger

logger = get_logger(__name__, "flow_cytometry")


class StatType(Enum):
    """Supported statistic types."""

    COUNT = "count"
    MEAN = "mean"
    MEDIAN = "median"
    GEOMETRIC_MEAN = "geometric_mean"
    MODE = "mode"
    SD = "sd"
    CV = "cv"
    MFI = "mfi"  # Median Fluorescence Intensity
    PERCENT_PARENT = "percent_parent"
    PERCENT_GRANDPARENT = "percent_grandparent"
    PERCENT_TOTAL = "percent_total"
    MIN = "min"
    MAX = "max"


@dataclass
class StatDefinition:
    """Specification for a single statistic to compute.

    Attributes:
        stat_type:  The type of statistic.
        parameter:  Channel/parameter name to compute on (None for Count).
        population: Gate name or ID this stat applies to.
    """

    stat_type: StatType
    parameter: str | None = None
    population: str | None = None


@dataclass
class StatResult:
    """Result of a single statistic computation.

    Attributes:
        definition: The :class:`StatDefinition` that produced this result.
        value:      The computed value (float or int).
        formatted:  Human-readable formatted string.
    """

    definition: StatDefinition
    value: float
    formatted: str = ""

    def __post_init__(self) -> None:
        if not self.formatted:
            if self.definition.stat_type == StatType.COUNT:
                self.formatted = f"{int(self.value):,}"
            elif self.definition.stat_type in (
                StatType.PERCENT_PARENT,
                StatType.PERCENT_GRANDPARENT,
                StatType.PERCENT_TOTAL,
                StatType.CV,
            ):
                self.formatted = f"{self.value:.2f}%"
            else:
                self.formatted = f"{self.value:.2f}"


def _compute_percent_statistic(  # noqa: PLR0911
    n: int,
    stat_type: StatType,
    parent_count: int | None,
    grandparent_count: int | None,
    total_count: int | None,
) -> float | None:
    if stat_type == StatType.PERCENT_PARENT:
        if parent_count and parent_count > 0:
            return float((n / parent_count) * 100.0)
        return 0.0

    if stat_type == StatType.PERCENT_GRANDPARENT:
        if grandparent_count and grandparent_count > 0:
            return float((n / grandparent_count) * 100.0)
        return 0.0

    if stat_type == StatType.PERCENT_TOTAL:
        if total_count and total_count > 0:
            return float((n / total_count) * 100.0)
        return 0.0

    return None


def _mean(values: np.ndarray) -> float:
    return float(np.mean(values))


def _median(values: np.ndarray) -> float:
    return float(np.median(values))


def _geometric_mean(values: np.ndarray) -> float:
    positive = values[values > 0]
    if len(positive) == 0:
        return 0.0
    return float(np.exp(np.mean(np.log(positive))))


def _mode(values: np.ndarray) -> float:
    hist, bin_edges = np.histogram(values, bins="auto")
    max_idx = np.argmax(hist)
    return float((bin_edges[max_idx] + bin_edges[max_idx + 1]) / 2.0)


def _standard_deviation(values: np.ndarray) -> float:
    return float(np.std(values, ddof=1))


def _coefficient_of_variation(values: np.ndarray) -> float:
    mean = np.mean(values)
    if mean == 0:
        return 0.0
    return float((np.std(values, ddof=1) / abs(mean)) * 100.0)


def _minimum(values: np.ndarray) -> float:
    return float(np.min(values))


def _maximum(values: np.ndarray) -> float:
    return float(np.max(values))


# Mirrors `gating/gate_factory.py`'s `_GATE_REGISTRY` dispatch-table pattern —
# adding a new value-based statistic means adding one entry here, not another
# elif branch.
_VALUE_STAT_REGISTRY: dict[StatType, Callable[[np.ndarray], float]] = {
    StatType.MEAN: _mean,
    StatType.MEDIAN: _median,
    StatType.MFI: _median,
    StatType.GEOMETRIC_MEAN: _geometric_mean,
    StatType.MODE: _mode,
    StatType.SD: _standard_deviation,
    StatType.CV: _coefficient_of_variation,
    StatType.MIN: _minimum,
    StatType.MAX: _maximum,
}


def _compute_value_statistic(values: np.ndarray, stat_type: StatType) -> float:
    fn = _VALUE_STAT_REGISTRY.get(stat_type)
    if fn is None:
        raise ValueError(f"Unsupported stat type: {stat_type}")
    return fn(values)


def compute_statistic(
    events: pd.DataFrame,
    param: str | None,
    stat_type: StatType,
    *,
    parent_count: int | None = None,
    grandparent_count: int | None = None,
    total_count: int | None = None,
) -> float:
    """Compute a single statistic on a population.

    Args:
        events:            Gated event DataFrame.
        param:             Channel name (ignored for COUNT and % stats).
        stat_type:         Which statistic to compute.
        parent_count:      Event count of the parent population
                           (required for PERCENT_PARENT).
        grandparent_count: Event count of grandparent (for PERCENT_GRANDPARENT).
        total_count:       Total ungated event count (for PERCENT_TOTAL).

    Returns:
        The computed statistic as a float.

    Raises:
        ValueError: If the parameter is missing from the DataFrame.
    """
    n = len(events)

    if stat_type == StatType.COUNT:
        return float(n)

    percent_stat = _compute_percent_statistic(
        n, stat_type, parent_count, grandparent_count, total_count
    )
    if percent_stat is not None:
        return percent_stat

    # Parameter-dependent stats
    if param is None:
        raise ValueError(f"Parameter required for {stat_type.value}")
    if param not in events.columns:
        raise ValueError(f"Parameter '{param}' not found in events")

    values = events[param].dropna().values

    if len(values) == 0:
        return 0.0

    return _compute_value_statistic(values, stat_type)


def compute_population_stats(
    events: pd.DataFrame,
    definitions: list[StatDefinition],
    *,
    parent_count: int | None = None,
    grandparent_count: int | None = None,
    total_count: int | None = None,
) -> list[StatResult]:
    """Compute multiple statistics on a population.

    Args:
        events:      Gated event DataFrame.
        definitions: List of :class:`StatDefinition` to compute.
        parent_count, grandparent_count, total_count:
                     Counts for percentage calculations.

    Returns:
        List of :class:`StatResult` instances.
    """
    results = []
    for defn in definitions:
        try:
            value = compute_statistic(
                events,
                defn.parameter,
                defn.stat_type,
                parent_count=parent_count,
                grandparent_count=grandparent_count,
                total_count=total_count,
            )
            results.append(StatResult(definition=defn, value=value))
        except (ValueError, KeyError) as exc:
            logger.warning("Stat computation failed for %s: %s", defn, exc)
            results.append(
                StatResult(
                    definition=defn,
                    value=0.0,
                    formatted=f"Error: {exc}",
                )
            )
    return results
