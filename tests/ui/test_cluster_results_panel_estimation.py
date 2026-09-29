"""Tests for `ClusterResultsPanel._create_populations`' scale_factor/is_estimated
origin fields — a UMAP-exported population's correction factor for being
built from a random subsample of its parent (see DagEvaluator's own
`_propagate_estimation` for how this flows downstream through the tree).
"""

from __future__ import annotations

import numpy as np
import pytest
from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtWidgets import QMessageBox

from karcytics_plugins.flow_cytometry.analysis.experiment import Sample
from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.ui.widgets import cluster_results_panel as panel_module
from karcytics_plugins.flow_cytometry.ui.widgets.cluster_results_panel import ClusterResultsPanel


class _FakeGlobalScheduler(QObject):
    """Minimal stand-in so `ClusterResultsPanel.__init__` (which connects to
    the module-level `task_scheduler` singleton unconditionally) doesn't
    touch the real scheduler — same shape as
    `test_cluster_results_panel_gallery.py`'s own fixture.
    """

    task_finished = pyqtSignal(str, dict)
    task_error = pyqtSignal(str, str)

    def submit(self, analyzer, state=None):
        QTimer.singleShot(0, lambda: None)
        worker = QObject()
        worker.task_id = "0"  # type: ignore[attr-defined]
        return worker


@pytest.fixture
def fake_scheduler(monkeypatch):
    scheduler = _FakeGlobalScheduler()
    monkeypatch.setattr(panel_module, "task_scheduler", scheduler)
    return scheduler


@pytest.fixture(autouse=True)
def _no_modal_dialogs(monkeypatch):
    # `_create_populations` ends with a `show_info(...)` call that pops a real
    # `QMessageBox.information` — patching `show_info` itself didn't stick
    # (it's imported locally inside the method from the SDK package), so
    # intercept at the one place that's guaranteed to be the actual call:
    # the Qt widget method itself.
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))


@pytest.fixture
def flow_state():
    state = FlowState()
    sample = Sample(sample_id="s1", display_name="Sample 1")
    state.data.experiment.samples["s1"] = sample
    return state


def _umap_results(*, n_events: int, parent_total_events: int):
    import pandas as pd

    rng = np.random.default_rng(0)
    clusters = np.zeros(n_events, dtype=int)
    # Same shape ClusterResultsPanel expects for the "Export Populations"
    # checkbox list — see UmapAnalysis.run's own `cluster_stats` construction.
    stats_df = pd.DataFrame({"Cluster ID": [0], "Cell Count": [n_events], "% of Total": [100.0]})
    return {
        "embedding": rng.normal(size=(n_events, 2)),
        "intensities": rng.normal(size=(n_events, 2)),
        "channels": ["CH0", "CH1"],
        "clusters": clusters,
        "cluster_stats": stats_df.to_dict(orient="split"),
        "indices": np.arange(n_events),
        "sample_id": "s1",
        "node_id": None,  # target the sample's root
        "n_events": n_events,
        "parent_total_events": parent_total_events,
    }


@pytest.mark.ui
def test_subsampled_run_marks_exported_populations_as_estimated(fake_scheduler, qtbot, flow_state):
    """8 of 10 parent events were subsampled — scale_factor should be 10/8."""
    results = _umap_results(n_events=8, parent_total_events=10)
    panel = ClusterResultsPanel(results, state=flow_state)
    qtbot.addWidget(panel)

    panel._create_populations()

    sample = flow_state.data.experiment.samples["s1"]
    umap_parent = next(c for c in sample.gate_tree.children if c.name == "UMAP Reduction")
    cluster_node = umap_parent.children[0]

    assert cluster_node.is_estimated is True
    assert cluster_node.scale_factor == pytest.approx(10 / 8)
    # The container itself is not a reported population — left untouched.
    assert umap_parent.is_estimated is False
    assert umap_parent.scale_factor == 1.0


@pytest.mark.ui
def test_non_subsampled_run_does_not_mark_populations_as_estimated(
    fake_scheduler, qtbot, flow_state
):
    """n_events == parent_total_events — nothing was actually subsampled."""
    results = _umap_results(n_events=10, parent_total_events=10)
    panel = ClusterResultsPanel(results, state=flow_state)
    qtbot.addWidget(panel)

    panel._create_populations()

    sample = flow_state.data.experiment.samples["s1"]
    umap_parent = next(c for c in sample.gate_tree.children if c.name == "UMAP Reduction")
    cluster_node = umap_parent.children[0]

    assert cluster_node.is_estimated is False
    assert cluster_node.scale_factor == 1.0
