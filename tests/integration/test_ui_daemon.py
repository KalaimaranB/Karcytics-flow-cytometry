"""Real-subprocess integration test for `ui_daemon.py`.

Spawns the actual daemon script under this plugin's own interpreter — the
same way `karcytics_sdk.plugin.PluginUIDaemon` does from the Hub — and speaks
its real msgpack-over-stdio protocol through the SDK's shared harness. No
mocking of the daemon itself: this is what proves the module can be hosted
standalone (`process_model = "isolated"`), not just that its imports resolve.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from karcytics_sdk.testing.ui_daemon import spawn_ui_daemon

REPO_ROOT = Path(__file__).resolve().parents[2]
DAEMON_SCRIPT = REPO_ROOT / "src" / "karcytics_plugins" / "flow_cytometry" / "ui_daemon.py"
NO_READY = "Daemon never sent a 'ready' event before exiting."


@pytest.fixture
def daemon():
    with spawn_ui_daemon(DAEMON_SCRIPT, cwd=REPO_ROOT) as running:
        yield running


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.timeout(60)
class TestUIDaemonIsolatedProcess:
    def test_reaches_ready_with_a_real_window_geometry(self, daemon):
        start = time.monotonic()
        frame = daemon.io.wait_for_event("ready", NO_READY)
        elapsed = time.monotonic() - start

        assert len(frame["payload"]["geometry"]) == 4  # noqa: PLR2004 - x, y, width, height
        # The Phase 2 view modules' imports (matplotlib/scipy) run at module
        # level in ui_daemon.py, before 'ready': importing them once a stdin
        # reader thread exists hangs on Windows. 'ready' carries that cost, so
        # guard it with margin under the Hub's 45 s Ready Gate.
        assert elapsed < 40.0, (
            f"'ready' took {elapsed:.1f}s — approaching the Hub's 45s Ready Gate."
        )  # noqa: PLR2004 - see comment

    def test_exit_request_shuts_the_process_down_cleanly(self, daemon):
        daemon.io.wait_for_event("ready", NO_READY)
        daemon.request(1, "exit")

        response = daemon.io.wait_for_response(1, "Daemon never responded to the 'exit' request.")
        assert response["payload"] == {"status": "ok"}
        returncode = daemon.process.wait(timeout=10)
        assert returncode == 0, f"--- daemon stderr ---\n{daemon.io.finished_stderr()}"

    def test_focus_request_is_answered_after_ready(self, daemon):
        daemon.io.wait_for_event("ready", NO_READY)
        daemon.request(7, "focus")

        response = daemon.io.wait_for_response(7, "Daemon never responded to 'focus'.")
        assert response == {"kind": "response", "request_id": 7, "payload": {"status": "ok"}}

    @pytest.mark.timeout(90)
    def test_phase_2_build_runs_after_ready(self, daemon):
        """The panel must leave its Phase 1 skeleton: `run_ui_daemon()` calls
        `panel.begin_async_init()` after the ready handshake. Phase 2's last
        step (`WorkspaceBuilder.connect_tab_bar`) emits `status_message`
        ("Ready"), which `_build_panel()` forwards as an event — its arrival
        proves Phase 2 ran.
        """
        daemon.io.wait_for_event("ready", NO_READY)

        frame = daemon.io.wait_for_event(
            "status_message", "Daemon never emitted 'status_message'.", timeout=75.0
        )
        assert frame["payload"] == "Ready"
