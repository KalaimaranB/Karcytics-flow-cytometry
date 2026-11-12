"""Gating from a template on planted samples (tests/fixtures/lens.py).

Cells: debris 8%; then CD4 T 40%, CD8 T 22%, NKT 8% (CD3+ CD8+ CD56+), NK 22% (CD3− CD56+).
"""

import numpy as np
import pytest

from karcytics_plugins.flow_cytometry.analysis.autogate import ProposalCommitter, TemplateRunner
from karcytics_plugins.flow_cytometry.analysis.autogate.models import TEMPLATE
from karcytics_plugins.flow_cytometry.analysis.autogate.template import (
    CELLS,
    MARKERS,
    Call,
    GatingTemplate,
    parse_calls,
)
from karcytics_plugins.flow_cytometry.analysis.axis_manager import AxisManager
from karcytics_plugins.flow_cytometry.analysis.experiment import SampleRole
from karcytics_plugins.flow_cytometry.analysis.services.derived_parameter_service import (
    DerivedParameterService,
)
from tests.fixtures.lens import TOP, TreeController, build_lens_state, make_sample

STEPS = [
    {"id": "c", "name": "Cells", "parent": None, "markers": "scatter"},
    {"id": "s", "name": "Singlets", "parent": "c", "markers": "singlets"},
    {"id": "t", "name": "T cells", "parent": "s", "markers": "CD3+"},
    {"id": "t4", "name": "CD4 T", "parent": "t", "markers": "CD4+ CD8-"},
    {"id": "t8", "name": "CD8 T", "parent": "t", "markers": "CD4− CD8+"},
    {"id": "nk", "name": "NK cells", "parent": "s", "markers": "CD3- CD56+"},
    {"id": "b", "name": "B cells", "parent": "s", "markers": "B220+"},
]


@pytest.fixture
def lens():
    state = build_lens_state()
    state.data.experiment.samples["s0"].gate_tree.children.clear()
    return state, TemplateRunner(state, AxisManager(state))


def _run(state, runner):
    plan = runner.run(GatingTemplate.from_dict({"name": "T and NK", "steps": STEPS}), "s0", None)
    assert not isinstance(plan, str), plan
    return plan, {o.step.name: o for o in plan.outcomes}


def test_markers_are_read_as_they_are_said():
    assert parse_calls("CD4+ CD8−") == (MARKERS, (Call("CD4", "+"), Call("CD8", "−")))
    assert parse_calls("CD45lo, CD3-") == (MARKERS, (Call("CD45", "lo"), Call("CD3", "−")))
    assert parse_calls("scatter") == (CELLS, ())
    assert "needs + / lo / −" in parse_calls("CD3")
    assert "At most 2" in parse_calls("CD3+ CD4+ CD8+")


def test_a_template_round_trips_through_its_file_form():
    template = GatingTemplate.from_dict({"name": "T and NK", "steps": STEPS})
    assert GatingTemplate.from_dict(template.to_dict()) == template
    assert [s.name for s in template.ordered()][:3] == ["Cells", "Singlets", "T cells"]


def test_each_population_is_found_where_it_was_planted(lens):
    state, runner = lens
    _plan, steps = _run(state, runner)

    assert steps["Cells"].proposal.gated[0].fraction == pytest.approx(0.92, abs=0.05)
    t_cells = steps["T cells"].proposal.gated[0]
    assert t_cells.name == "T cells" and t_cells.fraction == pytest.approx(0.70 / 0.92, abs=0.06)
    cd4 = steps["CD4 T"].proposal.gated[0]
    assert cd4.fraction == pytest.approx(0.40 / 0.70, abs=0.05)
    assert steps["CD8 T"].proposal.gated[0].fraction == pytest.approx(0.30 / 0.70, abs=0.05)
    assert steps["NK cells"].proposal.gated[0].fraction == pytest.approx(0.22 / 0.92, abs=0.04)
    assert "asked for CD4+ CD8−" in steps["CD4 T"].proposal.reason
    assert steps["CD4 T"].proposal.method_key == TEMPLATE.key


def test_what_this_sample_cant_show_is_said_and_stepped_around(lens):
    state, runner = lens
    _plan, steps = _run(state, runner)

    assert steps["Singlets"].proposal is None  # the planted samples have no FSC-H
    assert "start from Cells" in steps["Singlets"].message
    assert steps["B cells"].proposal is None
    assert "No channel measures B220" in steps["B cells"].message


def test_accepting_builds_the_tree_as_written(lens):
    state, runner = lens
    plan, _steps = _run(state, runner)

    created = ProposalCommitter(TreeController(state), DerivedParameterService(state)).accept_plan(
        plan
    )

    root = state.data.experiment.samples["s0"].gate_tree
    (cells,) = root.children
    assert cells.name == "Cells" and cells.node_id == created["c"]
    assert sorted(c.name for c in cells.children) == [
        "NK cells",
        "T cells",
    ]  # Singlets stepped aside
    t_cells = next(c for c in cells.children if c.name == "T cells")
    assert sorted(c.name for c in t_cells.children) == ["CD4 T", "CD8 T"]
    record = t_cells.children[0].gate.provenance
    assert record["template"] == "T and NK" and record["method"] == TEMPLATE.key


def _with_control(state, cd3_mean: float, role=SampleRole.FMO_CONTROL):
    """Adds a control tube: the same cells, with CD3 at ``cd3_mean`` for everyone."""
    sample, events, _truth = make_sample("fmo", seed=9)
    events["CD3"] = np.random.default_rng(9).normal(cd3_mean, 280, len(events)).clip(0, TOP)
    sample.role, sample.fmo_minus = role, "CD3" if role == SampleRole.FMO_CONTROL else None
    sample.display_name = "FMO CD3" if role == SampleRole.FMO_CONTROL else "Unstained"
    state.data.experiment.samples["fmo"] = sample


def _t_cells(runner):
    """The T cells step's outcome, gated from Cells."""
    template = GatingTemplate.from_dict(
        {"name": "T", "steps": [STEPS[0], STEPS[2] | {"parent": "c"}]}
    )
    plan = runner.run(template, "s0", None)
    assert not isinstance(plan, str), plan
    return {o.step.name: o for o in plan.outcomes}["T cells"]


def test_an_fmo_control_sets_where_positive_starts(lens):
    state, runner = lens
    _with_control(state, cd3_mean=500.0)

    t_cells = _t_cells(runner).proposal

    line = t_cells.provenance["control_lines"]["CD3"]
    assert line["kind"] == "FMO" and line["control"] == "FMO CD3"
    assert "above 99.5% of the FMO control FMO CD3" in t_cells.reason
    assert next(r for r in t_cells.gated if r.name == "T cells").fraction == pytest.approx(
        0.70 / 0.92, abs=0.05
    )


def test_an_unstained_control_stands_in_and_says_it_is_weaker(lens):
    state, runner = lens
    _with_control(state, cd3_mean=500.0, role=SampleRole.UNSTAINED)

    t_cells = _t_cells(runner).proposal

    assert t_cells.provenance["control_lines"]["CD3"]["kind"] == "unstained"
    assert "autofluorescence only" in t_cells.reason


def test_a_control_rules_out_what_lies_below_its_line_and_says_so(lens):
    state, runner = lens
    _with_control(state, cd3_mean=5000.0)  # brighter than the stained cells (mislabelled?)

    outcome = _t_cells(runner)

    assert outcome.proposal is None
    assert "no clear population above it" in outcome.message  # so it isn't cut at...
    assert "where the FMO control FMO CD3 puts CD3+" in outcome.message  # ...but still rules
