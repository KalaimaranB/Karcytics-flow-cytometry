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
