"""Tests for the "trivial" batch of `_apply_theme_styles` migrations to the
SDK's `theme_manager.apply_style()` (SDK_Abstraction_Performance_Plan.md DRY
item: 35 hand-rolled `_apply_theme_styles` methods; ribbons were migrated in
a prior session, this covers the next 11 static/unconditional-QSS classes).

`theme_fallback` is mocked wholesale in `tests/conftest.py`, so
`theme_manager.apply_style(...)` here is a no-op `MagicMock` call, not a real
`setStyleSheet` — these tests assert on the *call*, not on rendered style
output. `theme_manager` is a session-shared mock (its call history
accumulates across every test that constructs a themed widget), so each test
resets it immediately before constructing the widget under test rather than
asserting `assert_called_once_with`.
"""

from unittest.mock import MagicMock

import pandas as pd
import pytest
from karcytics_sdk.plugin.theme_fallback import theme_manager
from PyQt6.QtWidgets import QPushButton

from karcytics_plugins.flow_cytometry.analysis.config import PseudocolorConfig
from karcytics_plugins.flow_cytometry.analysis.scaling import AxisScale
from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.ui.graph.components.axis_control_panel import (
    AxisControlPanel,
)
from karcytics_plugins.flow_cytometry.ui.graph.components.graph_toolbar import GraphToolbar
from karcytics_plugins.flow_cytometry.ui.graph.components.transform_widgets import (
    AxisTransformPanel,
)
from karcytics_plugins.flow_cytometry.ui.graph.render_panels.pseudocolor_panel import (
    PseudocolorSettingsPanel,
)
from karcytics_plugins.flow_cytometry.ui.widgets.gate_hierarchy.hover_card import HoverCard
from karcytics_plugins.flow_cytometry.ui.widgets.gate_hierarchy.widget import GateHierarchy
from karcytics_plugins.flow_cytometry.ui.widgets.groups_panel import GroupsPanel
from karcytics_plugins.flow_cytometry.ui.widgets.properties_panel import PropertiesPanel
from karcytics_plugins.flow_cytometry.ui.widgets.sample_list import SampleList
from karcytics_plugins.flow_cytometry.ui.widgets.spectral_learning_tab import SpectralLearningTab

# Classes whose _apply_theme_styles is fully deleted (pure static QSS, no
# trailing non-styling side effect).
FULLY_DELETED_FACTORIES = [
    lambda state: GraphToolbar(),
    lambda state: AxisControlPanel(),
    lambda state: GroupsPanel(state),
    lambda state: GateHierarchy(state),
]


@pytest.fixture
def state():
    return FlowState()


@pytest.mark.ui
@pytest.mark.parametrize(
    "make_widget",
    FULLY_DELETED_FACTORIES,
    ids=["GraphToolbar", "AxisControlPanel", "GroupsPanel", "GateHierarchy"],
)
def test_no_longer_has_apply_theme_styles(make_widget, state, qtbot):
    """Guards against backsliding into a hand-rolled re-theming method
    instead of relying on theme_manager.apply_style()'s self-registration.
    """
    widget = make_widget(state)
    qtbot.addWidget(widget)

    assert not hasattr(widget, "_apply_theme_styles")


@pytest.mark.ui
def test_graph_toolbar_widgets_registered_for_theming(qtbot):
    theme_manager.apply_style.reset_mock()

    toolbar = GraphToolbar()
    qtbot.addWidget(toolbar)

    targets = [call.args[0] for call in theme_manager.apply_style.call_args_list]
    assert toolbar._btn_prev in targets
    assert toolbar._btn_next in targets
    assert toolbar._btn_parent in targets
    assert toolbar._breadcrumb in targets


@pytest.mark.ui
def test_axis_control_panel_widgets_registered_for_theming(qtbot):
    theme_manager.apply_style.reset_mock()

    panel = AxisControlPanel()
    qtbot.addWidget(panel)

    targets = [call.args[0] for call in theme_manager.apply_style.call_args_list]
    assert panel._x_label in targets
    assert panel._y_label in targets
    assert panel._fmo_label in targets
    assert panel._y_count_label in targets
    assert panel._render_spinner in targets
    assert panel._transform_btn in targets
    assert panel._btn_settings in targets


@pytest.mark.ui
def test_groups_panel_widgets_registered_for_theming(state, qtbot):
    theme_manager.apply_style.reset_mock()

    panel = GroupsPanel(state)
    qtbot.addWidget(panel)

    targets = [call.args[0] for call in theme_manager.apply_style.call_args_list]
    assert panel._header in targets
    assert panel._list in targets


@pytest.mark.ui
def test_gate_hierarchy_widgets_registered_for_theming(state, qtbot):
    theme_manager.apply_style.reset_mock()

    widget = GateHierarchy(state)
    qtbot.addWidget(widget)

    targets = [call.args[0] for call in theme_manager.apply_style.call_args_list]
    assert widget._header_widget in targets
    assert widget._section_label in targets
    assert widget._btn_all_samples in targets
    assert widget._scroll in targets
    assert widget.btn_zoom_in in targets
    assert widget.btn_zoom_out in targets
    assert widget.btn_fit in targets
    assert widget._empty_label in targets


@pytest.mark.ui
def test_hover_card_registered_for_theming(qtbot):
    theme_manager.apply_style.reset_mock()

    card = HoverCard(parent=None)
    qtbot.addWidget(card)

    assert any(call.args[0] is card for call in theme_manager.apply_style.call_args_list)
    assert not hasattr(card, "_apply_theme_styles")


@pytest.mark.ui
def test_pseudocolor_settings_panel_no_longer_needs_external_apply(qtbot):
    """Previously required an external `if hasattr(...): panel._apply_theme_styles()`
    call from pseudocolor_overlay_options.py to stay themed; now self-registers.
    """
    theme_manager.apply_style.reset_mock()

    panel = PseudocolorSettingsPanel(PseudocolorConfig())
    qtbot.addWidget(panel)

    assert not hasattr(panel, "_apply_theme_styles")
    targets = [call.args[0] for call in theme_manager.apply_style.call_args_list]
    assert panel._cmap_label in targets
    # 3 preset buttons + 4 cap buttons registered at construction time, no
    # tracking lists needed anymore (theme_manager owns re-application).
    button_targets = [t for t in targets if isinstance(t, QPushButton)]
    assert len(button_targets) >= 7  # noqa: PLR2004


@pytest.mark.ui
def test_axis_transform_panel_no_longer_needs_external_apply(qtbot):
    """Same as the pseudocolor panel: previously needed an external
    `_apply_theme_styles()` call to stay themed when reused; now self-registers.
    """
    theme_manager.apply_style.reset_mock()

    panel = AxisTransformPanel("X", AxisScale(), lambda current: (0.0, 1.0))
    qtbot.addWidget(panel)

    assert not hasattr(panel, "_apply_theme_styles")
    targets = [call.args[0] for call in theme_manager.apply_style.call_args_list]
    assert panel._lbl_hint in targets
    assert panel._btn_auto in targets


@pytest.mark.ui
def test_sample_list_no_longer_has_apply_theme_styles_but_keeps_empty_state(state, qtbot):
    """sample_list.py's `_update_empty_state()` call was never theme-derived —
    it piggybacked on the same construction-time call site as the QSS. Fully
    deleting `_apply_theme_styles` (not shrinking it) and calling
    `_update_empty_state()` directly preserves the one real behavior.
    """
    theme_manager.apply_style.reset_mock()

    widget = SampleList(state)
    qtbot.addWidget(widget)

    assert not hasattr(widget, "_apply_theme_styles")
    targets = [call.args[0] for call in theme_manager.apply_style.call_args_list]
    assert widget._tree in targets
    assert widget._empty_label in targets
    # No samples loaded -> empty state should already be showing (checked via
    # isHidden(), not isVisible(), since qtbot.addWidget() never shows the
    # widget on screen and isVisible() also depends on ancestor visibility).
    assert not widget._empty_label.isHidden()


@pytest.mark.ui
def test_properties_panel_shrunk_to_refresh_side_effect(qtbot):
    """properties_panel.py's chrome (header/splitter/scroll) self-themes now;
    `_apply_theme_styles` survives only to re-render the currently-displayed
    sample/group properties (Colors-derived content) on theme change.
    """
    theme_manager.apply_style.reset_mock()

    panel = PropertiesPanel(FlowState(), None, None, None)
    qtbot.addWidget(panel)

    targets = [call.args[0] for call in theme_manager.apply_style.call_args_list]
    assert panel._header in targets
    assert panel._splitter in targets
    assert panel._scroll in targets

    assert hasattr(panel, "_apply_theme_styles")
    panel.refresh = MagicMock()
    panel._current_sample_id = None
    panel._current_node_id = None
    panel._apply_theme_styles()
    panel.refresh.assert_not_called()

    panel._current_sample_id = "s1"
    panel._apply_theme_styles()
    panel.refresh.assert_called_once()


@pytest.mark.ui
def test_spectral_learning_tab_shrunk_to_update_view_side_effect(qtbot):
    """spectral_learning_tab.py's static widgets self-theme now;
    `_apply_theme_styles` survives only to rebuild the current step's
    interactive matplotlib content (Colors-derived) on theme change.
    """
    theme_manager.apply_style.reset_mock()

    tab = SpectralLearningTab(MagicMock())
    qtbot.addWidget(tab)

    targets = [call.args[0] for call in theme_manager.apply_style.call_args_list]
    assert tab._step_label in targets
    assert tab._explanation in targets
    assert tab._readout_label in targets
    assert tab._canvas_wrapper in targets

    assert hasattr(tab, "_apply_theme_styles")
    tab.update_view = MagicMock()
    tab._apply_theme_styles()
    tab.update_view.assert_called_once()


@pytest.mark.ui
def test_graph_window_no_longer_has_apply_theme_styles(qtbot):
    from karcytics_plugins.flow_cytometry.analysis.axis_manager import AxisManager
    from karcytics_plugins.flow_cytometry.analysis.experiment import Sample
    from karcytics_plugins.flow_cytometry.ui.graph.graph_window import GraphWindow

    state = FlowState()
    state.axis_manager = AxisManager(state)

    sample = Sample(sample_id="s_theme", display_name="Sample Theme")
    sample.fcs_data = MagicMock()
    sample.fcs_data.channels = ["FSC-A", "SSC-A"]
    sample.fcs_data.markers = ["", ""]
    sample.fcs_data.events = pd.DataFrame({"FSC-A": [100, 200, 300], "SSC-A": [10, 20, 30]})
    state.data.experiment.samples["s_theme"] = sample

    pop_mock = MagicMock()
    pop_mock.get_gated_events.return_value = sample.fcs_data.events

    theme_manager.apply_style.reset_mock()

    win = GraphWindow(
        state,
        "s_theme",
        axis_manager=state.axis_manager,
        population_service=pop_mock,
        controller=MagicMock(),
    )
    qtbot.addWidget(win)

    assert not hasattr(win, "_apply_theme_styles")
    assert any(call.args[0] is win._gate_info for call in theme_manager.apply_style.call_args_list)
