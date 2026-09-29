"""Tests for `GateNode`'s per-events mask memoization.

`_get_mask`/`apply_hierarchy` used to recompute the full ancestor chain
from raw events on every single call, with call sites in nearly every UI
refresh path (render, canvas, statistics, comparisons, population/UMAP
views) — so the same unchanged tree gets walked from scratch on every
repaint. The fix: cache each node's resolved mask keyed on the *identity*
of the `events` DataFrame passed in (stable between mutations — reloads
and compensation both replace the DataFrame object rather than mutating
it in place, so a changed dataset is a natural cache miss). Correctness
depends entirely on invalidation firing at every point the gate tree can
change; those call sites are covered separately in
`test_gate_mutation_invalidates_mask_cache.py`-style tests colocated with
the mutation services.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from karcytics_plugins.flow_cytometry.analysis.gating.base import Gate
from karcytics_plugins.flow_cytometry.analysis.gating.gate_node import GateNode


class CountingGate(Gate):
    """A gate whose `.contains()` result can be swapped mid-test (simulating
    a gate edit) while counting how many times it was actually evaluated.
    """

    def __init__(self, mask: np.ndarray) -> None:
        super().__init__(x_param="FSC-A", y_param="SSC-A")
        self.mask = mask
        self.call_count = 0

    def copy(self) -> CountingGate:
        return CountingGate(self.mask.copy())

    def contains(self, _events: pd.DataFrame) -> np.ndarray:
        self.call_count += 1
        return self.mask.copy()


@pytest.fixture
def events():
    return pd.DataFrame({"FSC-A": np.arange(10.0), "SSC-A": np.arange(10.0)})


def test_repeated_calls_with_same_events_reuse_the_cached_mask(events):
    gate = CountingGate(np.array([True] * 5 + [False] * 5))
    root = GateNode(name="All Events")
    node = GateNode(gate=gate, name="Gate A", parents=[root])
    root.children.append(node)

    node.apply_hierarchy(events)
    node.apply_hierarchy(events)
    node.apply_hierarchy(events)

    assert gate.call_count == 1


def test_a_new_events_object_is_a_cache_miss(events):
    gate = CountingGate(np.array([True] * 5 + [False] * 5))
    root = GateNode(name="All Events")
    node = GateNode(gate=gate, name="Gate A", parents=[root])
    root.children.append(node)

    node.apply_hierarchy(events)
    other_events = events.copy()  # a distinct object, e.g. after reload/compensation
    node.apply_hierarchy(other_events)

    assert gate.call_count == 2


def test_invalidate_mask_cache_forces_recompute_on_next_call(events):
    gate = CountingGate(np.array([True] * 5 + [False] * 5))
    root = GateNode(name="All Events")
    node = GateNode(gate=gate, name="Gate A", parents=[root])
    root.children.append(node)

    first = node.apply_hierarchy(events)
    assert len(first) == 5

    # Simulate a gate edit that widens the threshold.
    gate.mask = np.array([True] * 8 + [False] * 2)
    node.invalidate_mask_cache()

    second = node.apply_hierarchy(events)
    assert len(second) == 8
    assert gate.call_count == 2


def test_invalidate_mask_cache_propagates_to_descendants(events):
    gate_a = CountingGate(np.array([True] * 10))
    gate_b = CountingGate(np.array([True] * 5 + [False] * 5))
    root = GateNode(name="All Events")
    node_a = GateNode(gate=gate_a, name="Gate A", parents=[root])
    root.children.append(node_a)
    node_b = GateNode(gate=gate_b, name="Gate B", parents=[node_a])
    node_a.children.append(node_b)

    node_b.apply_hierarchy(events)
    assert gate_a.call_count == 1
    assert gate_b.call_count == 1

    # Invalidating the ancestor must also invalidate the already-cached
    # descendant mask, since node_b's mask was combined from node_a's.
    gate_a.mask = np.array([True] * 3 + [False] * 7)
    node_a.invalidate_mask_cache()

    node_b.apply_hierarchy(events)
    assert gate_a.call_count == 2
    assert gate_b.call_count == 2


def test_shared_ancestor_is_evaluated_once_across_a_diamond_dag(events):
    """A logic node with two parents that share a common ancestor gate
    should not re-evaluate that ancestor once per branch.
    """
    shared_gate = CountingGate(np.array([True] * 10))
    gate_a = CountingGate(np.array([True] * 8 + [False] * 2))
    gate_b = CountingGate(np.array([True] * 2 + [False] * 8))

    root = GateNode(name="All Events")
    shared = GateNode(gate=shared_gate, name="Shared", parents=[root])
    root.children.append(shared)
    node_a = GateNode(gate=gate_a, name="Gate A", parents=[shared])
    shared.children.append(node_a)
    node_b = GateNode(gate=gate_b, name="Gate B", parents=[shared])
    shared.children.append(node_b)
    node_or = GateNode(name="OR Node", logic_operator="OR", parents=[node_a, node_b])
    node_a.children.append(node_or)
    node_b.children.append(node_or)

    node_or.apply_hierarchy(events)

    assert shared_gate.call_count == 1
    assert gate_a.call_count == 1
    assert gate_b.call_count == 1


def test_mask_values_are_unaffected_by_caching(events):
    """The cache must be transparent — same inputs, same output as an
    uncached call would produce.
    """
    gate = CountingGate(np.array([True, False] * 5))
    root = GateNode(name="All Events")
    node = GateNode(gate=gate, name="Gate A", parents=[root])
    root.children.append(node)

    result = node.apply_hierarchy(events)
    expected_indices = events.index[np.array([True, False] * 5)]
    assert list(result.index) == list(expected_indices)
