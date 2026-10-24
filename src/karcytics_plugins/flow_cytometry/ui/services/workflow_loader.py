"""Loads a saved workflow (or, for smoke tests, a raw .fcs file) into the workspace.

The Hub, the Academy and the startup hand-over all reach this through the
panel's `load_workflow`. The samples reload in the background; the history
restarts from the loaded state once they are in.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from karcytics_sdk.plugin import get_logger
from karcytics_sdk.plugin.dialogs import show_error, show_warning
from karcytics_sdk.plugin.workflow import WorkflowContext

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

    from ...analysis.state import FlowState
    from ..composition_root import FlowServices

logger = get_logger(__name__, "flow_cytometry")


class WorkflowLoader:
    """Replaces the workspace with a saved workflow."""

    def __init__(
        self,
        state: FlowState,
        services: FlowServices,
        dialog_parent: QWidget,
        status: Callable[[str], None],
        refresh: Callable[[], None],
        on_loaded: Callable[[], None],
        data_loaded: Callable[[], None],
    ) -> None:
        self._state = state
        self._services = services
        self._document = services.document
        self._dialog_parent = dialog_parent
        self._status = status  # a line for the status bar
        self._refresh = refresh  # re-read the model into every view
        self._on_loaded = on_loaded  # a workflow finished loading (the Academy's hook)
        self._data_loaded = data_loaded  # the startup loader may cross-fade

    def load(self, payload: dict, filename: str | None, metadata: dict | None) -> None:
        if not self._document.confirm_discard_before_load():
            self._status("Workflow load cancelled — your workspace is unchanged.")
            return
        # Nothing records while the workspace is replaced; undo/redo refuse meanwhile.
        self._document.begin_load()
        if filename and filename.lower().endswith(".fcs"):
            self._load_raw_fcs(filename)
            return
        if filename:
            self._document.filename = filename
        if metadata:
            self._document.metadata = metadata

        pm = self._document.project_manager()
        if not self._services.workflow_service.load_workflow(
            payload,
            context=self._attachments(pm, filename),
            project_dir=pm.project_dir if pm else None,
            on_complete=self._on_samples_reloaded,
        ):
            # Whatever was partly replaced is unsaved, not a clean workflow.
            self._document.finish_load(clean=False)
            error = self._services.workflow_service.last_error
            show_error(self._dialog_parent, "Load Error", f"Failed to restore workflow. {error}")
            self._data_loaded()

    @staticmethod
    def _attachments(pm: Any, filename: str | None) -> WorkflowContext | None:
        """The project files saved with the workflow (e.g. UMAP runs)."""
        if pm is None or not filename:
            return None
        try:
            # Skip corrupt legacy attachments.
            atts = [a for a in pm.workflows.load_attachments(filename) if "relative_path" in a]
            return WorkflowContext.from_attachment_dicts(atts, pm.project_dir)
        except (OSError, KeyError, ValueError) as e:
            logger.warning(f"Failed to load attachments: {e}")
            return None

    def _on_samples_reloaded(self, reload_result: dict[str, list[str]] | None = None) -> None:
        for sid, sample in self._state.data.experiment.samples.items():
            if sample.fcs_data is not None and sample.gate_tree.children:
                self._services.gate_coordinator.recompute_all_stats(sid)
        self._document.finish_load(clean=True)  # the loaded workspace is the saved baseline
        self._on_loaded()
        self._refresh()

        failed = (reload_result or {}).get("failed") or []
        if failed:
            logger.error(f"FCS reload failed for {len(failed)} sample(s): {failed}")
            show_warning(
                self._dialog_parent,
                "Some Samples Failed to Load",
                f"{len(failed)} sample(s) could not be reloaded and will show 0 events:\n\n"
                + "\n".join(f"  • {name}" for name in failed)
                + "\n\nCheck the logs for details (e.g. a moved or corrupt FCS file).",
            )
            self._status(f"Workflow loaded with {len(failed)} sample(s) failed to reload.")
        else:
            self._status("Workflow loaded successfully.")
        self._data_loaded()

    def _load_raw_fcs(self, path: str) -> None:
        """CI smoke tests hand over a bare .fcs file instead of a workflow."""
        logger.info(f"Direct raw FCS injection detected: {path}")

        def _on_done(results: dict) -> None:
            logger.info(f"Raw FCS injection complete. Processed {len(results)} samples.")
            self._document.finish_load(clean=False)  # never saved as a workflow
            self._refresh()
            self._data_loaded()

        def _on_error(err: str) -> None:
            logger.error(f"FCS injection failed: {err}")
            self._document.finish_load(clean=False)
            self._data_loaded()

        self._services.data_loader_service.load_samples_async(
            [path], self._state, on_done=_on_done, on_error_cb=_on_error
        )
