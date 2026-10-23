"""FCS Loader Analysis — Background worker for loading FCS files asynchronously."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import TYPE_CHECKING, Any

from karcytics_sdk.plugin import AnalysisBase, PluginState, get_logger

from .fcs_io import load_fcs_batch

if TYPE_CHECKING:
    from .daemon_port import DaemonCall

logger = get_logger(__name__, "flow_cytometry")

# Files per daemon round-trip during phase 2. Bounded rather than sending the
# whole selection in one call, so peak memory (each in-flight file holds a
# raw array plus its base64-encoded transit copy inside the daemon process)
# stays predictable and the progress bar/cancel button stay responsive
# between chunks — while still large enough to keep the daemon's internal
# thread pool (see `_MAX_BATCH_WORKERS` in daemon_worker.py) fully utilized.
_CHUNK_SIZE = 6


class FCSLoaderAnalysis(AnalysisBase):
    """Background analyzer for parallel loading of FCS files."""

    def __init__(self, daemon: DaemonCall, plugin_id: str = "flow_cytometry"):
        super().__init__(plugin_id)
        self._daemon = daemon
        self.file_paths: list[str | Path] = []
        self.project_manager: object | None = None
        self.copy_all: bool = False

    def validate(self, _state: PluginState | None) -> tuple[bool, str]:
        """Verify that there are files to load and that they exist."""
        if not getattr(self, "file_paths", []):
            return False, "No files selected for loading."
        for path in self.file_paths:
            if not Path(path).exists():
                return False, f"File not found: {path}"
        return True, ""

    def run(self, _state: PluginState | None = None) -> dict[str, Any]:
        """Registers assets, then loads FCS files in parallel batches."""
        logger.info(f"FCSLoaderAnalysis: Starting load for {len(self.file_paths)} files")

        input_paths = [Path(p) for p in self.file_paths]
        total_files = len(input_paths)
        self.signals.analysis_progress.emit(0)

        # Registration gets the first 40% of the bar; parsing gets the rest.
        final_paths = self._register_assets(input_paths, total_files)
        if final_paths is None:
            return {"error": "Task cancelled."}

        results = self._load_in_chunks(input_paths, final_paths, total_files)
        if results is None:
            return {"error": "Task cancelled."}

        self.signals.analysis_progress.emit(100)
        logger.info(f"FCSLoaderAnalysis: Completed loading {len(results)} files")
        return {"loaded_data": results}

    def _register_assets(
        self, input_paths: list[Path], total_files: int
    ) -> dict[Path, Path] | None:
        """Hash/copy each file into the workspace, in parallel.

        Local disk I/O per file — independent of FCS parsing, and not
        subject to the single-daemon-process constraint chunked loading
        works around, so a plain thread pool is fine here. Returns None
        if the task was cancelled mid-registration.
        """
        pm_lock = threading.Lock()

        def register(path: Path) -> Path:
            final_path = path
            pm = getattr(self, "project_manager", None)
            if pm:
                with pm_lock:
                    is_in_workspace = pm.assets_dir.resolve() in path.resolve().parents
                    should_copy = getattr(self, "copy_all", False) and not is_in_workspace
                    try:
                        file_hash = pm.add_image(path, should_copy)
                        resolved = pm.get_asset_path(file_hash)
                        if resolved:
                            final_path = resolved
                    except Exception as e:
                        logger.exception(f"Asset registration error for {path}: {e}")
            return final_path

        final_paths: dict[Path, Path] = {}
        registered = 0

        with ThreadPoolExecutor() as executor:
            future_to_path = {executor.submit(register, p): p for p in input_paths}
            for future in as_completed(future_to_path):
                if self.is_cancelled():
                    for f in future_to_path:
                        f.cancel()
                    return None

                path = future_to_path[future]
                try:
                    final_paths[path] = future.result()
                except Exception as exc:
                    logger.exception(f"Asset registration error for {path}: {exc}")
                    final_paths[path] = path

                registered += 1
                self.signals.analysis_progress.emit(int((registered / total_files) * 40))

        return final_paths

    def _load_in_chunks(
        self, input_paths: list[Path], final_paths: dict[Path, Path], total_files: int
    ) -> dict[str, Any] | None:
        """Load registered files via chunked, daemon-batched FCS parsing.

        Returns None if the task was cancelled between chunks.
        """
        ordered_final_paths = [final_paths[p] for p in input_paths]
        results: dict[str, Any] = {}
        loaded = 0

        for i in range(0, len(ordered_final_paths), _CHUNK_SIZE):
            if self.is_cancelled():
                return None

            chunk = ordered_final_paths[i : i + _CHUNK_SIZE]
            chunk_results = load_fcs_batch(chunk, self._daemon, cancel_poll=self.is_cancelled)

            for final_path in chunk:
                value = chunk_results.get(final_path)
                if isinstance(value, Exception):
                    logger.exception(f"FCSLoaderAnalysis: Failed to load {final_path}: {value}")
                    results[str(final_path)] = {"error": str(value)}
                elif value is None:
                    results[str(final_path)] = {"error": "No result returned for file."}
                else:
                    results[str(final_path)] = value

            loaded += len(chunk)
            self.signals.analysis_progress.emit(40 + int((loaded / total_files) * 60))

        return results
