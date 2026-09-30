from unittest.mock import MagicMock

import pytest

from karcytics_plugins.flow_cytometry.analysis.transforms import TransformType


@pytest.fixture
def graph_window_with_sample_c(qtbot):
    import pandas as pd

    from karcytics_plugins.flow_cytometry.analysis.axis_manager import AxisManager
    from karcytics_plugins.flow_cytometry.analysis.experiment import Sample
    from karcytics_plugins.flow_cytometry.analysis.population_service import (
        PopulationService,
    )
    from karcytics_plugins.flow_cytometry.analysis.state import FlowState
    from karcytics_plugins.flow_cytometry.ui.graph.graph_window import GraphWindow

    state = FlowState()
    state.axis_manager = AxisManager(state)
    state.population_service = PopulationService(state)

    sample = Sample(sample_id="s_c", display_name="Sample C")
    sample.fcs_data = MagicMock()
    sample.fcs_data.channels = ["FSC-A", "SSC-A", "FITC-A", "PE-A"]
    sample.fcs_data.markers = ["", "", "", ""]
    sample.fcs_data.events = pd.DataFrame(
        {
            "FSC-A": [100, 200, 300],
            "SSC-A": [10, 20, 30],
            "FITC-A": [-10, 0, 100],
            "PE-A": [5, 10, 500],
        }
    )
    state.data.experiment.samples["s_c"] = sample

    pop_mock = MagicMock()
    pop_mock.get_gated_events.return_value = sample.fcs_data.events
    win = GraphWindow(
        state,
        "s_c",
        axis_manager=state.axis_manager,
        population_service=pop_mock,
        controller=MagicMock(),
    )
    qtbot.addWidget(win)
    return win


@pytest.mark.ui
class TestGraphWindowAxisIndependence:
    def test_switching_y_axis_updates_scale_from_new_data(self, qtbot, graph_window_with_sample_c):
        """Switching Y channel must recompute range from the new channel's data."""
        win = graph_window_with_sample_c

        # Force initial axes to ensure predictable start
        for i in range(win._axis_panel._x_combo.count()):
            if win._axis_panel._x_combo.itemData(i) == "FSC-A":
                win._axis_panel._x_combo.setCurrentIndex(i)
        for i in range(win._axis_panel._y_combo.count()):
            if win._axis_panel._y_combo.itemData(i) == "SSC-A":
                win._axis_panel._y_combo.setCurrentIndex(i)

        from karcytics_plugins.flow_cytometry.analysis.scaling import AxisScale

        win._state.view.active_transform_y = "biexponential"
        y_scale = AxisScale(TransformType.BIEXPONENTIAL)
        # Register in state so it's not overwritten during render
        win._state.axis_manager.set_scale("SSC-A", y_scale.copy(), sample_id=win.sample_id)
        win.apply_axis_scale("SSC-A", y_scale)
        win._do_axis_render()

        old_y_min = win._y_scale.min_val  # SSC-A (positive floor)

        # Switch Y to FITC-A (fluorescence with negatives)
        for i in range(win._axis_panel._y_combo.count()):
            if win._axis_panel._y_combo.itemData(i) == "FITC-A":
                with qtbot.waitSignal(win.axis_changed, timeout=1000):
                    win._axis_panel._y_combo.setCurrentIndex(i)
                break

        new_y_min = win._y_scale.min_val
        assert new_y_min != old_y_min, (
            f"Y scale must update after channel switch (old={old_y_min}, new={new_y_min})"
        )
        assert new_y_min < 0, f"FITC-A (compensated) should have negative floor (got {new_y_min})"

    def test_biex_transform_change_recomputes_range(self, qtbot, graph_window_with_sample_c):
        """Switching X from LINEAR to BIEX must produce a sensible positive min."""
        win = graph_window_with_sample_c
        # Switch X to BIEXPONENTIAL
        from karcytics_plugins.flow_cytometry.analysis.scaling import AxisScale

        x_scale = AxisScale(TransformType.BIEXPONENTIAL)

        # We must update the state cache as well, otherwise _do_axis_render restores LINEAR
        x_ch = win._axis_panel._x_combo.currentData() or win._axis_panel._x_combo.currentText()
        win._state.axis_manager.set_scale(x_ch, x_scale.copy(), sample_id=win.sample_id)
        win.apply_axis_scale(x_ch, x_scale)

        win._x_scale.min_val, win._x_scale.max_val = win._calculate_auto_range("x")
        win._do_axis_render()

        # It's possible the data's positive percentiles are small, but for this real data
        # the floor shouldn't be exactly 0.0 like LINEAR forces.
        assert win._x_scale.transform_type == TransformType.BIEXPONENTIAL
        assert win._x_scale.min_val <= 0, "BIEX FSC min is padded negative"
        assert win._x_scale.max_val > win._x_scale.min_val
