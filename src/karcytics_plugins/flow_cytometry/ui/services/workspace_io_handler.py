"""Workspace IO Handler.

Saves and updates flow cytometry workflows, into the project (ProjectManager) or a
standalone archive, off the GUI thread. The open workflow's name, metadata and
save state live on the `WorkflowDocument`. Loading goes through the panel's
`load_workflow`, which the Hub calls.
"""

from collections.abc import Callable
from typing import Any

from karcytics_sdk.plugin import CentralEventBus, get_logger
from karcytics_sdk.plugin.dialogs import SaveWorkflowDialog, get_save_path, show_error, show_info
from karcytics_sdk.plugin.managed_task import FunctionalTask
from karcytics_sdk.plugin.runtime_services import task_scheduler

from ...analysis import events
from .workflow_document import WorkflowDocument
from .workspace_save_service import WorkspaceSaveService
from .zip_export_service import ZipExportService

logger = get_logger(__name__, "flow_cytometry")


class WorkspaceIOHandler:
    """Writes the workspace to the project or to a standalone archive."""

    def __init__(self, workflow_service, document: WorkflowDocument, parent_widget: Any):
        self.workflow_service = workflow_service
        self.document = document
        self.parent_widget = parent_widget

    def _module_id(self) -> str:
        return getattr(self.parent_widget.window(), "current_module_id", "flow_cytometry")

    def _run_save(
        self,
        name: str,
        task: Callable[[], Any],
        on_success: Callable[[dict], None],
        on_error: Callable[[str], None],
    ) -> None:
        """Runs one save on the task pool, keeping the document's save state."""
        token = self.document.begin_save()

        def _on_finished(results: dict) -> None:
            self.document.finish_save(token)
            on_success(results)

        def _on_task_error(err: str) -> None:
            self.document.save_failed()
            on_error(err)

        worker = task_scheduler.submit(FunctionalTask(task, name=name), None)
        worker.finished.connect(_on_finished)
        worker.error.connect(_on_task_error)

    def save_to_project(
        self,
        pm: Any,
        filename: str | None,
        metadata: dict[str, Any],
        on_success: Callable[[str], None],
        on_error: Callable[[str], None],
    ) -> None:
        """Saves into the project as `filename` (a new workflow when None)."""
        module_id = self._module_id()
        self._run_save(
            "Save Workflow to PM",
            lambda: WorkspaceSaveService.save_to_pm(
                pm, self.workflow_service, filename, metadata, module_id
            ),
            lambda results: on_success(str(results.get("result", ""))),
            on_error,
        )

    @staticmethod
    def _publish_saved(**payload: str) -> None:
        try:
            CentralEventBus.publish(events.WORKFLOW_SAVED, payload)
        except Exception as e:
            logger.debug(f"Failed to publish workflow saved event: {e}")

    def handle_save(self) -> None:
        """Save: into the project when there is one, else to a standalone archive."""
        pm = self.document.project_manager()
        if pm is None:
            self._save_standalone()
            return

        filename, metadata = self.document.filename, self.document.metadata
        if not filename or not metadata:
            dialog = SaveWorkflowDialog(self.parent_widget)
            if not dialog.exec():
                return
            metadata = dialog.get_metadata()

        def _on_success(new_filename: str) -> None:
            self.document.filename = new_filename
            self.document.metadata = metadata
            show_info(
                self.parent_widget,
                "Workflow Saved",
                f"Workflow saved successfully to project:\n{new_filename}",
            )
            self._publish_saved(filename=new_filename)

        def _on_error(err: str) -> None:
            logger.error(f"Failed to save workflow to project: {err}")
            show_error(self.parent_widget, "Save Error", f"Failed to save workflow:\n{err}")

        self.save_to_project(pm, filename, metadata, _on_success, _on_error)

    def _save_standalone(self) -> None:
        path = self.document.path
        if not path:
            path = get_save_path(
                self.parent_widget,
                "Save Flow Cytometry Workflow",
                file_filter="Karcytics Flow Cytometry Archive (*.zip);;JSON Files (*.json)",
            )
            if not path:
                return
            self.document.path = path
        logger.info(f"Saving workflow to {path}")

        def _task() -> str:
            ZipExportService.save_standalone(self.workflow_service, path)
            return path

        def _on_success(_results: dict) -> None:
            show_info(
                self.parent_widget, "Workflow Saved", f"Workflow saved successfully to\n{path}"
            )
            self._publish_saved(path=path)

        def _on_error(err: str) -> None:
            logger.error(f"Failed to save workflow: {err}")
            show_error(self.parent_widget, "Save Error", f"Failed to save workflow:\n{err}")

        self._run_save("Save Standalone Workflow", _task, _on_success, _on_error)

    def _current_filename_and_pm(self) -> tuple[str, Any] | None:
        """`(filename, pm)` for the workflow already in the project, or None.

        Update and autosave only ever overwrite an already-named workflow.
        """
        filename = self.document.filename
        pm = self.document.project_manager()
        if not filename or pm is None:
            return None
        return filename, pm

    def handle_update(self) -> None:
        """Overwrite the workflow already saved in the project."""
        current = self._current_filename_and_pm()
        if current is None:
            if self.document.project_manager() is None:
                show_error(
                    self.parent_widget,
                    "Error",
                    "Project Manager not found. Cannot update workflow.",
                )
            else:
                show_info(
                    self.parent_widget,
                    "No Workflow Loaded",
                    "There is no currently loaded workflow to update. "
                    "Please use 'Save New Workflow' instead.",
                )
            return
        filename, pm = current

        def _on_success(_new_filename: str) -> None:
            show_info(
                self.parent_widget,
                "Workflow Updated",
                f"Workflow updated successfully:\n{filename}",
            )
            self._publish_saved(filename=filename)

        def _on_error(err: str) -> None:
            logger.error("Failed to update workflow: %s", err)
            show_error(self.parent_widget, "Update Error", f"Failed to update workflow:\n{err}")

        self.save_to_project(pm, filename, self.document.metadata or {}, _on_success, _on_error)

    def handle_autosave(self, on_done: Callable[[bool], None]) -> None:
        """Quiet variant of `handle_update()` for the SDK's `WorkflowAutosaveController`.

        No blocking dialogs: a periodic background save shouldn't interrupt the
        user. `on_done(True/False)` reports the outcome so the controller can
        show its own toast instead.
        """
        current = self._current_filename_and_pm()
        if current is None:
            on_done(False)
            return
        filename, pm = current

        def _on_success(_new_filename: str) -> None:
            self._publish_saved(filename=filename)
            on_done(True)

        def _on_error(err: str) -> None:
            logger.warning(f"Autosave failed: {err}")
            on_done(False)

        self.save_to_project(pm, filename, self.document.metadata or {}, _on_success, _on_error)
