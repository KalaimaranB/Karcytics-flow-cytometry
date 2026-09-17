"""Provisions the 10 Course 1 tutorial FCS files onto the local disk.

Checked in order: the current project's ``assets`` folder, a well-known
Downloads subfolder, and finally a fresh download from the public
Karcytics-flow-cytometry GitHub repo's ``tests/data/fcs/`` directory — the
exact files used in CI, so every tutorial gate/validator is drawn against
known-good data regardless of where a given user's copy came from.

Runs the actual download on a plain background thread (mirroring
``analysis/numba_warmup.py``'s pattern) — pure filesystem + network I/O,
no Qt objects touched, so it's safe to kick off from an ActionStep without
risking the cross-thread Qt crashes this plugin has hit before.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from karcytics_sdk.plugin import get_logger

logger = get_logger(__name__, "flow_cytometry")

TUTORIAL_FOLDER_NAME = "Karcytics CytoAcademy Flow Files"

TUTORIAL_FILENAMES = [
    "Specimen_001_Blank.fcs",
    "Specimen_001_PI.fcs",
    "Specimen_001_FMO APC.fcs",
    "Specimen_001_FMO APCCy7.fcs",
    "Specimen_001_FMO FITC.fcs",
    "Specimen_001_FMO PE.fcs",
    "Specimen_001_FMO e450.fcs",
    "Specimen_001_Sample A.fcs",
    "Specimen_001_Sample B.fcs",
    "Specimen_001_Sample C.fcs",
]

_GITHUB_RAW_BASE = (
    "https://raw.githubusercontent.com/KalaimaranB/Karcytics-flow-cytometry/main/tests/data/fcs/"
)

# Real FCS files here are always ~10-11MB; guards against a truncated
# download or a GitHub error page silently masquerading as a real file.
_MIN_VALID_FILE_SIZE = 1024
_MAX_ATTEMPTS_PER_FILE = 3

# How many times to retry the *whole batch* if a download attempt fails
# after exhausting its own per-file retries (e.g. a rate limit or network
# blip that outlasts one file's backoff window). Cheap to retry — files
# already downloaded successfully are skipped, not re-fetched.
MAX_PROVISION_ATTEMPTS = 3

# Independent safety net, checked by the validator rather than the download
# thread itself: if nothing has finished after this long, something is
# wrong (e.g. a hung socket the request timeout didn't catch) and we'd
# rather report a clear, actionable error than poll silently forever.
MAX_PROVISION_WAIT_SECONDS = 5 * 60


def resolve_downloads_folder() -> Path:
    """Resolves the OS's real Downloads folder — must be called on the main thread.

    Uses Qt's QStandardPaths (same convention as ``karcytics/tutorials/core_intro.py``)
    so this respects OS-level redirection (e.g. a OneDrive-redirected Downloads
    folder on Windows, XDG user-dirs on Linux) instead of blindly assuming
    ``~/Downloads``. QStandardPaths is a Qt call, so it's kept out of the
    background download thread entirely — resolved once here and threaded
    through as a plain Path from then on.
    """
    from PyQt6.QtCore import QStandardPaths

    download_loc = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation)
    base = Path(download_loc) if download_loc else Path.home() / "Downloads"
    return base / TUTORIAL_FOLDER_NAME


def _folder_has_all_files(folder: Path) -> bool:
    if not folder.is_dir():
        return False
    return all(
        (folder / name).is_file() and (folder / name).stat().st_size > _MIN_VALID_FILE_SIZE
        for name in TUTORIAL_FILENAMES
    )


def find_ready_folder(project_assets_dir: Path | None, downloads_folder: Path) -> Path | None:
    """Returns a folder that already has all 10 tutorial files, or None."""
    if project_assets_dir is not None and _folder_has_all_files(project_assets_dir):
        return project_assets_dir
    if _folder_has_all_files(downloads_folder):
        return downloads_folder
    return None


def _download_single_file(name: str, dest: Path, ssl_context: Any) -> None:
    import urllib.error
    import urllib.request

    url = _GITHUB_RAW_BASE + urllib.parse.quote(name)
    tmp_dest = dest.with_suffix(dest.suffix + ".part")
    last_exc: Exception | None = None
    for attempt in range(1, _MAX_ATTEMPTS_PER_FILE + 1):
        try:
            logger.info(f"Downloading tutorial file {name!r} (attempt {attempt})")
            req = urllib.request.Request(url, headers={"User-Agent": "Karcytics-Academy/1.0"})
            with (
                urllib.request.urlopen(req, timeout=60, context=ssl_context) as resp,
                open(tmp_dest, "wb") as f,
            ):
                while True:
                    chunk = resp.read(1024 * 256)
                    if not chunk:
                        break
                    f.write(chunk)
            tmp_dest.replace(dest)
            last_exc = None
            break
        except urllib.error.HTTPError as exc:
            last_exc = Exception(f"HTTP {exc.code} Server Error on {name}")
            logger.warning(f"Download attempt {attempt} for {name!r} failed: {exc}")
        except urllib.error.URLError as exc:
            if "CERTIFICATE_VERIFY_FAILED" in str(exc.reason):
                last_exc = Exception(
                    "SSL Certificate verification failed (often caused by corporate proxies or missing CA bundles)"
                )
            else:
                last_exc = Exception(f"Network connection failed: {exc.reason}")
            logger.warning(f"Download attempt {attempt} for {name!r} failed: {exc}")
        except PermissionError as exc:
            last_exc = Exception(
                "Permission denied. Does Karcytics have access to your Downloads folder?"
            )
            logger.warning(f"Download attempt {attempt} for {name!r} failed: {exc}")
        except Exception as exc:  # noqa: BLE001
            last_exc = Exception(f"Unexpected error: {exc}")
            logger.warning(f"Download attempt {attempt} for {name!r} failed: {exc}")

        tmp_dest.unlink(missing_ok=True)
        if attempt < _MAX_ATTEMPTS_PER_FILE:
            time.sleep(2 * attempt)

    if last_exc is not None:
        raise last_exc


def download_tutorial_files(
    folder: Path,
    progress_cb: Callable[[int, int], None] | None = None,
) -> Path:
    """Downloads any missing tutorial FCS files into ``folder``.

    Safe to call from a background thread — ``folder`` must already be a
    resolved Path (see ``resolve_downloads_folder``), so this never touches
    Qt itself. Skips any file already present and valid, so a
    retried/interrupted run resumes cheaply instead of re-fetching all
    ~107MB. Each file gets up to ``_MAX_ATTEMPTS_PER_FILE`` attempts before
    the error propagates.
    """
    import ssl

    ssl_context = ssl.create_default_context()
    try:
        import certifi

        ssl_context.load_verify_locations(certifi.where())
    except ImportError:
        pass

    folder.mkdir(parents=True, exist_ok=True)

    total = len(TUTORIAL_FILENAMES)
    for i, name in enumerate(TUTORIAL_FILENAMES):
        dest = folder / name
        if dest.is_file() and dest.stat().st_size > _MIN_VALID_FILE_SIZE:
            if progress_cb:
                progress_cb(i + 1, total)
            continue

        _download_single_file(name, dest, ssl_context)

        if progress_cb:
            progress_cb(i + 1, total)

    return folder


class _ProvisionStatus:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.started = False
        self.done = False
        self.error: str | None = None
        self.folder: Path | None = None
        # Where `folder` came from — lets step text describe the right
        # place instead of always pointing at Downloads. One of "project",
        # "downloads_existing", "downloaded", or None (not resolved yet).
        self.location_kind: str | None = None
        self.current_file_index = 0
        self.total_files = len(TUTORIAL_FILENAMES)
        # Which whole-batch attempt is in flight (0 = first try, no retry
        # yet) — surfaced in step text so a retry is visible, not silent.
        self.retry_count = 0
        # Set once the background thread actually starts (not on the
        # instant-ready path) — lets the validator detect a genuine stall
        # independent of whatever the download thread itself is doing.
        self.started_at: float | None = None


_status = _ProvisionStatus()


def get_status() -> _ProvisionStatus:
    return _status


def reset_status() -> None:
    """Clears state — mainly for tests, or re-entering the step after a restart."""
    global _status
    _status = _ProvisionStatus()


def ensure_tutorial_files(project_assets_dir: Path | None) -> None:
    """Idempotent: safe to call every poll tick, only launches work once.

    Must be called on the main thread (it resolves the Downloads folder via
    Qt). If the files are already present (project assets or Downloads),
    marks status done immediately — no thread, no network. Otherwise starts
    a background download thread and returns right away.
    """
    with _status.lock:
        if _status.started:
            return
        _status.started = True

    downloads_folder = resolve_downloads_folder()
    ready = find_ready_folder(project_assets_dir, downloads_folder)
    if ready is not None:
        with _status.lock:
            _status.folder = ready
            _status.location_kind = (
                "project" if ready == project_assets_dir else "downloads_existing"
            )
            _status.done = True
        return

    def _progress(i: int, total: int) -> None:
        with _status.lock:
            _status.current_file_index = i
            _status.total_files = total

    def _run() -> None:
        with _status.lock:
            _status.started_at = time.monotonic()

        # Retries the WHOLE batch, not just individual files — cheap, since
        # download_tutorial_files skips anything already downloaded and
        # valid, so a retry only re-fetches whatever actually failed. This
        # is what makes a transient blip (rate limit, one bad connection)
        # self-heal instead of permanently wedging the tutorial the moment
        # a single file's own retries run out.
        for attempt in range(1, MAX_PROVISION_ATTEMPTS + 1):
            try:
                folder = download_tutorial_files(downloads_folder, progress_cb=_progress)
                with _status.lock:
                    _status.folder = folder
                    _status.location_kind = "downloaded"
                    _status.error = None
                    _status.done = True
                return
            except Exception as exc:  # noqa: BLE001
                logger.exception(f"Tutorial file provisioning attempt {attempt} failed")
                with _status.lock:
                    _status.error = str(exc)
                    _status.retry_count = attempt
                if attempt < MAX_PROVISION_ATTEMPTS:
                    time.sleep(5 * attempt)

        # Every attempt failed — mark done anyway so the tutorial actually
        # advances (to a clear failure message) instead of polling a
        # background thread that has already given up, forever.
        with _status.lock:
            _status.done = True

    threading.Thread(target=_run, daemon=True, name="tutorial-fcs-provision").start()


def provisioning_has_stalled() -> bool:
    """True if provisioning started but neither finished nor errored out
    within ``MAX_PROVISION_WAIT_SECONDS`` — e.g. a hung socket the request
    timeout didn't catch. Independent of whatever the background thread
    thinks its own state is, so a genuinely stuck thread can still be
    detected and recovered from.
    """
    return (
        not _status.done
        and _status.started_at is not None
        and (time.monotonic() - _status.started_at) > MAX_PROVISION_WAIT_SECONDS
    )


def describe_files_location() -> str:
    """Short clause for step text describing where the provisioned tutorial
    files ended up — differs depending on whether they were already sitting
    in the project's own assets folder (no Downloads folder involved at
    all) versus needing to be found/fetched in Downloads.
    """
    if _status.location_kind == "project":
        return "your 10 tutorial files are already bundled into this project's assets folder"
    return f"your 10 tutorial files are waiting in Downloads → '{TUTORIAL_FOLDER_NAME}'"


def start_provisioning(panel) -> None:  # noqa: ANN001
    """ActionStep entry point — resolves the project's assets dir (if any) and
    kicks off ``ensure_tutorial_files``. Any failure resolving the project
    manager just falls back to the Downloads-only check.

    If a previous attempt (within this same app session) exhausted every
    retry and gave up, OR stalled out without ever finishing, ``_status``
    is reset first — otherwise ``ensure_tutorial_files``'s ``started``
    guard would make this a permanent no-op, and the ONLY way to ever try
    again would be to fully restart the application. Re-opening the course
    from the Academy hub (which re-runs this ActionStep) now genuinely
    retries instead. Any old, still-running background thread is simply
    abandoned (it's a daemon thread, so it dies with the app either way).
    """
    status = get_status()
    if (status.done and status.error) or provisioning_has_stalled():
        reset_status()

    assets_dir: Path | None = None
    try:
        pm = getattr(panel.window(), "project_manager", None)
        if pm is not None:
            assets_dir = pm.assets_dir
    except Exception:  # noqa: BLE001
        assets_dir = None
    ensure_tutorial_files(assets_dir)
