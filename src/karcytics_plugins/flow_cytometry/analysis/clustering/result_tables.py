"""A clustering run's Population Statistics: its tables, drawn populations and export.

A run is the dict stored in ``umap_results`` (see ``run_input.run_record``).
Populations drawn on the Interactive Map live in ``run["custom_clusters"]``
as ``{"name", "mask": [event indices], "verts"}``; drawing one takes its
events out of the automatic clusters (their id becomes ``DRAWN_AWAY``).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from ..gating.subset import SubsetGate
from .methods import method_of
from .run_input import cluster_tables

DRAWN_AWAY = -1  # cluster id of events moved into a drawn population (HDBSCAN noise shares it)


def run_array(run: dict[str, Any], key: str) -> np.ndarray:
    """``run[key]`` as an array, converted in place (loaded runs hold lists)."""
    value = run[key]
    if isinstance(value, list):
        value = np.array(value)
        run[key] = value
    return value


def marker_labels(run: dict[str, Any]) -> list[str]:
    """The run's channels as marker labels ("CD3"), or channel names for runs without them."""
    return list(run.get("channel_labels") or run.get("channels", []))


@dataclass(frozen=True)
class DrawnPopulation:
    """One population drawn on the map, as listed in the tables."""

    number: int  # 1-based position in ``run["custom_clusters"]``: "Custom 2"
    name: str
    mask: np.ndarray  # bool, over the run's events


def drawn_populations(run: dict[str, Any]) -> list[DrawnPopulation]:
    """The run's drawn populations that hold any events."""
    n_events = len(run_array(run, "embedding"))
    found = []
    for number, drawn in enumerate(run.get("custom_clusters", []), 1):
        mask = np.zeros(n_events, dtype=bool)
        mask[drawn.get("mask", [])] = True
        if mask.any():
            found.append(
                DrawnPopulation(number, drawn.get("name", f"Custom Cluster {number}"), mask)
            )
    return found


def _frame(stored: Any) -> pd.DataFrame:
    """A table stored on a run (``to_dict(orient="split")``, or a frame) as a fresh frame."""
    if isinstance(stored, dict):
        return pd.DataFrame(
            data=stored.get("data", []),
            index=stored.get("index", []),
            columns=stored.get("columns", []),
        )
    return stored.copy()


def statistics_table(run: dict[str, Any]) -> pd.DataFrame | None:
    """Cluster ID / Cell Count / % of Total, then a "Custom N" row per drawn population.

    None when the run has no cluster statistics.
    """
    stored = run.get("cluster_stats")
    if stored is None:
        return None
    stats = _frame(stored).reset_index(drop=True)
    n_events = len(run_array(run, "embedding"))
    for drawn in drawn_populations(run):
        count = int(drawn.mask.sum())
        stats.loc[len(stats)] = [f"Custom {drawn.number}", count, count / n_events * 100]
    return stats


def heatmap_table(run: dict[str, Any]) -> pd.DataFrame | None:
    """Median marker value per cluster (mean per drawn population), columns as marker labels.

    None when the run has neither a heatmap nor drawn populations.
    """
    stored = run.get("marker_heatmap")
    drawn = drawn_populations(run)
    if stored is None and not drawn:
        return None
    channels = list(run.get("channels", []))
    heatmap = _frame(stored) if stored is not None else pd.DataFrame(columns=channels)
    if drawn:
        intensities = run_array(run, "intensities")
        for population in drawn:
            heatmap.loc[f"Custom {population.number}"] = intensities[population.mask].mean(axis=0)
    labels = list(run.get("channel_labels", []))
    label_of = {ch: labels[i] for i, ch in enumerate(channels) if i < len(labels)}
    heatmap.columns = [label_of.get(str(col), str(col)) for col in heatmap.columns]
    return heatmap


def stacked_profiles(heatmap: pd.DataFrame) -> np.ndarray:
    """Each row's marker values as percentages of the row (shifted up if any are negative)."""
    values = heatmap.to_numpy(dtype=float, copy=True)
    if values.size and values.min() < 0:
        values -= values.min()
    totals = values.sum(axis=1, keepdims=True)
    totals[totals == 0] = 1e-9
    return values / totals * 100


def add_drawn_population(
    run: dict[str, Any], name: str, verts: Sequence[Any], mask: np.ndarray
) -> None:
    """Record a population drawn on the map and take its events out of the clusters.

    The cluster statistics are recomputed without those events; "% of Total"
    stays out of every event in the run.
    """
    run.setdefault("custom_clusters", []).append(
        {"name": name, "mask": np.flatnonzero(mask).tolist(), "verts": verts}
    )
    if "clusters" not in run:
        return
    clusters = run_array(run, "clusters")
    clusters[mask] = DRAWN_AWAY
    kept = clusters != DRAWN_AWAY
    intensities = run_array(run, "intensities")
    run.update(cluster_tables(intensities[kept], clusters[kept], marker_labels(run), len(clusters)))


@dataclass(frozen=True)
class ExportPicks:
    """What to export: chosen cluster ids and drawn populations, each with its typed name."""

    clusters: Mapping[Any, str]  # cluster id -> name ("" = the method's default name)
    drawn: Sequence[tuple[np.ndarray, str]]  # (event mask, name) per drawn population


def export_populations(run: dict[str, Any], experiment: Any, picks: ExportPicks) -> int | None:
    """Add the picked clusters to the run's gate tree as subset populations.

    They go under one parent node named for the method, below the node the run
    clustered. Returns how many were added, or None when the run's sample,
    node or events are gone.
    """
    sample = experiment.samples.get(run.get("sample_id")) if run.get("sample_id") else None
    if sample is None or sample.gate_tree is None:
        return None
    node_id = run.get("node_id")
    target = sample.gate_tree.find_node_by_id(node_id) if node_id else sample.gate_tree
    indices = np.asarray(run.get("indices", []))
    if target is None or len(indices) == 0:
        return None

    method = method_of(run)
    parent = target.add_child(
        gate=SubsetGate(indices=[int(i) for i in indices]), name=method.export_parent
    )
    parent.is_umap_parent = True  # a container: the pipeline skips its thumbnail
    run["exported_node_id"] = parent.node_id  # double-clicking it reopens the run

    # The run clustered a subsample of the parent population, so each exported
    # count is scaled back up and marked as an estimate (see
    # dag_evaluator._propagate_estimation for how that flows downstream).
    parent_total, n_events = run.get("parent_total_events"), run.get("n_events")
    scale_factor = parent_total / n_events if parent_total and n_events else 1.0

    chosen = [(mask, name or "Custom Cluster") for mask, name in picks.drawn]
    if "clusters" in run:
        clusters = run_array(run, "clusters")
        chosen[:0] = [
            (clusters == cluster_id, name or method.cluster_name(cluster_id))
            for cluster_id, name in picks.clusters.items()
        ]
    for mask, name in chosen:
        node = parent.add_child(gate=SubsetGate(indices=[int(i) for i in indices[mask]]), name=name)
        node.scale_factor = scale_factor
        node.is_estimated = scale_factor > 1.0
    return len(chosen)
