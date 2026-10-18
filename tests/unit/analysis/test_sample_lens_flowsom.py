"""The Sample Lens audit against a FlowSOM run of the planted sample."""

import pytest

from karcytics_plugins.flow_cytometry.analysis.flowsom_analysis import FlowsomAnalysis, recut_run
from karcytics_plugins.flow_cytometry.analysis.sample_lens import FindingKind, audit, build_scope
from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from tests.fixtures.lens import make_sample

NK = "CD56+"


@pytest.fixture(scope="module")
def planted():
    state = FlowState()
    sample, events, _truth = make_sample("s1")
    state.data.experiment.add_sample(sample)
    analysis = FlowsomAnalysis()
    analysis.target_sample_id = "s1"
    analysis.n_events = len(events)
    analysis.k = 5
    analysis.channels = ["CD3", "CD4", "CD8", "CD56"]
    return sample, events, analysis.run(state)


def findings_at(planted, k):
    sample, events, run = planted
    recut_run(run, k)
    return audit(build_scope(sample, run, events))


@pytest.mark.parametrize("k", [5, 8, 12])
def test_the_planted_mistakes_are_found_at_any_k(planted, k):
    found = findings_at(planted, k)
    missed = [f for f in found if f.kind is FindingKind.MISSED]
    assert any(f.phenotypes[0].endswith(NK) for f in missed)  # NK cells
    merges = [f for f in found if f.kind is FindingKind.MERGES]
    assert [f.population for f in merges] == ["Lymphocytes / T cells / CD8+"]  # + NKT
    cuts = [f for f in found if f.kind is FindingKind.CUTS]
    assert [f.population for f in cuts] == ["Lymphocytes / T cells / CD4+"]


def test_a_high_k_splitting_one_population_is_not_a_merge(planted):
    merges = [f for f in findings_at(planted, 12) if f.kind is FindingKind.MERGES]
    assert all("CD4+" not in f.population for f in merges)


def test_findings_with_one_phenotype_are_one_finding(planted):
    found = findings_at(planted, 12)
    keys = [(f.kind, f.population, f.phenotypes) for f in found]
    assert len(keys) == len(set(keys))
    nk = next(f for f in found if f.kind is FindingKind.MISSED and f.phenotypes[0].endswith(NK))
    if len(nk.clusters) > 1:
        assert nk.title.startswith("Metaclusters M") and "aren't" in nk.title


def test_findings_speak_of_metaclusters_and_phenotypes(planted):
    found = findings_at(planted, 5)
    merge = next(f for f in found if f.kind is FindingKind.MERGES)
    assert merge.title.endswith("different metaclusters")
    assert "CD56+" in merge.detail and "phenotypes" in merge.detail
