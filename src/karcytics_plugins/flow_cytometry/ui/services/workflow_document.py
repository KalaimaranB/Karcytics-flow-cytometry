"""The open workflow: its name and save metadata, and whether a save or load is running.

One per panel, built by `build_services()`. WorkspaceIOHandler saves through it, the
Academy reads and stamps its metadata, and the panel asks it before closing or
loading over unsaved work.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

    from ...analysis.history_recorder import HistoryRecorder
    from ...analysis.store import FlowStore
    from .gate_propagator import GatePropagator


class WorkflowDocument:
    """What is open, and the unsaved-changes rules around saving, loading and closing."""

    def __init__(self, store: FlowStore, propagator: GatePropagator, parent: QWidget) -> None:
        self._store = store
        self._propagator = propagator
        self._parent = parent  # parents the prompts; its window closes after a save
        self.filename: str | None = None  # the workflow's name in the project
        self.metadata: dict[str, Any] | None = None  # its save metadata (and Academy block)
        self.path: str | None = None  # a standalone .zip/.json, when there is no project
        self.saving = False
        self.loading = False  # a workflow is replacing the workspace
        self.close_after_save = False  # "Save" in the close prompt: close once it lands
        self.recorder: HistoryRecorder | None = None  # MainPanelController.wire builds it

    @property
    def is_dirty(self) -> bool:
        return self._store.is_dirty

    def project_manager(self) -> Any:
        """The Hub's ProjectManager, when the window has a project open."""
        try:
            return getattr(self._parent.window(), "project_manager", None)
        except (AttributeError, RuntimeError):
            return None

    def undo_blocked_reason(self) -> str | None:
        if self.loading:
            return "a workflow is loading"
        if self.saving:
            return "the workspace is being saved"
        return None

    def flush_history(self) -> None:
        """Lands a step still waiting for the end of this event-loop turn."""
        if self.recorder is not None:
            self.recorder.flush()

    # ── Saving ──────────────────────────────────────────────────────────

    def begin_save(self) -> Any:
        """Call right before a save starts; hand the token to `finish_save`."""
        self.flush_history()
        self.saving = True
        return self._store.begin_save()

    def finish_save(self, token: Any) -> None:
        """The save that began with `token` succeeded."""
        self.saving = False
        self._store.finish_save(token)
        if self.close_after_save:
            self.close_after_save = False
            self.close_window_when_idle()

    def save_failed(self) -> None:
        self.saving = False

    def close_window_when_idle(self) -> None:
        """Close the hosting window once no modal dialog (e.g. "Saved") is up."""
        if QApplication.activeModalWidget() is not None:
            QTimer.singleShot(200, self.close_window_when_idle)
            return
        window = self._parent.window()
        if window is not None:
            window.close()

    # ── Loading ─────────────────────────────────────────────────────────

    def begin_load(self) -> None:
        """Nothing records while the workspace is replaced (undo/redo refuse meanwhile)."""
        # Flush first: a step pending from before the load belongs to the old
        # history (which the load discards), not misattributed to the new one.
        self.flush_history()
        if not self.loading:
            self.loading = True
            self._store.pause()
        self._propagator.cancel_pending()

    def finish_load(self, clean: bool) -> None:
        """The load is done: the history restarts from here, saved (`clean`) or not."""
        # Only the load in progress may restart the history, never a stray late
        # callback, which would wipe edits made since.
        if not self.loading:
            return
        self.loading = False
        self._store.resume()
        self._store.reset(clean=clean)

    # ── Unsaved-changes prompts ─────────────────────────────────────────

    def ask_unsaved_changes(
        self, text: str, buttons: QMessageBox.StandardButton
    ) -> QMessageBox.StandardButton:
        # karcytics: allow KS220 - Save/Discard/Cancel: the SDK dialogs have no three-way prompt
        box = QMessageBox(self._parent)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Unsaved Changes")
        box.setText(text)
        box.setStandardButtons(buttons)
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        return QMessageBox.StandardButton(box.exec())

    def confirm_discard_before_load(self) -> bool:
        """A workflow is about to replace a workspace with unsaved changes."""
        if not self.is_dirty:
            return True
        Btn = QMessageBox.StandardButton
        choice = self.ask_unsaved_changes(
            "Loading a workflow will discard your unsaved changes to this workspace.\n\n"
            "Choose Cancel to keep working and save first.",
            Btn.Discard | Btn.Cancel,
        )
        return choice == Btn.Discard

    def confirm_close(
        self, academy_decision: Callable[[], bool | None], save: Callable[[], None]
    ) -> bool:
        """Whether the window may close now.

        Unsaved changes offer Save / Discard / Cancel. Save starts the usual
        (background) `save` and closes the window once it succeeds; if that
        save is cancelled or fails, the next close asks again. The Academy
        decides first for a workflow it has locked (None: no opinion).
        """
        if self.close_after_save:
            if self.saving:
                return False  # the save-then-close is still writing
            self.close_after_save = False  # it was cancelled or failed
        decision = academy_decision()
        if decision is not None:
            return decision
        if not self.is_dirty:
            return True
        Btn = QMessageBox.StandardButton
        choice = self.ask_unsaved_changes(
            "Save changes to this workspace before closing?", Btn.Save | Btn.Discard | Btn.Cancel
        )
        if choice == Btn.Discard:
            return True
        if choice == Btn.Save:
            self.close_after_save = True
            save()
            if not self.saving:
                self.close_after_save = False  # no save started (its dialog was cancelled)
        return False
