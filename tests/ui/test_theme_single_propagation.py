"""Regression tests for the theme-double-apply fix.

`MainPanel._apply_theme_styles` already cascades to every descendant widget
that defines `_apply_theme_styles` via a recursive `findChildren(QWidget)`
scan (see `main_panel.py`), so a widget that *also* connects directly to
`theme_manager.theme_changed` gets restyled twice on every toggle — once via
its own subscription, once via the cascade finding it. Per
SDK_Abstraction_Performance_Plan.md Priority 1 (UI) #3, the fix is to pick
one propagation mechanism (the cascade) and drop the redundant direct
subscriptions. These tests assert the subscription is gone, not that
restyling still works — that's already covered by each widget's own
construction tests (SDK's cascade doing the reaching-in is out of scope for
a single-widget test).

`theme_manager` is a session-shared `MagicMock` (see conftest.py), so each
test swaps in its own fresh `theme_changed` mock via monkeypatch instead of
reading the shared object's accumulated call history.
"""

from unittest.mock import MagicMock

import pytest
from karcytics_sdk.plugin.theme_fallback import theme_manager


@pytest.fixture
def fresh_theme_changed_signal(monkeypatch):
    """Swap in a fresh, empty mock signal so call history isn't polluted by
    other tests sharing the same session-wide `theme_manager` mock.
    """
    fresh_signal = MagicMock()
    monkeypatch.setattr(theme_manager, "theme_changed", fresh_signal)
    return fresh_signal


def _connected_callbacks(signal_mock) -> list:
    return [call.args[0] for call in signal_mock.connect.call_args_list if call.args]


@pytest.mark.ui
def test_sample_view_widget_relies_on_cascade_not_direct_subscription(
    qtbot, fresh_theme_changed_signal
):
    from karcytics_plugins.flow_cytometry.ui.widgets.gate_hierarchy.sample_view import (
        SampleViewWidget,
    )

    widget = SampleViewWidget(state=MagicMock())
    qtbot.addWidget(widget)

    connected = _connected_callbacks(fresh_theme_changed_signal)
    assert widget.update not in connected
    assert widget._apply_theme_styles not in connected


@pytest.mark.ui
def test_population_selection_popup_relies_on_cascade_not_direct_subscription(
    qtbot, fresh_theme_changed_signal
):
    from karcytics_plugins.flow_cytometry.ui.widgets.selection.population_selection_popup import (
        PopulationSelectionPopup,
    )

    widget = PopulationSelectionPopup()
    qtbot.addWidget(widget)

    connected = _connected_callbacks(fresh_theme_changed_signal)
    assert widget._apply_theme_styles not in connected


@pytest.mark.ui
def test_flow_combo_box_relies_on_cascade_not_direct_subscription(
    qtbot, fresh_theme_changed_signal
):
    """`FlowComboBox` is a 7th instance of this pattern, not named in the plan's
    "≥6 leaf widgets" count — caught incidentally while touching this file for
    the `repopulate_combo` dedup (Priority 1 UI #4).
    """
    from karcytics_plugins.flow_cytometry.ui.widgets.styled_combo import FlowComboBox

    widget = FlowComboBox()
    qtbot.addWidget(widget)

    connected = _connected_callbacks(fresh_theme_changed_signal)
    assert widget._apply_theme_styles not in connected


@pytest.mark.ui
def test_gate_hierarchy_relies_on_cascade_not_direct_subscription(
    qtbot, fresh_theme_changed_signal
):
    from karcytics_plugins.flow_cytometry.analysis.experiment import Sample
    from karcytics_plugins.flow_cytometry.analysis.state import FlowState
    from karcytics_plugins.flow_cytometry.ui.widgets.gate_hierarchy import GateHierarchy

    state = FlowState()
    state.data.experiment.samples["s1"] = Sample(sample_id="s1", display_name="Sample 1")

    widget = GateHierarchy(state)
    qtbot.addWidget(widget)

    # Fully migrated to theme_manager.apply_style() (SDK_Abstraction_Performance_Plan.md
    # DRY item, static _apply_theme_styles batch) — no _apply_theme_styles method left
    # to (redundantly) subscribe, and no direct theme_changed subscription at all.
    assert not hasattr(widget, "_apply_theme_styles")
    connected = _connected_callbacks(fresh_theme_changed_signal)
    assert connected == []


@pytest.mark.ui
def test_comparisons_viewer_relies_on_cascade_not_direct_subscription(
    qtbot, fresh_theme_changed_signal
):
    from karcytics_plugins.flow_cytometry.analysis.state import FlowState
    from karcytics_plugins.flow_cytometry.ui.widgets.comparisons_viewer import ComparisonsViewer

    widget = ComparisonsViewer(FlowState())
    qtbot.addWidget(widget)

    connected = _connected_callbacks(fresh_theme_changed_signal)
    assert widget._apply_theme_styles not in connected


@pytest.mark.ui
def test_statistics_explorer_still_subscribes_directly_but_no_longer_double_styles(
    qtbot, fresh_theme_changed_signal
):
    """`StatisticsExplorer._on_theme_changed` does real extra work the cascade
    can't reach — repainting an already-computed table/chart with the new
    theme's colors — so unlike the other 5 widgets it keeps its direct
    subscription. What it must *not* do anymore is also explicitly call
    `_apply_theme_styles()` itself, since the `MainPanel` cascade already
    calls that separately; that was the actual duplicated work.
    """
    from unittest.mock import MagicMock as Mock

    from karcytics_plugins.flow_cytometry.analysis.state import FlowState
    from karcytics_plugins.flow_cytometry.ui.widgets.statistics_explorer import StatisticsExplorer

    widget = StatisticsExplorer(FlowState())
    qtbot.addWidget(widget)

    # Still subscribed directly (this one legitimately needs to be).
    connected = _connected_callbacks(fresh_theme_changed_signal)
    assert widget._on_theme_changed in connected

    # But no longer re-applies styles itself — the cascade already will.
    widget._apply_theme_styles = Mock()
    widget._on_theme_changed()
    widget._apply_theme_styles.assert_not_called()
