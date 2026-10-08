"""Regression tests for FlowCanvas's post-deletion CentralEventBus guards.

CentralEventBus.publish() is queued through the Qt event loop, so an event
published just before a graph tab (and its FlowCanvas) closes can still be
delivered afterwards. The controller-event handlers guard against this with
`not shiboken6.isValid(self)`. These tests destroy the C++ side of a canvas
and then fire each handler, which must return without touching the widget.
"""

import pytest
import shiboken6

from karcytics_plugins.flow_cytometry.ui.graph.flow_canvas import FlowCanvas

_HANDLERS = [
    ("_on_controller_geometry_changed", ("s1", "gate1")),
    ("_on_controller_selected", ("s1", "node1")),
    ("_on_controller_gate_removed", ("s1", "node1")),
    ("_on_controller_gate_renamed", ("s1", "node1")),
]


@pytest.mark.ui
@pytest.mark.parametrize("handler_name,args", _HANDLERS)
def test_controller_handler_is_noop_after_canvas_deleted(qtbot, handler_name, args):
    canvas = FlowCanvas(parent=None)
    canvas._sample_id = "s1"
    # Not registered with qtbot: shiboken6.delete() below destroys the C++ side
    # immediately, and qtbot's own teardown calling .close() on an
    # already-deleted widget would itself raise.

    shiboken6.delete(canvas)
    assert not shiboken6.isValid(canvas)

    handler = getattr(canvas, handler_name)
    # Must return quietly (no ModuleNotFoundError, no RuntimeError touching
    # deleted C++ state) instead of raising.
    handler(*args)


@pytest.mark.ui
@pytest.mark.parametrize("handler_name,args", _HANDLERS)
def test_controller_handler_still_runs_while_canvas_is_alive(qtbot, handler_name, args):
    """Sanity check: the isdeleted guard must not swallow the live-object case."""
    canvas = FlowCanvas(parent=None)
    canvas._sample_id = "s1"
    qtbot.addWidget(canvas)

    assert shiboken6.isValid(canvas)
    handler = getattr(canvas, handler_name)
    handler(*args)  # should not raise for a live canvas either
