"""The Statistics tab's table: cells, estimates, chart values and CSV export.

A population exported from a subsampled clustering run carries dag_evaluator's
estimation correction in ``node.statistics``; only its Count and % Total read
the corrected value.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd
import pytest

from karcytics_plugins.flow_cytometry.analysis.experiment import Sample
from karcytics_plugins.flow_cytometry.analysis.fcs_io import FCSData
from karcytics_plugins.flow_cytometry.analysis.gating.subset import SubsetGate
from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.analysis.statistics import StatType, format_statistic
from karcytics_plugins.flow_cytometry.analysis.statistics_table import (
    PopulationPick,
    StatisticsRequest,
    compute_table,
    write_csv,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def experiment():
    sample = Sample(sample_id="s1", display_name="Sample 1")
    events = pd.DataFrame({"FSC-A": range(10), "FITC-A": [float(i) for i in range(10)]})
    sample.fcs_data = FCSData(
        file_path=Path("sample.fcs"), channels=["FSC-A", "FITC-A"], markers=["", ""], events=events
    )
    root = sample.gate_tree
    root.add_child(gate=SubsetGate(indices=list(range(5))), name="B-cells")
    exported = root.add_child(gate=SubsetGate(indices=list(range(3))), name="UMAP B Cells")
    # Set as dag_evaluator would (covered in test_dag_evaluator.py).
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
    state.data.experiment.samples["s2"] = Sample(sample_id="s2", display_name="Sample 2")
    return state.data.experiment


def _node_id(experiment, name: str) -> str:
    root = experiment.samples["s1"].gate_tree
    return next(c.node_id for c in root.children if c.name == name)


def _request(experiment, stats, names=("B-cells", "UMAP B Cells"), samples=("s1",), channel=None):
    picks = tuple(PopulationPick("s1", _node_id(experiment, n), n) for n in names)
    return StatisticsRequest(tuple(samples), picks, tuple(stats), channel)


def test_estimated_count_and_percent_total_use_the_corrected_value(experiment):
    stats = (StatType.COUNT, StatType.PERCENT_TOTAL, StatType.CV)
    table = compute_table(experiment, _request(experiment, stats, channel="FITC-A"))
    manual, exported = table.rows

    assert manual.cell("s1", StatType.COUNT).shown == "5"
    assert not any(cell.scale for cell in manual.cells.values())
    assert exported.cell("s1", StatType.COUNT).shown == "12*"
    assert exported.cell("s1", StatType.COUNT).scale == 4.0
    assert exported.cell("s1", StatType.PERCENT_TOTAL).shown == "120.00%*"
    assert exported.cell("s1", StatType.CV).scale is None  # computed from its own events
    assert table.has_estimates


def test_a_population_not_scale_valid_is_left_unscaled(experiment):
    exported = experiment.samples["s1"].gate_tree.find_node_by_id(
        _node_id(experiment, "UMAP B Cells")
    )
    exported.statistics["is_scale_valid"] = False

    table = compute_table(experiment, _request(experiment, [StatType.COUNT], ["UMAP B Cells"]))

    cell = table.rows[0].cell("s1", StatType.COUNT)
    assert (cell.shown, cell.scale) == ("3", None)


def test_a_sample_without_the_population_shows_a_dash(experiment):
    table = compute_table(
        experiment, _request(experiment, [StatType.COUNT], ["B-cells"], samples=("s1", "s2"))
    )

    assert table.sample_names == ("Sample 1", "Sample 2")
    assert table.rows[0].cell("s2", StatType.COUNT).shown == "—"


def test_a_channel_statistic_without_its_channel_fails_alone(experiment):
    table = compute_table(experiment, _request(experiment, [StatType.COUNT, StatType.MEAN]))
    row = table.rows[0]
    assert row.cell("s1", StatType.MEAN).shown == "Err"
    assert row.cell("s1", StatType.COUNT).shown == "5"


def test_chart_values_are_the_numbers_behind_the_cells(experiment):
    table = compute_table(experiment, _request(experiment, [StatType.COUNT], samples=("s1", "s2")))

    values, estimated = table.values(StatType.COUNT)

    assert values.tolist() == [[5.0, 0.0], [12.0, 0.0]]
    assert estimated.tolist() == [[False, False], [True, False]]


def test_csv_marks_estimates_and_has_one_column_per_sample_statistic(experiment, tmp_path):
    table = compute_table(
        experiment, _request(experiment, [StatType.COUNT, StatType.PERCENT_TOTAL])
    )
    path = tmp_path / "stats.csv"

    write_csv(path, table)

    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    assert reader.fieldnames == ["population", "s1::count", "s1::percent_total"]
    by_pop = {row["population"]: row for row in rows}
    assert by_pop["B-cells"]["s1::count"] == "5"
    assert by_pop["UMAP B Cells"]["s1::count"] == "12*"
    assert by_pop["UMAP B Cells"]["s1::percent_total"] == "120.00%*"


def test_statistic_labels_formats_and_channel_needs():
    assert StatType.PERCENT_PARENT.label == "Percent Parent"
    assert StatType.MFI.label == "MFI"
    assert not StatType.PERCENT_TOTAL.needs_channel
    assert StatType.MFI.needs_channel
    assert format_statistic(StatType.COUNT, 1234.0) == "1,234"
    assert format_statistic(StatType.CV, 12.5) == "12.50%"
    assert format_statistic(StatType.MEAN, 3.14159) == "3.14"
