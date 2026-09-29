"""Tests for how the pipeline canvas (`NodeItem` via `CanvasManager
._apply_stats_to_item`) and the properties panel (`PropertiesPanel
._add_estimation_rows`) surface a node's UMAP-subsample estimation
correction — the same `node.statistics` fields DagEvaluator computes
(see test_dag_evaluator.py::TestEstimationPropagation) and
statistics_explorer.py already consumes for the table (see
test_statistics_explorer_estimated_cells.py). All three views must agree.
"""

from __future__ import annotations

import pytest

from karcytics_plugins.flow_cytometry.ui.widgets.node_canvas.canvas_manager import CanvasManager
from karcytics_plugins.flow_cytometry.ui.widgets.node_canvas.items.node_item import NodeItem
from karcytics_plugins.flow_cytometry.ui.widgets.properties_panel import PropertiesPanel

# ── Canvas: CanvasManager._apply_stats_to_item ──────────────────────────────


@pytest.mark.ui
def test_scale_valid_node_shows_corrected_count_and_estimate_tooltip(qtbot):
    item = NodeItem("n1", "UMAP B Cells")
    statistics = {
        "count": 3,
        "is_estimated": True,
        "scale_factor": 4.0,
        "is_scale_valid": True,
        "estimated_count": 12,
    }

    CanvasManager._apply_stats_to_item(item, statistics)

    assert item.event_count == 12  # corrected, not the raw 3
    assert item.is_estimated is True
    assert item.is_scale_valid is True
    assert "Estimated" in item.toolTip()
    assert "×4.00" in item.toolTip()


@pytest.mark.ui
def test_not_scale_valid_node_keeps_raw_count_and_warns_it_cannot_be_corrected(qtbot):
    item = NodeItem("n2", "AND")
    statistics = {"count": 7, "is_estimated": True, "scale_factor": 1.0, "is_scale_valid": False}

    CanvasManager._apply_stats_to_item(item, statistics)

    assert item.event_count == 7  # raw — no estimated_count to prefer
    assert item.is_estimated is True
    assert item.is_scale_valid is False
    assert "can't be safely corrected" in item.toolTip()


@pytest.mark.ui
def test_non_estimated_node_has_no_tooltip(qtbot):
    item = NodeItem("n3", "B-cells")
    item.setToolTip("stale")  # simulate a previous estimated state

    CanvasManager._apply_stats_to_item(item, {"count": 5})

    assert item.event_count == 5
    assert item.is_estimated is False
    assert item.toolTip() == ""


# ── Properties panel: PropertiesPanel._add_estimation_rows ──────────────────


def _capture_rows():
    calls: list[tuple] = []

    def add_row(*args, **kwargs):
        calls.append((args, kwargs))

    return calls, add_row


def test_scale_valid_estimation_adds_corrected_rows():
    calls, add_row = _capture_rows()
    statistics = {
        "is_estimated": True,
        "is_scale_valid": True,
        "scale_factor": 4.0,
        "estimated_count": 12,
        "estimated_pct_total": 120.0,
    }

    PropertiesPanel._add_estimation_rows(add_row, statistics, count=3, pct_total=30.0)

    labels = [c[0][0] for c in calls]
    assert "Estimated Count:" in labels
    assert "Estimated % Total:" in labels
    assert any(label == "⚠ Estimate:" for label in labels)


def test_not_scale_valid_estimation_adds_only_the_warning_row():
    calls, add_row = _capture_rows()
    statistics = {"is_estimated": True, "is_scale_valid": False}

    PropertiesPanel._add_estimation_rows(add_row, statistics, count=7, pct_total=70.0)

    assert len(calls) == 1
    label, message = calls[0][0]
    assert label == "⚠ Estimate:"
    assert "can't be safely corrected" in message


def test_non_estimated_statistics_add_no_rows():
    calls, add_row = _capture_rows()

    PropertiesPanel._add_estimation_rows(add_row, {}, count=5, pct_total=50.0)

    assert calls == []
