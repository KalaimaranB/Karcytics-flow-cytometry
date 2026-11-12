"""Auto gating on real recordings (tests/data/fcs), not just planted blobs.

Real populations are lopsided and overlap, detectors clip at their limits, and
valleys are shallower than in synthetic data: the engine has to find the
obvious populations anyway, and still find nothing in an unstained tube.
"""

from __future__ import annotations

import pytest

from karcytics_plugins.flow_cytometry.analysis.autogate import GatingEngine, StepRequest
from karcytics_plugins.flow_cytometry.analysis.axis_manager import AxisManager
from karcytics_plugins.flow_cytometry.analysis.experiment import Sample
from karcytics_plugins.flow_cytometry.analysis.fcs_io import load_fcs
from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from tests.fixtures.daemon import in_process_daemon

pytestmark = pytest.mark.functional

SCATTER = ("FSC-A", "SSC-A")


def _engine(fcs_test_data_dir, name: str) -> tuple[GatingEngine, tuple[str, ...]]:
    state = FlowState()
    fcs = load_fcs(str(fcs_test_data_dir / f"Specimen_001_{name}.fcs"), in_process_daemon)
    state.data.experiment.samples["s"] = Sample(sample_id="s", display_name=name, fcs_data=fcs)
    markers = tuple(c for c in fcs.events.columns if c not in (*SCATTER, "Time"))
    return GatingEngine(state, AxisManager(state)), markers


def _request(method_key: str, channels: tuple[str, ...], cells_first: bool = False) -> StepRequest:
    return StepRequest(
        method_key,
        "s",
        None,
        channels,
        ("s",),
        x_channel="FSC-A",
        y_channel="SSC-A",
        cells_first=cells_first,
    )


@pytest.mark.parametrize("method_key", ["pairs", "pca"])
def test_dead_cells_are_found_in_a_stained_sample(fcs_test_data_dir, method_key):
    engine, markers = _engine(fcs_test_data_dir, "Sample A")
    proposal = engine.propose(_request(method_key, markers))

    assert not isinstance(proposal, str), proposal
    dead = [r for r in proposal.gated if "PI+" in r.name]
    assert dead and 0.03 < dead[0].fraction < 0.2  # noqa: PLR2004
    assert len(proposal.gated) >= 2  # noqa: PLR2004


def test_debris_is_cut_off_on_forward_scatter(fcs_test_data_dir):
    engine, _markers = _engine(fcs_test_data_dir, "Sample A")
    proposal = engine.propose(_request("valleys", SCATTER))

    assert not isinstance(proposal, str), proposal
    cells = max(proposal.gated, key=lambda r: r.fraction)
    assert cells.name.startswith("FSC-Amid") and cells.fraction > 0.8  # noqa: PLR2004


def test_an_unstained_tube_has_no_marker_split(fcs_test_data_dir):
    engine, markers = _engine(fcs_test_data_dir, "Blank")
    result = engine.propose(_request("pairs", markers))
    assert isinstance(result, str) and "No clear split" in result


def test_cells_come_first_from_all_events(fcs_test_data_dir):
    engine, markers = _engine(fcs_test_data_dir, "Sample A")
    proposal = engine.propose(_request("pairs", markers, cells_first=True))

    assert not isinstance(proposal, str), proposal
    assert [r.name for r in proposal.gated] == ["Cells"]
    assert 0.8 < proposal.gated[0].fraction < 0.98  # noqa: PLR2004


def test_the_cells_gate_follows_the_cells_and_leaves_out_saturated_events(fcs_test_data_dir):
    """Sample B has no debris valley on forward scatter, but its cells' outline still
    leaves out the column of events clipped at the forward-scatter limit.
    """
    engine, markers = _engine(fcs_test_data_dir, "Sample B")
    proposal = engine.propose(_request("pairs", markers, cells_first=True))

    assert not isinstance(proposal, str), proposal
    (cells,) = proposal.gated
    assert cells.gate.__class__.__name__ == "PolygonGate"
    events = proposal.context.data.events
    saturated = events["FSC-A"].to_numpy() >= events["FSC-A"].max()
    assert saturated.sum() > 50 and cells.mask[saturated].mean() < 0.05  # noqa: PLR2004


def _template_plan(fcs_test_data_dir, name: str):
    from karcytics_plugins.flow_cytometry.analysis.autogate import TemplateRunner
    from karcytics_plugins.flow_cytometry.analysis.autogate.template import GatingTemplate

    engine, _markers = _engine(fcs_test_data_dir, name)
    template = GatingTemplate.from_dict(
        {
            "name": "Spleen",
            "steps": [
                {"id": "c", "name": "Cells", "parent": None, "markers": "scatter"},
                {"id": "s", "name": "Singlets", "parent": "c", "markers": "singlets"},
                {"id": "l", "name": "Live", "parent": "s", "markers": "PI-"},
                {"id": "b", "name": "B cells", "parent": "l", "markers": "B220+"},
                {"id": "t", "name": "T cells", "parent": "l", "markers": "CD3+"},
            ],
        }
    )
    plan = TemplateRunner(engine._state, engine._axis_manager).run(template, "s", None)
    assert not isinstance(plan, str), plan
    return {o.step.name: o for o in plan.outcomes}


def test_a_template_finds_live_b_and_t_cells_in_a_stained_sample(fcs_test_data_dir):
    steps = _template_plan(fcs_test_data_dir, "Sample C")
    for name in ("Cells", "Live", "B cells", "T cells"):
        assert steps[name].proposal is not None, steps[name].message
    assert 0.5 < steps["B cells"].proposal.gated[0].fraction < 0.9  # noqa: PLR2004


def test_a_template_finds_no_stained_populations_in_an_unstained_tube(fcs_test_data_dir):
    steps = _template_plan(fcs_test_data_dir, "Blank")
    assert steps["Live"].proposal is None
    assert steps["B cells"].proposal is None and steps["T cells"].proposal is None


def _with_fmo_plan(fcs_test_data_dir, name: str, fmos: dict[str, str]):
    """A template run on ``name`` with FMO tubes (file name → marker left out) in the experiment."""
    from karcytics_plugins.flow_cytometry.analysis.autogate import TemplateRunner
    from karcytics_plugins.flow_cytometry.analysis.autogate.template import GatingTemplate
    from karcytics_plugins.flow_cytometry.analysis.experiment import SampleRole

    engine, _markers = _engine(fcs_test_data_dir, name)
    samples = engine._state.data.experiment.samples
    for tube, marker in fmos.items():
        fcs = load_fcs(str(fcs_test_data_dir / f"Specimen_001_{tube}.fcs"), in_process_daemon)
        samples[tube] = Sample(
            sample_id=tube,
            display_name=tube,
            fcs_data=fcs,
            role=SampleRole.FMO_CONTROL,
            fmo_minus=marker,
        )
    template = GatingTemplate.from_dict(
        {
            "name": "Spleen",
            "steps": [
                {"id": "c", "name": "Cells", "parent": None, "markers": "scatter"},
                {"id": "k", "name": "Leukocytes", "parent": "c", "markers": "CD45+"},
                {"id": "t", "name": "T cells", "parent": "k", "markers": "CD3+"},
            ],
        }
    )
    plan = TemplateRunner(engine._state, engine._axis_manager).run(template, "s", None)
    assert not isinstance(plan, str), plan
    return {o.step.name: o for o in plan.outcomes}


def test_an_fmo_tube_places_the_positive_line(fcs_test_data_dir):
    steps = _with_fmo_plan(fcs_test_data_dir, "Sample C", {"FMO e450": "CD3", "FMO APC": "CD45"})
    t_cells = steps["T cells"].proposal
    assert t_cells is not None, steps["T cells"].message
    assert t_cells.provenance["control_lines"]["CD3"]["control"] == "FMO e450"
    assert 0.05 < t_cells.gated[0].fraction < 0.4  # noqa: PLR2004


def test_an_fmo_line_with_only_a_tail_beyond_it_is_not_taken_for_a_population(
    fcs_test_data_dir,
):
    """The unstained tube sits a little brighter than the FMO on CD45 (its own
    autofluorescence), so some events cross the FMO's line, but no population does.
    """
    steps = _with_fmo_plan(fcs_test_data_dir, "Blank", {"FMO APC": "CD45"})
    assert steps["Leukocytes"].proposal is None
    assert "no clear population above it" in steps["Leukocytes"].message
