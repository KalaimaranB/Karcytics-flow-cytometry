"""The population picker's rules, without Qt: defaults, the two modes, and every click."""

from __future__ import annotations

import pytest

from karcytics_plugins.flow_cytometry.analysis.experiment import Sample
from karcytics_plugins.flow_cytometry.analysis.population_matching import ALL_EVENTS_LABEL
from karcytics_plugins.flow_cytometry.analysis.population_selection import PopulationSelection

ALL = ALL_EVENTS_LABEL


def _sample(sample_id: str, names: list[str]) -> Sample:
    sample = Sample(sample_id=sample_id, display_name=sample_id.upper())
    for name in names:
        sample.gate_tree.add_child(None, name=name)
    return sample


@pytest.fixture
def shared():
    """Both samples have Lymphocytes; only s1 has Debris."""
    return {"s1": _sample("s1", ["Lymphocytes", "Debris"]), "s2": _sample("s2", ["Lymphocytes"])}


@pytest.fixture
def unique():
    """Nothing shared but All Events: each sample has its own population."""
    return {"s1": _sample("s1", ["B-cells"]), "s2": _sample("s2", ["UMAP B Cells"])}


def _picker(samples, *, multi=True, single=False) -> PopulationSelection:
    picker = PopulationSelection()
    picker.set_multi_select(multi)
    picker.set_single_sample(single)
    picker.refresh(samples)
    return picker


def _cells(picker: PopulationSelection) -> set[tuple[str, str]]:
    return {(sid, label) for sid, _node_id, label in picker.checked_populations()}


# ── defaults ──


def test_everything_a_sample_has_starts_checked(shared):
    assert _cells(_picker(shared)) == {
        ("s1", ALL), ("s1", "Lymphocytes"), ("s1", "Debris"), ("s2", ALL), ("s2", "Lymphocytes"),
    }  # fmt: skip


def test_one_population_per_sample_starts_on_all_events(shared):
    assert _cells(_picker(shared, multi=False)) == {("s1", ALL), ("s2", ALL)}


def test_one_sample_mode_starts_on_the_first_samples_all_events(shared):
    assert _cells(_picker(shared, single=True)) == {("s1", ALL)}


def test_checked_populations_come_in_grid_order_with_node_ids(shared):
    picker = _picker(shared)

    found = picker.checked_populations()

    rows = [row.label_path for row in picker.rows]
    assert [(s, label) for s, _n, label in found] == sorted(
        _cells(picker), key=lambda c: (rows.index(c[1]), ("s1", "s2").index(c[0]))
    )
    assert all(node_id == picker.groups.node_index[s][label] for s, node_id, label in found)


def test_a_population_that_turns_up_after_the_user_picked_stays_unchecked(unique):
    picker = _picker(unique)
    picker.check_all(False)
    picker.toggle_cell("s1", "B-cells")
    for sample in unique.values():  # a gate propagates late
        sample.gate_tree.add_child(None, name="Leukocytes")

    picker.refresh(unique)

    assert _cells(picker) == {("s1", "B-cells")}
    picker.toggle_row("Leukocytes")  # and a click still checks it
    assert {("s1", "Leukocytes"), ("s2", "Leukocytes")} <= _cells(picker)


def test_before_any_click_a_late_population_starts_checked(unique):
    picker = _picker(unique)
    unique["s1"].gate_tree.add_child(None, name="Late")

    picker.refresh(unique)

    assert ("s1", "Late") in _cells(picker)


# ── clicks ──


def test_different_populations_for_different_samples(unique):
    picker = _picker(unique)
    picker.check_all(False)

    picker.toggle_cell("s1", "B-cells")
    picker.toggle_cell("s2", "UMAP B Cells")

    assert _cells(picker) == {("s1", "B-cells"), ("s2", "UMAP B Cells")}


def test_a_cell_the_sample_lacks_cannot_be_checked(shared):
    picker = _picker(shared)

    assert not picker.toggle_cell("s2", "Debris")
    assert not picker.applies("s2", "Debris")


def test_a_column_header_unchecks_then_rechecks_the_whole_sample(shared):
    picker = _picker(shared)

    picker.toggle_column("s2")
    assert {sid for sid, _label in _cells(picker)} == {"s1"}
    picker.toggle_column("s2")
    assert ("s2", "Lymphocytes") in _cells(picker)


def test_a_row_toggles_a_shared_population_for_every_sample(shared):
    picker = _picker(shared)
    picker.check_all(False)

    picker.toggle_row("Lymphocytes")
    assert _cells(picker) == {("s1", "Lymphocytes"), ("s2", "Lymphocytes")}
    picker.toggle_row("Lymphocytes")
    assert _cells(picker) == set()


def test_with_one_per_sample_a_row_becomes_every_samples_pick(shared):
    picker = _picker(shared, multi=False)

    picker.toggle_row("Lymphocytes")

    assert _cells(picker) == {("s1", "Lymphocytes"), ("s2", "Lymphocytes")}


def test_with_one_per_sample_a_cell_replaces_only_its_samples_pick(shared):
    picker = _picker(shared, multi=False)

    picker.toggle_cell("s1", "Debris")

    assert _cells(picker) == {("s1", "Debris"), ("s2", ALL)}


def test_all_and_none_follow_the_mode(shared):
    picker = _picker(shared, multi=False)
    assert picker.check_all(False) and _cells(picker) == set()
    assert picker.check_all(True) and _cells(picker) == {("s1", ALL), ("s2", ALL)}
    assert not picker.check_all(True)  # already so: nothing changed


def test_a_drag_paints_its_path_to_the_first_cells_new_state(shared):
    picker = _picker(shared)
    picker.check_all(False)
    labels = [row.label_path for row in picker.rows]

    picker.begin_drag("s1", labels[0])
    for label in labels[1:]:
        picker.drag_over("s1", label)
    picker.drag_over("s1", labels[0])  # crossing a cell twice doesn't flip it back
    assert picker.end_drag()

    assert _cells(picker) == {("s1", label) for label in labels if picker.applies("s1", label)}
    picker.begin_drag("s1", labels[0])  # started on a checked cell: the drag clears
    for label in labels[1:]:
        picker.drag_over("s1", label)
    picker.end_drag()
    assert _cells(picker) == set()


def test_moving_over_cells_without_a_drag_changes_nothing(shared):
    picker = _picker(shared)

    assert not picker.drag_over("s1", "Debris")
    assert not picker.end_drag()


# ── modes ──


def test_one_sample_mode_keeps_the_first_checked_sample_until_a_header_switches_it(shared):
    picker = _picker(shared)

    picker.set_single_sample(True)
    assert {sid for sid, _l in _cells(picker)} == {"s1"}
    assert picker.toggle_column("s2")
    assert {sid for sid, _l in _cells(picker)} == {"s2"}
    assert not picker.toggle_column("s2")  # the current sample: no toggling it off

    picker.set_single_sample(False)
    assert {sid for sid, _l in _cells(picker)} == {"s1", "s2"}


def test_entering_one_sample_mode_keeps_the_sample_the_user_picked_most_for(unique):
    picker = _picker(unique)
    picker.check_all(False)
    picker.toggle_cell("s1", ALL)
    picker.toggle_cell("s2", ALL)
    picker.toggle_cell("s2", "UMAP B Cells")

    picker.set_single_sample(True)

    assert _cells(picker) == {("s2", ALL), ("s2", "UMAP B Cells")}  # exactly what was picked


def test_in_one_sample_mode_a_cell_in_another_column_moves_the_selection(shared):
    picker = _picker(shared, single=True)

    picker.toggle_cell("s2", "Lymphocytes")

    assert _cells(picker) == {("s2", "Lymphocytes")}


def test_one_per_sample_keeps_all_events_if_checked_else_the_first_pick(shared):
    picker = _picker(shared)
    picker.toggle_cell("s2", ALL)  # s2 now has only Lymphocytes

    picker.set_multi_select(False)

    assert _cells(picker) == {("s1", ALL), ("s2", "Lymphocytes")}


def test_back_to_many_per_sample_catches_up_the_defaults_only_if_untouched(shared):
    untouched = _picker(shared, multi=False)
    untouched.set_multi_select(True)
    assert ("s1", "Debris") in _cells(untouched)

    picked = _picker(shared, multi=False)
    picked.toggle_cell("s1", "Debris")
    picked.set_multi_select(True)
    assert _cells(picked) == {("s1", "Debris"), ("s2", ALL)}  # no flood of unpicked rows


def test_switching_to_the_mode_it_is_in_changes_nothing(shared):
    picker = _picker(shared)

    assert not picker.set_multi_select(True)
    assert not picker.set_single_sample(False)


def test_the_summary_counts_picks_or_names_the_one_sample(shared):
    picker = _picker(shared)
    names = {"s1": "Sample One"}
    assert picker.summary(names) == "5 of 5 population picks selected"

    picker.set_single_sample(True)
    assert picker.summary(names).startswith("Comparing within Sample One")
    picker.check_all(False)
    assert picker.summary(names) == "No sample selected."
