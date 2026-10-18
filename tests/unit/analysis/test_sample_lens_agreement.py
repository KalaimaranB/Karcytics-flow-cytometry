"""Agreement: do other clustering runs of the same cells report a finding too?"""

import numpy as np

from karcytics_plugins.flow_cytometry.analysis.sample_lens import (
    FindingKind,
    OtherRun,
    agreements,
    audit,
    build_scope,
)
from tests.fixtures.lens import build_lens_state


def _scope(state, run):
    sample = state.data.experiment.samples["s0"]
    return build_scope(sample, run, sample.fcs_data.events)


def _setup():
    state = build_lens_state()
    run = state.data.umap_results["s0::root"][0]
    scope = _scope(state, run)
    return state, run, scope, audit(scope)


def test_an_identical_run_agrees_with_every_finding():
    state, run, scope, findings = _setup()
    assert {f.kind for f in findings} == set(FindingKind)
    twin = _scope(state, dict(run))
    result = agreements(scope, findings, [OtherRun("Twin", twin, audit(twin))])
    assert [a.found_by for a in result] == [("Twin",)] * len(findings)
    assert result[0].text == "Also found by Twin"


def test_a_run_that_puts_the_missed_cells_in_a_population_disagrees_on_them():
    state, run, scope, findings = _setup()
    missed = next(f for f in findings if f.kind is FindingKind.MISSED)
    clusters = np.asarray(run["clusters"]).copy()
    clusters[np.isin(clusters, missed.clusters)] = -1  # the other method calls them noise
    other = _scope(state, dict(run, clusters=clusters))
    result = agreements(scope, findings, [OtherRun("Other", other, audit(other))])
    by_kind = {f.kind: a for f, a in zip(findings, result, strict=True)}
    assert by_kind[FindingKind.MISSED].text == "Only this run finds it"
    assert by_kind[FindingKind.CUTS].found_by == ("Other",)  # the gates didn't change


def test_with_no_other_run_there_is_nothing_to_say():
    _state, _run, scope, findings = _setup()
    assert all(a.text == "" for a in agreements(scope, findings, []))
