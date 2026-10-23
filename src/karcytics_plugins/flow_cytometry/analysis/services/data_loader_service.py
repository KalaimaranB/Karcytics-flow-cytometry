"""Data loader service for handling FCS file loading and compensation.

Encapsulates data ingestion to adhere to SRP and DIP, preventing
high-level services like WorkflowService from depending directly
on concrete io functions.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from karcytics_sdk.plugin import PluginState, get_logger

from ..compensation import CompensationMatrix, apply_compensation
from ..experiment import Sample
from ..fcs_io import FCSData, load_fcs, load_fcs_batch
from ..fcs_loader_analysis import FCSLoaderAnalysis

if TYPE_CHECKING:
    from ..daemon_port import DaemonCall

logger = get_logger(__name__, "flow_cytometry")

_backend_diag_logged = False


def _log_dataframe_backend_once() -> None:
    """One-time diagnostic: which pandas/pyarrow copy is actually resolving.

    See SegFaultCrash.md — a crash was traced to pyarrow's bundled mimalloc
    allocator running inside this reload path (via pandas internally calling
    into it, e.g. through maybe_convert_objects), even though pyarrow isn't
    a declared dependency of this plugin. That's only possible if this
    process is silently running against the *host app's* pandas/pyarrow
    (both installed in Karcytics/.venv) instead of this plugin's own isolated
    copy — logged here so the next crash report confirms which one it was,
    without needing another live-lldb session to find out.
    """
    global _backend_diag_logged
    if _backend_diag_logged:
        return
    _backend_diag_logged = True
    try:
        import pandas

        logger.info(f"dataframe backend check: pandas {pandas.__version__} from {pandas.__file__}")
        try:
            import pyarrow  # type: ignore[import-not-found]  # optional — not a declared dependency

            logger.info(
                f"dataframe backend check: pyarrow {pyarrow.__version__} from {pyarrow.__file__}"
            )
        except ImportError:
            logger.info(
                "dataframe backend check: pyarrow not importable (expected — not a "
                "declared dependency of this plugin)."
            )
    except Exception as exc:
        logger.warning(f"dataframe backend check: diagnostic import failed: {exc}")


class DataLoaderService:
    """Service responsible for loading Flow Cytometry Standard data."""

    def __init__(
        self, scheduler: object | None, daemon: DaemonCall, plugin_id: str = "flow_cytometry"
    ):
        self._scheduler: Any = scheduler
        self._daemon = daemon
        self._current_worker = None
        self._current_task_id = None
        self._plugin_id = plugin_id

    def reload_sample(
        self, sample: Sample, path: Path, compensation_matrix: CompensationMatrix | None = None
    ) -> bool:
        """Reload FCS event data for a given sample.

        Args:
            sample: The sample object to reload data into.
            path: Path to the FCS file.
            compensation_matrix: Optional compensation matrix to re-apply.

        Returns:
            bool: True if reload was successful, False otherwise.
        """
        if not path.exists():
            logger.warning(f"FCS file no longer exists: {path} (sample: {sample.display_name})")
            return False

        try:
            fcs_data = load_fcs(path, self._daemon)

            # Re-apply compensation if it was active when saved
            if (
                sample.is_compensated
                and compensation_matrix is not None
                and not fcs_data.is_compensated
            ):
                fcs_data.events = apply_compensation(fcs_data, compensation_matrix)
                fcs_data.is_compensated = True
                logger.info(
                    f"Re-applied Karcytics compensation matrix to reloaded sample '{sample.display_name}'"
                )

            sample.fcs_data = fcs_data
            logger.info(
                f"Reloaded FCS data for '{sample.display_name}': {fcs_data.num_events} events"
            )
            return True
        except Exception as exc:
            logger.warning(f"Failed to reload FCS for '{sample.display_name}': {exc}")
            return False

    def reload_samples_batch(
        self,
        samples_with_paths: list[tuple[Sample, Path]],
        compensation_matrix: CompensationMatrix | None = None,
    ) -> dict[str, list[str]]:
        """Reload FCS event data for many samples via one batched daemon round-trip.

        Prefer this over calling ``reload_sample()`` for each sample from a
        pool of worker threads: every ``reload_sample()`` -> ``load_fcs()``
        call serializes through the worker process (PluginDaemon takes one call at a
        time), so "parallel" reloads collapse into one file at a
        time — and one slow or stuck file blocks every other sample's load
        behind it for up to its full IPC timeout. Batching sends a single
        request and lets the daemon parse files concurrently inside its own
        process (see ``load_fcs_batch`` / ``handle_load_fcs_batch``), with
        one bad file never blocking or failing the rest.

        Returns ``{"loaded": [display names], "failed": [display names]}``.
        """
        if not samples_with_paths:
            return {"loaded": [], "failed": []}

        _log_dataframe_backend_once()

        paths = [path for _, path in samples_with_paths]
        logger.info(f"reload_samples_batch: calling load_fcs_batch for {len(paths)} files...")
        t0 = time.monotonic()
        results = load_fcs_batch(paths, self._daemon)
        logger.info(
            f"reload_samples_batch: load_fcs_batch returned after {time.monotonic() - t0:.2f}s"
        )

        loaded: list[str] = []
        failed: list[str] = []

        for sample, path in samples_with_paths:
            result = results.get(path)
            if not isinstance(result, FCSData):
                reason = result if isinstance(result, Exception) else "no result returned"
                logger.warning(f"Failed to reload FCS for '{sample.display_name}': {reason}")
                failed.append(sample.display_name)
                continue

            fcs_data = result
            if (
                sample.is_compensated
                and compensation_matrix is not None
                and not fcs_data.is_compensated
            ):
                fcs_data.events = apply_compensation(fcs_data, compensation_matrix)
                fcs_data.is_compensated = True
                logger.info(
                    f"Re-applied Karcytics compensation matrix to reloaded sample "
                    f"'{sample.display_name}'"
                )

            sample.fcs_data = fcs_data
            logger.info(
                f"Reloaded FCS data for '{sample.display_name}': {fcs_data.num_events} events"
            )
            loaded.append(sample.display_name)

        return {"loaded": loaded, "failed": failed}

    def load_samples_async(  # noqa: PLR0913
        self,
        paths: list[str | Path],
        state: PluginState | None,
        on_done: Callable[[dict], None],
        on_error_cb: Callable[[str], None],
        on_progress: Callable[[int], None] | None = None,
        project_manager: object | None = None,
        copy_all: bool = False,
    ) -> None:
        """Submit a background task to load multiple FCS files."""
        if not self._scheduler:
            on_error_cb("No TaskScheduler available.")
            return

        analyzer = FCSLoaderAnalysis(self._daemon)
        analyzer.file_paths = paths
        analyzer.project_manager = project_manager
        analyzer.copy_all = copy_all

        try:
            worker = self._scheduler.submit(analyzer, state)
            self._current_worker = worker
            self._current_task_id = worker.task_id

            logger.info(f"DataLoaderService: Submitted load task {self._current_task_id}")

            if on_progress:
                worker.progress.connect(on_progress)

            def _on_finished(finished_task_id: str, results: dict):
                if finished_task_id == self._current_task_id:
                    self._current_worker = None
                    self._current_task_id = None
                    try:
                        self._scheduler.task_finished.disconnect(_on_finished)
                        self._scheduler.task_error.disconnect(_on_error)
                    except (TypeError, RuntimeError):
                        pass
                    on_done(results)

            def _on_error(error_task_id: str, error_msg: str):
                if error_task_id == self._current_task_id:
                    self._current_worker = None
                    self._current_task_id = None
                    try:
                        self._scheduler.task_finished.disconnect(_on_finished)
                        self._scheduler.task_error.disconnect(_on_error)
                    except (TypeError, RuntimeError):
                        pass
                    on_error_cb(error_msg)

            self._scheduler.task_finished.connect(_on_finished)
            self._scheduler.task_error.connect(_on_error)

        except Exception as e:
            logger.exception(f"DataLoaderService: Failed to submit task: {e}")
            on_error_cb(str(e))
