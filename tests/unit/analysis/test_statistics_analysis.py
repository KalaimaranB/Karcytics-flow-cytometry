"""Tests for `StatisticsAnalysis`, now a thin wrapper around the shared
`DagEvaluator.evaluate` walk (Priority 1 analysis #2 — this used to be its
own independent recursive tree-walker, `_walk_and_compute`, duplicating the
same AND/OR/NOT/gate-mask logic `DagEvaluator` and `GateNode._get_mask`
each implemented separately).

The one behavior worth testing in its own right (rather than relying on
`DagEvaluator`'s own suite) is that a gate-evaluation failure still emits
the Qt `analysis_error` signal exactly as the old walker did — that's the
part that would otherwise regress silently.
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd
import pytest
from PyQt6.QtWidgets import QApplication

from karcytics_plugins.flow_cytometry.analysis.gating.base import Gate
from karcytics_plugins.flow_cytometry.analysis.gating.gate_node import GateNode
from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.analysis.statistics_analysis import StatisticsAnalysis

app = QApplication.instance() or QApplication(sys.argv)


class MockFcsData:
    def __init__(self, events: pd.DataFrame) -> None:
        self.events = events


class FixedGate(Gate):
    def __init__(self, mask: np.ndarray | None = None, raises: Exception | None = None) -> None:
        super().__init__(x_param="FSC-A", y_param="SSC-A")
        self.mask = mask
        self.raises = raises

    def copy(self) -> FixedGate:
        return FixedGate(self.mask, self.raises)

    def contains(self, events: pd.DataFrame) -> np.ndarray:
        if self.raises is not None:
            raise self.raises
        assert self.mask is not None
        return self.mask[: len(events)]


@pytest.fixture
def state_with_sample():
    from karcytics_plugins.flow_cytometry.analysis.experiment import Sample

    state = FlowState()
    sample = Sample(sample_id="s1", display_name="S1")
    events = pd.DataFrame({"FSC-A": np.arange(10.0), "SSC-A": np.arange(10.0)})
    sample.fcs_data = MockFcsData(events)
    state.data.experiment.samples["s1"] = sample
    return state, sample


def test_run_computes_stats_for_every_node(state_with_sample):
    state, sample = state_with_sample
    node = GateNode(
        gate=FixedGate(np.array([True] * 6 + [False] * 4)), name="A", parents=[sample.gate_tree]
    )
    sample.gate_tree.children.append(node)

    analyzer = StatisticsAnalysis()
    analyzer.target_sample_id = "s1"
    results = analyzer.run(state)

    stats = results["stats"]
    assert stats[sample.gate_tree.node_id]["count"] == 10
    assert stats[node.node_id]["count"] == 6


def test_run_emits_analysis_error_when_a_gate_fails(state_with_sample):
    """`AnalysisBase.signals` is a `MagicMock` under this repo's global
    `karcytics_sdk` test mock (see `tests/conftest.py::DummyAnalysisBase`),
    not a real Qt signal — a connected slot never actually fires here, so
    the emission itself is asserted via the mock's own call record instead.
    """
    state, sample = state_with_sample
    node = GateNode(
        gate=FixedGate(raises=ValueError("boom")), name="Bad", parents=[sample.gate_tree]
    )
    sample.gate_tree.children.append(node)

    analyzer = StatisticsAnalysis()
    analyzer.target_sample_id = "s1"

    results = analyzer.run(state)

    analyzer.signals.analysis_error.emit.assert_called_once()
    (message,), _ = analyzer.signals.analysis_error.emit.call_args
    assert "Bad" in message
    # The failed node itself is still reported as zero, matching the old
    # walker — but this is checked as a subset since `stats_out` also
    # includes the root.
    assert results["stats"][node.node_id]["count"] == 0
