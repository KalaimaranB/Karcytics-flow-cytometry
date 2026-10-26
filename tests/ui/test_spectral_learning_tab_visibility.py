"""The Learning Compensation sub-tab shows only while Course 1 runs, even when a
step event was missed while the viewer was hidden.
"""

from unittest.mock import MagicMock

import pytest
from karcytics_sdk.plugin.runtime_services import tutorial_manager

from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.tutorials.course1 import course_1_fundamentals
from karcytics_plugins.flow_cytometry.ui.widgets.spectral_viewer import SpectralViewer


@pytest.fixture
def viewer(qtbot, monkeypatch):
    monkeypatch.setattr(tutorial_manager, "active_course", None)
    widget = SpectralViewer(FlowState(), MagicMock(), None)
    qtbot.addWidget(widget)
    return widget


def _learning_tab_shown(viewer: SpectralViewer) -> bool:
    return viewer._tabs.isTabVisible(viewer._tabs.indexOf(viewer.learning_tab))


@pytest.mark.ui
def test_hidden_outside_course_1(viewer):
    viewer.show()
    assert not _learning_tab_shown(viewer)


@pytest.mark.ui
def test_showing_the_viewer_catches_up_on_a_course_that_started_unseen(viewer, monkeypatch):
    assert not _learning_tab_shown(viewer)
    monkeypatch.setattr(tutorial_manager, "active_course", course_1_fundamentals)  # no event
    viewer.show()
    assert _learning_tab_shown(viewer)
