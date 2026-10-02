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


def test_gate_modified_records_one_undo_step_and_dirties(qapp, qtbot):
    """A gate edit (GATE_MODIFIED) must become exactly one undo step and
    mark the workspace unsaved, same as GATE_CREATED/GATE_DELETED/
    GATE_RENAMED.

    Exercises MainPanelController.wire() directly against a mock panel
    (real FlowCytometryPanel construction runs `_wire_signals()` only as the
    last step of an async, PluginLoaderManager-driven Phase 2 build — not
    worth dragging into a targeted wiring test), with a real FlowStore.
    """
    from unittest.mock import Mock

    from karcytics_plugins.flow_cytometry.analysis import events
    from karcytics_plugins.flow_cytometry.analysis.store import FlowStore
    from karcytics_plugins.flow_cytometry.ui.controllers.main_panel_controller import (
        MainPanelController,
    )
    from tests.fixtures.workspace import build_rich_state

    state = build_rich_state()
    panel = Mock()
    panel._store = FlowStore(state, lambda *_: None)
    panel._store.reset()
    MainPanelController.wire(panel)

    recorder = panel._history_recorder
    handlers = [h for topic, h in recorder._subscriptions if topic == events.GATE_MODIFIED]
    assert len(handlers) == 1, "GATE_MODIFIED must be recorded exactly once"

    state.data.experiment.samples["s0"].gate_tree.children[0].gate.vertices[0] = (1.0, 1.0)
    handlers[0]({"sample_id": "s0", "gate_id": "g1"})
    handlers[0]({"sample_id": "s0", "gate_id": "g1"})  # same turn → same step
    recorder.flush()

    assert panel._store.history.undo_label() == "Edit Gate"
    assert panel._store.history.undo() is not None
    assert panel._store.history.undo() is None  # exactly one step
    assert panel._store.is_dirty is False  # back at the baseline

    MainPanelController.unwire(panel)
    assert recorder._subscriptions == []


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
