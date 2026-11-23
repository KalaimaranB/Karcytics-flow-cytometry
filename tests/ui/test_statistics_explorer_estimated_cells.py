"""The Statistics tab's widgets: Compute, the table's estimate marks, copy, CSV and the chart.

What the cells hold (estimates, dashes, failures) is tested in
tests/unit/analysis/test_statistics_table.py.
"""

from __future__ import annotations

import csv
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest
from PySide6.QtWidgets import QApplication

from karcytics_plugins.flow_cytometry.analysis.experiment import Sample
from karcytics_plugins.flow_cytometry.analysis.fcs_io import FCSData
from karcytics_plugins.flow_cytometry.analysis.gating.subset import SubsetGate
from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.analysis.statistics import StatType
from karcytics_plugins.flow_cytometry.analysis.statistics_table import (
    PopulationPick,
    StatisticsRequest,
    compute_table,
)
from karcytics_plugins.flow_cytometry.ui.widgets import statistics_explorer as explorer_module
from karcytics_plugins.flow_cytometry.ui.widgets.copyable import CopyableCanvas
from karcytics_plugins.flow_cytometry.ui.widgets.statistics_explorer import StatisticsExplorer


@pytest.fixture
def state():
    sample = Sample(sample_id="s1", display_name="Sample 1")
    events = pd.DataFrame({"FSC-A": range(10), "FITC-A": [float(i) for i in range(10)]})
    sample.fcs_data = FCSData(
        file_path=Path("sample.fcs"), channels=["FSC-A", "FITC-A"], markers=["", ""], events=events
    )
    root = sample.gate_tree
    root.add_child(gate=SubsetGate(indices=list(range(5))), name="B-cells")
    exported = root.add_child(gate=SubsetGate(indices=list(range(3))), name="UMAP B Cells")
    exported.statistics = {
        "count": 3,
        "is_estimated": True,
        "scale_factor": 4.0,
        "is_scale_valid": True,
        "estimated_count": 12,
        "estimated_pct_total": 120.0,
    }
    state = FlowState()
    state.data.experiment.samples["s1"] = sample
    return state


@pytest.fixture
def widget(qtbot, state):
    w = StatisticsExplorer(state)
    qtbot.addWidget(w)
    return w


def _show(widget, stats=(StatType.COUNT,)):
    """Compute the table for both populations and show it."""
    root = widget._state.data.experiment.samples["s1"].gate_tree
    picks = tuple(PopulationPick("s1", c.node_id, c.name) for c in root.children)
    table = compute_table(
        widget._state.data.experiment, StatisticsRequest(("s1",), picks, tuple(stats), None)
    )
    widget.show_table(table)
    return table


@pytest.mark.ui
def test_compute_runs_in_the_background_and_shows_the_table(widget, qtbot):
    widget._stat_picker.set_selected([StatType.COUNT])

    widget._compute_btn.click()

    qtbot.waitUntil(lambda: widget._table is not None, timeout=5000)
    assert widget._table_view.rowCount() >= 2
    assert widget._export_btn.isEnabled()
    assert widget._compute_btn.isVisibleTo(widget)


@pytest.mark.ui
def test_estimated_cells_carry_a_star_a_tooltip_and_a_caption(widget):
    _show(widget)

    # Column 0 = Population, column 1 = Sample 1's separator, column 2 = its Count.
    manual, estimated = widget._table_view.item(0, 2), widget._table_view.item(1, 2)
    assert (manual.text(), manual.toolTip()) == ("5", "")
    assert estimated.text() == "12*"
    assert "25%" in estimated.toolTip()  # 1 / scale factor 4
    assert not widget._estimated_caption.isHidden()


@pytest.mark.ui
def test_copy_selected_rows_puts_tab_separated_lines_on_the_clipboard(widget):
    _show(widget)
    widget._table_view.selectRow(1)

    widget._table_view._copy_selected()

    lines = QApplication.clipboard().text().split("\n")
    assert len(lines) == 2
    assert lines[0].split("\t") == ["Population", "", "Sample 1 Count"]
    assert lines[1].split("\t") == ["UMAP B Cells", "", "12*"]


@pytest.mark.ui
def test_csv_export_writes_the_table(widget, tmp_path):
    _show(widget, (StatType.COUNT, StatType.PERCENT_TOTAL))
    path = tmp_path / "export.csv"

    with patch.object(explorer_module, "get_save_path", return_value=str(path)):
        widget._export_btn.click()

    with path.open(newline="", encoding="utf-8") as f:
        by_pop = {row["population"]: row for row in csv.DictReader(f)}
    assert by_pop["UMAP B Cells"]["s1::percent_total"] == "120.00%*"
    assert widget.completed_exports == {"csv"}


@pytest.mark.ui
def test_a_failed_csv_export_reports_a_diagnostic_instead_of_crashing(widget, tmp_path):
    _show(widget)
    with (
        patch.object(explorer_module, "get_save_path", return_value=str(tmp_path / "x.csv")),
        patch.object(explorer_module, "write_csv", side_effect=RuntimeError("boom")),
        patch("karcytics_sdk.plugin.runtime_services.diagnostics.report_error") as report_error,
    ):
        widget._export_btn.click()  # must not raise

    _args, kwargs = report_error.call_args
    assert isinstance(kwargs["exception"], RuntimeError)
    assert kwargs["fatal"] is False
    assert "Export failed" in widget._status_lbl.text()
    assert widget.completed_exports == set()


@pytest.mark.ui
@pytest.mark.parametrize("chart_type", ["Grouped Bar", "Horizontal Bar", "Heatmap"])
def test_the_chart_renders_in_the_background(widget, qtbot, chart_type):
    _show(widget)
    widget._chart_type_combo.setCurrentText(chart_type)

    widget._view_buttons.button(2).click()  # Chart

    qtbot.waitUntil(lambda: widget._chart_page.findChild(CopyableCanvas) is not None, timeout=5000)
    assert widget._figure is not None
    assert widget._figure.axes[0].get_title() == "Count by Population"
