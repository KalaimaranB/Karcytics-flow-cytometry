"""Tests for `DagEvaluator.evaluate` — the single tree-walker `StatisticsAnalysis`
and `propagation_worker.py` now share (Priority 1 analysis #2: these used to be
three independent implementations of the same AND/OR/NOT/gate-mask walk that
could silently drift from each other).

Failure-handling behavior is the part that mattered most to port faithfully:
`StatisticsAnalysis._walk_and_compute` used to emit a Qt error signal and drop
an entire failed subtree from the results rather than silently reporting
zero counts for it. `on_gate_error` reproduces exactly that, opt-in, so
`propagation_worker.py` (which doesn't pass it) keeps its original
zero-mask-and-keep-going behavior unchanged.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from karcytics_plugins.flow_cytometry.analysis.compute.dag_evaluator import DagEvaluator
from karcytics_plugins.flow_cytometry.analysis.gating.base import Gate
from karcytics_plugins.flow_cytometry.analysis.gating.gate_node import GateNode


class FixedGate(Gate):
    """A gate with a hardcoded boolean result, or one that raises."""

    def __init__(self, mask: np.ndarray | None = None, raises: Exception | None = None) -> None:
        super().__init__(x_param="FSC-A", y_param="SSC-A")
        self.mask = mask
        self.raises = raises
        self.call_count = 0

    def copy(self) -> FixedGate:
        return FixedGate(self.mask, self.raises)

    def contains(self, events: pd.DataFrame) -> np.ndarray:
        self.call_count += 1
        if self.raises is not None:
            raise self.raises
        assert self.mask is not None
        return self.mask[: len(events)]


@pytest.fixture
def events():
    return pd.DataFrame({"FSC-A": np.arange(10.0), "SSC-A": np.arange(10.0)})


def test_root_gets_full_count_stats(events):
    root = GateNode(name="All Events")

    stats = DagEvaluator.evaluate(root, events)

    assert stats[root.node_id] == {"count": 10, "pct_parent": 100.0, "pct_total": 100.0}


def test_regular_node_stats_match_its_gate(events):
    root = GateNode(name="All Events")
    node = GateNode(gate=FixedGate(np.array([True] * 6 + [False] * 4)), name="A", parents=[root])
    root.children.append(node)

    stats = DagEvaluator.evaluate(root, events)

    assert stats[node.node_id]["count"] == 6
    assert stats[node.node_id]["pct_parent"] == 60.0
    assert stats[node.node_id]["pct_total"] == 60.0


def test_logic_node_gets_per_parent_overlap_percentages(events):
    root = GateNode(name="All Events")
    node_a = GateNode(gate=FixedGate(np.array([True] * 8 + [False] * 2)), name="A", parents=[root])
    root.children.append(node_a)
    node_b = GateNode(gate=FixedGate(np.array([True] * 5 + [False] * 5)), name="B", parents=[root])
    root.children.append(node_b)
    node_and = GateNode(
        name="AND", logic_operator="AND", parents=[node_a, node_b], is_logic_node=True
    )
    node_a.children.append(node_and)
    node_b.children.append(node_and)

    stats = DagEvaluator.evaluate(root, events)

    per_parent = stats[node_and.node_id]["per_parent_pcts"]
    assert per_parent[node_a.node_id]["parent_count"] == 8
    assert per_parent[node_b.node_id]["parent_count"] == 5
    # AND count is 5 (both True for indices 0-4); overlap vs A (8) = 62.5%
    assert per_parent[node_a.node_id]["pct_overlap"] == pytest.approx(62.5)


def test_gate_failure_without_callback_zero_masks_but_keeps_walking_descendants(events):
    """Default behavior (no `on_gate_error`) — used by propagation_worker.py
    today — must stay exactly as it was: log and continue, not raise, not prune.
    """
    root = GateNode(name="All Events")
    failing = GateNode(gate=FixedGate(raises=ValueError("boom")), name="Bad", parents=[root])
    root.children.append(failing)
    child = GateNode(gate=FixedGate(np.array([True] * 10)), name="Child", parents=[failing])
    failing.children.append(child)

    stats = DagEvaluator.evaluate(root, events)

    assert stats[failing.node_id]["count"] == 0
    assert child.node_id in stats  # descendant still computed, per existing behavior


def test_gate_failure_with_callback_invokes_it_and_prunes_the_subtree(events):
    root = GateNode(name="All Events")
    failing = GateNode(gate=FixedGate(raises=ValueError("boom")), name="Bad", parents=[root])
    root.children.append(failing)
    child = GateNode(gate=FixedGate(np.array([True] * 10)), name="Child", parents=[failing])
    failing.children.append(child)

    errors = []
    stats = DagEvaluator.evaluate(
        root, events, on_gate_error=lambda node, exc: errors.append((node.node_id, exc))
    )

    assert len(errors) == 1
    assert errors[0][0] == failing.node_id
    assert isinstance(errors[0][1], ValueError)

    assert stats[failing.node_id] == {"count": 0, "pct_parent": 0.0, "pct_total": 0.0}
    # Descendant of a failed node is dropped entirely, matching the old
    # StatisticsAnalysis._walk_and_compute behavior (no stale/misleading entry).
    assert child.node_id not in stats


def test_a_sibling_unaffected_by_a_failing_nodes_pruning(events):
    root = GateNode(name="All Events")
    failing = GateNode(gate=FixedGate(raises=ValueError("boom")), name="Bad", parents=[root])
    root.children.append(failing)
    healthy = GateNode(
        gate=FixedGate(np.array([True] * 7 + [False] * 3)), name="Good", parents=[root]
    )
    root.children.append(healthy)

    stats = DagEvaluator.evaluate(root, events, on_gate_error=lambda node, exc: None)

    assert stats[healthy.node_id]["count"] == 7


class TestEvaluateScoped:
    """`evaluate_scoped` (Priority 1 analysis #3) — recompute only a changed
    node and its descendants, reusing `GateNode._get_mask`'s own cache
    (Priority 1 analysis #1) for the unaffected ancestor chain rather than
    walking the whole tree from root again.
    """

    def test_only_returns_the_changed_node_and_its_descendants(self, events):
        root = GateNode(name="All Events")
        changed = GateNode(
            gate=FixedGate(np.array([True] * 6 + [False] * 4)), name="A", parents=[root]
        )
        root.children.append(changed)
        grandchild = GateNode(
            gate=FixedGate(np.array([True] * 10)), name="A-child", parents=[changed]
        )
        changed.children.append(grandchild)
        sibling = GateNode(gate=FixedGate(np.array([True] * 10)), name="B", parents=[root])
        root.children.append(sibling)

        stats = DagEvaluator.evaluate_scoped([changed], events)

        assert set(stats.keys()) == {changed.node_id, grandchild.node_id}
        assert root.node_id not in stats
        assert sibling.node_id not in stats

    def test_uses_the_cached_parent_mask_without_recomputing_it(self, events):
        parent_gate = FixedGate(np.array([True] * 8 + [False] * 2))
        root = GateNode(name="All Events")
        parent = GateNode(gate=parent_gate, name="Parent", parents=[root])
        root.children.append(parent)
        changed = GateNode(
            gate=FixedGate(np.array([True] * 5 + [False] * 5)), name="Changed", parents=[parent]
        )
        parent.children.append(changed)

        parent.apply_hierarchy(events)  # populate parent's mask cache
        assert parent_gate.call_count == 1

        changed.invalidate_mask_cache()
        DagEvaluator.evaluate_scoped([changed], events)

        assert parent_gate.call_count == 1  # still 1 — cache hit, not recomputed

    def test_matches_a_full_evaluate_for_the_same_subtree(self, events):
        root = GateNode(name="All Events")
        node_a = GateNode(
            gate=FixedGate(np.array([True] * 7 + [False] * 3)), name="A", parents=[root]
        )
        root.children.append(node_a)
        node_b = GateNode(
            gate=FixedGate(np.array([True] * 6 + [False] * 4)), name="B", parents=[node_a]
        )
        node_a.children.append(node_b)

        full = DagEvaluator.evaluate(root, events)
        node_a.invalidate_mask_cache()
        scoped = DagEvaluator.evaluate_scoped([node_a], events)

        assert scoped[node_a.node_id] == full[node_a.node_id]
        assert scoped[node_b.node_id] == full[node_b.node_id]

    def test_logic_node_per_parent_pcts_uses_persisted_count_for_an_out_of_scope_parent(
        self, events
    ):
        root = GateNode(name="All Events")
        stable = GateNode(
            gate=FixedGate(np.array([True] * 9 + [False])), name="Stable", parents=[root]
        )
        root.children.append(stable)
        changed = GateNode(
            gate=FixedGate(np.array([True] * 4 + [False] * 6)), name="Changed", parents=[root]
        )
        root.children.append(changed)
        or_node = GateNode(
            name="OR", logic_operator="OR", parents=[stable, changed], is_logic_node=True
        )
        stable.children.append(or_node)
        changed.children.append(or_node)

        # Establish a baseline (as if this had been computed before).
        DagEvaluator.evaluate(root, events)

        changed.invalidate_mask_cache()
        or_node.invalidate_mask_cache()
        stats = DagEvaluator.evaluate_scoped([changed, or_node], events)

        overlap = stats[or_node.node_id]["per_parent_pcts"]
        assert overlap[stable.node_id]["parent_count"] == 9  # persisted, not recomputed

    def test_gate_failure_with_callback_prunes_within_the_scoped_subtree(self, events):
        root = GateNode(name="All Events")
        changed = GateNode(
            gate=FixedGate(raises=ValueError("boom")), name="Changed", parents=[root]
        )
        root.children.append(changed)
        grandchild = GateNode(
            gate=FixedGate(np.array([True] * 10)), name="Grandchild", parents=[changed]
        )
        changed.children.append(grandchild)

        errors = []
        stats = DagEvaluator.evaluate_scoped(
            [changed], events, on_gate_error=lambda node, exc: errors.append(node.node_id)
        )

        assert errors == [changed.node_id]
        assert stats[changed.node_id]["count"] == 0
        assert grandchild.node_id not in stats


class TestEstimationPropagation:
    """`_propagate_estimation` — how a UMAP-exported node's `scale_factor`
    correction flows through the DAG. A plain gate or an AND combination
    only ever *restricts* an estimated ancestor's subsample, so the
    correction transfers validly; OR/NOT can pull in events the subsample
    never touched, so it doesn't (flagged, left unscaled).
    """

    def test_non_estimated_node_has_no_estimation_keys(self, events):
        root = GateNode(name="All Events")
        node = GateNode(
            gate=FixedGate(np.array([True] * 6 + [False] * 4)), name="A", parents=[root]
        )
        root.children.append(node)

        stats = DagEvaluator.evaluate(root, events)

        assert "is_estimated" not in stats[node.node_id]
        assert "estimated_count" not in stats[node.node_id]

    def test_origin_estimated_node_gets_scaled_count(self, events):
        root = GateNode(name="All Events")
        est = GateNode(
            gate=FixedGate(np.array([True] * 3 + [False] * 7)), name="UMAP B Cells", parents=[root]
        )
        root.children.append(est)
        est.is_estimated = True
        est.scale_factor = 4.0

        stats = DagEvaluator.evaluate(root, events)

        s = stats[est.node_id]
        assert s["count"] == 3  # raw, unscaled
        assert s["is_estimated"] is True
        assert s["scale_factor"] == 4.0
        assert s["is_scale_valid"] is True
        assert s["estimated_count"] == 12
        assert s["estimated_pct_total"] == pytest.approx(120.0)

    def test_plain_gate_under_estimated_parent_inherits_scale_factor(self, events):
        root = GateNode(name="All Events")
        est = GateNode(
            gate=FixedGate(np.array([True] * 8 + [False] * 2)),
            name="UMAP Reduction",
            parents=[root],
        )
        root.children.append(est)
        est.is_estimated = True
        est.scale_factor = 4.0
        child = GateNode(gate=FixedGate(np.array([True] * 8)), name="UMAP B Cells", parents=[est])
        est.children.append(child)

        stats = DagEvaluator.evaluate(root, events)

        s = stats[child.node_id]
        assert s["count"] == 8
        assert s["is_estimated"] is True
        assert s["scale_factor"] == 4.0
        assert s["is_scale_valid"] is True
        assert s["estimated_count"] == 32

    def test_and_node_combining_estimated_and_exact_parent_is_scale_valid(self, events):
        root = GateNode(name="All Events")
        est = GateNode(
            gate=FixedGate(np.array([True] * 6 + [False] * 4)), name="UMAP B Cells", parents=[root]
        )
        root.children.append(est)
        est.is_estimated = True
        est.scale_factor = 4.0
        exact = GateNode(
            gate=FixedGate(np.array([True] * 5 + [False] * 5)), name="B-cells", parents=[root]
        )
        root.children.append(exact)
        and_node = GateNode(
            name="AND", logic_operator="AND", parents=[est, exact], is_logic_node=True
        )
        est.children.append(and_node)
        exact.children.append(and_node)

        stats = DagEvaluator.evaluate(root, events)

        s = stats[and_node.node_id]
        assert s["count"] == 5  # AND of first-6-True & first-5-True
        assert s["is_estimated"] is True
        assert s["scale_factor"] == 4.0
        assert s["is_scale_valid"] is True
        assert s["estimated_count"] == 20

    def test_and_node_per_parent_pcts_rescales_the_exact_parent_but_not_the_estimated_one(
        self, events
    ):
        """Regression: an AND node's own raw `count` only ever has support
        inside its estimated parent's subsample, so dividing it by an
        *exact* parent's full-population count (as `_per_parent_pcts` used
        to, unconditionally) silently deflated that one ratio by the scale
        factor — e.g. a real UMAP B Cells x B-cells AND showed "20.7% of
        B-cells" for an overlap that was actually ~94% once corrected.
        The estimated parent's own ratio needs no such correction (both
        sides are subsample-scoped, so the scale factor cancels).
        """
        root = GateNode(name="All Events")
        est = GateNode(
            gate=FixedGate(np.array([True] * 6 + [False] * 4)), name="UMAP B Cells", parents=[root]
        )
        root.children.append(est)
        est.is_estimated = True
        est.scale_factor = 4.0
        exact = GateNode(
            gate=FixedGate(np.array([True] * 5 + [False] * 5)), name="B-cells", parents=[root]
        )
        root.children.append(exact)
        and_node = GateNode(
            name="AND", logic_operator="AND", parents=[est, exact], is_logic_node=True
        )
        est.children.append(and_node)
        exact.children.append(and_node)

        stats = DagEvaluator.evaluate(root, events)

        overlap = stats[and_node.node_id]["per_parent_pcts"]
        # "% of UMAP B Cells": raw AND count (5) / UMAP B Cells' own raw
        # count (6) — same subsample footing on both sides, untouched.
        assert overlap[est.node_id]["pct_overlap"] == pytest.approx(5 / 6 * 100.0)
        assert "is_scaled" not in overlap[est.node_id]
        # "% of B-cells": the AND's raw overlap (5) rescaled to B-cells'
        # full-population footing (5 * scale_factor 4.0 = 20) before
        # dividing by B-cells' own count (5), and flagged as such.
        assert overlap[exact.node_id]["pct_overlap"] == pytest.approx(20 / 5 * 100.0)
        assert overlap[exact.node_id]["is_scaled"] is True

    def test_or_node_combining_estimated_and_exact_parent_is_not_scale_valid(self, events):
        root = GateNode(name="All Events")
        est = GateNode(
            gate=FixedGate(np.array([True] * 6 + [False] * 4)), name="UMAP B Cells", parents=[root]
        )
        root.children.append(est)
        est.is_estimated = True
        est.scale_factor = 4.0
        exact = GateNode(
            gate=FixedGate(np.array([True] * 5 + [False] * 5)), name="B-cells", parents=[root]
        )
        root.children.append(exact)
        or_node = GateNode(name="OR", logic_operator="OR", parents=[est, exact], is_logic_node=True)
        est.children.append(or_node)
        exact.children.append(or_node)

        stats = DagEvaluator.evaluate(root, events)

        s = stats[or_node.node_id]
        assert s["is_estimated"] is True
        assert s["is_scale_valid"] is False
        assert "estimated_count" not in s

    def test_not_node_of_an_estimated_parent_is_not_scale_valid(self, events):
        root = GateNode(name="All Events")
        est = GateNode(
            gate=FixedGate(np.array([True] * 6 + [False] * 4)), name="UMAP B Cells", parents=[root]
        )
        root.children.append(est)
        est.is_estimated = True
        est.scale_factor = 4.0
        not_node = GateNode(name="NOT", logic_operator="NOT", parents=[est], is_logic_node=True)
        est.children.append(not_node)

        stats = DagEvaluator.evaluate(root, events)

        s = stats[not_node.node_id]
        assert s["is_estimated"] is True
        assert s["is_scale_valid"] is False
        assert "estimated_count" not in s

    def test_and_node_with_conflicting_scale_factors_is_not_scale_valid(self, events):
        root = GateNode(name="All Events")
        est_a = GateNode(
            gate=FixedGate(np.array([True] * 8 + [False] * 2)), name="UMAP Run A", parents=[root]
        )
        root.children.append(est_a)
        est_a.is_estimated = True
        est_a.scale_factor = 4.0
        est_b = GateNode(
            gate=FixedGate(np.array([True] * 7 + [False] * 3)), name="UMAP Run B", parents=[root]
        )
        root.children.append(est_b)
        est_b.is_estimated = True
        est_b.scale_factor = 2.0
        and_node = GateNode(
            name="AND", logic_operator="AND", parents=[est_a, est_b], is_logic_node=True
        )
        est_a.children.append(and_node)
        est_b.children.append(and_node)

        stats = DagEvaluator.evaluate(root, events)

        s = stats[and_node.node_id]
        assert s["is_estimated"] is True
        assert s["is_scale_valid"] is False
        assert "estimated_count" not in s

    def test_and_node_with_matching_scale_factors_from_two_estimated_parents_is_valid(self, events):
        root = GateNode(name="All Events")
        est_a = GateNode(
            gate=FixedGate(np.array([True] * 8 + [False] * 2)), name="UMAP Run A", parents=[root]
        )
        root.children.append(est_a)
        est_a.is_estimated = True
        est_a.scale_factor = 4.0
        est_b = GateNode(
            gate=FixedGate(np.array([True] * 7 + [False] * 3)), name="UMAP Run B", parents=[root]
        )
        root.children.append(est_b)
        est_b.is_estimated = True
        est_b.scale_factor = 4.0
        and_node = GateNode(
            name="AND", logic_operator="AND", parents=[est_a, est_b], is_logic_node=True
        )
        est_a.children.append(and_node)
        est_b.children.append(and_node)

        stats = DagEvaluator.evaluate(root, events)

        s = stats[and_node.node_id]
        assert s["count"] == 7  # AND of first-8-True & first-7-True
        assert s["is_estimated"] is True
        assert s["scale_factor"] == 4.0
        assert s["is_scale_valid"] is True
        assert s["estimated_count"] == 28

    def test_evaluate_scoped_uses_persisted_estimation_for_an_out_of_scope_parent(self, events):
        root = GateNode(name="All Events")
        est = GateNode(
            gate=FixedGate(np.array([True] * 8 + [False] * 2)), name="UMAP B Cells", parents=[root]
        )
        root.children.append(est)
        est.is_estimated = True
        est.scale_factor = 4.0
        exact = GateNode(
            gate=FixedGate(np.array([True] * 5 + [False] * 5)), name="B-cells", parents=[root]
        )
        root.children.append(exact)
        and_node = GateNode(
            name="AND", logic_operator="AND", parents=[est, exact], is_logic_node=True
        )
        est.children.append(and_node)
        exact.children.append(and_node)

        DagEvaluator.evaluate(root, events)  # baseline — persists est's stats onto est.statistics

        and_node.invalidate_mask_cache()
        stats = DagEvaluator.evaluate_scoped([and_node], events)

        s = stats[and_node.node_id]
        assert s["is_estimated"] is True
        assert s["is_scale_valid"] is True
        assert s["scale_factor"] == 4.0
