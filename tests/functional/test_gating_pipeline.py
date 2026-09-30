"""Golden-value tests for the real gating pipeline on real FCS files.

One realistic gate tree (rectangle -> range -> quadrant, plus an AND logic
node) is evaluated through the same code paths the app uses —
`DagEvaluator.evaluate`, `GateNode.apply_hierarchy`, and
`PopulationService.get_gated_events` — on the Specimen_001 files in
`tests/data/fcs/` (loaded via `load_fcs`, so embedded spill compensation is
applied exactly as it is for a user).

The golden counts pin the end-to-end result: an unintended change anywhere
in loading, compensation, gate math, or the DAG walk shows up here as a
count diff. If a change *intentionally* moves them, re-derive and update
the table — don't loosen the assertions into ranges.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from karcytics_plugins.flow_cytometry.analysis.compute.dag_evaluator import DagEvaluator
from karcytics_plugins.flow_cytometry.analysis.experiment import Sample
from karcytics_plugins.flow_cytometry.analysis.fcs_io import FCSData, load_fcs
from karcytics_plugins.flow_cytometry.analysis.gating import (
    QuadrantGate,
    RangeGate,
    RectangleGate,
)
from karcytics_plugins.flow_cytometry.analysis.gating.gate_node import GateNode
from karcytics_plugins.flow_cytometry.analysis.population_service import PopulationService
from karcytics_plugins.flow_cytometry.analysis.state import FlowState

pytestmark = pytest.mark.functional

GOLDEN_COUNTS = {
    "Sample A": {
        "All Events": 302017,
        "Cells": 293773,
        "APC+": 287074,
        "Q1": 174511,
        "Q2": 46047,
        "Q3": 53037,
        "Q4": 13479,
        "FITC+": 61053,
        "PE+": 221394,
        "FITC+ AND PE+": 46178,
    },
    "Sample C": {
        "All Events": 319359,
        "Cells": 275770,
        "APC+": 257226,
        "Q1": 8044,
        "Q2": 28074,
        "Q3": 18226,
        "Q4": 202882,
        "FITC+": 242122,
        "PE+": 36291,
        "FITC+ AND PE+": 28232,
    },
    "Blank": {
        "All Events": 306425,
        "Cells": 225769,
        "APC+": 2,
        "Q1": 0,
        "Q2": 0,
        "Q3": 0,
        "Q4": 2,
        "FITC+": 47952,
        "PE+": 3,
        "FITC+ AND PE+": 3,
    },
}

# Gate bounds, shared by the tree builder and the independent numpy oracle.
CELLS = {"x_min": 30_000, "x_max": 200_000, "y_min": 1_000, "y_max": 15_000}
APC_LOW = 10_000
FITC_MID = 500
PE_MID = 5_000
UPPER = 262_144


@pytest.fixture(scope="module")
def events_by_sample(fcs_test_data_dir) -> dict[str, pd.DataFrame]:
    return {
        name: load_fcs(str(fcs_test_data_dir / f"Specimen_001_{name}.fcs")).events
        for name in GOLDEN_COUNTS
    }


def _build_tree() -> GateNode:
    root = GateNode(name="All Events")
    cells = root.add_child(RectangleGate("FSC-A", "SSC-A", **CELLS), name="Cells")
    apc = cells.add_child(RangeGate("APC-A", low=APC_LOW, high=UPPER), name="APC+")
    QuadrantGate("FITC-A", "PE-A", x_mid=FITC_MID, y_mid=PE_MID).create_nodes(apc)
    fitc = cells.add_child(RangeGate("FITC-A", low=FITC_MID, high=UPPER), name="FITC+")
    pe = cells.add_child(RangeGate("PE-A", low=PE_MID, high=UPPER), name="PE+")
    both = GateNode(
        name="FITC+ AND PE+", logic_operator="AND", parents=[fitc, pe], is_logic_node=True
    )
    fitc.children.append(both)
    pe.children.append(both)
    return root


def _counts_by_name(root: GateNode, events: pd.DataFrame) -> dict[str, int]:
    stats = DagEvaluator.evaluate(root, events)
    return {node.name: stats[node.node_id]["count"] for node in root.iter_dag()}


def _fcs_data(events: pd.DataFrame) -> FCSData:
    channels = list(events.columns)
    return FCSData(
        file_path=Path("sample.fcs"), channels=channels, markers=[""] * len(channels), events=events
    )


def _node(root: GateNode, name: str) -> GateNode:
    return next(n for n in root.iter_dag() if n.name == name)


@pytest.mark.parametrize("sample_name", list(GOLDEN_COUNTS))
def test_tree_produces_golden_counts(events_by_sample, sample_name):
    counts = _counts_by_name(_build_tree(), events_by_sample[sample_name])

    assert counts == GOLDEN_COUNTS[sample_name]


def test_counts_match_an_independent_numpy_oracle(events_by_sample):
    """Recompute every population straight from the raw columns, with no
    plugin gating code involved, so the golden table isn't just the
    pipeline agreeing with itself.
    """
    ev = events_by_sample["Sample A"]
    fsc, ssc = ev["FSC-A"].to_numpy(), ev["SSC-A"].to_numpy()
    fitc, pe, apc = ev["FITC-A"].to_numpy(), ev["PE-A"].to_numpy(), ev["APC-A"].to_numpy()

    cells = (
        (fsc >= CELLS["x_min"])
        & (fsc <= CELLS["x_max"])
        & (ssc >= CELLS["y_min"])
        & (ssc <= CELLS["y_max"])
    )
    apc_pos = cells & (apc >= APC_LOW) & (apc <= UPPER)
    fitc_pos = cells & (fitc >= FITC_MID) & (fitc <= UPPER)
    pe_pos = cells & (pe >= PE_MID) & (pe <= UPPER)

    counts = _counts_by_name(_build_tree(), ev)

    assert counts["Cells"] == int(cells.sum())
    assert counts["APC+"] == int(apc_pos.sum())
    assert counts["FITC+"] == int(fitc_pos.sum())
    assert counts["PE+"] == int(pe_pos.sum())
    assert counts["FITC+ AND PE+"] == int((fitc_pos & pe_pos).sum())


@pytest.mark.parametrize("sample_name", list(GOLDEN_COUNTS))
def test_quadrants_partition_their_parent(events_by_sample, sample_name):
    root = _build_tree()
    stats = DagEvaluator.evaluate(root, events_by_sample[sample_name])
    apc = _node(root, "APC+")
    quadrants = [_node(root, q) for q in ("Q1", "Q2", "Q3", "Q4")]

    assert sum(stats[q.node_id]["count"] for q in quadrants) == stats[apc.node_id]["count"]
    if stats[apc.node_id]["count"]:
        pct = sum(stats[q.node_id]["pct_parent"] for q in quadrants)
        # DagEvaluator rounds each pct to 2 dp, so four of them can drift ±0.02.
        assert pct == pytest.approx(100.0, abs=0.02)


def test_percentages_are_relative_to_parent_and_total(events_by_sample):
    ev = events_by_sample["Sample A"]
    root = _build_tree()
    stats = DagEvaluator.evaluate(root, ev)
    cells, apc = _node(root, "Cells"), _node(root, "APC+")
    golden = GOLDEN_COUNTS["Sample A"]

    assert stats[apc.node_id]["pct_parent"] == pytest.approx(
        100 * golden["APC+"] / golden["Cells"], abs=0.005
    )
    assert stats[apc.node_id]["pct_total"] == pytest.approx(
        100 * golden["APC+"] / len(ev), abs=0.005
    )
    assert stats[cells.node_id]["pct_parent"] == stats[cells.node_id]["pct_total"]


def test_every_gating_entry_point_agrees(events_by_sample):
    """The graph view (PopulationService), the per-node hierarchy walk
    (apply_hierarchy), and the stats walk (DagEvaluator) are three separate
    ways the app turns a node into events — they must never disagree.
    """
    ev = events_by_sample["Sample A"]
    state = FlowState()
    sample = Sample(sample_id="a", display_name="Sample A")
    sample.fcs_data = _fcs_data(ev)
    sample.gate_tree = _build_tree()
    state.data.experiment.samples["a"] = sample
    service = PopulationService(state)

    stats = DagEvaluator.evaluate(sample.gate_tree, ev)
    for node in sample.gate_tree.iter_dag():
        if node.is_root:
            continue
        via_service = service.get_gated_events("a", node.node_id)
        assert via_service is not None, node.name
        assert len(via_service) == stats[node.node_id]["count"], node.name
        assert len(node.apply_hierarchy(ev)) == stats[node.node_id]["count"], node.name


def test_saved_and_reloaded_tree_gives_identical_counts(events_by_sample):
    """Workflow save/load round-trips the tree through to_dict/from_dict;
    a reopened project must reproduce exactly the same populations.
    """
    ev = events_by_sample["Sample A"]
    reloaded = GateNode.from_dict(_build_tree().to_dict())
    assert reloaded is not None

    assert _counts_by_name(reloaded, ev) == GOLDEN_COUNTS["Sample A"]


def test_same_tree_applied_to_another_sample_uses_that_samples_data(events_by_sample):
    """Copying a gate tree onto a second sample (as propagation does) must
    re-gate against the new sample's events, not reuse cached masks.
    """
    tree = _build_tree()
    counts_a = _counts_by_name(tree, events_by_sample["Sample A"])
    copied = GateNode.from_dict(tree.to_dict())
    assert copied is not None

    counts_c = _counts_by_name(copied, events_by_sample["Sample C"])

    assert counts_a == GOLDEN_COUNTS["Sample A"]
    assert counts_c == GOLDEN_COUNTS["Sample C"]
