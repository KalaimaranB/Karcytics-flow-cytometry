"""Tests for the Properties | Histogram switch on the properties panel."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from karcytics_plugins.flow_cytometry.ui.widgets import properties_panel
from karcytics_plugins.flow_cytometry.ui.widgets.properties_panel import PropertiesPanel

pytestmark = pytest.mark.ui

SAMPLE_ID = "test_sample_1"


@pytest.fixture
def remembered_choice(monkeypatch):
    """Stand-in for the persisted toggle choice (FlowConfig)."""
    choice = {"histogram": False}
    monkeypatch.setattr(
        properties_panel.FlowConfig,
        "get_properties_histogram_view",
        classmethod(lambda cls: choice["histogram"]),
    )
    monkeypatch.setattr(
        properties_panel.FlowConfig,
        "set_properties_histogram_view",
        classmethod(lambda cls, value: choice.update(histogram=value)),
    )
    return choice


@pytest.fixture
def make_panel(qtbot, flow_state, remembered_choice):
    def _make():
        panel = PropertiesPanel(
            flow_state, flow_state.axis_manager, flow_state.population_service, MagicMock()
        )
        qtbot.addWidget(panel)
        return panel

    return _make


def _showing_histogram(panel) -> bool:
    return panel._top_stack.currentWidget() is panel._histogram_panel is not None


def test_starts_on_properties_without_building_the_histogram(make_panel):
    panel = make_panel()

    assert panel._btn_properties.isChecked()
    assert panel._histogram_panel is None
    assert panel._top_stack.currentWidget() is panel._scroll


def test_toggle_switches_the_top_pane_and_remembers_the_choice(
    make_panel, remembered_choice, flow_state
):
    panel = make_panel()
    assert flow_state.view.properties_view == "properties"

    panel._btn_histogram.click()
    assert _showing_histogram(panel)
    assert remembered_choice["histogram"] is True
    assert flow_state.view.properties_view == "histogram"  # what tutorials read

    panel._btn_properties.click()
    assert panel._top_stack.currentWidget() is panel._scroll
    assert remembered_choice["histogram"] is False
    assert flow_state.view.properties_view == "properties"


def test_remembered_choice_waits_for_a_displayed_population(make_panel, remembered_choice):
    remembered_choice["histogram"] = True

    panel = make_panel()
    # Built during the startup skeleton: must not construct matplotlib canvases yet.
    assert panel._histogram_panel is None
    assert panel._btn_properties.isChecked()

    panel.set_displayed_population(SAMPLE_ID, None)
    assert _showing_histogram(panel)
    assert panel._btn_histogram.isChecked()


def test_histogram_tracks_displayed_population_and_selection(make_panel, flow_state):
    from karcytics_plugins.flow_cytometry.analysis.gating import RectangleGate

    root = flow_state.data.experiment.samples[SAMPLE_ID].gate_tree
    gate = RectangleGate("FSC-A", "SSC-A", x_min=1, x_max=2, y_min=1, y_max=2)
    selected = gate.create_nodes(root, "Cells")[0]
    panel = make_panel()
    panel._btn_histogram.click()

    # The main plot shows the root population; one of its gates is selected.
    panel.set_displayed_population(SAMPLE_ID, None)
    panel.show_sample_properties(SAMPLE_ID, selected.node_id)

    histogram = panel._histogram_panel
    assert (histogram._sample_id, histogram._node_id, histogram._selected_node_id) == (
        SAMPLE_ID,
        None,
        selected.node_id,
    )


@pytest.mark.parametrize("mode", ["Histogram", "CDF"])
def test_switch_is_disabled_while_the_main_plot_is_one_dimensional(
    make_panel, flow_state, remembered_choice, mode
):
    panel = make_panel()
    panel._btn_histogram.click()

    flow_state.view.active_plot_type = mode
    panel._on_display_mode_changed({"mode": mode})

    assert not panel._btn_histogram.isEnabled()
    assert panel._top_stack.currentWidget() is panel._scroll
    assert remembered_choice["histogram"] is True  # the choice survives

    flow_state.view.active_plot_type = "Pseudocolor"
    panel._on_display_mode_changed({"mode": "Pseudocolor"})

    assert panel._btn_histogram.isEnabled()
    assert _showing_histogram(panel)


def test_cleanup_tears_down_the_histogram_panel(make_panel):
    panel = make_panel()
    panel._btn_histogram.click()

    panel.cleanup()

    assert not panel._histogram_panel._is_alive
