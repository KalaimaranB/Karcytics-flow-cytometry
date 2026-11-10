"""Auto gating on planted samples (tests/fixtures/lens.py), where the populations are known.

T cells hold CD4 T (CD4+ CD8−), CD8 T and NKT (CD4− CD8+); sample s2 has dimmer CD4.
"""

from dataclasses import replace

import numpy as np
import pytest

from karcytics_plugins.flow_cytometry.analysis.autogate import (
    GatingEngine,
    ProposalCommitter,
    StepRequest,
)
from karcytics_plugins.flow_cytometry.analysis.autogate.density import find_valley, separation
from karcytics_plugins.flow_cytometry.analysis.autogate.mixture import fit_mixture, inside
from karcytics_plugins.flow_cytometry.analysis.autogate.models import METHODS
from karcytics_plugins.flow_cytometry.analysis.axis_manager import AxisManager
from karcytics_plugins.flow_cytometry.analysis.derived.expression import parse_formula
from karcytics_plugins.flow_cytometry.analysis.gating.gate_factory import gate_from_dict
from karcytics_plugins.flow_cytometry.analysis.services.derived_parameter_service import (
    DerivedParameterService,
)
from tests.fixtures.lens import TreeController, build_lens_state

CHANNELS = ("CD3", "CD4", "CD8", "CD56")


@pytest.fixture
def lens():
    state = build_lens_state()
    return state, GatingEngine(state, AxisManager(state))


def _t_cells(state, sid="s0"):
    return state.data.experiment.samples[sid].gate_tree.children[0].children[0]


def _request(state, method_key, **kw):
    return StepRequest(
        method_key,
        "s0",
        _t_cells(state).node_id,
        CHANNELS,
        tuple(state.data.experiment.samples),
        x_channel="CD4",
        y_channel="CD8",
        **kw,
    )


# ── The numbers underneath ────────────────────────────────────────────


def test_a_valley_sits_in_the_middle_of_an_empty_gap():
    rng = np.random.default_rng(0)
    values = np.concatenate((rng.normal(0, 1, 5000), rng.normal(10, 1, 5000)))
    valley = find_valley(values)
    assert valley is not None and valley.depth > 0.95  # noqa: PLR2004
    assert 4 < valley.position < 6  # noqa: PLR2004


def test_one_peak_has_no_clear_valley_and_no_separation():
    rng = np.random.default_rng(0)
    valley = find_valley(rng.normal(0, 1, 10_000))
    assert (
        valley is None or valley.depth < 0.2
    )  # noise dips are far below any threshold  # noqa: PLR2004
    assert separation(rng.normal(0, 1, 10_000), rng.normal(0, 1, 10_000)) < 0.2  # noqa: PLR2004


def test_bic_finds_two_groups_and_one():
    rng = np.random.default_rng(0)
    two = np.vstack((rng.normal((0, 0), 1, (3000, 2)), rng.normal((8, 8), 1, (2000, 2))))
    assert len(fit_mixture(two).components) == 2  # noqa: PLR2004
    assert len(fit_mixture(rng.normal(0, 1, (4000, 2))).components) == 1


# ── Proposals ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("info", METHODS, ids=lambda m: m.key)
def test_every_method_finds_cd4_and_cd8_t_cells(lens, info):
    state, engine = lens
    proposal = engine.propose(_request(state, info.key))

    assert not isinstance(proposal, str), proposal
    names = proposal.plot.main_names
    assert any("CD4+" in n and "CD8−" in n for n in names), names
    assert any("CD4−" in n and "CD8+" in n for n in names), names
    assert proposal.reason and proposal.view_sections
    assert proposal.provenance["method"] == info.key


@pytest.mark.parametrize("info", METHODS, ids=lambda m: m.key)
def test_a_proposal_shows_exactly_what_its_gates_will_hold(lens, info):
    state, engine = lens
    proposal = engine.propose(_request(state, info.key))
    events = engine._with_pending(proposal.context.data.events, proposal.context.view)

    for region in proposal.gated:
        # Not exact: the biexponential display transform varies by ~5e-5 between calls,
        # so an event sitting on a gate's edge can fall either way.
        assert np.mean(region.gate.contains(events) == region.mask) > 0.995  # noqa: PLR2004
        assert region.fraction == pytest.approx(region.mask.mean())


def test_an_ellipse_gate_keeps_the_shape_it_was_fitted_as(lens):
    state, engine = lens
    proposal = engine.propose(_request(state, "pairs"))
    view = proposal.context.view
    xy = np.column_stack((view.x.values, view.y.values))
    events = proposal.context.data.events

    for component, region in zip(proposal.context.split.components, proposal.gated, strict=False):
        shape = inside(xy, component)
        assert np.mean(region.gate.contains(events) == shape) > 0.99  # noqa: PLR2004 - edge rounding


def test_pca_axes_are_formulas_that_reproduce_the_components(lens):
    state, engine = lens
    proposal = engine.propose(_request(state, "pca"))
    view = proposal.context.view

    assert [a.name.split(" ·")[0] for a in proposal.pending_axes] == ["PC1", "PC2"]
    for axis in (view.x, view.y):
        values = parse_formula(axis.pending.formula).evaluate(proposal.context.data.events)
        assert np.allclose(values, axis.values, equal_nan=True)
    assert "asinh([CD4] / 150)" in proposal.pending_axes[0].formula


def test_too_few_events_or_no_valley_say_why(lens):
    state, engine = lens
    assert "fewer than" in engine.propose(_request(state, "pca", min_events=10**7))
    no_valley = engine.propose(
        replace(_request(state, "valleys"), min_valley=1.01)
    )  # planted gaps are empty: depth 1
    assert isinstance(no_valley, str) and "No clear valley" in no_valley


def test_the_next_best_view_is_another_view(lens):
    state, engine = lens
    best = engine.propose(_request(state, "pairs"))
    second = engine.propose(_request(state, "pairs", view_rank=1))
    assert second.context.view.name != best.context.view.name
    assert second.reason.startswith("Runner-up view 2")


# ── Group, comparison, record ─────────────────────────────────────────


def test_the_group_preview_flags_the_sample_that_drifted(lens):
    state, engine = lens
    request = _request(state, "valleys")
    preview = engine.preview_group(engine.propose(request), request)

    by_sample = {row.sample: row for row in preview.rows}
    assert set(by_sample) == {"S0", "S1", "S2", "S3"}
    assert not by_sample["S0"].flagged and not by_sample["S1"].flagged
    assert by_sample["S2"].flagged  # dimmer CD4
    assert abs(sum(by_sample["S1"].percents.values()) - 100) < 2  # noqa: PLR2004


def test_compare_scores_every_method_against_your_gates(lens):
    state, engine = lens
    outcomes = engine.compare(_request(state, "pca"))

    assert [o.label for o in outcomes] == ["Your gates", *(m.name for m in METHODS)]
    assert set(outcomes[0].percents) == {"CD4+", "CD8+"}
    assert all(o.agreement and max(o.agreement.values()) > 0.8 for o in outcomes[1:])  # noqa: PLR2004


def test_accepting_adds_named_gates_with_their_record_and_pc_parameters(lens):
    state, engine = lens
    proposal = engine.propose(_request(state, "pca"))
    controller = TreeController(state)
    derived = DerivedParameterService(state)

    added = ProposalCommitter(controller, derived).accept(proposal)

    t_cells = _t_cells(state)
    new = [c for c in t_cells.children if c.node_id in added]
    assert [c.name for c in new] == list(proposal.plot.main_names)
    params = {d.param_id for d in derived.definitions}
    assert len(params) == 2  # noqa: PLR2004 - PC1 and PC2
    assert {new[0].gate.x_param, new[0].gate.y_param} == params
    restored = gate_from_dict(new[0].gate.to_dict())
    assert restored.provenance["population"] == new[0].name
    assert engine.story("s0", new[0].node_id).facts[0] == ("Method", "PCA")


def test_accepting_twice_reuses_the_same_pc_parameters(lens):
    state, engine = lens
    derived = DerivedParameterService(state)
    committer = ProposalCommitter(TreeController(state), derived)
    committer.accept(engine.propose(_request(state, "pca")))
    committer.accept(engine.propose(_request(state, "pca")))
    assert len(derived.definitions) == 2  # noqa: PLR2004


def test_a_gate_drawn_by_hand_has_no_story(lens):
    state, engine = lens
    assert engine.story("s0", _t_cells(state).node_id) is None


def test_the_cells_split_runs_on_forward_and_side_scatter(lens):
    state, engine = lens
    request = StepRequest(
        "valleys", "s0", None, CHANNELS, x_channel="FSC-A", y_channel="SSC-A", min_valley=0.5
    )
    proposal = engine.propose(request)

    assert not isinstance(proposal, str), proposal
    cells = max(proposal.plot.regions, key=lambda r: r.fraction)
    assert cells.fraction == pytest.approx(0.92, abs=0.02)  # the planted debris is 8%
    assert cells.name == "FSC-Ahi SSC-Ahi"
    assert len(proposal.gated) == 1  # the debris is a sliver, not a population to keep
