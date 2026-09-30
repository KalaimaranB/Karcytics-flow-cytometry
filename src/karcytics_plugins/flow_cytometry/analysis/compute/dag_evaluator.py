"""DAG Evaluator.

Handles evaluating boolean logic and subsetting for gate populations.
"""

from collections.abc import Callable
from typing import NotRequired, TypedDict, cast

import numpy as np
import pandas as pd
from karcytics_sdk.plugin import get_logger

from ..gating import GateNode

logger = get_logger(__name__, "flow_cytometry")


class ParentOverlap(TypedDict):
    """One parent's contribution to a logic node's population."""

    name: str
    parent_count: int
    pct_overlap: float
    # True when `pct_overlap` was computed from the node's scaled
    # `estimated_count` rather than its raw `count` — see `_per_parent_pcts`.
    is_scaled: NotRequired[bool]


class NodeStatistics(TypedDict):
    """Statistics for a gated population."""

    count: int
    pct_parent: float
    pct_total: float
    per_parent_pcts: NotRequired[dict[str, ParentOverlap]]
    # Estimation-correction fields — see DagEvaluator._propagate_estimation.
    # `count`/`pct_parent`/`pct_total` above are always the raw, unscaled
    # values; these are purely additive and only present when relevant, so
    # every existing consumer of the three keys above is unaffected.
    is_estimated: NotRequired[bool]
    scale_factor: NotRequired[float]
    is_scale_valid: NotRequired[bool]
    estimated_count: NotRequired[int]
    estimated_pct_total: NotRequired[float]


class DagEvaluator:
    """Evaluates the boolean gating DAG over a set of events."""

    @staticmethod
    def _collect_nodes(root: GateNode) -> list[GateNode]:
        return list(root.iter_dag())

    @staticmethod
    def _combine_parent_masks(
        node: GateNode,
        evaluated_masks: dict[str, np.ndarray],
        total_count: int,
        events: pd.DataFrame,
    ) -> np.ndarray:
        if node.is_incomplete:
            # Unwired/under-wired logic node — no valid population yet, unlike the
            # sentinel root (which also has no parents but means "all events").
            return np.zeros(total_count, dtype=bool)
        if not node.parents:
            return np.ones(total_count, dtype=bool)

        # A parent outside this pass's own traversal (scoped recompute — see
        # `evaluate_scoped`) falls back to GateNode's own cached mask instead
        # of KeyError-ing; a full-tree `evaluate()` call always has every
        # parent in `evaluated_masks` already, so this branch is a no-op there.
        parent_masks = [
            evaluated_masks[p.node_id] if p.node_id in evaluated_masks else p._get_mask(events)
            for p in node.parents
        ]
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
    ) -> tuple[np.ndarray, Exception | None]:
        if not node.gate:
            return mask, None
        try:
            subset_events = events[mask]
            subset_mask = node.gate.contains(subset_events)
            if getattr(node, "negated", False):
                subset_mask = ~subset_mask

            full_gate_mask = np.zeros(total_count, dtype=bool)
            full_gate_mask[mask] = subset_mask
            return full_gate_mask, None
        except Exception as e:
            logger.warning("Gate evaluation failed for %s: %s", node.name, e)
            return np.zeros(total_count, dtype=bool), e

    @staticmethod
    def _parent_stats(
        p: GateNode,
        stats_out: dict[str, NodeStatistics],
        fall_back_to_persisted: bool,
    ) -> NodeStatistics | dict:
        """`p`'s own last-known statistics: this pass's result if `p` was
        (re)computed, else its persisted `p.statistics` when the caller
        allows that fallback (`evaluate_scoped`, for a parent outside the
        changed subtree), else empty (nothing trustworthy is known).
        """
        return stats_out.get(p.node_id) or (p.statistics if fall_back_to_persisted else {})

    @staticmethod
    def _per_parent_pcts(
        node: GateNode,
        count: int,
        stats_out: dict[str, NodeStatistics],
        total_count: int,
        *,
        fall_back_to_persisted: bool = False,
        node_scale: tuple[bool, float, bool] = (False, 1.0, True),
    ) -> dict[str, ParentOverlap]:
        """One entry per parent: that parent's own count, and what share of
        it this AND/OR/NOT node's population overlaps.

        `count` is always this node's *raw*, unscaled mask count (see
        `NodeStatistics` — never mutated). Dividing it by a parent's own
        raw count is safe whenever both sides sit on the same footing —
        two exact parents, or an estimated parent against this node's raw
        count at that *same* subsample scale (the scale factor cancels).
        It silently breaks for a parent on a *different* footing: Course
        3's `B-cells AND UMAP B Cells` has an exact parent (B-cells, full
        population) and an estimated one (UMAP B Cells, ~22% subsample).
        The AND's raw overlap only ever has support inside that subsample,
        so dividing it by B-cells' full-population count deflates the
        ratio by roughly the same factor the estimate exists to correct
        for (~20% shown instead of the ~94% the subsample actually
        supports). Rescale the numerator to each parent's own footing
        before dividing instead of using the same raw `count` for every
        parent.
        """
        node_is_estimated, node_scale_factor, node_scale_valid = node_scale
        node_estimated_count = (
            round(count * node_scale_factor) if node_is_estimated and node_scale_valid else None
        )

        per_parent_pcts: dict[str, ParentOverlap] = {}
        for p in node.parents:
            if p.is_root:
                p_count = total_count
                p_scale_factor = 1.0
            else:
                ps = DagEvaluator._parent_stats(p, stats_out, fall_back_to_persisted)
                p_count = ps.get("count", 0)
                p_scale_factor = ps.get("scale_factor", 1.0) if ps.get("is_estimated") else 1.0

            is_scaled = node_estimated_count is not None and round(p_scale_factor, 6) != round(
                node_scale_factor, 6
            )
            numerator = (
                node_estimated_count if is_scaled and node_estimated_count is not None else count
            )

            entry: ParentOverlap = {
                "name": p.name,
                "parent_count": p_count,
                "pct_overlap": (numerator / p_count * 100.0) if p_count > 0 else 0.0,
            }
            if is_scaled:
                entry["is_scaled"] = True
            per_parent_pcts[p.node_id] = entry
        return per_parent_pcts

    @staticmethod
    def _propagate_estimation(
        node: GateNode,
        stats_out: dict[str, NodeStatistics],
        *,
        fall_back_to_persisted: bool = False,
    ) -> tuple[bool, float, bool]:
        """Returns `(is_estimated, scale_factor, is_scale_valid)` for `node`.

        Origin case: `node.is_estimated` was set once, at UMAP-export time
        (see `cluster_results_panel.py::_create_populations`). Otherwise the
        flag is inherited from parents — AND (the default `logic_operator`,
        so this covers an ordinary single-parent gate too) only ever
        *restricts* an estimated parent's subsample, so its `scale_factor`
        still applies validly. OR/NOT can pull in events the subsample never
        touched at all, so the correction does not transfer: the node is
        still flagged estimated (for visibility) but left un-scaled.
        """
        if getattr(node, "is_estimated", False):
            return True, getattr(node, "scale_factor", 1.0), True
        if not node.parents:
            return False, 1.0, True

        flags = []
        for p in node.parents:
            ps = DagEvaluator._parent_stats(p, stats_out, fall_back_to_persisted)
            flags.append(
                (
                    ps.get("is_estimated", False),
                    ps.get("scale_factor", 1.0),
                    ps.get("is_scale_valid", True),
                )
            )

        if not any(f[0] for f in flags):
            return False, 1.0, True
        if node.logic_operator != "AND":
            return True, 1.0, False

        estimated_scales = {round(f[1], 6) for f in flags if f[0]}
        all_valid = all(f[2] for f in flags if f[0])
        if len(estimated_scales) == 1 and all_valid:
            return True, estimated_scales.pop(), True
        return True, 1.0, False  # conflicting/invalid estimated parents — flag, don't guess

    @staticmethod
    def _build_estimation_stats(
        count: int,
        total_count: int,
        estimation: tuple[bool, float, bool],
    ) -> dict:
        is_estimated, scale_factor, is_scale_valid = estimation
        if not is_estimated:
            return {}
        extra: dict = {
            "is_estimated": True,
            "scale_factor": scale_factor,
            "is_scale_valid": is_scale_valid,
        }
        if is_scale_valid:
            estimated_count = round(count * scale_factor)
            extra["estimated_count"] = estimated_count
            extra["estimated_pct_total"] = (
                round(estimated_count / total_count * 100.0, 2) if total_count > 0 else 0.0
            )
        return extra

    @staticmethod
    def _enqueue_ready_children(
        node: GateNode, in_degrees: dict[str, int], ready: list[GateNode]
    ) -> None:
        for child in node.children:
            in_degrees[child.node_id] -= 1
            if in_degrees[child.node_id] == 0:
                ready.append(child)

    @staticmethod
    def evaluate(
        root: GateNode,
        events: pd.DataFrame,
        on_gate_error: Callable[[GateNode, Exception], None] | None = None,
    ) -> dict[str, NodeStatistics]:
        """Evaluates the gate tree DAG and returns statistics for each node.

        Args:
            root: The root GateNode of the tree.
            events: A pandas DataFrame containing event data.
            on_gate_error: Called with `(node, exception)` when a gate's
                `.contains()` raises. When given, the failing node still
                gets a zero-count stats entry, but its entire subtree is
                dropped from the result rather than continuing with
                zero-masked (and therefore misleading) descendant stats.
                When omitted (the default, used by `propagation_worker.py`),
                behavior is unchanged: log a warning, treat the gate as
                matching nothing, and keep walking descendants normally.

        Returns:
            A dictionary mapping node_id to statistics.
        """
        stats_out: dict[str, NodeStatistics] = {}
        all_nodes = DagEvaluator._collect_nodes(root)
        in_degrees = {n.node_id: len(n.parents) for n in all_nodes}
        ready = [n for n in all_nodes if in_degrees[n.node_id] == 0]
        total_count = len(events)
        evaluated_masks: dict[str, np.ndarray] = {}
        pruned: set[str] = set()

        while ready:
            node = ready.pop(0)

            if node.node_id in pruned or any(p.node_id in pruned for p in node.parents):
                pruned.add(node.node_id)
                DagEvaluator._enqueue_ready_children(node, in_degrees, ready)
                continue

            mask = DagEvaluator._combine_parent_masks(node, evaluated_masks, total_count, events)
            parent_count = np.sum(mask) if node.parents else total_count

            mask, error = DagEvaluator._apply_gate(node, events, mask, total_count)
            evaluated_masks[node.node_id] = mask

            count = int(np.sum(mask))
            pct_parent = (count / parent_count * 100.0) if parent_count > 0 else 0.0
            pct_total = (count / total_count * 100.0) if total_count > 0 else 0.0

            stats: NodeStatistics = {
                "count": count,
                "pct_parent": round(pct_parent, 2),
                "pct_total": round(pct_total, 2),
            }
            estimation = DagEvaluator._propagate_estimation(node, stats_out)
            stats.update(
                cast(
                    "NodeStatistics",
                    DagEvaluator._build_estimation_stats(count, total_count, estimation),
                )
            )

            if node.is_logic_node and node.parents:
                stats["per_parent_pcts"] = DagEvaluator._per_parent_pcts(
                    node, count, stats_out, total_count, node_scale=estimation
                )

            node.statistics = cast(dict, stats)
            stats_out[node.node_id] = stats

            if error is not None and on_gate_error is not None:
                on_gate_error(node, error)
                pruned.add(node.node_id)

            DagEvaluator._enqueue_ready_children(node, in_degrees, ready)

        return stats_out

    @staticmethod
    def evaluate_scoped(
        changed_nodes: list[GateNode],
        events: pd.DataFrame,
        on_gate_error: Callable[[GateNode, Exception], None] | None = None,
    ) -> dict[str, NodeStatistics]:
        """Recompute stats for only `changed_nodes` and their descendants.

        Companion to `evaluate()` for the common case where a mutation only
        changed one node's gate or wiring: everything *above* the changed
        nodes is untouched, so their masks come from `GateNode._get_mask`'s
        own cache (Priority 1 analysis #1) instead of being recomputed —
        this is the "scope recompute to the mutated node's descendants"
        fix for Priority 1 analysis #3. Callers must invalidate the mask
        cache for `changed_nodes` themselves before calling this (this
        method only reads masks, it doesn't decide what's stale).

        Args:
            changed_nodes: The node(s) whose gate or wiring changed —
                typically one, but `modify_gate` can affect several nodes
                sharing the same gate instance.
            events: A pandas DataFrame containing event data.
            on_gate_error: Same contract as `evaluate()`.

        Returns:
            A dictionary mapping node_id to statistics, containing only
            `changed_nodes` and their descendants — callers merge this into
            an existing full stats map rather than replacing it.
        """
        total_count = len(events)
        scope: dict[str, GateNode] = {}
        stack = list(changed_nodes)
        while stack:
            n = stack.pop()
            if n.node_id in scope:
                continue
            scope[n.node_id] = n
            stack.extend(n.children)

        in_degrees = {
            nid: sum(1 for p in n.parents if p.node_id in scope) for nid, n in scope.items()
        }
        ready = [n for nid, n in scope.items() if in_degrees[nid] == 0]
        stats_out: dict[str, NodeStatistics] = {}
        evaluated_masks: dict[str, np.ndarray] = {}
        pruned: set[str] = set()

        while ready:
            node = ready.pop(0)

            if node.node_id in pruned or any(
                p.node_id in pruned for p in node.parents if p.node_id in scope
            ):
                pruned.add(node.node_id)
                DagEvaluator._enqueue_scoped_ready(node, scope, in_degrees, ready)
                continue

            mask = DagEvaluator._combine_parent_masks(node, evaluated_masks, total_count, events)
            parent_count = np.sum(mask) if node.parents else total_count

            mask, error = DagEvaluator._apply_gate(node, events, mask, total_count)
            evaluated_masks[node.node_id] = mask

            count = int(np.sum(mask))
            pct_parent = (count / parent_count * 100.0) if parent_count > 0 else 0.0
            pct_total = (count / total_count * 100.0) if total_count > 0 else 0.0

            stats: NodeStatistics = {
                "count": count,
                "pct_parent": round(pct_parent, 2),
                "pct_total": round(pct_total, 2),
            }
            estimation = DagEvaluator._propagate_estimation(
                node, stats_out, fall_back_to_persisted=True
            )
            stats.update(
                cast(
                    "NodeStatistics",
                    DagEvaluator._build_estimation_stats(count, total_count, estimation),
                )
            )

            if node.is_logic_node and node.parents:
                stats["per_parent_pcts"] = DagEvaluator._per_parent_pcts(
                    node,
                    count,
                    stats_out,
                    total_count,
                    fall_back_to_persisted=True,
                    node_scale=estimation,
                )

            node.statistics = cast(dict, stats)
            stats_out[node.node_id] = stats

            if error is not None and on_gate_error is not None:
                on_gate_error(node, error)
                pruned.add(node.node_id)

            DagEvaluator._enqueue_scoped_ready(node, scope, in_degrees, ready)

        return stats_out

    @staticmethod
    def _enqueue_scoped_ready(
        node: GateNode,
        scope: dict[str, GateNode],
        in_degrees: dict[str, int],
        ready: list[GateNode],
    ) -> None:
        for child in node.children:
            if child.node_id not in scope:
                continue
            in_degrees[child.node_id] -= 1
            if in_degrees[child.node_id] == 0:
                ready.append(child)
