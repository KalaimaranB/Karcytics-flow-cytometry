# Plan: pause and resume Academy courses (Academy workflows)

**Status:** built 2026-10-17 and run through offscreen. Commits: SDK `281a1aa`, `220428d`, `53d64f9`, `6df5846`; flow `10edcd5`, `7b5302c`, `da1c27d`; Hub `b694cab` on `feature/academy-pause-resume`. Open: the user's own play-through.

**Why:** the five flow courses run 58–65 steps each. A learner can't stop partway: closing the module loses their place, and the catalog only knows "not started" or "completed".

**Repos and branches:**
- Karcytics-SDK — commits on `main`.
- Karcytics-flow-cytometry — commits on `main`.
- Karcytics (Hub) — branch `feature/academy-pause-resume` off the latest `develop`.
- One commit per phase. The user handles version bumps and releases.

---

## 1. The model: an Academy workflow

A course always runs inside a saved workflow. Starting a course from the catalog turns the current workflow into an **Academy workflow**. Cyto says so first, and an unnamed workspace is named and saved at that point. The same workflow carries the learner through all five courses, because each course builds on the one before.

An Academy workflow is in one of four states:

| State | When | What the learner sees |
| --- | --- | --- |
| `running` | A course is on screen | The normal course overlay, plus a ⏸ Pause button |
| `paused` | The learner pressed Pause, closed the window mid-course, or the app quit | The panel is dimmed and inert. A centred card shows Cyto waiting, "Ready to continue Course 2: Compensation?", "Step 23 of 60", **▶ Resume** and **Leave course…** |
| `between_courses` | Course N (N < 5) just finished | The same locked card: "Course 2 complete — start Course 3?", with **▶ Start Course 3** (default) and **Leave Academy** |
| `graduated` | Course 5 finished | The workflow unlocks. It stays marked as an Academy workflow, with "All courses completed" |

**Leave course / Leave Academy** removes the `academy` block, so the workflow becomes an ordinary workflow and keeps all its work. This is how a learner stops after N courses to explore on their own. By default, each finished course prompts them into the next one.

A workflow that has an `academy` block is never interactive outside `running`, except once `graduated`.

## 2. What gets saved, and where

**Workflow metadata** (`metadata["academy"]` in the workflow JSON) is the source of truth for resuming:

```json
{
  "academy": {
    "state": "paused",
    "course_id": "flow_course_2_compensation",
    "course_title": "Building a matrix & clean-up gates",
    "course_number": 2,
    "course_count": 5,
    "step_id": "c2_b20_save",
    "step_history": ["c2_s01", "..."],
    "subtask_progress": {},
    "step_number": 23,
    "step_total": 60,
    "completed_courses": ["flow_course_1_fundamentals"],
    "ui": {"tab": 2},
    "updated_at": "2026-10-17T10:00:00+00:00"
  }
}
```

- The Hub reads this block directly to draw the dashboard card. It can't ask the plugin, because the plugin process isn't running.
- `_current_workflow_metadata` already rides along on Save, Update and autosave, so autosave during a course keeps the block current. If the app crashes, a workflow found in the `running` state is treated as `paused`.
- The step number comes from `Course.get_main_path()`, the same count the overlay's progress bar uses.

**`progress.json`** (the plugin's own Academy data) gains `in_progress[course_id]` for the catalog: workflow filename, project dir, step number and total, and updated time. The latest attempt wins. Several attempts at the same course may exist in different workflows, and the catalog shows the latest one.

## 3. Pausing and resuming

**Pause:**
- The ⏸ Pause button in the bubble header replaces the "×" exit, which currently means "lose your place".
- Closing the module window mid-course asks first (user's call, 2026-10-17: never save without asking). **Save** pauses, saves and then closes; **Don't Save** closes with nothing saved, so the course later resumes from the last save; **Cancel** keeps the window open.
- The catalog's progress for an attempt updates only when the workflow is saved (Pause, the course's Save steps, Update, autosave), never per step. Otherwise Don't Save would leave the catalog showing a step the saved workflow never reached.
- Pause is disabled while a modal dialog is open (for example the gate-name prompt), so a course is never saved halfway through a dialog.

**Resume:** the saved step id, step history and sub-task progress are restored, plus the panel's tab. Then the step is shown again.

**Steps that rely on a window or dialog that isn't saved:** resuming checks that the step's spotlight targets are all on screen. If one isn't (it lives in a popup, a dialog, a Compensation sub-page or an unsaved tab), the course resumes on the latest visited step whose targets all show — usually the one that opens them. A step can also name `resume_step_id` explicitly. The Phase 4 audit found that no course needs one yet: the gate-drawing steps tell the learner to pick the tool themselves, and their `_verify` steps only check the saved gate.

**While locked:** the overlay covers the whole panel and takes all input, and the isolated window's menu bar is disabled.

## 4. Catalog and Hub

- **Catalog card:** a progress bar and "IN PROGRESS · Step 23/60". The button becomes **Resume**. If the attempt is in the current project, Resume opens that workflow. Otherwise the card names the project to open.
- **Hub dashboard:** each workflow card with an `academy` block gets a 🎓 pill: "Course 2 · Paused · 38%", "Course 2 done · next: Course 3", or "Academy · all courses done". Projects and the launcher's recent list are unchanged; projects are not Academy projects.

## Phases and checkpoints

- [x] **Phase 1 — SDK engine.**
  - `AcademyManager` gains `session_snapshot()` and `restore_session()`, real in-progress `get_progress()` and `step_position()`, and `in_progress` in `progress.json`.
  - New events: `ACADEMY_COURSE_PAUSED` and `ACADEMY_COURSE_RESUMED`.
  - `BaseStep.resume_step_id`.
  - Unit tests.
- [x] **Phase 2 — SDK UI.**
  - The ⏸ Pause button, the `AcademyLockCard` widget (paused and between-courses variants), and the pause and leave hooks the plugin supplies.
  - Auto-pause on close in the isolated window, and the menu bar disabled while locked.
  - Catalog progress and Resume.
  - UI tests.
- [x] **Phase 3 — Flow lifecycle.**
  - Starting a course converts the workflow, and Cyto explains it.
  - Save on pause, lock on load, resume, and the prompt to start the next course or leave the Academy.
  - Graduation after Course 5, and `confirm_close` integration.
- [x] **Phase 4 — Flow course audit.**
  - `resume_step_id` on steps that depend on transient UI, and restoring the open tab.
  - Integration test: pause at several steps of every course, reload, resume, and check that the step's validator still passes.
  - Raise the SDK lower bound when the user releases.
- [x] **Phase 5 — Hub.** The 🎓 pill on dashboard workflow cards, the workflow properties dialog keeping the `academy` key, and `docs/internal`.
- [ ] **Phase 6 — Play-through.** Run the app offscreen and go pause → close → reopen → resume → finish → next-course prompt → leave Academy, for each course. Then hand over to the user for a play-through.
  - 2026-10-17 self-run on the real panel, offscreen, with a temporary project: start (conversion card) → pause at Course 1 step 2/59 → close → reopen locked → resume on the same step → close mid-course (auto-pause and save) → finish → next-course card → Course 2 in the same workflow → pause → leave (ordinary workflow, attempt forgotten). This run found the lock card stretching to full height (fixed in SDK `6df5846`).
  - The user's play-through on 2026-10-17 found that the "Leave the course?" Yes/No did nothing: the lock card disabled the dialog because it was parented to the locked panel (fixed in SDK `50e5b9c`). The user also asked for closing mid-course to prompt rather than auto-save (see §3).
  - [ ] The user's play-through in the app.
