"""Gated event arrays and per-population statistics for the Comparisons tab.

Returns plain numpy data the comparison renderers draw; no Qt, no matplotlib.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .fcs_io import get_channel_marker_label
from .population_service import population_events
from .state import FlowState
from .statistics import StatType, value_statistic


def _population(state: FlowState, sample_id: str, node_id: str | None) -> pd.DataFrame | None:
    sample = state.data.experiment.samples.get(sample_id)
    node = sample.gate_tree.find_node_by_id(node_id) if sample and node_id else None
    return population_events(state.data.experiment, sample, node)


def _finite(events: pd.DataFrame | None, channel: str) -> np.ndarray:
    if events is None or channel not in events.columns:
        return np.array([])
    values = events[channel].to_numpy(dtype=float)
    return values[np.isfinite(values)]


class ComparisonsDataExtractor:
    """Pulls gated data out of FlowState for the comparison renderers."""

    def get_events_for_population(
        self, state: FlowState, sample_id: str, node_id: str | None, channel: str
    ) -> np.ndarray:
        """Finite values of one channel for a gated population."""
        return _finite(_population(state, sample_id, node_id), channel)

    def get_2d_events_for_population(
        self,
        state: FlowState,
        sample_id: str,
        node_id: str | None,
        x_channel: str,
        y_channel: str,
    ) -> tuple[np.ndarray, np.ndarray]:
        """(x, y) values for a gated population, keeping only events finite in both."""
        events = _population(state, sample_id, node_id)
        if events is None or x_channel not in events.columns or y_channel not in events.columns:
            return np.array([]), np.array([])
        x = events[x_channel].to_numpy(dtype=float)
        y = events[y_channel].to_numpy(dtype=float)
        valid = np.isfinite(x) & np.isfinite(y)
        return x[valid], y[valid]

    def get_statistic_matrix(
        self,
        state: FlowState,
        pop_pairs: list[tuple[str, str | None, str]],
        channels: list[str],
        stat_type: StatType = StatType.MEDIAN,
    ) -> tuple[np.ndarray, list[str], list[str]]:
        """A (populations × channels) matrix of one statistic; NaN where there is no data.

        Args:
            pop_pairs: (sample_id, node_id or None, label), one row each.
            channels:  FCS channel keys, one column each.
            stat_type: the statistic per cell.

        Returns:
            (matrix, row_labels, col_labels); the column labels come from the
            first sample with data.
        """
        samples = state.data.experiment.samples
        reference = next(
            (s for sid, _, _ in pop_pairs if (s := samples.get(sid)) and s.fcs_data), None
        )
        col_labels = (
            [get_channel_marker_label(reference.fcs_data, ch) for ch in channels]
            if reference is not None and reference.fcs_data is not None
            else channels[:]
        )

        matrix = np.full((len(pop_pairs), len(channels)), np.nan)
        row_labels: list[str] = []
        for row, (sid, nid, label) in enumerate(pop_pairs):
            sample = samples.get(sid)
            events = _population(state, sid, nid)
            if sample is None or events is None:
                row_labels.append(label)
                continue
            row_labels.append(f"{sample.display_name} / {label}")
            for col, channel in enumerate(channels):
                values = _finite(events, channel)
                if len(values):
                    matrix[row, col] = value_statistic(values, stat_type)
        return matrix, row_labels, col_labels

    def get_channel_list(self, state: FlowState, sample_id: str) -> list[tuple[str, str]]:
        """[(display_label, channel_key), ...] for a sample."""
        sample = state.data.experiment.samples.get(sample_id)
        if not sample or sample.fcs_data is None:
            return []
        return [
            (get_channel_marker_label(sample.fcs_data, ch), ch) for ch in sample.fcs_data.channels
        ]
