"""Numbers the Academy courses quote stay true to the tutorial data.

Course text quotes real results ("B cells are ~68% of Sample C's
Leukocytes", "the peaks sit ~60× apart"). They were first measured on one
set of hand-drawn gates. This test recomputes each one from the tutorial
files in `tests/data/fcs/` with the gates learners are shown how to draw:
every draw step's on-canvas guide shape. If a change to the data,
compensation, gate math or a guide moves a quoted number, it fails here
instead of shipping a course that contradicts the screen.

`QUOTES` ties each number to the step that quotes it, so the test also fails
if the text is reworded without updating the table.

Not covered: numbers that need a UMAP run (UMAP B Cells' median, CV and
share of Leukocytes, and the AND node's overlap in Courses 3 and 4). Re-check
those by hand when Course 3's run settings or the UMAP export change.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import pytest
from karcytics_sdk.plugin.tutorial_models import QuestionStep

from karcytics_plugins.flow_cytometry.analysis.compute.dag_evaluator import DagEvaluator
from karcytics_plugins.flow_cytometry.analysis.derived.expression import parse_formula
from karcytics_plugins.flow_cytometry.analysis.fcs_io import load_fcs
from karcytics_plugins.flow_cytometry.analysis.gating import PolygonGate, RangeGate, RectangleGate
from karcytics_plugins.flow_cytometry.analysis.gating.gate_node import GateNode
from karcytics_plugins.flow_cytometry.analysis.statistics import StatType, compute_statistic
from karcytics_plugins.flow_cytometry.tutorials.courses import (
    course_1_fundamentals,
    course_2_gating,
    course_4_reporting,
)

pytestmark = pytest.mark.functional

SAMPLES = ("Sample A", "Sample B", "Sample C")

# Course 4's derived parameter: B220 ÷ CD45, non-positive CD45 → invalid (NaN).
RATIO = parse_formula("[FITC-A] / [APC-A]")

# The valley between the ratio histogram's two peaks on Sample C's
# Leukocytes, where c4_d12b's "Range gate on the right peak" starts.
RATIO_VALLEY = 0.1

STEPS = {
    s.id: s for c in (course_1_fundamentals, course_2_gating, course_4_reporting) for s in c.steps
}


def _guide(step_id: str, key: str):
    return STEPS[step_id].metadata[key]


def _build_tree() -> GateNode:
    """Course 1–2's gate tree, drawn exactly along each step's guide."""
    lx, hx, ly, hy = _guide("c1_s30h_draw_gate", "guide_rect")
    tx0, tx1, ty0, ty1 = _guide("c2_s07_draw_tcell", "guide_rect")

    root = GateNode(name="All Events")
    cells = root.add_child(
        PolygonGate("FSC-A", "SSC-A", list(_guide("c1_s24_cells_gate", "guide_data_poly"))),
        name="Cells",
    )
    live_low, live_high = _guide("c1_s27f_draw_live_gate", "guide_range")
    live = cells.add_child(
        RangeGate("PerCP-Cy5-5-A", low=live_low, high=live_high), name="Live Cells"
    )
    leuk = live.add_child(
        RectangleGate("APC-A", "SSC-A", x_min=lx, x_max=hx, y_min=ly, y_max=hy),
        name="Leukocytes",
    )
    leuk.add_child(
        RectangleGate("FITC-A", "Pacific Blue-A", x_min=tx0, x_max=tx1, y_min=ty0, y_max=ty1),
        name="T-cells",
    )
    b_low, b_high = _guide("c2_s18_draw_bcell", "guide_range")
    leuk.add_child(RangeGate("FITC-A", low=b_low, high=b_high), name="B-cells")
    return root


def _measure_sample(events: pd.DataFrame) -> dict[str, float]:
    events = events.assign(ratio=RATIO.evaluate(events))
    root = _build_tree()
    stats = DagEvaluator.evaluate(root, events)
    nodes = {n.name: n for n in root.iter_dag()}

    def stat(name: str, key: str) -> float:
        return stats[nodes[name].node_id][key]

    leuk = nodes["Leukocytes"].apply_hierarchy(events)
    b_cells = nodes["B-cells"].apply_hierarchy(events)
    t_cells = nodes["T-cells"].apply_hierarchy(events)
    right_peak = leuk[leuk["ratio"] >= RATIO_VALLEY]
    return {
        "leuk_pct_total": stat("Leukocytes", "pct_total"),
        "b_pct_leuk": stat("B-cells", "pct_parent"),
        "b_pct_total": stat("B-cells", "pct_total"),
        "b_count": stat("B-cells", "count"),
        "b_ratio_median": compute_statistic(b_cells, "ratio", StatType.MEDIAN),
        "b_ratio_cv": compute_statistic(b_cells, "ratio", StatType.CV),
        "t_ratio_median": compute_statistic(t_cells, "ratio", StatType.MEDIAN),
        "leuk_ratio_invalid_pct": 100 * float(leuk["ratio"].isna().mean()),
        "ratio_gate_b_purity": 100 * float(np.isin(right_peak.index, b_cells.index).mean()),
    }


@pytest.fixture(scope="module")
def measured(fcs_test_data_dir) -> dict[str, dict[str, float]]:
    m = {
        s: _measure_sample(load_fcs(str(fcs_test_data_dir / f"Specimen_001_{s}.fcs")).events)
        for s in SAMPLES
    }
    c, b = m["Sample C"], m["Sample B"]
    c["peak_gap"] = c["b_ratio_median"] / c["t_ratio_median"]
    c["vs_b_pct_total"] = c["b_pct_total"] / b["b_pct_total"]
    c["vs_b_pct_leuk"] = c["b_pct_leuk"] / b["b_pct_leuk"]
    return m


@dataclass(frozen=True)
class Quote:
    step_id: str
    text: str  # exactly as it appears in the step
    sample: str
    measure: str
    value: float
    tolerance: float


QUOTES = [
    # Sample A (thymus) has almost no B cells.
    Quote("c2_s54_mystery_reveal", "0.4% of", "Sample A", "b_pct_leuk", 0.4, 0.05),
    Quote("c4_s07_read_table", "B cells are 0.4%", "Sample A", "b_pct_leuk", 0.4, 0.05),
    Quote("c4_s07_read_table", "~43% of its Leukocytes", "Sample B", "b_pct_leuk", 43, 0.5),
    Quote("c4_s07_read_table", "~68% of its Leukocytes", "Sample C", "b_pct_leuk", 68, 0.5),
    Quote("c4_s14_heatmap_read", "are **68%** of Leukocytes", "Sample C", "b_pct_leuk", 68, 0.5),
    # % Parent vs % Total: debris differs between samples.
    Quote("c4_s06q_fair_abundance", "89% of Sample A", "Sample A", "leuk_pct_total", 89, 0.5),
    Quote("c4_s06q_fair_abundance", "77% of B", "Sample B", "leuk_pct_total", 77, 0.5),
    Quote("c4_s06q_fair_abundance", "65% of C", "Sample C", "leuk_pct_total", 65, 0.5),
    Quote("c4_s06q_fair_abundance", "1.35×", "Sample C", "vs_b_pct_total", 1.35, 0.01),
    Quote("c4_s06q_fair_abundance", "1.6×", "Sample C", "vs_b_pct_leuk", 1.6, 0.05),
    # The B220 ÷ CD45 ratio on Sample C.
    Quote("c4_d08b_compare", "~0%", "Sample C", "leuk_ratio_invalid_pct", 0, 0.5),
    Quote("c4_d12b_two_peaks", "near 0.01", "Sample C", "t_ratio_median", 0.01, 0.005),
    Quote("c4_d12b_two_peaks", "near 0.6", "Sample C", "b_ratio_median", 0.6, 0.05),
    Quote("c4_d12b_two_peaks", "~60× apart", "Sample C", "peak_gap", 60, 6),
    Quote("c4_d12b_two_peaks", "~97% pure", "Sample C", "ratio_gate_b_purity", 97, 1),
    Quote("c4_s25_histogram_info", "ratio **0.64**", "Sample C", "b_ratio_median", 0.64, 0.005),
    Quote("c4_s25_histogram_info", "CV **46%**", "Sample C", "b_ratio_cv", 46, 0.5),
    # CV across samples.
    Quote("c4_s09_cv_question", "tightest (~35%)", "Sample B", "b_ratio_cv", 35, 1),
    Quote("c4_s09_cv_question", "Sample A's ~75%", "Sample A", "b_ratio_cv", 75, 1),
    Quote("c4_s09_cv_question", "only ~1,000 cells", "Sample A", "b_count", 1000, 50),
    Quote("c4_s25_histogram_info", "only ~1,000 thymus", "Sample A", "b_count", 1000, 50),
]

IDS = [f"{q.step_id}:{q.text}" for q in QUOTES]


def _step_text(step) -> str:
    parts = [step.text]
    if isinstance(step, QuestionStep):
        parts += [step.explanation or ""] + [c.feedback or "" for c in step.choices]
    return " ".join(parts)


@pytest.mark.parametrize("quote", QUOTES, ids=IDS)
def test_quote_is_in_its_step(quote):
    assert quote.text in _step_text(STEPS[quote.step_id])


@pytest.mark.parametrize("quote", QUOTES, ids=IDS)
def test_quote_matches_the_data(measured, quote):
    actual = measured[quote.sample][quote.measure]
    assert actual == pytest.approx(quote.value, abs=quote.tolerance), (
        f"{quote.step_id} says {quote.text!r}, but {quote.sample}'s "
        f"{quote.measure} is {actual:.4g} with the guide gates"
    )
