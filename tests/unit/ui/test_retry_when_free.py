"""A preview drawn while the raster lock is busy is retried once, with the latest request."""

from karcytics_plugins.flow_cytometry.ui.graph.gate_drawing_fsm import _RetryWhenFree


def test_only_the_latest_deferred_call_runs_and_only_once(qtbot):
    calls = []
    retry = _RetryWhenFree(5)

    retry.defer(lambda: calls.append("first drag position"))
    retry.defer(lambda: calls.append("latest drag position"))
    qtbot.waitUntil(lambda: bool(calls), timeout=1000)
    qtbot.wait(30)

    assert calls == ["latest drag position"]


def test_a_call_deferred_after_the_retry_fired_is_retried_again(qtbot):
    calls = []
    retry = _RetryWhenFree(5)

    retry.defer(lambda: calls.append(1))
    qtbot.waitUntil(lambda: calls == [1], timeout=1000)
    retry.defer(lambda: calls.append(2))
    qtbot.waitUntil(lambda: calls == [1, 2], timeout=1000)
