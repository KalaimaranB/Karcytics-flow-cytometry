"""UI smoke tests for the shared sample/population selector widgets used by
the Statistics and Comparisons tabs.
"""

import pytest

from karcytics_plugins.flow_cytometry.analysis.experiment import Sample
from karcytics_plugins.flow_cytometry.ui.widgets.selection.selector_panel import (
    SampleAndPopulationSelector,
)


def _sample_with_siblings(sample_id: str, names: list[str]) -> Sample:
    sample = Sample(sample_id=sample_id, display_name=sample_id)
    for name in names:
        sample.gate_tree.add_child(None, name=name)
    return sample


@pytest.fixture
def two_samples_shared_and_specific():
    # Both samples share "Lymphocytes"; s1 additionally has "Debris" alone.
    s1 = _sample_with_siblings("s1", ["Lymphocytes", "Debris"])
    s2 = _sample_with_siblings("s2", ["Lymphocytes"])
    return {"s1": s1, "s2": s2}


@pytest.fixture
def two_samples_each_with_a_unique_population():
    # No shared populations besides the "All Events" sentinel — each sample
    # has its own, distinct population.
    s1 = _sample_with_siblings("s1", ["B-cells"])
    s2 = _sample_with_siblings("s2", ["UMAP B Cells"])
    return {"s1": s1, "s2": s2}


def _row(widget: SampleAndPopulationSelector, label: str):
    return next(r for r in widget.population_selector._rows if r.label_path == label)


@pytest.mark.ui
def test_multi_select_defaults_all_checked_and_groups_correctly(
    qtbot, two_samples_shared_and_specific
):
    widget = SampleAndPopulationSelector(multi_population=True)
    qtbot.addWidget(widget)

    widget.refresh(two_samples_shared_and_specific)

    assert set(widget.get_checked_sample_ids()) == {"s1", "s2"}

    checked = widget.get_checked_populations()
    checked_labels = {(sid, label) for sid, _node_id, label in checked}

    # "All Events" and "Lymphocytes" are shared, so both samples get them.
    assert ("s1", "All Events") in checked_labels
    assert ("s2", "All Events") in checked_labels
    assert ("s1", "Lymphocytes") in checked_labels
    assert ("s2", "Lymphocytes") in checked_labels
    # "Debris" only exists on s1.
    assert ("s1", "Debris") in checked_labels
    assert ("s2", "Debris") not in checked_labels


@pytest.mark.ui
def test_unchecking_a_sample_column_removes_its_populations(qtbot, two_samples_shared_and_specific):
    """There's no separate sample checklist anymore — a whole sample is
    included/excluded by clicking its own column header in the grid.
    """
    widget = SampleAndPopulationSelector(multi_population=True)
    qtbot.addWidget(widget)
    widget.refresh(two_samples_shared_and_specific)
    assert set(widget.get_checked_sample_ids()) == {"s1", "s2"}

    widget.population_selector._toggle_column("s2")  # uncheck s2's whole column

    assert widget.get_checked_sample_ids() == ["s1"]
    checked_sids = {sid for sid, _nid, _label in widget.get_checked_populations()}
    assert checked_sids == {"s1"}


@pytest.mark.ui
def test_multi_select_can_pick_different_populations_per_sample(
    qtbot, two_samples_each_with_a_unique_population
):
    """The original ask this grid replaces the tree to support: exactly one
    population from sample 1, a *different* population from sample 2 — no
    cross product, no per-row exclusion hack needed.
    """
    widget = SampleAndPopulationSelector(multi_population=True)
    qtbot.addWidget(widget)
    widget.refresh(two_samples_each_with_a_unique_population)

    widget.population_selector.check_all(False)
    widget.population_selector._toggle_cell("s1", "B-cells")
    widget.population_selector._toggle_cell("s2", "UMAP B Cells")

    checked = widget.get_checked_populations()
    checked_labels = {(sid, label) for sid, _nid, label in checked}
    assert checked_labels == {("s1", "B-cells"), ("s2", "UMAP B Cells")}


@pytest.mark.ui
def test_late_arriving_population_stays_unchecked_after_user_has_curated(
    qtbot, two_samples_each_with_a_unique_population
):
    """A population that only becomes visible on a later refresh() call —
    e.g. a gate that finishes propagating after the user already clicked
    None and hand-picked a couple of populations — must NOT get silently
    auto-checked. Before the `_user_has_interacted` guard, any refresh()
    (sample checklist toggle, tab switch, ...) that happened to run after
    the new population appeared would default-check it with no click behind
    it at all.
    """
    widget = SampleAndPopulationSelector(multi_population=True)
    qtbot.addWidget(widget)
    widget.refresh(two_samples_each_with_a_unique_population)

    widget.population_selector.check_all(False)
    widget.population_selector._toggle_cell("s1", "B-cells")
    assert {(sid, label) for sid, _nid, label in widget.get_checked_populations()} == {
        ("s1", "B-cells")
    }

    # A population that didn't exist at the first refresh appears later
    # (mirrors a gate propagating onto a sample after the fact).
    two_samples_each_with_a_unique_population["s2"].gate_tree.add_child(None, name="Leukocytes")
    two_samples_each_with_a_unique_population["s1"].gate_tree.add_child(None, name="Leukocytes")

    # Some unrelated refresh happens (any of these mirrors a real trigger:
    # a sample checklist toggle, or a plain tab-switch refresh() re-call).
    widget.refresh(two_samples_each_with_a_unique_population)

    checked_labels = {label for _sid, _nid, label in widget.get_checked_populations()}
    assert "Leukocytes" not in checked_labels

    # Explicitly checking it afterwards still works normally.
    widget.population_selector._toggle_row(_row(widget, "Leukocytes"))
    checked_labels = {(sid, label) for sid, _nid, label in widget.get_checked_populations()}
    assert ("s1", "Leukocytes") in checked_labels
    assert ("s2", "Leukocytes") in checked_labels


@pytest.mark.ui
def test_single_sample_mode_defaults_to_one_sample_and_switches_on_header_click(
    qtbot, two_samples_shared_and_specific
):
    """Plot types like Pseudocolor Overlay only ever render one sample —
    `set_single_sample_mode` is the sole mechanism enforcing that once
    there's no separate sample checklist. Enabling it with samples already
    checked collapses to one; a column-header click switches which one is
    active, visibly (the header itself gets highlighted) and in one click.
    """
    widget = SampleAndPopulationSelector(multi_population=True)
    qtbot.addWidget(widget)
    widget.refresh(two_samples_shared_and_specific)
    assert set(widget.get_checked_sample_ids()) == {"s1", "s2"}

    widget.set_sample_mode(True)
    assert widget.get_checked_sample_ids() == ["s1"]

    picker = widget.population_selector
    assert picker._active_sample_id() == "s1"

    # Column-header click switches the active sample.
    picker._toggle_column("s2")
    assert widget.get_checked_sample_ids() == ["s2"]
    assert picker._active_sample_id() == "s2"

    # Clicking the already-active column again is a no-op (not a toggle-off
    # that would leave zero samples selected).
    picker._toggle_column("s2")
    assert widget.get_checked_sample_ids() == ["s2"]

    # The active column's header is visibly distinguished from the rest —
    # column order in the grid matches picker._sample_ids. (Can't compare
    # against Colors.ACCENT_PRIMARY directly: the test env's DummyColors
    # returns the same "#000000" for every token, so assert on the
    # structural styling difference instead.)
    s2_col = picker._sample_ids.index("s2")
    s1_col = picker._sample_ids.index("s1")
    active_header = picker._header_grid.itemAtPosition(0, s2_col).widget()
    inactive_header = picker._header_grid.itemAtPosition(0, s1_col).widget()
    assert "background: transparent" not in active_header.styleSheet()
    assert "background: transparent" in inactive_header.styleSheet()
    assert active_header.toolTip() != inactive_header.toolTip()

    # Switching back to multi-sample mode restores both samples.
    widget.set_sample_mode(False)
    assert set(widget.get_checked_sample_ids()) == {"s1", "s2"}


@pytest.mark.ui
def test_drag_select_checks_every_cell_crossed_in_one_pass(qtbot, two_samples_shared_and_specific):
    """A press-and-drag down a column should behave like clicking each cell
    it crosses, painting them all to the same (checked) target state.
    """
    widget = SampleAndPopulationSelector(multi_population=True)
    qtbot.addWidget(widget)
    widget.refresh(two_samples_shared_and_specific)

    selector = widget.population_selector
    selector.check_all(False)
    labels = [r.label_path for r in selector._rows]

    selector._begin_cell_drag("s1", labels[0])
    for label in labels[1:]:
        selector._drag_enter_cell("s1", label)
    selector._end_cell_drag()

    checked_labels = {(sid, label) for sid, _nid, label in widget.get_checked_populations()}
    s1_applicable = {
        label for label in labels if label in selector._groups.node_index.get("s1", {})
    }
    assert checked_labels == {("s1", label) for label in s1_applicable}
    assert checked_labels  # non-empty: the drag actually selected something


@pytest.mark.ui
def test_drag_select_starting_on_a_checked_cell_deselects_the_path(
    qtbot, two_samples_shared_and_specific
):
    """Dragging back over an already-checked path clears it — the same
    gesture selects or deselects depending on the first cell's state.
    """
    widget = SampleAndPopulationSelector(multi_population=True)
    qtbot.addWidget(widget)
    widget.refresh(two_samples_shared_and_specific)

    selector = widget.population_selector
    labels = [r.label_path for r in selector._rows]
    assert widget.get_checked_populations()  # defaults to all-checked

    selector._begin_cell_drag("s1", labels[0])
    for label in labels[1:]:
        selector._drag_enter_cell("s1", label)
    selector._end_cell_drag()

    checked_sids = {sid for sid, _nid, _label in widget.get_checked_populations()}
    assert "s1" not in checked_sids
    assert "s2" in checked_sids  # only s1's path was dragged over


@pytest.mark.ui
def test_multi_select_row_click_toggles_shared_population_for_every_sample(
    qtbot, two_samples_shared_and_specific
):
    widget = SampleAndPopulationSelector(multi_population=True)
    qtbot.addWidget(widget)
    widget.refresh(two_samples_shared_and_specific)

    widget.population_selector.check_all(False)
    widget.population_selector._toggle_row(_row(widget, "Lymphocytes"))

    checked_labels = {(sid, label) for sid, _nid, label in widget.get_checked_populations()}
    assert checked_labels == {("s1", "Lymphocytes"), ("s2", "Lymphocytes")}


@pytest.mark.ui
def test_single_select_mode_defaults_to_all_events_per_sample(
    qtbot, two_samples_shared_and_specific
):
    widget = SampleAndPopulationSelector(multi_population=False)
    qtbot.addWidget(widget)
    widget.refresh(two_samples_shared_and_specific)

    checked = widget.get_checked_populations()
    assert len(checked) == 2  # one per sample
    assert all(label == "All Events" for _sid, _nid, label in checked)


@pytest.mark.ui
def test_single_select_mode_shared_label_applies_to_every_sample(
    qtbot, two_samples_shared_and_specific
):
    """Checking a shared population ("Lymphocytes", present on both samples)
    picks it for every sample at once — a row-label click sets it as the
    pick for every column, matching what the old grouped tree's "check one
    shared row" convenience did.
    """
    widget = SampleAndPopulationSelector(multi_population=False)
    qtbot.addWidget(widget)
    widget.refresh(two_samples_shared_and_specific)

    widget.population_selector._toggle_row(_row(widget, "Lymphocytes"))

    checked = widget.get_checked_populations()
    labels_by_sid = {sid: label for sid, _nid, label in checked}
    assert labels_by_sid == {"s1": "Lymphocytes", "s2": "Lymphocytes"}


@pytest.mark.ui
def test_single_select_mode_specific_label_overrides_just_that_sample(
    qtbot, two_samples_shared_and_specific
):
    """Checking a sample-specific population ("Debris", only on s1) overrides
    just s1's pick, leaving s2's ("All Events", the shared default) untouched.
    """
    widget = SampleAndPopulationSelector(multi_population=False)
    qtbot.addWidget(widget)
    widget.refresh(two_samples_shared_and_specific)

    widget.population_selector._toggle_cell("s1", "Debris")

    checked = widget.get_checked_populations()
    labels_by_sid = {sid: label for sid, _nid, label in checked}
    assert labels_by_sid == {"s1": "Debris", "s2": "All Events"}
