"""The Sample Lens tab on planted samples (see tests/fixtures/lens.py)."""

from dataclasses import replace

import pytest
from PySide6.QtWidgets import QLabel

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
    qtbot.waitUntil(lambda: tab._model._active)  # catches up just after painting
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


def test_backgating_works_without_a_run(lens):
    tab, state, _ = lens
    tab._sample_combo.setCurrentIndex(tab._sample_combo.findData("s1"))
    assert tab._model.scope is None
    assert "Backgating and Across samples work" in tab._scope_caption.text()

    tab._model.select(_cd4_node(state, "s1").node_id)
    assert len(_shown(tab)) == 3  # noqa: PLR2004 - the CD4+ path
    assert len(tab._model.checks) == 4  # noqa: PLR2004 - every sample


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


def _shown(tab):
    return [p for p in tab._path._plots if not p.isHidden()]


def test_the_path_plots_share_the_width_and_keep_whole_gates_in_view(lens, qtbot):
    from karcytics_plugins.flow_cytometry.ui.widgets.sample_lens.gating_path import (
        PLOT_W_MAX,
        PLOT_W_MIN,
    )

    tab, state, _ = lens
    tab._model.select(_cd4_node(state).node_id)
    qtbot.waitUntil(lambda: not tab._path._resizing)  # plots resize one at a time
    plots = _shown(tab)
    assert all(PLOT_W_MIN <= p.canvas.width() <= PLOT_W_MAX for p in plots)
    cd4 = _cd4_node(state)
    x_scale = plots[-1].canvas._x_scale
    assert x_scale.min_val < cd4.gate.x_min and cd4.gate.x_max < x_scale.max_val


def test_an_unchanged_plot_is_not_redrawn_and_a_drag_is_waited_out(lens, qtbot, monkeypatch):
    tab, state, _ = lens
    tab._model.select(_cd4_node(state).node_id)
    first = _shown(tab)[0].canvas
    calls = []
    monkeypatch.setattr(first, "set_data", lambda *a, **k: calls.append(a))

    tab._render()  # nothing changed
    assert calls == []

    monkeypatch.setattr(type(first), "is_interacting", property(lambda self: self is first))
    tab._model.select(state.data.experiment.samples["s0"].gate_tree.children[0].node_id)
    assert tab._path._pending is not None  # held back while the gate is dragged
    monkeypatch.setattr(type(first), "is_interacting", property(lambda self: False))
    qtbot.waitUntil(lambda: tab._path._pending is None)
    assert [p.caption.text() for p in _shown(tab)] == ["All Events  →  Lymphocytes"]


def test_the_wheel_scrolls_the_strip_instead_of_zooming(lens):
    tab, _, _ = lens
    assert tab._path._plot(0).canvas._wheel_zoom is False


def test_a_flowsom_run_gets_a_k_control_that_recuts_the_audit(qtbot):
    from karcytics_plugins.flow_cytometry.analysis.flowsom_analysis import FlowsomAnalysis
    from karcytics_plugins.flow_cytometry.analysis.services import experiment_edits

    state = build_lens_state()
    analysis = FlowsomAnalysis()
    analysis.target_sample_id = "s0"
    analysis.n_events = 10**6
    analysis.k = 5
    analysis.channels = ["CD3", "CD4", "CD8", "CD56"]
    experiment_edits.add_umap_run(state, analysis.run(state))
    tab = SampleLensTab(
        state,
        PopulationService(state),
        FakeUmapService(),
        TreeController(state),
        AxisManager(state),
    )
    qtbot.addWidget(tab)
    tab.resize(1400, 900)
    tab.show()
    qtbot.waitUntil(lambda: tab._model._active)  # catches up just after painting
    tab._run_combo.setCurrentIndex(tab._run_combo.count() - 1)

    assert "FlowSOM k=5" in tab._run_combo.currentText()
    assert tab._k_row.isVisibleTo(tab)
    assert "(FlowSOM, k = 5)" in tab._scope_caption.text()

    tab._k_spin.setValue(8)
    tab._k_timer.timeout.emit()

    assert tab._model.run["k"] == 8  # noqa: PLR2004
    assert "(FlowSOM, k = 8)" in tab._scope_caption.text()
    missed = next(f for f in tab._model.findings if f.kind.value == "missed")
    tab._on_fix_requested(missed)
    assert tab._path._title.text().startswith("Proposed gates · metacluster")


def test_the_lens_remembers_the_run_picked_for_each_sample(lens):
    from karcytics_plugins.flow_cytometry.analysis.flowsom_analysis import FlowsomAnalysis
    from karcytics_plugins.flow_cytometry.analysis.services import experiment_edits
    from karcytics_plugins.flow_cytometry.tutorials.validators import (
        LensKValidator,
        LensRunMethodValidator,
    )

    tab, state, _ = lens
    analysis = FlowsomAnalysis()
    analysis.target_sample_id = "s0"
    analysis.n_events = 10**6
    analysis.channels = ["CD3", "CD4", "CD8", "CD56"]
    experiment_edits.add_umap_run(state, analysis.run(state))
    state.view._sample_lens = tab
    tab._model.sample_id = None
    tab._populate_samples()
    assert LensRunMethodValidator("flowsom").validate(state)  # the newest

    umap = next(
        i for i in range(tab._run_combo.count()) if "FlowSOM" not in tab._run_combo.itemText(i)
    )
    tab._run_combo.setCurrentIndex(umap)
    assert LensRunMethodValidator("umap_hdbscan").validate(state)
    tab._sample_combo.setCurrentIndex(tab._sample_combo.findData("s1"))
    tab._sample_combo.setCurrentIndex(tab._sample_combo.findData("s0"))
    assert LensRunMethodValidator("umap_hdbscan").validate(state)

    flowsom = next(
        i for i in range(tab._run_combo.count()) if "FlowSOM" in tab._run_combo.itemText(i)
    )
    tab._run_combo.setCurrentIndex(flowsom)
    assert not LensKValidator(8).validate(state)
    tab._k_spin.setValue(8)
    tab._k_timer.timeout.emit()
    assert LensKValidator(8).validate(state)


def test_unticking_a_proposed_step_leaves_its_gate_out(lens):
    tab, _, _ = lens
    missed = next(f for f in tab._model.findings if f.kind is FindingKind.MISSED)
    tab._on_fix_requested(missed)
    first = tab._proposal.steps[0]  # the planted cluster needs one gate: ask it twice
    tab._proposal = proposal = replace(tab._proposal, steps=[first, first])
    tab._render()
    toggles = [p.toggle for p in _shown(tab)]
    assert all(t.isVisibleTo(tab) and t.isChecked() for t in toggles)
    assert len(_shown(tab)[1].canvas._current_data) < len(proposal.events)  # narrowed by step 1

    toggles[0].setChecked(False)
    assert tab._proposal.left_out == {0}
    assert _shown(tab)[0].caption.text() == "Step 1 · left out"
    assert tab._proposal_pills[0].text() == "1 of 2 gates"
    assert tab._proposal_pills[1].text() == f"F1 {first.f1:.2f}"  # step 2 alone, same box
    assert len(_shown(tab)[1].canvas._current_data) == len(proposal.events)  # no longer narrowed

    toggles[1].setChecked(False)
    assert not tab._accept_btn.isEnabled()
    toggles[0].setChecked(True)
    tab._accept_btn.click()
    assert [name for name, _ in tab._model._controller.added] == [
        f"Cluster {missed.clusters[0]}"  # the one kept step, named as the last
    ]


def test_clicking_a_sibling_gate_edits_it_on_that_plot_only(lens):
    from karcytics_plugins.flow_cytometry.analysis.gating import RectangleGate

    tab, state, _ = lens
    sample = state.data.experiment.samples["s0"]
    lymph = sample.gate_tree.children[0]
    nk = lymph.add_child(
        RectangleGate("CD3", "CD56", x_min=0, x_max=1500, y_min=0, y_max=1500), "NK"
    )

    def gates_for_display(sample_id, parent_node_id=None):
        parent = (
            sample.gate_tree.find_node_by_id(parent_node_id) if parent_node_id else sample.gate_tree
        )
        nodes = [c for c in parent.children if c.gate is not None]
        return [c.gate for c in nodes], nodes

    tab._model._controller.get_gates_for_display = gates_for_display
    state.view.current_gate_id = None
    tab._model.select(_cd4_node(state).node_id)
    plots = _shown(tab)
    t_plot = plots[1]  # Lymphocytes → T cells, where NK sits too
    t_cells = lymph.children[0]
    assert t_plot.canvas._selected_gate_id == t_cells.node_id

    canvas = t_plot.canvas
    canvas.draw()
    box = canvas._gate_overlay_artists[nk.gate.gate_id]["patch"].get_window_extent()
    x, y = canvas._ax.transData.inverted().transform(((box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2))
    assert canvas._try_select_gate(x, y)

    assert canvas._selected_gate_id == nk.node_id
    assert plots[2].canvas._selected_gate_id == _cd4_node(state).node_id  # kept its handles
    assert state.view.current_gate_id is None  # the Gating tab's selection is untouched
    tab._render()  # a redraw (as after an edit) keeps the click's choice
    assert canvas._selected_gate_id == nk.node_id


def test_focus_mode_gives_the_plots_the_tab(lens, qtbot):
    from karcytics_plugins.flow_cytometry.tutorials.validators import (
        LensColumnsValidator,
        LensFocusValidator,
    )

    tab, state, _ = lens
    state.view._sample_lens = tab
    tab._model.select(_cd4_node(state).node_id)
    qtbot.waitUntil(lambda: not tab._path._resizing)
    small = _shown(tab)[0].canvas.width()
    assert not LensFocusValidator().validate(state)

    tab._path._focus_btn.click()
    assert LensFocusValidator().validate(state)
    assert tab._sidebar.isHidden() and tab._lower.isHidden()
    tab._path.set_columns(2)
    assert LensColumnsValidator(2).validate(state)
    grid = tab._path._grid
    rows = [grid.getItemPosition(grid.indexOf(p))[:2] for p in _shown(tab)]
    assert rows == [(0, 0), (0, 1), (1, 0)]
    plot = _shown(tab)[0]
    assert plot.target is not None or plot.canvas.width() > small  # waits its turn, or done
    qtbot.waitUntil(lambda: not tab._path._resizing)
    assert not any(p.target for p in _shown(tab))
    assert plot.canvas.width() > small  # bigger, same shape
    assert plot.canvas.height() > plot.canvas.width() * 0.8  # noqa: PLR2004

    tab._path.set_focus(False)
    assert not tab._sidebar.isHidden() and not tab._lower.isHidden()
    assert tab._path._focus_btn.text() == "Focus"


def test_each_plot_switches_view_where_its_gate_allows(lens):
    from karcytics_plugins.flow_cytometry.analysis.gating import RangeGate
    from karcytics_plugins.flow_cytometry.tutorials.validators import LensPlotViewValidator
    from karcytics_plugins.flow_cytometry.ui.graph.flow_canvas import DisplayMode

    tab, state, _ = lens
    state.view._sample_lens = tab
    t_cells = state.data.experiment.samples["s0"].gate_tree.children[0].children[0]
    bright = t_cells.add_child(RangeGate("CD56", low=2000, high=10**5), "CD56 bright")
    tab._model.select(bright.node_id)
    plot = _shown(tab)[-1]
    assert plot.canvas._display_mode is DisplayMode.HISTOGRAM
    assert [plot.view.itemData(i) for i in range(plot.view.count())] == [
        "histogram",
        "vs:SSC-A",
        "vs:FSC-A",
    ]
    plot.view.setCurrentIndex(plot.view.findData("vs:SSC-A"))
    assert plot.canvas._display_mode is DisplayMode.PSEUDOCOLOR
    assert plot.canvas._y_param == "SSC-A"
    assert LensPlotViewValidator("cd56 bright", "vs:SSC-A").validate(state)

    two_d = _shown(tab)[0]  # a rectangle: 2-D views, histogram greyed out
    model = two_d.view.model()
    histogram = two_d.view.findData("histogram")
    assert not model.item(histogram).isEnabled()
    two_d.view.setCurrentIndex(two_d.view.findData("contour"))
    assert two_d.canvas._display_mode is DisplayMode.CONTOUR

    tab._model.select(_cd4_node(state).node_id)  # another population, same upstream gates
    tab._model.select(bright.node_id)
    assert _shown(tab)[0].canvas._display_mode is DisplayMode.CONTOUR  # remembered
    assert _shown(tab)[-1].canvas._y_param == "SSC-A"


def _phenograph_lens(qtbot, monkeypatch, resolution=0.1):
    from karcytics_plugins.flow_cytometry.analysis import phenograph_analysis
    from karcytics_plugins.flow_cytometry.analysis.services import experiment_edits
    from tests.fixtures.phenograph import in_process_compute

    monkeypatch.setattr(phenograph_analysis, "compute", in_process_compute)
    state = build_lens_state()
    analysis = phenograph_analysis.PhenographAnalysis()
    analysis.target_sample_id = "s0"
    analysis.n_events = 10**6
    analysis.resolution = resolution
    analysis.channels = ["CD3", "CD4", "CD8", "CD56"]
    experiment_edits.add_umap_run(state, analysis.run(state))
    umap = FakeUmapService()
    tab = SampleLensTab(
        state, PopulationService(state), umap, TreeController(state), AxisManager(state)
    )
    qtbot.addWidget(tab)
    tab.resize(1400, 900)
    tab.show()
    qtbot.waitUntil(lambda: tab._model._active)  # catches up just after painting
    tab._run_combo.setCurrentIndex(tab._run_combo.count() - 1)
    return tab, state, umap


def test_a_phenograph_run_gets_a_resolution_control_that_reclusters_the_audit(qtbot, monkeypatch):
    tab, _state, umap = _phenograph_lens(qtbot, monkeypatch)

    assert "PhenoGraph res=0.1" in tab._run_combo.currentText()
    assert "(PhenoGraph, res = 0.1)" in tab._scope_caption.text()
    assert tab._k_label.text() == "Resolution:"
    assert tab._res_spin.isVisibleTo(tab) and not tab._k_spin.isVisibleTo(tab)
    before = int(tab._model.run["clusters"].max()) + 1

    tab._res_spin.setValue(2.0)
    tab._k_timer.timeout.emit()

    assert ("recluster", 2.0) in umap.calls
    assert tab._model.run["resolution"] == 2.0  # noqa: PLR2004
    assert int(tab._model.run["clusters"].max()) + 1 > before
    assert "(PhenoGraph, res = 2.0)" in tab._scope_caption.text()
    assert tab._run_status.text() == ""
    assert tab._run_btn.isEnabled()


def test_phenograph_findings_name_clusters_and_the_map_draws_their_links(qtbot, monkeypatch):
    from matplotlib.collections import LineCollection

    tab, _state, _umap = _phenograph_lens(qtbot, monkeypatch, resolution=2.0)
    missed = next(f for f in tab._model.findings if f.kind.value == "missed")
    assert missed.title.startswith("Cluster C")
    axes = tab._map._canvas.figure.axes
    assert any(isinstance(c, LineCollection) for ax in axes for c in ax.collections)
    tab._on_fix_requested(missed)
    assert tab._path._title.text().startswith("Proposed gates · cluster C")


def test_a_failed_recluster_says_so_and_keeps_the_run(qtbot, monkeypatch):
    tab, _state, umap = _phenograph_lens(qtbot, monkeypatch)
    clusters = tab._model.run["clusters"].copy()
    umap.recluster_phenograph = lambda run, res, on_done, on_error_cb: on_error_cb("daemon gone")
    tab._res_spin.setValue(0.5)
    tab._k_timer.timeout.emit()
    assert "daemon gone" in tab._run_status.text()
    assert (tab._model.run["clusters"] == clusters).all()
    assert tab._res_spin.value() == 0.1  # noqa: PLR2004 - back to the run's own setting


def test_findings_say_whether_another_run_of_the_population_agrees(lens):
    from karcytics_plugins.flow_cytometry.analysis.services import experiment_edits

    tab, state, _ = lens
    run = state.data.umap_results["s0::root"][0]
    experiment_edits.add_umap_run(state, dict(run, name="Second look"))
    tab._model.refresh()
    notes = [label.text() for label in tab._findings.findChildren(QLabel, "SampleLensAgreement")]
    assert len(notes) == len(tab._model.findings)
    assert all(n == "Also found by UMAP + HDBSCAN" for n in notes)


def test_the_tab_paints_before_catching_up(qtbot):
    """Switching to the tab is instant: the audit and plots follow a moment later."""
    state = build_lens_state()
    tab = SampleLensTab(
        state,
        PopulationService(state),
        FakeUmapService(),
        TreeController(state),
        AxisManager(state),
    )
    qtbot.addWidget(tab)
    tab.show()
    assert not tab._model._active  # nothing computed during the switch
    qtbot.waitUntil(lambda: tab._model._active)
    assert tab._model.scope is not None


def test_a_theme_change_redraws_the_plots(lens, qtbot):
    tab, state, _ = lens
    tab._model.select(_cd4_node(state).node_id)
    plots = _shown(tab)
    assert all(p.drawn is not None for p in plots)
    redrawn = []
    tab._map.show_scope = lambda *a, **k: redrawn.append(a)  # type: ignore[method-assign]
    tab._apply_theme_styles()
    assert redrawn  # the map, drawn with the new colours
    assert all(p.drawn is not None for p in plots)  # and every path plot, again


def test_the_lens_says_it_is_under_construction(lens):
    tab, _, _ = lens
    banner = tab.findChild(QLabel, "SampleLensBetaBanner")
    assert banner is not None and banner.isVisible()
    assert "under construction" in banner.text().lower()


def test_plots_waiting_to_resize_say_so(lens, qtbot):
    tab, state, _ = lens
    tab._model.select(_cd4_node(state).node_id)
    qtbot.waitUntil(lambda: not tab._path._resizing)
    tab._path.set_focus(True)
    waiting = [p for p in _shown(tab) if p.target]
    assert waiting  # resized one per turn of the event loop
    assert all(p.canvas._overlay_manager._loading_label.isVisible() for p in waiting)
    assert "Loading plot" in waiting[0].canvas._overlay_manager._loading_label.text()
    qtbot.waitUntil(lambda: not tab._path._resizing)


def test_plots_per_row_offers_all_as_a_choice(lens):
    """'All' is picked from the list, not typed as a number."""
    from karcytics_plugins.flow_cytometry.tutorials.validators import LensColumnsValidator

    tab, state, _ = lens
    state.view._sample_lens = tab
    combo = tab._path._columns
    assert combo.itemText(0) == "All"
    combo.setCurrentIndex(combo.findText("2"))
    assert LensColumnsValidator(2).validate(state)
    combo.setCurrentIndex(combo.findText("All"))
    assert LensColumnsValidator(0).validate(state)
