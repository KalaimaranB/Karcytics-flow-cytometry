"""DAG Evaluator.

Handles evaluating boolean logic and subsetting for gate populations.
"""

from typing import TypedDict, cast

import numpy as np
import pandas as pd
from karcytics_sdk.plugin import get_logger

from ..gating import GateNode

logger = get_logger(__name__, "flow_cytometry")


class NodeStatistics(TypedDict):
    """Statistics for a gated population."""

    count: int
    pct_parent: float
    pct_total: float


class DagEvaluator:
    """Evaluates the boolean gating DAG over a set of events."""

    @staticmethod
    def _collect_nodes(root: GateNode) -> list[GateNode]:
        all_nodes = []
        visited = set()
        stack = [root]
        while stack:
            n = stack.pop()
            if n.node_id not in visited:
                visited.add(n.node_id)
                all_nodes.append(n)
                stack.extend(n.children)
        return all_nodes

    @staticmethod
    def _combine_parent_masks(
        node: GateNode, evaluated_masks: dict[str, np.ndarray], total_count: int
    ) -> np.ndarray:
        if node.is_incomplete:
            # Unwired/under-wired logic node — no valid population yet, unlike the
            # sentinel root (which also has no parents but means "all events").
            return np.zeros(total_count, dtype=bool)
        if not node.parents:
            return np.ones(total_count, dtype=bool)

        parent_masks = [evaluated_masks[p.node_id] for p in node.parents]
        if node.logic_operator == "AND":
            mask = parent_masks[0].copy()
            for pm in parent_masks[1:]:
                mask &= pm
        elif node.logic_operator == "OR":
            mask = parent_masks[0].copy()
            for pm in parent_masks[1:]:
                mask |= pm
        elif node.logic_operator == "NOT":
            if len(parent_masks) == 1:
                mask = ~parent_masks[0]
            else:
                mask = parent_masks[0].copy()
                for pm in parent_masks[1:]:
                    mask &= ~pm
        else:
            mask = np.ones(total_count, dtype=bool)

        return mask

    @staticmethod
    def _apply_gate(
        node: GateNode, events: pd.DataFrame, mask: np.ndarray, total_count: int
    ) -> np.ndarray:
        if not node.gate:
            return mask
        try:
            subset_events = events[mask]
            subset_mask = node.gate.contains(subset_events)
            if getattr(node, "negated", False):
                subset_mask = ~subset_mask

            full_gate_mask = np.zeros(total_count, dtype=bool)
            full_gate_mask[mask] = subset_mask
            return full_gate_mask
        except Exception as e:
            logger.warning("Gate evaluation failed for %s: %s", node.name, e)
            return np.zeros(total_count, dtype=bool)

    @staticmethod
    def evaluate(root: GateNode, events: pd.DataFrame) -> dict[str, NodeStatistics]:
        """Evaluates the gate tree DAG and returns statistics for each node.

        Args:
            root: The root GateNode of the tree.
            events: A pandas DataFrame containing event data.

        Returns:
            A dictionary mapping node_id to statistics.
        """
        stats_out: dict[str, NodeStatistics] = {}
        all_nodes = DagEvaluator._collect_nodes(root)
        in_degrees = {n.node_id: len(n.parents) for n in all_nodes}
        ready = [n for n in all_nodes if in_degrees[n.node_id] == 0]
        total_count = len(events)
        evaluated_masks: dict[str, np.ndarray] = {}

        while ready:
            node = ready.pop(0)

            mask = DagEvaluator._combine_parent_masks(node, evaluated_masks, total_count)
            parent_count = np.sum(mask) if node.parents else total_count

            mask = DagEvaluator._apply_gate(node, events, mask, total_count)
            evaluated_masks[node.node_id] = mask

            count = int(np.sum(mask))
            pct_parent = (count / parent_count * 100.0) if parent_count > 0 else 0.0
            pct_total = (count / total_count * 100.0) if total_count > 0 else 0.0

            stats: NodeStatistics = {
                "count": count,
                "pct_parent": round(pct_parent, 2),
                "pct_total": round(pct_total, 2),
            }
            node.statistics = cast(dict, stats)
            stats_out[node.node_id] = stats

            for child in node.children:
                in_degrees[child.node_id] -= 1
                if in_degrees[child.node_id] == 0:
                    ready.append(child)

        return stats_out
