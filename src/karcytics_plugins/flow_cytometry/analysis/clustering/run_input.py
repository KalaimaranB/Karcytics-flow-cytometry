"""The events a clustering run works on, and the tables every run reports.

Shared by UMAP + HDBSCAN and FlowSOM: pick the population, subsample it,
and logicle-transform the chosen fluorescence channels with each channel's
display scale.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from ..fcs_io import get_channel_marker_label, get_fluorescence_channels
from ..transforms import biexponential_transform

if TYPE_CHECKING:
    from ..state import FlowState


@dataclass
class RunInput:
    channels: list[str]
    channel_labels: list[str]
    x: np.ndarray  # (events, channels), transformed
    indices: np.ndarray  # event row labels of the picked events
    parent_total: int  # events in the population before subsampling


def prepare_run_input(  # noqa: PLR0913
    state: FlowState,
    sample_id: str,
    node_id: str | None,
    channels: list[str],
    n_events: int,
    seed: int,
    min_events: int,
    *,
    cancelled: Callable[[], bool] = lambda: False,
) -> RunInput | str:
    """The run's input, or an error message for the user."""
    sample = state.data.experiment.samples[sample_id]
    fcs = sample.fcs_data
    if fcs is None or fcs.events is None:
        return "No FCS data loaded for this sample."
    fluo = _run_channels(fcs, channels)
    if isinstance(fluo, str):
        return fluo
    events = _population_events(sample, node_id, min_events)
    if isinstance(events, str):
        return events

    total = len(events)
    n = min(n_events, total)
    if n <= 0:
        return "No events available for analysis."
    np.random.seed(seed)  # the legacy global seed, so UMAP runs stay reproducible
    picked = events.iloc[np.random.choice(total, size=n, replace=False)]

    columns = []
    for ch in fluo:
        if cancelled():
            return "Task cancelled."
        scale = state.axis_manager.get_scale(ch, sample_id) if state.axis_manager else None
        columns.append(
            biexponential_transform(
                picked[ch].to_numpy(dtype=np.float64),
                top=getattr(scale, "logicle_t", 262144.0),
                width=getattr(scale, "logicle_w", 1.0),
                positive=getattr(scale, "logicle_m", 4.5),
                negative=getattr(scale, "logicle_a", 0.0),
            )
        )
    return RunInput(
        channels=fluo,
        channel_labels=[get_channel_marker_label(fcs, ch) for ch in fluo],
        x=np.column_stack(columns),
        indices=np.asarray(picked.index),
        parent_total=total,
    )


def _run_channels(fcs: Any, channels: list[str]) -> list[str] | str:
    """The fluorescence channels to use (all, or the chosen ones)."""
    fluo = get_fluorescence_channels(fcs)
    if not fluo:
        return "No fluorescence channels found in this sample."
    if channels:
        fluo = [ch for ch in fluo if ch in channels]
        if not fluo:
            return "None of the selected channels are available in this sample."
    return fluo


def _population_events(sample: Any, node_id: str | None, min_events: int) -> pd.DataFrame | str:
    events = sample.fcs_data.events
    node = sample.gate_tree.find_node_by_id(node_id) if node_id and sample.gate_tree else None
    if node is None:
        return events
    events = node.apply_hierarchy(events)
    if len(events) < min_events:
        return f"Gate '{node.name}' contains too few events ({len(events)}) for this run."
    return events


def cluster_tables(x: np.ndarray, clusters: np.ndarray, labels: list[str]) -> dict[str, Any]:
    """Per-cluster event counts and median marker values, as stored on a run."""
    df = pd.DataFrame(x, columns=labels)
    df["Cluster_ID"] = clusters
    counts = df["Cluster_ID"].value_counts().sort_index()
    stats = pd.DataFrame(
        {
            "Cluster ID": counts.index,
            "Cell Count": counts.values,
            "% of Total": (counts / len(df) * 100).values,
        }
    )
    return {
        "cluster_stats": stats.to_dict(orient="split"),
        "marker_heatmap": df.groupby("Cluster_ID").median().to_dict(orient="split"),
    }
