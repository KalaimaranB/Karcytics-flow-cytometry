"""Tests for the Statistics tab honoring a UMAP-exported node's estimation
correction (`node.statistics["is_estimated"/"is_scale_valid"/"estimated_count"
/"estimated_pct_total"]`, populated by DagEvaluator — see its own
`_propagate_estimation`). Only COUNT/%Total should read the corrected value;
%Parent/CV/etc. must always come from `compute_statistic`'s raw computation.
"""

from __future__ import annotations

import csv
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from karcytics_plugins.flow_cytometry.analysis.experiment import Sample
from karcytics_plugins.flow_cytometry.analysis.fcs_io import FCSData
from karcytics_plugins.flow_cytometry.analysis.gating.subset import SubsetGate
from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.analysis.statistics import StatType
from karcytics_plugins.flow_cytometry.ui.widgets.statistics_explorer import StatisticsExplorer


@pytest.fixture
def sample_with_estimated_node():
    sample = Sample(sample_id="s1", display_name="Sample 1")
    events = pd.DataFrame({"FSC-A": range(10), "FITC-A": [float(i) for i in range(10)]})
    sample.fcs_data = FCSData(
        file_path=Path("sample.fcs"), channels=["FSC-A", "FITC-A"], markers=["", ""], events=events
    )

    root = sample.gate_tree
    bcells = root.add_child(gate=SubsetGate(indices=list(range(5))), name="B-cells")

    umap_bcells = root.add_child(gate=SubsetGate(indices=list(range(3))), name="UMAP B Cells")
    # Bypass DagEvaluator (covered separately in test_dag_evaluator.py) and set
    # the estimation fields directly, to isolate what statistics_explorer.py
    # does with them.
    umap_bcells.statistics = {
        "count": 3,
        "pct_parent": 30.0,
        "pct_total": 30.0,
        "is_estimated": True,
        "scale_factor": 4.0,
        "is_scale_valid": True,
        "estimated_count": 12,
        "estimated_pct_total": 120.0,
    }

    return sample, bcells, umap_bcells


@pytest.fixture
def widget(qtbot, sample_with_estimated_node):
    sample, _bcells, _umap_bcells = sample_with_estimated_node
    state = FlowState()
    state.data.experiment.samples["s1"] = sample
    w = StatisticsExplorer(state)
    qtbot.addWidget(w)
    return w


@pytest.mark.ui
def test_estimated_populations_count_and_percent_total_use_the_corrected_value(
    widget, sample_with_estimated_node
):
    _sample, bcells, umap_bcells = sample_with_estimated_node
    rows = widget._compute_results(
        ["s1"],
        [("s1", bcells.node_id, "B-cells"), ("s1", umap_bcells.node_id, "UMAP B Cells")],
        [StatType.COUNT, StatType.PERCENT_TOTAL, StatType.CV],
        channel="FITC-A",
    )
    by_pop = {r["population"]: r for r in rows}

    # Manually-gated population: untouched, no ::scale key anywhere.
    manual_row = by_pop["B-cells"]
    assert manual_row["s1::count"] == "5"
    assert "s1::count::scale" not in manual_row
    assert "s1::percent_total::scale" not in manual_row

    # UMAP-exported, scale-valid population: COUNT/%Total use the corrected
    # value and carry the ::scale marker; CV does not.
    est_row = by_pop["UMAP B Cells"]
    assert est_row["s1::count"] == "12"
    assert est_row["s1::count::scale"] == 4.0
    assert est_row["s1::percent_total"] == "120.00%"
    assert est_row["s1::percent_total::scale"] == 4.0
    assert "s1::cv::scale" not in est_row


@pytest.mark.ui
def test_not_scale_valid_population_is_left_unscaled(widget, sample_with_estimated_node):
    _sample, bcells, umap_bcells = sample_with_estimated_node
    umap_bcells.statistics["is_scale_valid"] = False
    umap_bcells.statistics.pop("estimated_count", None)
    umap_bcells.statistics.pop("estimated_pct_total", None)

    rows = widget._compute_results(
        ["s1"],
        [("s1", umap_bcells.node_id, "UMAP B Cells")],
        [StatType.COUNT],
        channel=None,
    )

    row = rows[0]
    assert row["s1::count"] == "3"  # raw compute_statistic result, not corrected
    assert "s1::count::scale" not in row


@pytest.mark.ui
def test_table_marks_estimated_cells_with_asterisk_and_tooltip(widget, sample_with_estimated_node):
    _sample, bcells, umap_bcells = sample_with_estimated_node
    pop_pairs = [("s1", bcells.node_id, "B-cells"), ("s1", umap_bcells.node_id, "UMAP B Cells")]
    stats = [StatType.COUNT]
    widget._last_results = widget._compute_results(["s1"], pop_pairs, stats, channel=None)

    widget._populate_table(["s1"], pop_pairs, stats, channel=None)

    # Column 0 = Population, column 1 = separator, column 2 = s1::count.
    manual_cell = widget._table.item(0, 2)
    est_cell = widget._table.item(1, 2)
    assert manual_cell.text() == "5"
    assert manual_cell.toolTip() == ""
    assert est_cell.text() == "12*"
    assert "25%" in est_cell.toolTip()  # 1 / scale_factor(4.0) = 25% subsample
    # isVisible() requires a shown top-level window (not the case in an
    # offscreen test); isHidden() reflects the explicit setVisible() call.
    assert not widget._estimated_caption.isHidden()


@pytest.mark.ui
def test_csv_export_does_not_crash_on_mixed_scale_keys(
    widget, sample_with_estimated_node, tmp_path
):
    """Regression test: row 0 (B-cells) has no `::scale` keys, row 1 (UMAP
    B Cells) does — csv.DictWriter derived fieldnames from row 0 alone and
    raised ValueError the moment it hit row 1's extra key. See _on_export.
    """
    _sample, bcells, umap_bcells = sample_with_estimated_node
    pop_pairs = [("s1", bcells.node_id, "B-cells"), ("s1", umap_bcells.node_id, "UMAP B Cells")]
    widget._last_results = widget._compute_results(
        ["s1"], pop_pairs, [StatType.COUNT, StatType.PERCENT_TOTAL], channel=None
    )

    out_path = tmp_path / "export.csv"
    with patch(
        "karcytics_plugins.flow_cytometry.ui.widgets.statistics_explorer.QFileDialog.getSaveFileName",
        return_value=(str(out_path), "CSV Files (*.csv)"),
    ):
        widget._on_export()

    with out_path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    assert not any(k.endswith("::scale") for row in rows for k in row)
    by_pop = {row["population"]: row for row in rows}
    assert by_pop["B-cells"]["s1::count"] == "5"
    assert by_pop["UMAP B Cells"]["s1::count"] == "12*"
    assert by_pop["UMAP B Cells"]["s1::percent_total"] == "120.00%*"


@pytest.mark.ui
def test_csv_export_reports_a_diagnostic_instead_of_crashing_on_unexpected_failure(
    widget, sample_with_estimated_node, tmp_path
):
    """Defense in depth for whatever the *next* unanticipated row shape is:
    any failure inside _on_export must surface as a non-fatal diagnostic
    report (and a status-label message) rather than an unhandled exception
    escaping the button's clicked handler.
    """
    _sample, bcells, _umap_bcells = sample_with_estimated_node
    widget._last_results = widget._compute_results(
        ["s1"], [("s1", bcells.node_id, "B-cells")], [StatType.COUNT], channel=None
    )

    out_path = tmp_path / "export.csv"
    with (
        patch(
            "karcytics_plugins.flow_cytometry.ui.widgets.statistics_explorer.QFileDialog.getSaveFileName",
            return_value=(str(out_path), "CSV Files (*.csv)"),
        ),
        patch(
            "karcytics_plugins.flow_cytometry.ui.widgets.statistics_explorer.csv.DictWriter",
            side_effect=RuntimeError("boom"),
        ),
        patch("karcytics_sdk.plugin.runtime_services.diagnostics.report_error") as report_error,
    ):
        widget._on_export()  # must not raise

    assert report_error.call_count == 1
    _args, kwargs = report_error.call_args
    assert isinstance(kwargs.get("exception"), RuntimeError)
    assert kwargs.get("fatal") is False
    assert "Export failed" in widget._status_lbl.text()
