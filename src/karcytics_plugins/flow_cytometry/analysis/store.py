"""FlowStore — undo/redo and unsaved-changes tracking for one ``FlowState``.

The store never owns a second copy of the workspace: ``FlowState`` stays the
single source of truth, and the store only records *snapshots* of it (see
``workspace_document.capture_model``) into an SDK ``UndoHistory``.

Recording — every change to the analysis model reaches the store in one of
three ways (``HistoryRecorder`` maps domain events onto these):

* ``commit(label)`` — a completed user action; becomes one undo step.
* ``absorb()`` — a background follow-up to the latest step (e.g. gate
  propagation finishing a moment after the edit that triggered it). Folded
  into the current step: undoing that step undoes both.
* ``mark_display_dirty()`` — a display setting that is saved with the
  workflow but isn't undoable (axis scales, render settings).

Restoring (undo/redo) rebuilds ``state.data.experiment`` from the snapshot
*in place* — ``state``/``state.data``/``state.view`` keep their identity —
reattaches the heavy data snapshots only reference by id (event data, UMAP
embeddings, group scales), repairs view pointers that no longer resolve, and
publishes ``events.STATE_RESTORED`` so every view re-reads the state.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from karcytics_sdk.plugin import UndoHistory, get_logger

from . import events
from .derived import sync_experiment
from .workspace_document import capture_model, deserialize_compensation, model_experiment

if TYPE_CHECKING:
    from .fcs_io import FCSData
    from .scaling import AxisScale
    from .state import FlowState

logger = get_logger(__name__, "flow_cytometry")

#: Label used when the safety net records a change nothing announced.
UNRECORDED_CHANGE_LABEL = "Edit"

#: Key under which each UMAP result dict carries its stable run id.
UMAP_RUN_ID_KEY = "run_id"

Publish = Callable[[str, Any], None]


@dataclass(frozen=True)
class SaveToken:
    """What a save captured when it started; hand back to ``finish_save``."""

    revision: int | None
    display_generation: int


class FlowStore:
    """Undo history + dirty tracking over a single, long-lived ``FlowState``."""

    def __init__(self, state: FlowState, publish: Publish, max_steps: int = 100) -> None:
        self._state = state
        self._publish = publish
        self.history: UndoHistory[dict[str, Any]] = UndoHistory(max_steps=max_steps)
        self.history.add_listener(self._notify_dirty)

        # Heavy data a snapshot can bring back but doesn't contain itself.
        self._event_data: dict[str, FCSData] = {}
        self._umap_runs: dict[str, dict[str, Any]] = {}
        self._group_scales: dict[str, dict[str, AxisScale]] = {}

        self._suspended = 0
        self._batch_depth = 0
        self._batch_label: str | None = None
        self._restoring = False

        self._display_dirty = False
        self._display_generation = 0
        self._last_dirty: bool | None = None
        self._dirty_listeners: list[Callable[[bool], None]] = []

    # ── Snapshots ─────────────────────────────────────────────────────

    def _umap_run_ids(self) -> dict[str, list[str]]:
        """Stable ids for every UMAP run, assigning one to runs that lack it."""
        ids: dict[str, list[str]] = {}
        for key, runs in self._state.data.umap_results.items():
            run_ids = []
            for run in runs:
                run_id = run.get(UMAP_RUN_ID_KEY)
                if not run_id:
                    run_id = uuid.uuid4().hex
                    run[UMAP_RUN_ID_KEY] = run_id
                self._umap_runs[run_id] = run
                run_ids.append(run_id)
            ids[key] = run_ids
        return ids

    def capture(self) -> dict[str, Any]:
        """Snapshot the live model (also caches the heavy data it references)."""
        exp = self._state.data.experiment
        for sid, sample in exp.samples.items():
            if sample.fcs_data is not None:
                self._event_data[sid] = sample.fcs_data
        for gid, group in exp.groups.items():
            self._group_scales[gid] = group.channel_scales
        return capture_model(self._state, self._umap_run_ids())

    def _prune(self) -> None:
        """Drop cached heavy data no reachable step (nor the live state) uses."""
        sample_ids: set[str] = set(self._state.data.experiment.samples)
        group_ids: set[str] = set(self._state.data.experiment.groups)
        run_ids: set[str] = set()
        for snap in self.history.snapshots():
            sample_ids.update(snap["experiment"]["samples"])
            group_ids.update(snap["experiment"]["groups"])
            for ids in snap["umap_runs"].values():
                run_ids.update(ids)
        for runs in self._state.data.umap_results.values():
            run_ids.update(r[UMAP_RUN_ID_KEY] for r in runs if UMAP_RUN_ID_KEY in r)
        self._event_data = {k: v for k, v in self._event_data.items() if k in sample_ids}
        self._group_scales = {k: v for k, v in self._group_scales.items() if k in group_ids}
        self._umap_runs = {k: v for k, v in self._umap_runs.items() if k in run_ids}

    # ── Recording ─────────────────────────────────────────────────────

    @property
    def is_recording(self) -> bool:
        return not (self._suspended or self._restoring)

    def reset(self, clean: bool = True) -> None:
        """Start a fresh history at the current state (after a load / new workspace)."""
        self._display_dirty = False
        self._display_generation += 1
        self.history.reset(self.capture(), clean=clean)
        self._prune()
        self._notify_dirty()

    def commit(self, label: str) -> bool:
        """Record the current state as one undoable step. Returns True if recorded."""
        if not self.is_recording:
            return False
        if self._batch_depth:
            self._batch_label = self._batch_label or label
            return False
        if not self.history.is_initialized:
            self.reset(clean=False)
            return False
        recorded = self.history.record(label, self.capture())
        if recorded:
            self._prune()
        return recorded

    def absorb(self) -> None:
        """Fold the current state into the latest step without making a new one."""
        if not self.is_recording or self._batch_depth or not self.history.is_initialized:
            return
        self.history.replace_current(self.capture())

    @contextmanager
    def batch(self, label: str) -> Iterator[None]:
        """Coalesce every commit inside into one step named `label`."""
        self._batch_depth += 1
        try:
            yield
        finally:
            self._batch_depth -= 1
            if self._batch_depth == 0:
                pending, self._batch_label = self._batch_label, None
                if pending is not None:
                    self.commit(label)

    def pause(self) -> None:
        """Stop recording until the matching ``resume()``.

        For work that spans several event-loop turns, like a workflow load
        waiting on its background FCS reload. Pauses nest.
        """
        self._suspended += 1

    def resume(self) -> None:
        self._suspended = max(0, self._suspended - 1)

    @contextmanager
    def suspended(self) -> Iterator[None]:
        """Record nothing inside."""
        self.pause()
        try:
            yield
        finally:
            self.resume()

    def record_unannounced_changes(self) -> bool:
        """Safety net: record live changes no event reported, as their own step.

        Called before every undo/redo so a mutation that forgot to announce
        itself is undone on its own instead of being silently merged into —
        and lost with — the step before it.
        """
        current = self.history.current
        if current is None or not self.is_recording:
            return False
        if self.capture() == current.snapshot:
            return False
        logger.warning(
            "Recording a model change no event announced — the code path that "
            "made it should publish events.MODEL_EDITED."
        )
        return self.commit(UNRECORDED_CHANGE_LABEL)

    # ── Restoring ─────────────────────────────────────────────────────

    def restore(self, snapshot: dict[str, Any]) -> None:
        """Make the live state match `snapshot` (used for undo and redo)."""
        state = self._state
        live = state.data.experiment
        # Anything live right now might be needed again by a later redo.
        self.capture()

        experiment = model_experiment(snapshot)
        for sid, sample in experiment.samples.items():
            live_sample = live.samples.get(sid)
            sample.fcs_data = (
                live_sample.fcs_data
                if live_sample is not None and live_sample.fcs_data is not None
                else self._event_data.get(sid)
            )
            if live_sample is not None:
                sample.last_viewed_axes = live_sample.last_viewed_axes
        for gid, group in experiment.groups.items():
            live_group = live.groups.get(gid)
            group.channel_scales = (
                live_group.channel_scales
                if live_group is not None
                else self._group_scales.get(gid, {})
            )

        self._restoring = True
        try:
            state.data.experiment = experiment
            state.data.compensation = deserialize_compensation(snapshot["compensation"])
            state.data.umap_results = {
                key: [self._umap_runs[rid] for rid in ids if rid in self._umap_runs]
                for key, ids in snapshot["umap_runs"].items()
            }
            sync_experiment(experiment)
            self._repair_view()
            # Store the restored state exactly as it now serializes. They
            # normally match already, but a snapshot taken of a subtly
            # inconsistent model (e.g. a dangling logic-node parent, which
            # serialization drops) would otherwise differ from its own
            # restore — and record_unannounced_changes would then turn the
            # next undo into a phantom step that wipes the redo stack.
            self.history.replace_current(self.capture())
            self._publish(events.STATE_RESTORED, {})
        finally:
            self._restoring = False

    def _repair_view(self) -> None:
        """Point view selections at something that still exists."""
        view = self._state.view
        exp = self._state.data.experiment
        if view.current_sample_id not in exp.samples:
            view.current_sample_id = next(iter(exp.samples), None)
            view.current_gate_id = None
        if view.current_gate_id is not None:
            sample = exp.samples.get(view.current_sample_id) if view.current_sample_id else None
            if sample is None or sample.gate_tree.find_node_by_id(view.current_gate_id) is None:
                view.current_gate_id = None
        if view.active_fmo_sample_id is not None and view.active_fmo_sample_id not in exp.samples:
            view.active_fmo_sample_id = None
        if view.active_group_filter not in ("__all__", *exp.groups):
            view.active_group_filter = "__all__"

    # ── Unsaved changes ───────────────────────────────────────────────

    @property
    def is_dirty(self) -> bool:
        return self._display_dirty or not self.history.is_clean

    def mark_display_dirty(self) -> None:
        """A saved-but-not-undoable setting changed."""
        if not self.is_recording:
            return
        self._display_dirty = True
        self._display_generation += 1
        self._notify_dirty()

    def begin_save(self) -> SaveToken:
        """Capture what a save that's about to start will contain."""
        self.record_unannounced_changes()
        return SaveToken(self.history.revision, self._display_generation)

    def finish_save(self, token: SaveToken) -> None:
        """Mark what `token` captured as saved (changes made since stay dirty)."""
        if token.display_generation == self._display_generation:
            self._display_dirty = False
        self.history.mark_clean(token.revision)
        self._notify_dirty()

    def add_dirty_listener(self, callback: Callable[[bool], None]) -> None:
        """Call `callback(is_dirty)` whenever the dirty state flips."""
        self._dirty_listeners.append(callback)

    def _notify_dirty(self) -> None:
        dirty = self.is_dirty
        if dirty == self._last_dirty:
            return
        self._last_dirty = dirty
        for callback in list(self._dirty_listeners):
            callback(dirty)
