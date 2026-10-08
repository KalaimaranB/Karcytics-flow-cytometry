"""Regression tests for GateHierarchy's stale-callback RuntimeErrors.

`_cleanup()` unsubscribes from CentralEventBus when `self.destroyed` fires,
but CentralEventBus.publish() is queued through the Qt event loop — a gate
event published just before the widget (or one of its children, e.g.
`_scroll` or `_sample_view`) is torn down can still be delivered afterwards,
raising "wrapped C/C++ object ... has been deleted" from inside
_on_gate_change / _on_gate_selected. Both handlers must swallow that and
unsubscribe instead of letting it propagate.
"""

import pytest
import shiboken6

from karcytics_plugins.flow_cytometry.analysis.experiment import Sample
from karcytics_plugins.flow_cytometry.analysis.gating import RectangleGate
from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.ui.widgets.gate_hierarchy import GateHierarchy


@pytest.fixture
def flow_state_hierarchy():
    state = FlowState()
    sample1 = Sample(sample_id="s1", display_name="Sample 1")
    gate = RectangleGate("FSC-A", "SSC-A", x_min=10, x_max=100, y_min=10, y_max=100)
    gate.gate_id = "g1"
    node = sample1.gate_tree.add_child(gate, name="Singlets")
    node.statistics = {"count": 1000, "pct_parent": 50.0, "pct_total": 50.0}
    state.data.experiment.samples["s1"] = sample1
    state.view.current_sample_id = "s1"
    return state


@pytest.mark.ui
def test_on_gate_change_survives_scroll_deleted_before_widget(qtbot, flow_state_hierarchy):
    """Regression test for: RuntimeError: wrapped C/C++ object of type QScrollArea has been deleted."""
    widget = GateHierarchy(flow_state_hierarchy)
    qtbot.addWidget(widget)

    # Simulate the exact ordering from the traceback: a child (_scroll) is
    # torn down by Qt before `self.destroyed` fires for the parent and
    # unsubscribes us from CentralEventBus.
    shiboken6.delete(widget._scroll)

    # Must not raise.
    widget._on_gate_change({})


@pytest.mark.ui
def test_on_gate_selected_survives_sample_view_deleted_before_widget(qtbot, flow_state_hierarchy):
    """Regression test for: RuntimeError: wrapped C/C++ object of type SampleViewWidget has been deleted."""
    widget = GateHierarchy(flow_state_hierarchy)
    qtbot.addWidget(widget)

    shiboken6.delete(widget._sample_view)

    # Must not raise.
    widget._on_gate_selected({})


@pytest.mark.ui
def test_on_gate_change_unsubscribes_after_swallowing_stale_callback(qtbot, flow_state_hierarchy):
    """After catching the RuntimeError once, it must unsubscribe so it can't recur forever."""
    from karcytics_sdk.plugin import CentralEventBus

    widget = GateHierarchy(flow_state_hierarchy)
    qtbot.addWidget(widget)
    shiboken6.delete(widget._scroll)

    calls_before = CentralEventBus.unsubscribe.call_count
    widget._on_gate_change({})
    assert CentralEventBus.unsubscribe.call_count > calls_before
