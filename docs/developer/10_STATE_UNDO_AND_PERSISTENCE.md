# 10. State, Undo/Redo & Persistence

How the flow module keeps **one** source of truth, turns edits into undo
steps, knows when the workspace is unsaved, and saves/loads it — and the
rules new code has to follow so all of that keeps working.

---

## 1. The single source of truth

`FlowState` (`analysis/state.py`) holds the whole session: `state.data`
(experiment, compensation, UMAP runs) and `state.view` (selection and display
settings). **One instance lives for the whole session.** Loads and undo/redo
change its contents *in place*; `state`, `state.data` and `state.view` are
never replaced, so the ~40 services and widgets that receive `state` in their
constructor can keep that reference forever.

What *does* get replaced is `state.data.experiment` — and with it every
`Sample`, `Group` and `GateNode` object. So:

> **Never cache a `Sample`, `Group` or `GateNode` across a user action.**
> Keep ids (`sample_id`, `node_id`) and look objects up through `state`
> when you need them.

`GraphWindow` is the model to follow: it stores `sample_id`/`node_id` and
resolves the sample on every render.

---

## 2. The one serializer

`analysis/workspace_document.py` is the only code that turns the workspace
into plain data or back:

| Function | Used by | Shape |
| --- | --- | --- |
| `serialize_workspace` / `apply_workspace` | `WorkflowService` save/load, `FlowState.to_dict`/`from_dict` | the **workflow document**: `experiment`, `compensation`, `view` (`WorkflowService` adds `sample_paths` and binary attachments around it) |
| `capture_model` / `model_experiment` | `FlowStore` (undo history) | the **model snapshot**: `experiment` (minus scales/axis memory), `compensation`, UMAP run ids |

`apply_workspace` replaces the *entire* previous workspace — including UMAP
runs, the group filter, the FMO overlay and fallback scales — and view
defaults come from a fresh `ViewState()`, so a load and a new workspace always
agree. The persisted view fields are listed once, in `PERSISTED_VIEW_FIELDS`.

Adding a persisted field means adding it to `ExperimentSerializer` (model) or
`PERSISTED_VIEW_FIELDS` (view) — nowhere else. `test_workspace_document.py`
fails if a field doesn't round-trip exactly.

---

## 3. What undo covers

| Kind of change | Examples | Undoable | Marks unsaved |
| --- | --- | --- | --- |
| **Analysis model** | gates, logic wiring, samples, groups, roles, markers, compensation, derived parameters, UMAP runs | ✅ | ✅ |
| **Display settings & annotations** | channel scales/transforms, render settings, UMAP cluster names/custom clusters | ❌ | ✅ |
| **Navigation** | selected sample/gate, active tab, per-sample last-viewed axes, default axis params | ❌ | ❌ |

Channel scales aren't undoable because rendering writes auto-ranged defaults
into them (`AxisManager.get_scale` materializes a default on first read), so
every first draw would otherwise look like a user edit.

---

## 4. `FlowStore` — history over the live state

`analysis/store.py`. Owns an SDK `UndoHistory` of model snapshots; the panel
binds it with `PluginBase.bind_undo_history(store.history, store.restore)`,
which is what Edit → Undo/Redo (Cmd/Ctrl+Z, Cmd+Shift+Z / Ctrl+Y) and the
menu labels ("Undo Delete Gate") run on.

- **`commit(label)`** — record the current state as one step.
- **`absorb()`** — fold the current state into the latest step. For
  background follow-ups to a user action (gate propagation to other samples
  lands ~300 ms after the edit): undoing the edit undoes both.
- **`mark_unsaved_change()`** — a saved-but-not-undoable change (display settings, UMAP cluster names).
- **`batch(label)`** / **`pause()`**/**`resume()`** — coalesce, or stop
  recording across a multi-turn operation (a workflow load).
- **`restore(snapshot)`** — rebuild the experiment from a snapshot, reattach
  what snapshots only reference by id (event data, UMAP embeddings, group
  scales — cached by the store and released once no reachable step needs
  them), recompute compensated event data where it no longer matches the
  restored compensation flags/matrix (Apply/Toggle Compensation rewrite
  `fcs_data.events` in place), repair view pointers that no longer resolve,
  and publish `STATE_RESTORED`.
- **`record_unannounced_changes()`** — safety net run before every
  undo/redo/save: a live change that no event announced becomes its own
  "Edit" step (and logs a warning) instead of being merged into — and lost
  with — the previous one.

### Unsaved changes

`store.is_dirty` = a saved-but-not-undoable change was made **or** the current history step
isn't the saved one. Because it's revision-based, undoing back to the saved
step reads as clean again. A save calls `panel._begin_save()` when it
*starts* and `panel._finish_save(token)` when it succeeds: edits made while
a background save runs stay dirty.

Everything that cares about unsaved changes reads `store.is_dirty`:

- the **Save Workspace** button (via the store's dirty listener);
- **closing the window** — the SDK's isolated window calls
  `panel.confirm_close()`, which offers Save / Discard / Cancel. Save runs
  the normal background save and closes once `_finish_save` sees it
  succeed; a cancelled or failed save just means the next close asks again.
  A close the Hub requests is never prompted;
- **loading a workflow** over unsaved edits (e.g. the Hub injecting another
  one) asks "Discard and load" / Cancel first;
- the SDK's **15-minute autosave** (`has_unsaved_changes=`) skips a tick
  entirely — no rewrite, no reminder toast — when nothing changed.

---

## 5. Recording edits — `HistoryRecorder`

`analysis/history_recorder.py` is the one table mapping domain events to the
store (`STEP_EVENTS`, `ABSORB_EVENTS`, `UNTRACKED_EVENTS`).
`MainPanelController.wire()` starts it.

`CentralEventBus` delivers **synchronously** on the GUI thread, and one user
action often publishes several events (a quadrant creates four nodes; a
rename is applied across samples). The recorder therefore defers the commit
to the end of the event-loop turn: everything requested in one turn is one
step, named by the first request. Undo, redo and save `flush()` it first.

**Adding a new kind of edit:** non-gate edits live in
`analysis/services/experiment_edits.py` (samples, groups, roles, templates,
compensation, UMAP runs) — each function mutates `state` by id and then
announces itself with `MODEL_EDITED` plus the UI-refresh events widgets
already listen for. Widgets call these; they never mutate the experiment
directly. A new edit either goes there or, at minimum, ends with

```python
experiment_edits.announce("Rename Group")          # one undo step
experiment_edits.announce_unsaved_change()         # saved, not undoable
```

Gate edits go through `GateCoordinator` as before (their events are already
in `STEP_EVENTS`). Address samples/groups/nodes **by id** in any callback —
a captured object is detached by the next undo.

---

## 6. Reacting to undo/redo — `STATE_RESTORED`

After a restore every model object is new. The panel's `_on_state_restored`
cancels pending propagation, recomputes statistics, calls
`GraphManager.reconcile_with_state()` (closes graphs whose sample/population
is gone, reloads the rest by id) and refreshes every widget. A widget that
keeps model-derived state of its own must refresh it from `state` here.

Undo/redo also first cancel any half-finished gate drag, and are refused
while a workflow is loading or a save is running.

---

## 7. Workflow load lifecycle

1. `load_workflow` → `_begin_workflow_load()`: flush any pending step,
   `store.pause()`, cancel propagation.
2. `WorkflowService.load_workflow` → `apply_workspace` (whole workspace
   replaced in place) → background FCS reload → attachments.
3. `_on_fcs_done` → `_finish_workflow_load(clean=True)`: resume and
   `store.reset()` — the loaded workflow is the clean baseline, with nothing
   to undo into the previous workspace.

A failed load resets to an *unsaved* baseline; a reload task that errors is
reported as every sample failing (so the load still completes); and only the
load actually in progress can reset history — a stray late callback can't
wipe edits made since.

Tests: `tests/unit/analysis/test_store.py`, `test_history_recorder.py`,
`test_workspace_document.py`, `tests/ui/test_workflow_load_unload.py`,
`tests/ui/test_undo_restore_ui.py`.
