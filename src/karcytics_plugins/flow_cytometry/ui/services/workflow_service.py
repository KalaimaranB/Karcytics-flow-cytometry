"""Workflow service for managing serialization and hydration of flow experiments."""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ...analysis.state import FlowState

from PyQt6.QtCore import QObject, pyqtSlot

from ...analysis.derived import sync_experiment


class WorkflowService(QObject):
    """Handles saving and loading of flow cytometry workflows."""

    def __init__(self, state: FlowState, data_loader_service, attachment_manager, parent=None):
        super().__init__(parent)
        from karcytics_sdk.plugin import get_logger

        self.logger = get_logger("flow.workflow_service", "flow_cytometry")

        self._state = state
        self._data_loader = data_loader_service
        self._attachment_manager = attachment_manager
        self._pending_task_id = None
        self._pending_on_complete = None

        scheduler = getattr(self._data_loader, "_scheduler", None)
        if scheduler is not None and hasattr(scheduler, "task_finished"):
            scheduler.task_finished.connect(self._on_task_done_handler)
            if hasattr(scheduler, "task_error"):
                scheduler.task_error.connect(self._on_task_error_handler)
            self.logger.info(
                f"Successfully connected to TaskScheduler.task_finished in __init__. id(self)={id(self)}"
            )
        else:
            self.logger.warning(
                f"Could not connect to TaskScheduler.task_finished. scheduler={scheduler} id(self)={id(self)}"
            )

    def export_workflow(self, context=None, project_dir: Path | None = None) -> dict:
        """Serialize the current state to a workflow dictionary.

        Args:
            context: Optional WorkflowContext for binary attachments.
            project_dir: Root of the current project, if any. Sample FCS
                paths that live inside it are stored *relative* to it (POSIX
                style) instead of as an absolute path, so the workflow
                resolves correctly when the whole project directory is
                copied to a different machine or OS. Files outside the
                project (or when no project_dir is known) still fall back to
                an absolute path — unchanged from before, and still what
                gets read by workflows saved prior to this.
        """
        sample_paths = {}
        for sid, sample in self._state.data.experiment.samples.items():
            if sample.fcs_data and sample.fcs_data.file_path:
                file_path = sample.fcs_data.file_path
                if project_dir is not None:
                    try:
                        if file_path.is_relative_to(project_dir):
                            sample_paths[sid] = file_path.relative_to(project_dir).as_posix()
                            continue
                    except ValueError:
                        pass
                sample_paths[sid] = str(file_path)

        from ...analysis.workspace_document import serialize_workspace

        payload = serialize_workspace(self._state)
        payload["sample_paths"] = sample_paths

        if context is not None:
            attachments_meta = self._attachment_manager.serialize_attachments(self._state, context)
            if attachments_meta:
                payload["attachments"] = attachments_meta

        return payload

    def load_workflow(  # noqa: PLR0915
        self,
        payload: dict,
        context=None,
        on_complete=None,
        project_dir: Path | None = None,
        **kwargs,
    ) -> bool:
        """Restore the state from a workflow dictionary.

        Args:
            project_dir: Root of the current project, if any. Used to resolve
                sample FCS paths that were stored relative to the project
                (see export_workflow) — required for a workflow saved on one
                machine/OS to find its data after the whole project directory
                is copied to another.
        """
        from ...analysis.workspace_document import apply_workspace

        if not payload:
            self.logger.warning("Empty workflow payload.")
            return False

        self.logger.info("Restoring FlowState from workflow payload...")
        try:
            actual_data = payload.get("payload", payload)

            # Replaces the whole previous workspace in place — experiment,
            # compensation, view, and any UMAP runs (restored below from
            # attachments, if this workflow has any).
            apply_workspace(self._state, actual_data)
            exp_data = actual_data.get("experiment", {})

            def _post_fcs_load(reload_result: dict[str, list[str]] | None = None):
                if context is not None:
                    # Legacy format compatibility
                    if "umap_results_meta" in actual_data:
                        meta_dict = actual_data["umap_results_meta"]
                        if isinstance(meta_dict, dict) and any(
                            isinstance(v, list) for v in meta_dict.values()
                        ):
                            results = self._attachment_manager.hydrate_umap_results(
                                meta_dict, self._state, context
                            )
                            if results:
                                self._state.data.umap_results = results
                                self.logger.info("Restored legacy UMAP binary attachments.")
                        else:
                            self.logger.info(
                                "Discarded old single-run UMAP format for compatibility."
                            )

                    # New generic format
                    if "attachments" in actual_data:
                        self._attachment_manager.hydrate_attachments(
                            actual_data["attachments"], self._state, context
                        )
                        self.logger.info("Restored binary attachments.")

                self.logger.info("Workflow loaded successfully.")
                if on_complete:
                    on_complete(reload_result)

            if exp_data:
                sample_paths = actual_data.get("sample_paths", {})
                if sample_paths:
                    self.reload_fcs_data(
                        sample_paths, project_dir=project_dir, on_complete=_post_fcs_load
                    )
                else:
                    _post_fcs_load()
            else:
                _post_fcs_load()

            return True
        except Exception as exc:
            self._last_error = str(exc)
            self.logger.exception(f"Failed to load workflow: {exc}")
            return False

    def reload_fcs_data(
        self,
        sample_paths: dict[str, str],
        project_dir: Path | None = None,
        on_complete=None,
    ) -> None:
        """Reload FCS event data asynchronously using SDK FunctionalTask on background thread.

        Loads every sample in a single batched daemon round-trip
        (``DataLoaderService.reload_samples_batch``) instead of fanning out
        N per-sample ``load_fcs()`` calls across a thread pool — those all
        serialize through fcs_io's single process-wide daemon IPC lock, so
        one slow/stuck file used to stall every other sample's load behind
        it for up to that file's full IPC timeout, well past the UI's
        45s crossfade watchdog, with no error surfaced anywhere.

        Args:
            project_dir: Root of the current project. A non-absolute stored
                path (see export_workflow) is resolved against this — an
                absolute stored path (legacy saves, or files outside the
                project) is used as-is, same as before.
            on_complete: Called with a ``{"loaded": [...], "failed": [...]}``
                dict of sample display names once the reload finishes.
        """
        from karcytics_sdk.plugin.managed_task import FunctionalTask

        t_submitted = time.monotonic()

        def _bg_reload() -> dict[str, list[str]]:
            queue_delay = time.monotonic() - t_submitted
            self.logger.info(f"_bg_reload: started executing {queue_delay:.2f}s after submission")
            samples_with_paths: list[tuple[Any, Path]] = []
            for sid, path_str in sample_paths.items():
                sample = self._state.data.experiment.samples.get(sid)
                if sample is None:
                    continue
                path = Path(path_str)
                if not path.is_absolute() and project_dir is not None:
                    path = project_dir / path
                samples_with_paths.append((sample, path))

            result = self._data_loader.reload_samples_batch(
                samples_with_paths, self._state.data.compensation
            )
            # Rebuild derived columns before on_complete evaluates any gates
            # that were drawn on them.
            sync_experiment(self._state.data.experiment)
            return result

        task = FunctionalTask(_bg_reload, plugin_id="flow_cytometry", name="Reload FCS Files")
        scheduler = getattr(self._data_loader, "_scheduler", None)

        if scheduler is not None:
            try:
                worker = scheduler.submit(task, None)
                task_id = getattr(worker, "task_id", None)
                self.logger.info(f"Submitted FCS reload FunctionalTask {task_id} to TaskScheduler.")
                if on_complete:
                    self._pending_task_id = task_id
                    self._pending_on_complete = on_complete
                return
            except Exception as e:
                self.logger.exception(f"Failed to submit async reload task to TaskScheduler: {e}")

        # Fallback for sync environments without TaskScheduler
        result = _bg_reload()
        if on_complete:
            on_complete(result)

    @pyqtSlot(str, str)
    def _on_task_error_handler(self, failed_id: str, error_msg: str) -> None:
        """A reload task that raised still has to complete its load.

        Without this, the caller's on_complete never ran — the panel stayed
        "loading" (undo refused, nothing recorded) for the rest of the
        session. Reported as every sample having failed to reload.
        """
        if not self._pending_task_id or failed_id != self._pending_task_id:
            return
        self.logger.error(f"FCS reload task {failed_id} failed: {error_msg}")
        self._pending_task_id = None
        cb, self._pending_on_complete = self._pending_on_complete, None
        if cb:
            names = [s.display_name for s in self._state.data.experiment.samples.values()]
            cb({"loaded": [], "failed": names})

    @pyqtSlot(str, dict)
    def _on_task_done_handler(self, finished_id: str, results: dict) -> None:
        """Handle completion of background FunctionalTasks from TaskScheduler."""
        pending_id = self._pending_task_id

        if pending_id and finished_id == pending_id:
            self.logger.info(
                f"FCS reload FunctionalTask {finished_id} finished! Executing on_complete callback..."
            )
            self._pending_task_id = None
            cb = getattr(self, "_pending_on_complete", None)
            self._pending_on_complete = None
            if cb:
                cb(results)
