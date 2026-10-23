"""The worker warm-up runs on the task pool and never fails the panel."""

import threading

from karcytics_sdk.plugin.runtime_services import task_scheduler

from karcytics_plugins.flow_cytometry.ui.services import flow_daemon


def test_the_warm_up_starts_the_worker_off_the_gui_thread(qtbot, monkeypatch):
    started_on = []
    monkeypatch.setattr(
        flow_daemon.PluginDaemon,
        "start_instance",
        lambda plugin_id: started_on.append((plugin_id, threading.current_thread())),
    )

    with qtbot.waitSignal(task_scheduler.task_finished, timeout=5000):
        flow_daemon.warm_up_flow_daemon()

    [(plugin_id, thread)] = started_on
    assert plugin_id == "flow_cytometry"
    assert thread is not threading.main_thread()


def test_a_worker_that_will_not_start_is_left_for_the_first_real_call(monkeypatch):
    def refuse(_plugin_id):
        raise RuntimeError("no interpreter")

    warnings = []
    monkeypatch.setattr(flow_daemon.PluginDaemon, "start_instance", refuse)
    monkeypatch.setattr(flow_daemon.logger, "warning", lambda *args: warnings.append(args))

    flow_daemon._start_daemon()  # returns; the first load starts it again

    [(_message, error)] = warnings
    assert str(error) == "no interpreter"
