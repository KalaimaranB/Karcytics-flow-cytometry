"""Course 5's validators on a real Sample Lens tab (planted samples, see tests/fixtures/lens.py)."""

import pytest

from karcytics_plugins.flow_cytometry.analysis.axis_manager import AxisManager
from karcytics_plugins.flow_cytometry.analysis.population_service import PopulationService
from karcytics_plugins.flow_cytometry.analysis.sample_lens import FindingKind
from karcytics_plugins.flow_cytometry.tutorials.validators import (
    ClusteredRunValidator,
    LensFindingFocusedValidator,
    LensFindingValidator,
    LensPopulationSelectedValidator,
    LensProposalAddedValidator,
    LensProposalValidator,
    LensRunReadyValidator,
    LensSampleValidator,
)
from karcytics_plugins.flow_cytometry.ui.widgets.sample_lens import SampleLensTab
from tests.fixtures.lens import FakeUmapService, TreeController, build_lens_state


@pytest.fixture
def lens(qtbot):
    state = build_lens_state()
    tab = SampleLensTab(
        state,
        PopulationService(state),
        FakeUmapService(),
        TreeController(state),
        AxisManager(state),
    )
    state.view._sample_lens = tab  # as the workspace builder registers it
    qtbot.addWidget(tab)
    tab.show()
    qtbot.waitUntil(lambda: tab._model._active)  # catches up just after painting
    return tab, state


def _missed(tab):
    return next(f for f in tab._model.findings if f.kind is FindingKind.MISSED)


def test_the_lens_is_on_the_clustered_sample(lens):
    tab, state = lens
    assert ClusteredRunValidator("s0").validate(state)
    assert not ClusteredRunValidator("s1").validate(state)
    assert LensSampleValidator("s0").validate(state)
    assert LensRunReadyValidator().validate(state)

    tab._sample_combo.setCurrentIndex(tab._sample_combo.findData("s1"))
    assert not LensSampleValidator("s0").validate(state)
    assert not LensRunReadyValidator().validate(state)


def test_a_population_must_be_selected_by_name(lens):
    tab, state = lens
    validator = LensPopulationSelectedValidator("CD4+")
    assert not validator.validate(state)
    cd4 = tab._model.node_for_path("Lymphocytes / T cells / CD4+")
    tab._model.select(cd4.node_id)
    assert validator.validate(state)
    assert not LensPopulationSelectedValidator("CD8+").validate(state)


def test_findings_are_matched_by_kind_and_gate_and_named_live(lens):
    _, state = lens
    seen = []
    assert LensFindingValidator(FindingKind.MISSED, on_found=seen.append).validate(state)
    assert seen and seen[0].kind is FindingKind.MISSED
    assert LensFindingValidator(FindingKind.CUTS, gate="cd4+").validate(state)
    assert not LensFindingValidator(FindingKind.CUTS, gate="T cells").validate(state)
    assert not LensFindingValidator(FindingKind.MISSED, present=False).validate(state)


def test_clicking_the_finding_focuses_it(lens):
    tab, state = lens
    validator = LensFindingFocusedValidator(FindingKind.MISSED)
    assert not validator.validate(state)
    tab._on_finding_clicked(_missed(tab))
    assert validator.validate(state)


def test_proposing_then_adding_gates(lens):
    tab, state = lens
    assert not LensProposalValidator().validate(state)
    tab._on_fix_requested(_missed(tab))
    assert LensProposalValidator().validate(state)
    assert not LensProposalAddedValidator().validate(state)

    tab._accept_btn.click()
    assert LensProposalAddedValidator().validate(state)
    assert LensFindingValidator(FindingKind.MISSED, present=False).validate(state)


def test_without_the_lens_every_check_fails():
    state = build_lens_state()
    assert not LensSampleValidator("s0").validate(state)
    assert not LensFindingValidator(FindingKind.MISSED).validate(state)


def test_what_the_run_still_reports_picks_the_branch_and_the_text(lens):
    """Runs differ: Course 5 branches on what the learner's own run reports."""
    from karcytics_plugins.flow_cytometry.tutorials import course5
    from karcytics_plugins.flow_cytometry.tutorials.validators import LensNoFindingsValidator

    tab, state = lens
    steps = {s.id: s for s in course5.course_5_sample_lens.steps}
    check = steps["c5_s36b_whats_left"]
    assert check.on_success_step_id == "c5_s37_clean"
    assert check.on_fail_step_id == "c5_s37b_leftovers"

    findings = list(tab._model.findings)  # a missed cluster and a cut on CD4+
    assert not check.validator.validate(state)
    text = course5._leftover_step.text
    assert f"**{len(findings)} more**" in text
    cut = next(f for f in findings if f.kind is FindingKind.CUTS)
    assert cut.title in text and f"keeps {cut.shares[0]:.0%}" in text
    assert "a gate that cut a population" in course5._prediction_back_step.text

    # A cut sends the learner to fix it; no cut skips straight on.
    assert steps["c5_s37c_any_cut"].on_fail_step_id == "c5_s37d_fix_cut"
    assert not steps["c5_s37c_any_cut"].validator.validate(state)

    tab._model.findings = []
    assert LensNoFindingsValidator().validate(state)
    assert steps["c5_s37c_any_cut"].validator.validate(state)


def test_a_dn_merge_is_explained_not_fixed():
    from karcytics_plugins.flow_cytometry.analysis.sample_lens import Finding
    from karcytics_plugins.flow_cytometry.tutorials import course5

    dn = Finding(FindingKind.MERGES, (0, 3), "Leukocytes / T-cells / DN", shares=(0.1, 0.29))
    line = course5._leftover_line(dn)
    assert "CD3− population" in line and "Course 6" in line
