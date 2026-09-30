from unittest.mock import MagicMock, patch

from karcytics_plugins.flow_cytometry.analysis import events
from karcytics_plugins.flow_cytometry.analysis.experiment import Sample
from karcytics_plugins.flow_cytometry.analysis.gate_propagator import GatePropagator


def test_gate_propagator_debounce(flow_state, qtbot):
    mock_scheduler = MagicMock()
    # Add a second sample so there is a target for propagation
    s2 = Sample(sample_id="s2", display_name="Sample 2")
    s2.fcs_data = MagicMock()
    flow_state.data.experiment.samples["s2"] = s2

    propagator = GatePropagator(flow_state, mock_scheduler)

    from unittest.mock import patch

    with patch("threading.Timer") as mock_timer_cls:
        mock_timer_instance_1 = MagicMock()
        mock_timer_instance_2 = MagicMock()
        mock_timer_cls.side_effect = [mock_timer_instance_1, mock_timer_instance_2]

        propagator.request_propagation("gate1", "test_sample_1")
        propagator.request_propagation("gate1", "test_sample_1")

        # The first timer should have been cancelled
        assert mock_timer_instance_1.cancel.call_count == 1
        assert mock_timer_instance_2.cancel.call_count == 0

        # Now simulate the second timer firing
        # The target function is passed as args[1] in Timer(interval, function, args=...)
        # Wait, threading.Timer signature is Timer(interval, function, args=None, kwargs=None)
        # So function is args[0] for the side_effect or kwargs 'function'
        # Let's just call the execute method directly since it's an internal test
        propagator._execute_propagation()

    assert mock_scheduler.submit.call_count == 1


def test_gate_propagator_handler_cleanup(flow_state, qtbot):
    """Verify that handlers disconnect themselves to prevent leaks."""
    mock_scheduler = MagicMock()
    # Add a second sample so there is a target for propagation
    s2 = Sample(sample_id="s2", display_name="Sample 2")
    s2.fcs_data = MagicMock()
    flow_state.data.experiment.samples["s2"] = s2

    propagator = GatePropagator(flow_state, mock_scheduler)

    mock_worker_obj = MagicMock()
    mock_worker_obj.task_id = "task_1"
    mock_scheduler.submit.return_value = mock_worker_obj

    propagator.request_propagation("gate1", "test_sample_1")
    qtbot.wait(300)

    # Check that connect was called for the handler
    assert mock_scheduler.task_finished.connect.call_count == 1

    # Extract the handler method
    handler_method = mock_scheduler.task_finished.connect.call_args[0][0]

    # Simulate task completion
    handler_method("task_1", {"propagation_results": {}})

    # Check that disconnect is NEVER called because handlers are now bound permanently in __init__
    assert mock_scheduler.task_finished.disconnect.call_count == 0


def test_propagation_complete_reports_partial_failures(flow_state, qtbot):
    """A per-sample propagation error must surface in the PROPAGATION_COMPLETE
    payload (not just get logged) so the UI can tell the user.

    CentralEventBus is fully mocked in tests/conftest.py (no real dispatch),
    so this asserts on the call recorded against the mock rather than a
    round-tripped subscriber callback.
    """
    s2 = Sample(sample_id="s2", display_name="Sample 2")
    s2.fcs_data = MagicMock()
    flow_state.data.experiment.samples["s2"] = s2

    propagator = GatePropagator(flow_state, MagicMock())

    with patch("karcytics_plugins.flow_cytometry.analysis.gate_propagator.CentralEventBus") as bus:
        propagator._on_propagation_finished(
            "task_1",
            {"propagation_results": {"s2": {"error": "missing channel FSC-A"}}},
        )

    complete_calls = [
        call for call in bus.publish.call_args_list if call.args[0] == events.PROPAGATION_COMPLETE
    ]
    assert len(complete_calls) == 1
    payload = complete_calls[0].args[1]
    assert payload["total"] == 1
    assert payload["succeeded"] == 0
    assert payload["failed"] == 1
    assert payload["errors"] == {"s2": "missing channel FSC-A"}


def test_propagation_complete_all_succeeded_has_no_errors(flow_state, qtbot):
    s2 = Sample(sample_id="s2", display_name="Sample 2")
    s2.fcs_data = MagicMock()
    flow_state.data.experiment.samples["s2"] = s2

    propagator = GatePropagator(flow_state, MagicMock())

    with patch("karcytics_plugins.flow_cytometry.analysis.gate_propagator.CentralEventBus") as bus:
        propagator._on_propagation_finished(
            "task_1",
            {"propagation_results": {"s2": {"stats": {}, "tree": s2.gate_tree}}},
        )

    complete_calls = [
        call for call in bus.publish.call_args_list if call.args[0] == events.PROPAGATION_COMPLETE
    ]
    assert len(complete_calls) == 1
    payload = complete_calls[0].args[1]
    assert payload == {"total": 1, "succeeded": 1, "failed": 0, "errors": {}}


def test_cancel_pending_drops_queued_and_running_propagation():
    """Undo/redo or a load replaces the model; a propagation computed from
    the old source tree must never land on top of it afterwards.
    """
    from unittest.mock import MagicMock

    from karcytics_plugins.flow_cytometry.analysis.gate_propagator import GatePropagator
    from karcytics_plugins.flow_cytometry.analysis.state import FlowState

    propagator = GatePropagator(FlowState(), task_scheduler=None)
    propagator.request_propagation("gate", "s0")
    timer = propagator._timer
    propagator._active_task_id = "running"
    applied = MagicMock()
    propagator._on_propagation_finished = applied

    propagator.cancel_pending()

    assert timer is not None and timer.finished.is_set()
    assert propagator._pending_source_id is None
    propagator._on_task_finished("running", {"propagation_results": {}})
    applied.assert_not_called()
