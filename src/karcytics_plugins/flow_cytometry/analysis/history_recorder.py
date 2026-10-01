"""HistoryRecorder — turns domain events into ``FlowStore`` undo steps.

This is the one table that decides which events are undoable steps, which
are follow-ups folded into the previous step, and which only mark the
workspace unsaved. A new kind of model edit either publishes one of the
events below or ``events.MODEL_EDITED`` with its own label.

One user action often publishes several events (a quadrant gate creates
four nodes; renaming a population across samples renames it once per
sample; a cascade delete). ``CentralEventBus`` delivers synchronously, so
commits are *deferred* to the end of the current event-loop turn and every
request raised in that turn becomes a single step, named by the first one.
``flush()`` forces a pending commit through immediately — undo/redo and
save call it first so they never race a step still waiting to be recorded.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from . import events

if TYPE_CHECKING:
    from .store import FlowStore

Subscribe = Callable[[str, Callable[[Any], None]], None]

CONNECTION_ADDED = "flow.pipeline.connection_added"
CONNECTION_REMOVED = "flow.pipeline.connection_removed"

_DERIVED_ACTION_LABELS = {
    "created": "Add Derived Parameter",
    "updated": "Edit Derived Parameter",
    "deleted": "Delete Derived Parameter",
    # "synced" is a rebuild after reload/compensation — not a user edit.
}


def _payload(data: Any) -> dict[str, Any]:
    return data if isinstance(data, dict) else {}


def _gate_created_label(data: Any) -> str:
    payload = _payload(data)
    if payload.get("is_split"):
        return "Split Population"
    name = payload.get("name")
    return f"Add Gate '{name}'" if name else "Add Gate"


def _gate_renamed_label(data: Any) -> str:
    name = _payload(data).get("new_name")
    return f"Rename Gate to '{name}'" if name else "Rename Gate"


def _model_edited_label(data: Any) -> str:
    return str(_payload(data).get("label") or "Edit")


def _derived_label(data: Any) -> str | None:
    return _DERIVED_ACTION_LABELS.get(str(_payload(data).get("action")))


#: topic → step label (a string, or a function of the payload returning
#: the label, or None for "not a user edit this time").
STEP_EVENTS: dict[str, str | Callable[[Any], str | None]] = {
    events.GATE_CREATED: _gate_created_label,
    events.GATES_CREATED: "Add Gates",
    events.LOGIC_NODE_CREATED: "Add Logic Gate",
    events.GATE_DELETED: "Delete Gate",
    events.GATE_RENAMED: _gate_renamed_label,
    events.GATE_MODIFIED: "Edit Gate",
    CONNECTION_ADDED: "Connect Gates",
    CONNECTION_REMOVED: "Disconnect Gates",
    events.SAMPLE_LOADED: "Add Samples",
    events.COMPENSATION_APPLIED: "Change Compensation",
    events.DERIVED_PARAMS_CHANGED: _derived_label,
    events.UMAP_COMPLETED: "Run UMAP",
    events.MODEL_EDITED: _model_edited_label,
}

#: Background completions that belong to the step that triggered them.
ABSORB_EVENTS: tuple[str, ...] = (events.PROPAGATION_COMPLETE,)

#: Saved-but-not-undoable changes.
UNTRACKED_EVENTS: tuple[str, ...] = (events.UNSAVED_CHANGE,)


class HistoryRecorder:
    """Subscribes to the event bus and feeds a ``FlowStore``."""

    def __init__(
        self,
        store: FlowStore,
        subscribe: Subscribe,
        unsubscribe: Subscribe,
        defer: Callable[[Callable[[], None]], None],
    ) -> None:
        self._store = store
        self._subscribe = subscribe
        self._unsubscribe = unsubscribe
        self._defer = defer
        self._pending_label: str | None = None
        self._subscriptions: list[tuple[str, Callable[[Any], None]]] = []

    # ── Lifecycle ─────────────────────────────────────────────────────

    def start(self) -> None:
        if self._subscriptions:
            return
        for topic, label in STEP_EVENTS.items():
            self._add(topic, self._make_step_handler(label))
        for topic in ABSORB_EVENTS:
            self._add(topic, self._on_absorb)
        for topic in UNTRACKED_EVENTS:
            self._add(topic, self._on_display)

    def stop(self) -> None:
        for topic, handler in self._subscriptions:
            self._unsubscribe(topic, handler)
        self._subscriptions.clear()
        self._pending_label = None

    def _add(self, topic: str, handler: Callable[[Any], None]) -> None:
        self._subscribe(topic, handler)
        self._subscriptions.append((topic, handler))

    # ── Handlers ──────────────────────────────────────────────────────

    def _make_step_handler(self, label: str | Callable[[Any], str | None]) -> Callable[[Any], None]:
        def _handler(data: Any) -> None:
            resolved = label(data) if callable(label) else label
            if resolved is not None:
                self.request_commit(resolved)

        return _handler

    def _on_absorb(self, _data: Any) -> None:
        self.flush()
        self._store.absorb()

    def _on_display(self, _data: Any) -> None:
        self._store.mark_unsaved_change()

    # ── Commit coalescing ─────────────────────────────────────────────

    def request_commit(self, label: str) -> None:
        """Record a step at the end of this event-loop turn (coalesced)."""
        if not self._store.is_recording:
            return
        if self._pending_label is None:
            self._pending_label = label
            self._defer(self.flush)

    def flush(self) -> None:
        """Commit a pending step now, if any."""
        label, self._pending_label = self._pending_label, None
        if label is not None:
            self._store.commit(label)

    @property
    def has_pending(self) -> bool:
        return self._pending_label is not None
