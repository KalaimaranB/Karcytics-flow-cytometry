import sys

import pytest
from PyQt6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    """Create a QApplication instance for UI tests."""
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def test_gate_modified_pushes_undo_and_dirty_flag(qapp, qtbot):
    """A gate edit (GATE_MODIFIED) must coalesce to exactly one undo
    snapshot + dirty-flag set, same as GATE_CREATED/GATE_DELETED/GATE_RENAMED
    — this was a gap: modify_gate() previously had no callers, so nothing
    ever exercised whether editing a gate was undoable.

    Exercises MainPanelController.wire() directly against a mock panel
    (real FlowCytometryPanel construction runs `_wire_signals()` only as the
    last step of an async, PluginLoaderManager-driven Phase 2 build — not
    worth dragging into a targeted wiring test).
    """
    from unittest.mock import Mock

    from karcytics_plugins.flow_cytometry.analysis import events
    from karcytics_plugins.flow_cytometry.ui.controllers.main_panel_controller import (
        MainPanelController,
    )

    panel = Mock()
    panel._loading = False
    MainPanelController.wire(panel)

    matches = [cb for topic, cb in panel._subscriptions if topic == events.GATE_MODIFIED]
    assert len(matches) == 1, "GATE_MODIFIED must be subscribed exactly once"

    panel.push_state.reset_mock()
    panel.set_dirty.reset_mock()

    matches[0]({"sample_id": "s1", "gate_id": "g1"})

    panel.push_state.assert_called_once()
    panel.set_dirty.assert_called_once_with(True)


def test_graph_manager_opens_a_graph_for_a_sample(qapp, qtbot, flow_state):
    """`open_graph_for_sample` should make a graph available via `get_open_graph`.

    Asserts through `GraphManager`'s own domain accessor rather than reaching
    into the underlying `QTabWidget` — the tab count/index are an
    implementation detail of how open graphs happen to be displayed, not
    what this behavior is about.
    """
    from unittest.mock import MagicMock

    from karcytics_plugins.flow_cytometry.ui.graph.graph_manager import GraphManager
    from karcytics_plugins.flow_cytometry.ui.graph.graph_window import GraphWindow

    mock_controller = MagicMock()
    mock_controller.get_gates_for_display.return_value = ([], [])
    manager = GraphManager(flow_state, None, MagicMock(), mock_controller)
    qtbot.addWidget(manager)

    sample_id = "test_sample_1"
    manager.open_graph_for_sample(sample_id)

    graph = manager.get_open_graph(sample_id)
    assert isinstance(graph, GraphWindow)
    assert graph.sample_id == sample_id


def test_group_preview_panel_initialization(qapp, qtbot, flow_state):
    """Smoke test: Verify GroupPreviewPanel can rebuild its grid."""
    from karcytics_plugins.flow_cytometry.ui.widgets.group_preview import GroupPreviewPanel

    try:
        from unittest.mock import MagicMock

        panel = GroupPreviewPanel(flow_state, "test_sample_1", MagicMock(), MagicMock())
        qtbot.addWidget(panel)

        # Add another sample to ensure there are peers to preview
        from karcytics_plugins.flow_cytometry.analysis.experiment import Sample

        flow_state.data.experiment.samples["test_sample_2"] = Sample(
            sample_id="test_sample_2",
            display_name="Sample 2",
        )

        # Set context to trigger rebuild
        sample_id = "test_sample_1"
        panel.update_context(sample_id, None)
        panel._rebuild()

        assert len(panel._thumbnails) > 0
    except Exception as e:
        pytest.fail(f"GroupPreviewPanel failed: {e}")
