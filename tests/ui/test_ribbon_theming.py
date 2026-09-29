"""Tests for the 6 ribbons' migration to the SDK's `ThemedToolbarContainer`
(SDK_Abstraction_Performance_Plan.md DRY item: 6 ribbon classes duplicating
an identical container stylesheet; Priority 3 SDK gap #2).

`theme_fallback` is mocked wholesale in `tests/conftest.py`, so
`theme_manager.apply_style(...)` here is a no-op `MagicMock` call, not a real
`setStyleSheet` — these tests assert on the *call*, not on rendered style
output. `theme_manager` is a session-shared mock (its call history
accumulates across every test that constructs a themed widget), so each test
resets it immediately before constructing the widget under test rather than
asserting `assert_called_once_with`.
"""

import pytest
from karcytics_sdk.plugin.ribbon import ThemedToolbarContainer
from karcytics_sdk.plugin.theme_fallback import theme_manager

from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.ui.ribbons.compensation_ribbon import CompensationRibbon
from karcytics_plugins.flow_cytometry.ui.ribbons.gating_ribbon import GatingRibbon
from karcytics_plugins.flow_cytometry.ui.ribbons.pipeline_ribbon import PipelineRibbon
from karcytics_plugins.flow_cytometry.ui.ribbons.spectral_ribbon import SpectralRibbon
from karcytics_plugins.flow_cytometry.ui.ribbons.statistics_ribbon import StatisticsRibbon
from karcytics_plugins.flow_cytometry.ui.ribbons.workspace_ribbon import WorkspaceRibbon

RIBBON_CLASSES = [
    CompensationRibbon,
    GatingRibbon,
    PipelineRibbon,
    SpectralRibbon,
    StatisticsRibbon,
    WorkspaceRibbon,
]


@pytest.fixture
def state():
    return FlowState()


@pytest.mark.ui
@pytest.mark.parametrize("ribbon_cls", RIBBON_CLASSES, ids=lambda c: c.__name__)
def test_ribbon_is_a_themed_toolbar_container(ribbon_cls, state, qtbot):
    ribbon = ribbon_cls(state)
    qtbot.addWidget(ribbon)

    assert isinstance(ribbon, ThemedToolbarContainer)


@pytest.mark.ui
@pytest.mark.parametrize("ribbon_cls", RIBBON_CLASSES, ids=lambda c: c.__name__)
def test_ribbon_no_longer_has_its_own_apply_theme_styles(ribbon_cls, state, qtbot):
    """Guards against backsliding into a hand-rolled re-theming method
    instead of relying on ThemedToolbarContainer's base implementation.
    """
    ribbon = ribbon_cls(state)
    qtbot.addWidget(ribbon)

    assert not hasattr(ribbon, "_apply_theme_styles")


@pytest.mark.ui
@pytest.mark.parametrize("ribbon_cls", RIBBON_CLASSES, ids=lambda c: c.__name__)
def test_ribbon_container_is_registered_for_theming(ribbon_cls, state, qtbot):
    theme_manager.apply_style.reset_mock()

    ribbon = ribbon_cls(state)
    qtbot.addWidget(ribbon)

    assert any(call.args[0] is ribbon for call in theme_manager.apply_style.call_args_list)


@pytest.mark.ui
def test_gating_ribbon_extra_widgets_are_registered_for_theming(state, qtbot):
    theme_manager.apply_style.reset_mock()

    ribbon = GatingRibbon(state)
    qtbot.addWidget(ribbon)

    themed_targets = [call.args[0] for call in theme_manager.apply_style.call_args_list]
    assert ribbon._tools_label in themed_targets
    assert ribbon._sep1 in themed_targets
    assert ribbon._sep2 in themed_targets


@pytest.mark.ui
def test_pipeline_ribbon_extra_widgets_are_registered_for_theming(state, qtbot):
    theme_manager.apply_style.reset_mock()

    ribbon = PipelineRibbon(state)
    qtbot.addWidget(ribbon)

    themed_targets = [call.args[0] for call in theme_manager.apply_style.call_args_list]
    assert ribbon._lbl1 in themed_targets
    assert ribbon._lbl_orient in themed_targets
    assert ribbon._sep0 in themed_targets
    assert ribbon._sep in themed_targets
    for btn in ribbon._logic_buttons:
        assert btn in themed_targets
