"""Regression coverage for tutorial file provisioning's retry/stall handling.

Guards against the bug reported in production: a single exhausted per-file
retry (or any download exception) permanently wedged the tutorial with no
recovery path short of restarting the whole application — `_status` is a
module-level singleton whose `started` flag never reset, and the
provisioning VerificationStep had no `on_fail_step_id`, so it just polled
`False` forever with a static, unchanging message.
"""

import time
from unittest.mock import patch

import pytest

from karcytics_plugins.flow_cytometry.tutorials import tutorial_assets as ta

# Captured before any test patches `ta.time.sleep` to a no-op (needed to keep
# the batch-retry backoff fast in tests) — `ta.time` and this module's `time`
# are the SAME module object, so patching one patches both; polling loops
# below use this real reference instead, so they still actually yield to the
# background thread rather than busy-spinning.
_real_sleep = time.sleep


@pytest.fixture(autouse=True)
def _reset_provisioning_state():
    ta.reset_status()
    yield
    ta.reset_status()


def _make_valid_files(folder):
    folder.mkdir(parents=True, exist_ok=True)
    for name in ta.TUTORIAL_FILENAMES:
        (folder / name).write_bytes(b"0" * 2000)


def test_download_tutorial_files_skips_already_valid_files(tmp_path):
    """A retry must not re-download files that already succeeded — this is
    what makes whole-batch retry cheap instead of re-fetching ~107MB again.
    """
    folder = tmp_path / "dl"
    _make_valid_files(folder)

    def fake_get(*_args, **_kwargs):
        raise AssertionError("should not be called — every file is already valid")

    with patch("requests.get", side_effect=fake_get):
        result = ta.download_tutorial_files(folder)

    assert result == folder


def test_ensure_tutorial_files_retries_whole_batch_on_transient_failure(tmp_path):
    """Regression: a download exception used to permanently set
    `_status.error` + `done=True` after just ONE batch attempt, with no
    automatic recovery. It must now retry the whole batch (cheaply, since
    already-downloaded files are skipped) before giving up.
    """
    downloads_folder = tmp_path / "downloads" / ta.TUTORIAL_FOLDER_NAME
    project_dir = tmp_path / "empty_project"
    project_dir.mkdir()

    attempts = {"n": 0}

    def fake_download(folder, progress_cb=None):
        attempts["n"] += 1
        if attempts["n"] < 2:
            raise ConnectionError("simulated transient network failure")
        _make_valid_files(folder)
        if progress_cb:
            progress_cb(len(ta.TUTORIAL_FILENAMES), len(ta.TUTORIAL_FILENAMES))
        return folder

    with (
        patch.object(ta, "resolve_downloads_folder", return_value=downloads_folder),
        patch.object(ta, "download_tutorial_files", side_effect=fake_download),
        patch.object(ta.time, "sleep", return_value=None),
    ):
        ta.ensure_tutorial_files(project_dir)
        for _ in range(100):
            if ta.get_status().done:
                break
            _real_sleep(0.02)

    status = ta.get_status()
    assert status.done
    assert status.error is None
    assert status.retry_count == 1
    assert attempts["n"] == 2


def test_ensure_tutorial_files_gives_up_after_max_attempts_but_still_marks_done(tmp_path):
    """Regression: previously, once `_status.error` was set, the provisioning
    VerificationStep (which has no `on_fail_step_id`) polled `False` forever
    with zero path forward. `done` must become True even on total failure,
    so the tutorial can at least reach a clear, actionable failure message
    instead of silently hanging.
    """
    downloads_folder = tmp_path / "downloads" / ta.TUTORIAL_FOLDER_NAME
    project_dir = tmp_path / "empty_project"
    project_dir.mkdir()

    def always_fails(folder, progress_cb=None):
        raise ConnectionError("simulated permanent network failure")

    with (
        patch.object(ta, "resolve_downloads_folder", return_value=downloads_folder),
        patch.object(ta, "download_tutorial_files", side_effect=always_fails),
        patch.object(ta.time, "sleep", return_value=None),
    ):
        ta.ensure_tutorial_files(project_dir)
        for _ in range(200):
            if ta.get_status().done:
                break
            _real_sleep(0.02)

    status = ta.get_status()
    assert status.done
    assert status.error is not None
    assert status.retry_count == ta.MAX_PROVISION_ATTEMPTS


def test_provisioning_has_stalled_detects_a_hung_thread():
    ta._status.started_at = time.monotonic() - (ta.MAX_PROVISION_WAIT_SECONDS + 5)
    ta._status.done = False
    assert ta.provisioning_has_stalled() is True


def test_provisioning_has_stalled_false_before_the_deadline():
    ta._status.started_at = time.monotonic()
    ta._status.done = False
    assert ta.provisioning_has_stalled() is False


def test_provisioning_has_stalled_false_once_done():
    ta._status.started_at = time.monotonic() - (ta.MAX_PROVISION_WAIT_SECONDS + 5)
    ta._status.done = True
    assert ta.provisioning_has_stalled() is False


class _FakeProjectManager:
    def __init__(self, assets_dir):
        self.assets_dir = assets_dir


class _FakeWindow:
    def __init__(self, project_manager):
        self.project_manager = project_manager


class _FakePanel:
    def __init__(self, project_manager):
        self._win = _FakeWindow(project_manager)

    def window(self):
        return self._win


def test_start_provisioning_resets_after_a_permanent_failure(tmp_path):
    """Regression: this is the actual fix for "had to restart the app" —
    re-entering the course (which re-runs the ActionStep calling
    `start_provisioning`) must genuinely retry from scratch instead of the
    `started` guard silently making it a permanent no-op forever.
    """
    project_dir = tmp_path / "project_assets"
    _make_valid_files(project_dir)
    panel = _FakePanel(_FakeProjectManager(project_dir))

    ta._status.started = True
    ta._status.done = True
    ta._status.error = "simulated prior permanent failure"

    ta.start_provisioning(panel)

    status = ta.get_status()
    assert status.done
    assert status.error is None
    assert status.location_kind == "project"


def test_start_provisioning_resets_after_a_stall(tmp_path):
    project_dir = tmp_path / "project_assets"
    _make_valid_files(project_dir)
    panel = _FakePanel(_FakeProjectManager(project_dir))

    ta._status.started = True
    ta._status.done = False
    ta._status.started_at = time.monotonic() - (ta.MAX_PROVISION_WAIT_SECONDS + 5)

    ta.start_provisioning(panel)

    status = ta.get_status()
    assert status.done
    assert status.error is None
    assert status.location_kind == "project"


def test_start_provisioning_does_not_reset_a_healthy_in_progress_run(tmp_path):
    """A currently-running (not stalled, not failed) attempt must not be
    clobbered just because the ActionStep happens to re-fire.
    """
    project_dir = tmp_path / "project_assets"
    panel = _FakePanel(_FakeProjectManager(project_dir))

    ta._status.started = True
    ta._status.done = False
    ta._status.started_at = time.monotonic()
    ta._status.current_file_index = 4

    ta.start_provisioning(panel)

    status = ta.get_status()
    assert status.current_file_index == 4  # untouched — no reset happened
