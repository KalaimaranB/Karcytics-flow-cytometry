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
def test_unchecking_a_sample_removes_its_populations(qtbot, two_samples_shared_and_specific):
    widget = SampleAndPopulationSelector(multi_population=True)
    qtbot.addWidget(widget)
    widget.refresh(two_samples_shared_and_specific)

    widget.sample_list.set_all_checked(False)
    # Re-check only s1.
    item = widget.sample_list.list_widget.item(0)
    from PyQt6.QtCore import Qt

    if item.data(Qt.ItemDataRole.UserRole) != "s1":
        item = widget.sample_list.list_widget.item(1)
    item.setCheckState(Qt.CheckState.Checked)

    assert widget.get_checked_sample_ids() == ["s1"]
    checked_sids = {sid for sid, _nid, _label in widget.get_checked_populations()}
    assert checked_sids == {"s1"}


def _find_tree_item(tree, text_fragment: str):
    from PyQt6.QtWidgets import QTreeWidgetItemIterator

    it = QTreeWidgetItemIterator(tree)
    while it.value():
        item = it.value()
        if text_fragment in item.text(0):
            return item
        it += 1
    return None


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
    picks it for every sample at once — the whole point of reusing the
    grouped Shared/Sample-Specific tree for one-per-sample mode instead of
    the old flat per-sample tree, which required clicking it under every
    sample individually.
    """
    widget = SampleAndPopulationSelector(multi_population=False)
    qtbot.addWidget(widget)
    widget.refresh(two_samples_shared_and_specific)

    from PyQt6.QtCore import Qt

    lymph_item = _find_tree_item(widget.population_tree.tree, "Lymphocytes")
    assert lymph_item is not None
    lymph_item.setCheckState(0, Qt.CheckState.Checked)

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

    from PyQt6.QtCore import Qt

    debris_item = _find_tree_item(widget.population_tree.tree, "Debris")
    assert debris_item is not None
    debris_item.setCheckState(0, Qt.CheckState.Checked)

    checked = widget.get_checked_populations()
    labels_by_sid = {sid: label for sid, _nid, label in checked}
    assert labels_by_sid == {"s1": "Debris", "s2": "All Events"}
