"""Workspace IO Handler.

Manages saving, loading, and updating of flow cytometry workflows,
separating persistence orchestration from the UI layout.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from karcytics_sdk.plugin import get_logger
from PyQt6.QtWidgets import QFileDialog

from .workspace_save_service import WorkspaceSaveService
from .zip_export_service import ZipExportService

logger = get_logger(__name__, "flow_cytometry")


class WorkspaceIOHandler:
    """Handles all logic for reading/writing workflows and communicating with the ProjectManager."""

    def __init__(self, workflow_service, parent_widget: Any):
        self.workflow_service = workflow_service
        self.parent_widget = parent_widget

    def _get_project_manager(self):
        try:
            return getattr(self.parent_widget.window(), "project_manager", None)
        except AttributeError:
            return None

    def _run_save_to_pm(
        self,
        pm: Any,
        filename: str,
        metadata: dict[str, Any],
        on_success: Callable[[str], None],
        on_error: Callable[[str], None],
    ) -> None:
        """Shared async plumbing for saving/updating a workflow already known
        to the ProjectManager. `handle_update()` and `handle_autosave()` both
        overwrite an existing workflow the same way — this keeps the
        task-scheduler dispatch written once instead of twice.
        """
        module_id = getattr(self.parent_widget.window(), "current_module_id", "flow_cytometry")

        from karcytics_sdk.plugin.managed_task import FunctionalTask
        from karcytics_sdk.plugin.runtime_services import task_scheduler

        self.parent_widget._loading = True

        def _task():
            return WorkspaceSaveService.save_to_pm(
                pm, self.workflow_service, filename, metadata, module_id
            )

        def _on_finished(results: dict):
            self.parent_widget._loading = False
            on_success(str(results.get("result", "")))

        def _on_task_error(err: str):
            self.parent_widget._loading = False
            on_error(err)

        task = FunctionalTask(_task, name="Save Workflow to PM")
        worker = task_scheduler.submit(task, None)
        worker.finished.connect(_on_finished)
        worker.error.connect(_on_task_error)

    @staticmethod
    def _publish_saved(filename: str) -> None:
        try:
            from karcytics_sdk.plugin import CentralEventBus

            CentralEventBus.publish("flow.workflow.saved", {"filename": filename})
        except Exception as e:
            logger.debug(f"Failed to publish workflow saved event: {e}")

    def handle_save(self) -> None:  # noqa: PLR0915
        """Handle save workspace request."""
        pm = self._get_project_manager()

        if pm:
            try:
                filename = getattr(self.parent_widget, "_current_workflow_filename", None)
                metadata = getattr(self.parent_widget, "_current_workflow_metadata", None)

                if not filename or not metadata:
                    from karcytics_sdk.plugin.dialogs import SaveWorkflowDialog

                    dialog = SaveWorkflowDialog(self.parent_widget)
                    if not dialog.exec():
                        return
                    metadata = dialog.get_metadata()

                module_id = getattr(
                    self.parent_widget.window(), "current_module_id", "flow_cytometry"
                )

                from karcytics_sdk.plugin.managed_task import FunctionalTask
                from karcytics_sdk.plugin.runtime_services import task_scheduler

                self.parent_widget._loading = True

                def _save_task():
                    return WorkspaceSaveService.save_to_pm(
                        pm, self.workflow_service, filename, metadata, module_id
                    )

                def _on_save_finished(results: dict):
                    self.parent_widget._loading = False
                    new_filename = results.get("result")
                    self.parent_widget._current_workflow_filename = new_filename
                    self.parent_widget._current_workflow_metadata = metadata
                    self.parent_widget.set_dirty(False)
                    from karcytics_sdk.plugin.dialogs import show_info

                    show_info(
                        self.parent_widget,
                        "Workflow Saved",
                        f"Workflow saved successfully to project:\n{new_filename}",
                    )

                    try:
                        from karcytics_sdk.plugin import CentralEventBus

                        CentralEventBus.publish("flow.workflow.saved", {"filename": new_filename})
                    except Exception as e:
                        logger.debug(f"Failed to publish workflow saved event: {e}")

                def _on_save_error(err: str):
                    self.parent_widget._loading = False
                    logger.exception(f"Failed to save workflow to project: {err}")
                    from karcytics_sdk.plugin.dialogs import show_error

                    show_error(
                        self.parent_widget,
                        "Save Error",
                        f"Failed to save workflow:\n{err}",
                    )

                task = FunctionalTask(_save_task, name="Save Workflow to PM")
                worker = task_scheduler.submit(task, None)
                worker.finished.connect(_on_save_finished)
                worker.error.connect(_on_save_error)
                return
            except (ImportError, RuntimeError, KeyError, ValueError) as e:
                logger.exception(f"Failed to prepare workflow save: {e}")
                from karcytics_sdk.plugin.dialogs import show_error

                show_error(self.parent_widget, "Save Error", f"Failed to save workflow:\n{e}")
                return

        # Standalone fallback
        from karcytics_sdk.plugin.dialogs import get_save_path

        path = getattr(self.parent_widget, "_current_workflow_path", None)
        if not path:
            path = get_save_path(
                self.parent_widget,
                "Save Flow Cytometry Workflow",
                file_filter="Karcytics Flow Cytometry Archive (*.zip);;JSON Files (*.json)",
            )
            if not path:
                return
            self.parent_widget._current_workflow_path = path

        logger.info(f"Saving workflow to {path}")

        from karcytics_sdk.plugin.managed_task import FunctionalTask
        from karcytics_sdk.plugin.runtime_services import task_scheduler

        self.parent_widget._loading = True

        def _standalone_save_task():
            ZipExportService.save_standalone(self.workflow_service, path)
            return path

        def _on_standalone_save_finished(results: dict):
            self.parent_widget._loading = False
            self.parent_widget.set_dirty(False)
            from karcytics_sdk.plugin.dialogs import show_info

            show_info(
                self.parent_widget,
                "Workflow Saved",
                f"Workflow saved successfully to\n{path}",
            )

            try:
                from karcytics_sdk.plugin import CentralEventBus

                CentralEventBus.publish("flow.workflow.saved", {"path": path})
            except Exception as e:
                logger.debug(f"Failed to publish workflow saved event: {e}")

        def _on_standalone_save_error(err: str):
            self.parent_widget._loading = False
            logger.exception(f"Failed to save workflow: {err}")
            from karcytics_sdk.plugin.dialogs import show_error

            show_error(self.parent_widget, "Save Error", f"Failed to save workflow:\n{err}")

        task = FunctionalTask(_standalone_save_task, name="Save Standalone Workflow")
        worker = task_scheduler.submit(task, None)
        worker.finished.connect(_on_standalone_save_finished)
        worker.error.connect(_on_standalone_save_error)

    def _current_filename_and_pm(self) -> tuple[str, Any] | None:
        """Returns `(filename, pm)` for the workflow currently loaded/saved
        into the ProjectManager, or `None` if there isn't one — shared guard
        for `handle_update()` and `handle_autosave()`, which both only ever
        overwrite an already-named workflow.
        """
        filename = getattr(self.parent_widget, "_current_workflow_filename", None)
        if not filename:
            return None
        pm = self._get_project_manager()
        if pm is None:
            return None
        return filename, pm

    def handle_update(self) -> None:
        """Overwrite the currently loaded workflow using Karcytics SDK services."""
        current = self._current_filename_and_pm()
        if current is None:
            if self._get_project_manager() is None:
                from karcytics_sdk.plugin.dialogs import show_error

                show_error(
                    self.parent_widget,
                    "Error",
                    "Project Manager not found. Cannot update workflow.",
                )
            else:
                from karcytics_sdk.plugin.dialogs import show_info

                show_info(
                    self.parent_widget,
                    "No Workflow Loaded",
                    "There is no currently loaded workflow to update. Please use 'Save New Workflow' instead.",
                )
            return
        filename, pm = current

        metadata = getattr(self.parent_widget, "_current_workflow_metadata", {})

        def _on_success(_new_filename: str) -> None:
            self.parent_widget.set_dirty(False)
            from karcytics_sdk.plugin.dialogs import show_info

            show_info(
                self.parent_widget,
                "Workflow Updated",
                f"Workflow updated successfully:\n{filename}",
            )
            self._publish_saved(filename)

        def _on_error(err: str) -> None:
            logger.error("Failed to update workflow: %s", err)
            from karcytics_sdk.plugin.dialogs import show_error

            show_error(self.parent_widget, "Update Error", f"Failed to update workflow:\n{err}")

        self._run_save_to_pm(pm, filename, metadata, _on_success, _on_error)

    def handle_autosave(self, on_done: Callable[[bool], None]) -> None:
        """Quiet variant of `handle_update()` for the SDK's
        `WorkflowAutosaveController` (see `PluginBase.setup_workflow_autosave`,
        wired in `FlowCytometryPanel._setup_services`).

        No blocking dialogs — a periodic background save shouldn't interrupt
        the user. `on_done(True/False)` reports the outcome so the
        controller can show its own toast instead.
        """
        current = self._current_filename_and_pm()
        if current is None:
            on_done(False)
            return
        filename, pm = current

        metadata = getattr(self.parent_widget, "_current_workflow_metadata", {})

        def _on_success(_new_filename: str) -> None:
            self.parent_widget.set_dirty(False)
            self._publish_saved(filename)
            on_done(True)

        def _on_error(err: str) -> None:
            logger.warning(f"Autosave failed: {err}")
            on_done(False)

        self._run_save_to_pm(pm, filename, metadata, _on_success, _on_error)

    def handle_load(self) -> None:  # noqa: PLR0915
        """Handle load workspace request."""
        pm = self._get_project_manager()

        if pm:
            wf_dir = str(pm.project_dir / "workflows")
            path, _ = QFileDialog.getOpenFileName(
                self.parent_widget,
                "Load Flow Cytometry Workflow",
                wf_dir,
                "JSON Files (*.json)",
            )
            if not path:
                return

            filename = Path(path).name

            from karcytics_sdk.plugin.managed_task import FunctionalTask
            from karcytics_sdk.plugin.runtime_services import task_scheduler

            self.parent_widget._loading = True

            def _load_task():
                success, metadata = WorkspaceSaveService.load_from_pm(
                    pm, self.workflow_service, filename
                )
                if not success:
                    raise RuntimeError("Failed to load workflow payload.")
                return {"metadata": metadata}

            def _on_load_finished(results: dict):
                self.parent_widget._loading = False
                metadata = results.get("metadata", {})
                self.parent_widget._current_workflow_metadata = metadata
                self.parent_widget._current_workflow_filename = filename

                # _on_tab_changed already refreshes the Population Analysis
                # viewer from state.data.umap_results (keyed per sample/node)
                # when tab 6 is active — no separate _on_analysis_done call
                # is needed (and that method expects a single flat run dict,
                # not the full keyed umap_results mapping).
                self.parent_widget._on_tab_changed(self.parent_widget._tab_bar.currentIndex())

                self.parent_widget.set_dirty(False)
                from karcytics_sdk.plugin.dialogs import show_info

                show_info(
                    self.parent_widget,
                    "Workflow Loaded",
                    "Workflow loaded successfully from project.",
                )

            def _on_load_error(err: str):
                self.parent_widget._loading = False
                logger.error(f"Failed to load from PM: {err}")
                from karcytics_sdk.plugin.dialogs import show_error

                show_error(self.parent_widget, "Load Error", f"Failed to load workflow: {err}")

            task = FunctionalTask(_load_task, name="Load Workflow PM")
            worker = task_scheduler.submit(task, None)
            worker.finished.connect(_on_load_finished)
            worker.error.connect(_on_load_error)
            return

        # Standalone fallback
        path, _ = QFileDialog.getOpenFileName(
            self.parent_widget,
            "Load Flow Cytometry Workflow",
            "",
            "Karcytics Flow Cytometry Archive (*.zip);;JSON Files (*.json)",
        )
        if not path:
            return

        self.parent_widget._current_workflow_path = path
        logger.info(f"Loading workflow from {path}")

        from karcytics_sdk.plugin.managed_task import FunctionalTask
        from karcytics_sdk.plugin.runtime_services import task_scheduler

        self.parent_widget._loading = True

        def _standalone_load_task():
            success = ZipExportService.load_standalone(self.workflow_service, path)
            if not success:
                raise RuntimeError("Failed to load standalone workflow.")
            return True

        def _on_standalone_load_finished(results: dict):
            self.parent_widget._loading = False
            # _on_tab_changed already refreshes the Population Analysis viewer
            # from state.data.umap_results when tab 6 is active — see the
            # matching comment in handle_load's _on_load_finished above.
            self.parent_widget._on_tab_changed(self.parent_widget._tab_bar.currentIndex())

            self.parent_widget.set_dirty(False)
            from karcytics_sdk.plugin.dialogs import show_info

            show_info(self.parent_widget, "Workflow Loaded", "Workflow loaded successfully.")

        def _on_standalone_load_error(err: str):
            self.parent_widget._loading = False
            logger.exception(f"Failed to load workflow: {err}")
            from karcytics_sdk.plugin.dialogs import show_error

            show_error(self.parent_widget, "Load Error", f"Failed to load workflow:\n{err}")

        task = FunctionalTask(_standalone_load_task, name="Load Standalone Workflow")
        worker = task_scheduler.submit(task, None)
        worker.finished.connect(_on_standalone_load_finished)
        worker.error.connect(_on_standalone_load_error)
