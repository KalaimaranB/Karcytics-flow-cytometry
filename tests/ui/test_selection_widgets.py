"""The population picker's widgets: the selector panel and the grid popup.

The picker's rules are tested headlessly in
``tests/unit/analysis/test_population_selection.py``; this covers what only the
widgets do: wiring, the summary line, painting cells and announcing changes.
"""

import pytest

from karcytics_plugins.flow_cytometry.analysis.experiment import Sample
from karcytics_plugins.flow_cytometry.ui.widgets.selection.selector_panel import (
    SampleAndPopulationSelector,
)

pytestmark = pytest.mark.ui


def _sample(sample_id: str, names: list[str]) -> Sample:
    sample = Sample(sample_id=sample_id, display_name=sample_id)
    for name in names:
        sample.gate_tree.add_child(None, name=name)
    return sample


@pytest.fixture
def samples():
    """Both samples have Lymphocytes; only s1 has Debris."""
    return {"s1": _sample("s1", ["Lymphocytes", "Debris"]), "s2": _sample("s2", ["Lymphocytes"])}


@pytest.fixture
def selector(qtbot, samples):
    widget = SampleAndPopulationSelector(multi_population=True)
    qtbot.addWidget(widget)
    widget.refresh(samples)
    return widget


def test_the_panel_reports_the_pickers_samples_in_experiment_order(selector):
    assert selector.get_checked_sample_ids() == ["s1", "s2"]
    assert selector._summary_lbl.text() == "5 of 5 population picks selected"

    selector.population_selector._header_clicked("s1")

    assert selector.get_checked_sample_ids() == ["s2"]


def test_the_panel_passes_its_modes_to_the_picker(selector):
    selector.set_multi_population(False)
    assert selector.get_checked_populations() == [
        (sid, selector.population_selector.selection.groups.node_index[sid]["All Events"],
         "All Events")
        for sid in ("s1", "s2")
    ]  # fmt: skip

    selector.set_sample_mode(True)
    assert selector.get_checked_sample_ids() == ["s1"]


def test_a_click_announces_a_change_and_a_no_op_does_not(qtbot, selector):
    picker = selector.population_selector
    with qtbot.waitSignal(selector.selectionChanged):
        picker.check_all(False)

    with qtbot.assertNotEmitted(picker.selectionChanged):
        picker.check_all(False)


def test_in_one_sample_mode_the_active_column_header_stands_out(selector):
    selector.set_sample_mode(True)
    picker = selector.population_selector
    columns = picker.selection.sample_ids
    active = picker._header_grid.itemAtPosition(0, columns.index("s1")).widget()
    inactive = picker._header_grid.itemAtPosition(0, columns.index("s2")).widget()

    # DummyColors gives every token the same value, so compare the styling's shape.
    assert "background: transparent" not in active.styleSheet()
    assert "background: transparent" in inactive.styleSheet()
    assert active.toolTip() != inactive.toolTip()


def test_a_drag_repaints_each_crossed_cell_as_it_goes(qtbot, selector):
    picker = selector.population_selector
    picker.check_all(False)
    labels = [row.label_path for row in picker.selection.rows]

    with qtbot.waitSignal(picker.selectionChanged):
        picker._begin_cell_drag("s1", labels[0])
    picker._drag_enter_cell("s1", labels[1])

    assert picker._cell_widgets[("s1", labels[0])]._checked
    assert picker._cell_widgets[("s1", labels[1])]._checked
    picker._end_cell_drag()
    assert picker._cell_widgets[("s1", labels[1])]._checked  # rebuilt from the selection
