"""Regression tests for the "no error was ever raised" half of the FCS-reload bug.

Two independent silent fallbacks used to swallow a stuck/partial FCS
reload: the 45s crossfade watchdog forced the UI open regardless of
whether loading finished, and a completed reload with per-sample failures
never told the user which samples came up empty. Both now surface a
QMessageBox.warning instead of failing silently.
"""

import sys
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QMessageBox

from karcytics_plugins.flow_cytometry.ui.startup_sequencer import StartupSequencer


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


@pytest.fixture
def panel(qapp, qtbot):
    from karcytics_plugins.flow_cytometry.ui.main_panel import FlowCytometryPanel

    p = FlowCytometryPanel(plugin_id="flow_smoke_test")
    qtbot.addWidget(p)
    # DummyPluginBase (see tests/conftest.py) doesn't set up a logger the
    # way the real karcytics_sdk PluginBase does in production.
    p.logger = MagicMock()
    return p


class _ReadyGate(QObject):
    panel_ready = Signal()
    data_ready = Signal()


@pytest.fixture
def gate(monkeypatch):
    monkeypatch.setattr(
        "karcytics_plugins.flow_cytometry.analysis.numba_warmup.warmup_numba_jit", lambda: None
    )
    return _ReadyGate()


def test_watchdog_warns_and_still_emits_data_ready_when_load_never_finished(
    panel, gate, monkeypatch, qtbot
):
    """The 45s timer firing while a reload is still pending must warn, not stay silent."""
    startup = StartupSequencer(gate.panel_ready, gate.data_ready, panel)
    with qtbot.waitSignal(gate.panel_ready):
        startup.start([], take_deferred_load=lambda: lambda: None)  # a load that never ends

    warnings = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda *a, **k: warnings.append(a) or QMessageBox.StandardButton.Ok,
    )

    received_ready = []
    gate.data_ready.connect(lambda: received_ready.append(True))

    startup.on_load_watchdog_timeout()

    assert len(warnings) == 1, "watchdog timeout with an unfinished load must warn the user"
    assert received_ready == [True], "the UI must still unblock even after warning"


def test_watchdog_stays_silent_when_load_already_finished(panel, gate, monkeypatch):
    """With no handed-over load still pending, the watchdog is a no-op."""
    startup = StartupSequencer(gate.panel_ready, gate.data_ready, panel)

    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warnings.append(a))

    startup.on_load_watchdog_timeout()

    assert warnings == []


def test_load_workflow_warns_when_some_samples_fail_to_reload(panel, monkeypatch):
    """A completed reload with per-sample failures must name the failed samples."""
    monkeypatch.setattr(panel.services.document, "project_manager", lambda: None)
    # _refresh_all() touches Phase-2 widgets this minimal panel never built;
    # irrelevant to the warning logic under test here.
    monkeypatch.setattr(panel, "_refresh_all", lambda: None)

    def fake_service_load_workflow(payload, context=None, project_dir=None, on_complete=None):
        on_complete({"loaded": ["Sample A"], "failed": ["Sample B"]})
        return True

    monkeypatch.setattr(
        panel.services.workflow_service, "load_workflow", fake_service_load_workflow
    )

    warnings = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda *a, **k: warnings.append(a) or QMessageBox.StandardButton.Ok,
    )

    panel.load_workflow({"payload": {}})

    assert len(warnings) == 1
    title, message = warnings[0][1], warnings[0][2]
    assert "Sample B" in message
    assert "Sample A" not in message


def test_load_workflow_does_not_warn_when_all_samples_load(panel, monkeypatch):
    monkeypatch.setattr(panel.services.document, "project_manager", lambda: None)
    monkeypatch.setattr(panel, "_refresh_all", lambda: None)

    def fake_service_load_workflow(payload, context=None, project_dir=None, on_complete=None):
        on_complete({"loaded": ["Sample A"], "failed": []})
        return True

    monkeypatch.setattr(
        panel.services.workflow_service, "load_workflow", fake_service_load_workflow
    )

    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warnings.append(a))

    panel.load_workflow({"payload": {}})

    assert warnings == []
