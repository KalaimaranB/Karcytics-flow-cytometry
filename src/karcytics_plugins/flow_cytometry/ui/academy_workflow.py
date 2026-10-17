"""Academy workflows: courses that run inside a saved workflow and can pause.

A flow course always runs in a saved workflow, and that workflow carries the
learner through all five courses (each builds on the one before). Its
metadata holds an ``academy`` block — the course, its place in it, and the
courses already finished — which is what lets a learner pause, close the
module, and resume later, and what the Hub's dashboard reads to badge the
workflow card.

While no course is on screen, an Academy workflow is locked behind an
`AcademyLockCard`: paused mid-course ("Ready to continue?") or between two
courses ("Ready for Course 3?"). The workspace must stay exactly as the last
step left it, because the next step's checks expect it. Leaving the course
(or the Academy) drops the block, and the workflow becomes ordinary — with
all its work kept. After the final course it stays an Academy workflow but
unlocks.

The block is updated in memory on every step, so any save — the course's own
"Save Workspace" steps, autosave, a pause — records a place that matches the
workspace saved with it.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from karcytics_sdk.plugin.academy import (
    ACADEMY_COURSE_COMPLETED,
    ACADEMY_STEP_CHANGED,
    AcademyManager,
)
from karcytics_sdk.plugin.academy_lock_card import AcademyLockCard, LockCardContent
from karcytics_sdk.plugin.dialogs import ask_yes_no, show_info, show_warning
from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QInputDialog

logger = logging.getLogger(__name__)

ACADEMY_KEY = "academy"
RUNNING = "running"
PAUSED = "paused"
BETWEEN_COURSES = "between_courses"
GRADUATED = "graduated"

DEFAULT_WORKFLOW_NAME = "Flow Academy"

# What the lock card is asking; decides what its two buttons do.
_MODE_CONVERT = "convert"
_MODE_PAUSED = "paused"
_MODE_BETWEEN = "between"

# The snapshot keys copied into the block (see AcademyManager.session_snapshot).
_SNAPSHOT_KEYS = (
    "course_id",
    "course_title",
    "step_id",
    "step_history",
    "subtask_progress",
    "step_number",
    "step_total",
    "updated_at",
)


def course_order() -> list[str]:
    """The flow courses' ids, in the order a learner takes them."""
    from ..tutorials.courses import (
        course_1_fundamentals,
        course_2_compensation,
        course_3_gating,
        course_4_analysis,
        course_5_reporting,
    )

    return [
        c.id
        for c in (
            course_1_fundamentals,
            course_2_compensation,
            course_3_gating,
            course_4_analysis,
            course_5_reporting,
        )
    ]


def academy_block(metadata: dict[str, Any] | None) -> dict[str, Any] | None:
    """The ``academy`` block of a workflow's metadata, if it is an Academy workflow."""
    block = (metadata or {}).get(ACADEMY_KEY)
    return block if isinstance(block, dict) else None


class AcademyWorkflowController(QObject):
    """Runs flow courses inside Academy workflows for one panel.

    `manager` / `event_bus` default to the plugin process's own Academy
    (`runtime_services`); tests pass their own.
    """

    def __init__(
        self,
        panel: Any,
        manager: AcademyManager | None = None,
        event_bus: Any = None,
    ) -> None:
        super().__init__(panel)
        if manager is None or event_bus is None:
            from karcytics_sdk.plugin.runtime_services import academy_event_bus, tutorial_manager

            manager = manager or tutorial_manager
            event_bus = event_bus or academy_event_bus
        self._panel = panel
        self._manager = manager
        self._bus = event_bus
        self._card: AcademyLockCard | None = None
        self._mode: str | None = None
        self._pending_course_id: str | None = None
        self._bus.subscribe(ACADEMY_STEP_CHANGED, self._on_step_changed)
        self._bus.subscribe(ACADEMY_COURSE_COMPLETED, self._on_course_completed)

    def dispose(self) -> None:
        """Unsubscribes from the Academy bus (the panel is going away)."""
        self._bus.unsubscribe(ACADEMY_STEP_CHANGED, self._on_step_changed)
        self._bus.unsubscribe(ACADEMY_COURSE_COMPLETED, self._on_course_completed)

    # ── State ──────────────────────────────────────────────────────────

    @property
    def block(self) -> dict[str, Any] | None:
        return academy_block(getattr(self._panel, "_current_workflow_metadata", None))

    @property
    def is_locked(self) -> bool:
        return self._card is not None and self._card.is_locked

    def _course_running_here(self) -> bool:
        block = self.block
        active = self._manager.active_course
        return bool(
            block
            and block.get("state") == RUNNING
            and active
            and active.id == block.get("course_id")
        )

    def _project_manager(self) -> Any:
        return self._panel._get_project_manager()

    # ── Entry points ───────────────────────────────────────────────────

    def start_course(self, course_id: str) -> None:
        """Starts `course_id` from the catalog, in this workflow.

        An ordinary workflow first becomes an Academy workflow — Cyto says
        so on the lock card and the learner agrees. Without a project
        (nowhere to save), the course runs as before, just not pausable.
        """
        if self._manager.active_course is not None:
            show_info(
                self._panel, "Karcytics Academy", "Finish or pause the course on screen first."
            )
            return
        if course_id not in course_order() or self._project_manager() is None:
            self._manager.start_course_confirmed(course_id)
            self._show_overlay(pausable=False)
            return
        if self.block is not None:
            self._begin(course_id)
            return

        self._pending_course_id = course_id
        course = self._manager.find_course(course_id)
        number = course_order().index(course_id) + 1
        self._show_card(
            _MODE_CONVERT,
            LockCardContent(
                eyebrow="KARCYTICS ACADEMY",
                title=f"Start Course {number}: {course.title if course else ''}?",
                message=(
                    "Cyto will turn this workflow into an <b>Academy workflow</b>. Your place in the "
                    "course is saved as you go, so you can pause and come back any time. While a "
                    "course is paused the workspace stays locked, exactly as the next step expects "
                    "it. The same workflow carries you through every course; leave the Academy "
                    "whenever you like and it becomes an ordinary workflow again."
                ),
                primary_text="▶ Start course",
                secondary_text="Not now",
            ),
        )

    def resume_from_catalog(self, course_id: str, attempt: dict[str, Any]) -> None:
        """The catalog's "Resume Course": open the attempt's workflow, or resume it here."""
        pm = self._project_manager()
        where = attempt.get("workflow_name") or attempt.get("workflow") or "an Academy workflow"
        if pm is None or str(attempt.get("project_dir")) != str(pm.project_dir):
            show_info(
                self._panel,
                "Resume Course",
                f"This attempt is saved in “{where}” in another project:\n"
                f"{attempt.get('project_dir', 'unknown')}\n\n"
                "Open that project and workflow from the Hub to resume.",
            )
            return

        filename = attempt.get("workflow")
        if filename and filename == getattr(self._panel, "_current_workflow_filename", None):
            block = self.block
            if block and block.get("state") == PAUSED and block.get("course_id") == course_id:
                self.resume()
            elif not self._course_running_here():
                self._forget_attempt(course_id)
                show_info(
                    self._panel, "Resume Course", "This workflow is no longer in that course."
                )
            return

        path = Path(pm.project_dir) / "workflows" / str(filename)
        if not filename or not path.exists():
            self._manager.forget_in_progress(course_id, workflow=filename)
            show_info(self._panel, "Resume Course", f"The workflow “{where}” no longer exists.")
            return
        from karcytics_sdk.plugin.io import load_json

        data = load_json(str(path))
        # Opens locked on the paused card — one click resumes.
        self._panel.load_workflow(
            data.get("payload", {}), filename=filename, metadata=data.get("metadata", {})
        )

    def pause(self) -> None:
        """⏸ Pause: save the place, lock the workflow."""
        if not self._course_running_here():
            return
        self._pause_into_block()
        self._hide_overlay()
        self._show_paused_card()
        self._save()

    def resume(self) -> None:
        """Lock card's ▶ Resume: back to the saved step."""
        block = self.block
        if not block:
            return
        tab = (block.get("ui") or {}).get("tab")
        tab_bar = getattr(self._panel, "_tab_bar", None)
        if isinstance(tab, int) and tab_bar is not None and 0 <= tab < tab_bar.count():
            tab_bar.setCurrentIndex(tab)
        if self._card is not None:
            self._card.unlock()
        if not self._manager.restore_session(block):
            show_warning(self._panel, "Karcytics Academy", "This course could not be resumed.")
            self._show_paused_card()
            return
        self._show_overlay(pausable=True)

    def on_workflow_loaded(self) -> None:
        """A workflow finished loading: lock it if it's an Academy workflow mid-course."""
        block = self.block or {}
        state = block.get("state")
        if state in (RUNNING, PAUSED):
            if self._manager.active_course is not None:
                self._manager.pause()  # a course from the workflow this one replaced
                self._hide_overlay()
            # RUNNING here means the module closed without pausing (a crash,
            # or the Hub closing it): resume from the last saved place.
            block["state"] = PAUSED
            self._show_paused_card()
        elif state == BETWEEN_COURSES:
            self._show_between_card()
        elif self._card is not None:
            self._card.unlock()

    def confirm_close(self) -> bool | None:
        """Closing the window mid-course pauses and saves, then closes.

        None when this isn't an Academy matter (the panel's usual prompt
        applies); otherwise whether the window may close right now.
        """
        state = (self.block or {}).get("state")
        if state not in (RUNNING, PAUSED, BETWEEN_COURSES) or self._project_manager() is None:
            return None  # an ordinary (or graduated, unlocked) workflow
        if self._course_running_here():
            self._pause_into_block()
        elif not self._panel._store.is_dirty:
            return True
        self._panel._close_after_save = True
        self._save()
        return False

    # ── Lock card ──────────────────────────────────────────────────────

    def _show_card(self, mode: str, content: LockCardContent) -> None:
        if self._card is None:
            self._card = AcademyLockCard(self._panel, show_character=self._manager.show_character)
            self._card.primary_clicked.connect(self._on_card_primary)
            self._card.secondary_clicked.connect(self._on_card_secondary)
        self._mode = mode
        self._card.set_show_character(self._manager.show_character)
        self._card.show_lock(content)

    def _show_paused_card(self) -> None:
        block = self.block or {}
        number = self._course_number(block.get("course_id"))
        self._show_card(
            _MODE_PAUSED,
            LockCardContent(
                eyebrow="KARCYTICS ACADEMY · PAUSED",
                title=f"Ready to continue Course {number}?",
                message=(
                    f"<b>{block.get('course_title', '')}</b><br>Cyto saved your place. The workspace "
                    "stays locked until you resume, so it's exactly as the next step expects."
                ),
                primary_text="▶ Resume course",
                secondary_text="Leave course…",
                step_number=int(block.get("step_number") or 0),
                step_total=int(block.get("step_total") or 0),
            ),
        )

    def _show_between_card(self) -> None:
        block = self.block or {}
        next_id = block.get("next_course_id")
        course = self._manager.find_course(next_id) if next_id else None
        if course is None:
            if self._card is not None:
                self._card.unlock()
            return
        done = self._course_number(block.get("last_completed_course_id"))
        number = self._course_number(next_id)
        self._show_card(
            _MODE_BETWEEN,
            LockCardContent(
                eyebrow=f"KARCYTICS ACADEMY · COURSE {done} COMPLETE",
                title=f"Ready for Course {number}?",
                message=(
                    f"Next up: <b>{course.title}</b>. It continues from this workflow, so Cyto "
                    "keeps it locked until you start.<br><br>Rather explore on your own? Leave "
                    "the Academy and this becomes an ordinary workflow — your work stays."
                ),
                primary_text=f"▶ Start Course {number}",
                secondary_text="Leave Academy",
            ),
        )

    def _on_card_primary(self) -> None:
        if self._mode == _MODE_CONVERT and self._pending_course_id:
            self._convert_and_begin(self._pending_course_id)
        elif self._mode == _MODE_PAUSED:
            self.resume()
        elif self._mode == _MODE_BETWEEN:
            next_id = (self.block or {}).get("next_course_id")
            if next_id and self._card is not None:
                self._card.unlock()
            if next_id:
                self._begin(next_id)

    def _on_card_secondary(self) -> None:
        if self._mode == _MODE_CONVERT:
            self._pending_course_id = None
            if self._card is not None:
                self._card.unlock()
            return
        what = "course" if self._mode == _MODE_PAUSED else "Academy"
        if not ask_yes_no(
            self._panel,
            f"Leave the {what}?",
            "This workflow becomes an ordinary workflow and keeps all your work. You can start "
            "Academy courses again any time from the 🎓 Academy button.",
        ):
            return
        self._leave()

    # ── Lifecycle ──────────────────────────────────────────────────────

    def _convert_and_begin(self, course_id: str) -> None:
        metadata = dict(getattr(self._panel, "_current_workflow_metadata", None) or {})
        if not getattr(self._panel, "_current_workflow_filename", None) or not metadata.get("name"):
            name, ok = QInputDialog.getText(
                self._panel,
                "Name your Academy workflow",
                "Workflow name:",
                text=DEFAULT_WORKFLOW_NAME,
            )
            if not ok:
                return  # the card stays up; they can try again or choose "Not now"
            metadata.update(
                {
                    "name": name.strip() or DEFAULT_WORKFLOW_NAME,
                    "description": "Karcytics Academy workflow",
                    "tags": sorted({*metadata.get("tags", []), "academy"}),
                    "timestamp": datetime.now().isoformat(),
                }
            )
        metadata[ACADEMY_KEY] = {"state": RUNNING, "completed_courses": []}
        self._panel._current_workflow_metadata = metadata
        self._pending_course_id = None
        if self._card is not None:
            self._card.unlock()
        self._begin(course_id)

    def _begin(self, course_id: str) -> None:
        block = self.block
        if block is None:
            return
        block.pop("next_course_id", None)
        block["state"] = RUNNING
        if not self._manager.start_course_confirmed(course_id):
            return
        self._show_overlay(pausable=True)
        self._save()

    def _pause_into_block(self) -> None:
        snapshot = self._manager.pause()
        block = self.block
        if snapshot is None or block is None:
            return
        block.update({key: snapshot[key] for key in _SNAPSHOT_KEYS if key in snapshot})
        block["state"] = PAUSED
        block["ui"] = self._ui_state()
        self._record_attempt(block)

    def _leave(self) -> None:
        block = self.block or {}
        if block.get("course_id") and block.get("state") in (RUNNING, PAUSED):
            self._forget_attempt(block["course_id"])
        if self._manager.active_course is not None:
            self._manager.pause()
            self._hide_overlay()
        metadata = getattr(self._panel, "_current_workflow_metadata", None) or {}
        metadata.pop(ACADEMY_KEY, None)
        if self._card is not None:
            self._card.unlock()
        self._mode = None
        self._save()
        status = getattr(self._panel, "status_message", None)
        if status is not None:
            status.emit("Left the Academy — this is now an ordinary workflow.")

    def _on_step_changed(self, step: Any) -> None:
        """Keeps the block's place current, so any save records it."""
        block = self.block
        course = self._manager.active_course
        if step is None or block is None or course is None or course.id not in course_order():
            return
        snapshot = self._manager.session_snapshot()
        if snapshot is None:
            return
        block.update({key: snapshot[key] for key in _SNAPSHOT_KEYS})
        block["state"] = RUNNING
        block["ui"] = self._ui_state()
        self._record_attempt(block)

    def _on_course_completed(self, course_id: str, _badge_reward: Any) -> None:
        block = self.block
        order = course_order()
        if block is None or course_id not in order or block.get("course_id") != course_id:
            return
        completed = block.setdefault("completed_courses", [])
        if course_id not in completed:
            completed.append(course_id)
        for key in (
            "step_id",
            "step_history",
            "subtask_progress",
            "step_number",
            "step_total",
            "ui",
        ):
            block.pop(key, None)
        block["last_completed_course_id"] = course_id
        index = order.index(course_id)
        if index + 1 < len(order):
            block["state"] = BETWEEN_COURSES
            block["next_course_id"] = order[index + 1]
        else:
            block["state"] = GRADUATED
        self._save()
        # The overlay's completion screen comes first; the next-course card
        # follows once the learner dismisses it.
        QTimer.singleShot(0, self._after_completion_screen)

    def _after_completion_screen(self) -> None:
        if (self.block or {}).get("state") != BETWEEN_COURSES:
            return
        overlay = getattr(self._panel.window(), "_academy_overlay", None)
        container = getattr(overlay, "completion_container", None)
        if container is not None and container.isVisible():
            container.dismissed.connect(self._show_between_card)
        else:
            self._show_between_card()

    # ── Helpers ────────────────────────────────────────────────────────

    def _course_number(self, course_id: str | None) -> int:
        order = course_order()
        return order.index(course_id) + 1 if course_id in order else 0

    def _ui_state(self) -> dict[str, Any]:
        tab_bar = getattr(self._panel, "_tab_bar", None)
        return {"tab": tab_bar.currentIndex()} if tab_bar is not None else {}

    def _record_attempt(self, block: dict[str, Any]) -> None:
        pm = self._project_manager()
        metadata = getattr(self._panel, "_current_workflow_metadata", None) or {}
        self._manager.record_in_progress(
            block["course_id"],
            {
                "workflow": getattr(self._panel, "_current_workflow_filename", None),
                "workflow_name": metadata.get("name"),
                "project_dir": str(pm.project_dir) if pm is not None else None,
                "step_number": block.get("step_number", 0),
                "step_total": block.get("step_total", 0),
            },
        )

    def _forget_attempt(self, course_id: str) -> None:
        self._manager.forget_in_progress(
            course_id, workflow=getattr(self._panel, "_current_workflow_filename", None)
        )

    def _save(self) -> None:
        """Saves the workflow with its block, quietly (no "Saved" dialog)."""
        pm = self._project_manager()
        if pm is None:
            return
        filename = getattr(self._panel, "_current_workflow_filename", None)
        metadata = getattr(self._panel, "_current_workflow_metadata", None) or {}

        def _on_success(new_filename: str) -> None:
            if new_filename and new_filename != filename:
                self._panel._current_workflow_filename = new_filename
                block = self.block
                if block and block.get("state") in (RUNNING, PAUSED) and block.get("course_id"):
                    self._record_attempt(block)

        def _on_error(err: str) -> None:
            logger.error(f"Academy: saving the workflow failed: {err}")
            self._panel._close_after_save = False
            show_warning(
                self._panel,
                "Karcytics Academy",
                f"Your place in the course couldn't be saved:\n{err}",
            )

        self._panel._workspace_io_handler._run_save_to_pm(
            pm, filename, metadata, _on_success, _on_error
        )

    def _show_overlay(self, pausable: bool) -> None:
        from karcytics_sdk.plugin.academy_driver import show_academy_overlay

        overlay = show_academy_overlay(self._panel.window(), self._panel)
        overlay.set_pausable(pausable)

    def _hide_overlay(self) -> None:
        overlay = getattr(self._panel.window(), "_academy_overlay", None)
        if overlay is not None:
            overlay.hide()
