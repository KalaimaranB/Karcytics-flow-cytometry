"""Gate statistics for a sample's boolean gating DAG.

`evaluate` walks the whole tree; `evaluate_scoped` only the nodes a
mutation changed and their descendants. Both share one walk.
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
    # Estimation-correction fields — see `_propagate_estimation`.
    # `count`/`pct_parent`/`pct_total` above are always the raw, unscaled
    # values; these are purely additive and only present when relevant, so
    # every existing consumer of the three keys above is unaffected.
    is_estimated: NotRequired[bool]
    scale_factor: NotRequired[float]
    is_scale_valid: NotRequired[bool]
    estimated_count: NotRequired[int]
    estimated_pct_total: NotRequired[float]


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
            ps = _parent_stats(p, stats_out, fall_back_to_persisted)
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
        ps = _parent_stats(p, stats_out, fall_back_to_persisted)
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


def _parent_mask(node: GateNode, masks: dict[str, np.ndarray], events: pd.DataFrame) -> np.ndarray:
    """Which events reach `node`: its parents' masks combined by its operator.

    A parent outside this pass (a scoped recompute) contributes its own
    cached mask from `GateNode.mask`.
    """
    if node.is_incomplete:
        # Unwired/under-wired logic node — no valid population yet, unlike the
        # sentinel root (which also has no parents but means "all events").
        return np.zeros(len(events), dtype=bool)
    parent_masks = [
        masks[p.node_id] if p.node_id in masks else p.mask(events) for p in node.parents
    ]
    return node.combine_parent_masks(parent_masks, len(events))


def _node_stats(
    node: GateNode,
    count: int,
    parent_count: int,
    total_count: int,
    stats_out: dict[str, NodeStatistics],
    fall_back_to_persisted: bool,
) -> NodeStatistics:
    pct_parent = (count / parent_count * 100.0) if parent_count > 0 else 0.0
    pct_total = (count / total_count * 100.0) if total_count > 0 else 0.0
    stats: NodeStatistics = {
        "count": count,
        "pct_parent": round(pct_parent, 2),
        "pct_total": round(pct_total, 2),
    }
    estimation = _propagate_estimation(
        node, stats_out, fall_back_to_persisted=fall_back_to_persisted
    )
    stats.update(cast("NodeStatistics", _build_estimation_stats(count, total_count, estimation)))
    if node.is_logic_node and node.parents:
        stats["per_parent_pcts"] = _per_parent_pcts(
            node,
            count,
            stats_out,
            total_count,
            fall_back_to_persisted=fall_back_to_persisted,
            node_scale=estimation,
        )
    return stats


def _walk(
    scope: dict[str, GateNode],
    events: pd.DataFrame,
    on_gate_error: Callable[[GateNode, Exception], None] | None,
    *,
    fall_back_to_persisted: bool,
) -> dict[str, NodeStatistics]:
    """Evaluate the nodes in `scope` in topological order, parents first.

    Parents outside `scope` count as already evaluated: their masks come
    from GateNode's cache and, with `fall_back_to_persisted`, their stats
    from `GateNode.statistics`.
    """
    total_count = len(events)
    in_degrees = {nid: sum(1 for p in n.parents if p.node_id in scope) for nid, n in scope.items()}
    ready = [n for nid, n in scope.items() if in_degrees[nid] == 0]
    stats_out: dict[str, NodeStatistics] = {}
    masks: dict[str, np.ndarray] = {}
    pruned: set[str] = set()

    while ready:
        node = ready.pop(0)
        skip = node.node_id in pruned or any(p.node_id in pruned for p in node.parents)
        if skip:
            pruned.add(node.node_id)
        else:
            mask = _parent_mask(node, masks, events)
            parent_count = int(np.sum(mask)) if node.parents else total_count
            mask, error = _apply_gate(node, events, mask, total_count)
            masks[node.node_id] = mask

            stats = _node_stats(
                node,
                int(np.sum(mask)),
                parent_count,
                total_count,
                stats_out,
                fall_back_to_persisted,
            )
            node.statistics = cast(dict, stats)
            stats_out[node.node_id] = stats

            if error is not None and on_gate_error is not None:
                on_gate_error(node, error)
                pruned.add(node.node_id)

        for child in node.children:
            if child.node_id in scope:
                in_degrees[child.node_id] -= 1
                if in_degrees[child.node_id] == 0:
                    ready.append(child)

    return stats_out


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
    scope = {n.node_id: n for n in root.iter_dag()}
    return _walk(scope, events, on_gate_error, fall_back_to_persisted=False)


def evaluate_scoped(
    changed_nodes: list[GateNode],
    events: pd.DataFrame,
    on_gate_error: Callable[[GateNode, Exception], None] | None = None,
) -> dict[str, NodeStatistics]:
    """Recompute stats for only `changed_nodes` and their descendants.

    Companion to `evaluate()` for the common case where a mutation only
    changed one node's gate or wiring: everything *above* the changed
    nodes is untouched, so their masks come from GateNode's own mask
    cache instead of being recomputed. Callers must invalidate the mask
    cache for `changed_nodes` themselves before calling this (this
    function only reads masks, it doesn't decide what's stale).

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
    scope = {n.node_id: n for changed in changed_nodes for n in changed.iter_dag()}
    return _walk(scope, events, on_gate_error, fall_back_to_persisted=True)
