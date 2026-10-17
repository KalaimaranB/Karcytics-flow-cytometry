"""The Sample Lens tab on planted samples (see tests/fixtures/lens.py)."""

import pytest

from karcytics_plugins.flow_cytometry.analysis.axis_manager import AxisManager
from karcytics_plugins.flow_cytometry.analysis.experiment import SampleRole
from karcytics_plugins.flow_cytometry.analysis.population_service import PopulationService
from karcytics_plugins.flow_cytometry.analysis.sample_lens import FindingKind
from karcytics_plugins.flow_cytometry.ui.widgets.sample_lens import SampleLensTab
from tests.fixtures.lens import (
    FakeUmapService,
    TreeController,
    build_lens_state,
    make_run,
    make_sample,
)

CD4_PATH = "Lymphocytes / T cells / CD4+"


@pytest.fixture
def lens(qtbot):
    state = build_lens_state()
    umap = FakeUmapService()
    controller = TreeController(state)
    tab = SampleLensTab(state, PopulationService(state), umap, controller, AxisManager(state))
    qtbot.addWidget(tab)
    tab.resize(1400, 900)
    tab.show()
    return tab, state, umap


def _cd4_node(state, sid="s0"):
    return state.data.experiment.samples[sid].gate_tree.children[0].children[0].children[0]


def _visible_cards(tab):
    layout = tab._findings._layout
    return [layout.itemAt(i).widget() for i in range(layout.count())]


def test_opens_on_the_current_sample_and_its_clustered_run(lens):
    tab, _, _ = lens
    model = tab._model
    assert model.sample_id == "s0"
    assert model.run_ref is not None and model.run_ref.key == "s0::root"
    assert {f.kind for f in model.findings} == set(FindingKind)
    assert len(_visible_cards(tab)) == 3  # noqa: PLR2004
    assert "Judging 2 final populations" in tab._scope_caption.text()


def test_selecting_a_population_shows_its_path_and_every_sample(lens):
    tab, state, _ = lens
    tab._model.select(_cd4_node(state).node_id)

    shown = [p for p in tab._path._plots if not p.isHidden()]
    assert [p.caption.text() for p in shown] == [
        "All Events  →  Lymphocytes",
        "Lymphocytes  →  T cells",
        "T cells  →  CD4+",
    ]
    table = tab._across._table
    assert table.rowCount() == 4  # noqa: PLR2004
    assert "outlier" in table.item(2, 4).text()  # s2 has dimmer CD4


def test_clicking_a_population_row_selects_it(lens):
    tab, _, _ = lens
    rows = tab._populations
    texts = [rows.item(i).text() for i in range(rows.count())]
    assert "Lymphocytes" in texts[0] and texts[1].strip() == "T cells"  # indented by depth
    rows.itemClicked.emit(rows.item(next(i for i, t in enumerate(texts) if t.strip() == "CD4+")))

    assert tab._model.selected_path() == CD4_PATH
    current = tab._populations.currentItem()  # rebuilt on render, selection kept
    assert current.text().strip() == "CD4+" and current.font().bold()  # a final population


def test_controls_are_left_out_of_across_samples(lens):
    tab, state, _ = lens
    state.data.experiment.samples["s3"].role = SampleRole.SINGLE_STAIN
    tab._model.select(_cd4_node(state).node_id)
    assert [c.sample_id for c in tab._model.checks] == ["s0", "s1", "s2"]


def test_a_finding_selects_its_population(lens):
    tab, state, _ = lens
    merges = next(f for f in tab._model.findings if f.kind is FindingKind.MERGES)
    tab._on_finding_clicked(merges)
    assert tab._model.selected_path() == "Lymphocytes / T cells / CD8+"
    assert tab._emphasis == merges.clusters


def test_a_sample_without_a_run_says_how_to_get_one(lens):
    tab, _, _ = lens
    tab._sample_combo.setCurrentIndex(tab._sample_combo.findData("s1"))
    assert tab._model.scope is None
    assert "No clustering run" in tab._scope_caption.text()
    assert len(_visible_cards(tab)) == 1


def test_running_umap_stores_the_run_and_switches_to_it(lens, qtbot):
    tab, state, umap = lens
    tab._sample_combo.setCurrentIndex(tab._sample_combo.findData("s1"))
    tab._run_btn.click()

    params, on_done, _ = umap.calls[-1]
    assert params.target_sample_id == "s1" and params.run_hdbscan
    assert not tab._run_btn.isEnabled()

    _, events, truth = make_sample("s1", seed=1)
    on_done({**make_run(events, truth), "sample_id": "s1", "name": "Sample Lens"})
    qtbot.waitUntil(lambda: tab._model.scope is not None)
    assert len(state.data.umap_results["s1::root"]) == 1
    assert tab._run_btn.isEnabled()


def test_a_failed_run_is_reported(lens, qtbot):
    tab, _, umap = lens
    tab._run_btn.click()
    umap.calls[-1][2]("boom")
    qtbot.waitUntil(lambda: "boom" in tab._run_status.text())
    assert tab._run_btn.isEnabled()


def test_a_gate_edit_anywhere_refreshes_the_findings(lens, qtbot):
    tab, state, _ = lens
    sample = state.data.experiment.samples["s0"]
    _cd4_node(state).gate.x_min = 1600  # move the edge off the CD4 T cells
    sample.gate_tree.invalidate_mask_cache()  # as the gate coordinator does on an edit

    tab._model._on_gates_changed({"sample_id": "s0"})
    qtbot.waitUntil(lambda: all(f.kind is not FindingKind.CUTS for f in tab._model.findings))


def test_proposing_gates_previews_them_then_adds_the_chain(lens):
    tab, state, _ = lens
    missed = next(f for f in tab._model.findings if f.kind is FindingKind.MISSED)
    tab._on_fix_requested(missed)

    assert not tab._proposal_bar.isHidden()
    proposal = tab._proposal
    assert proposal is not None and proposal.steps
    assert proposal.steps[-1].f1 > 0.9  # noqa: PLR2004
    shown = [p for p in tab._path._plots if not p.isHidden()]
    assert len(shown) == len(proposal.steps)
    assert tab._path._title.text() == f"Proposed gates · cluster {missed.clusters[0]}"

    tab._accept_btn.click()

    controller = tab._model._controller
    names = [name for name, _ in controller.added]
    assert names[-1] == f"Cluster {missed.clusters[0]}"
    # A chain under the run's population (All Events): each step under the previous one.
    parents = [parent for _, parent in controller.added]
    assert parents[0] is None
    assert tab._proposal_bar.isHidden()
    assert all(f.kind is not FindingKind.MISSED for f in tab._model.findings)
    assert tab._model.population_name(tab._model.selected_node_id) == names[-1]


def test_cancelling_a_proposal_changes_nothing(lens):
    tab, state, _ = lens
    missed = next(f for f in tab._model.findings if f.kind is FindingKind.MISSED)
    tab._on_fix_requested(missed)
    tab._close_proposal()
    assert tab._proposal_bar.isHidden()
    assert tab._model._controller.added == []
    assert any(f.kind is FindingKind.MISSED for f in tab._model.findings)
