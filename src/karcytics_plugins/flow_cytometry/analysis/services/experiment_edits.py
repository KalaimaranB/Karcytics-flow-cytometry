"""User edits to the experiment that aren't gate edits.

Widgets used to mutate ``state.data.experiment`` directly and then publish
whatever event they happened to pick (or nothing), so many of these edits
were neither undoable nor marked the workspace unsaved. Each function here
changes ``state`` and then *announces* the change: ``events.MODEL_EDITED``
with the undo step's label (see ``HistoryRecorder``), followed by the same
UI-refresh events the widgets published before, so existing subscribers keep
working unchanged.

Everything is addressed by id, never by a held ``Sample``/``Group`` object —
those are replaced wholesale on undo/redo, so a captured object would
silently edit a detached copy.

``publish`` defaults to ``CentralEventBus.publish``; tests pass their own.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from karcytics_sdk.plugin import get_logger

from .. import events
from ..compensation import CompensationMatrix, apply_compensation
from ..derived import sync_experiment
from ..experiment import Group, GroupRole, SampleRole, WorkflowTemplate

if TYPE_CHECKING:
    from ..state import FlowState

logger = get_logger(__name__, "flow_cytometry")

Publish = Callable[[str, Any], None]


def _bus(publish: Publish | None) -> Publish:
    if publish is not None:
        return publish
    from karcytics_sdk.plugin import CentralEventBus

    return CentralEventBus.publish


def announce(label: str, *follow_ups: tuple[str, Any], publish: Publish | None = None) -> None:
    """Publish ``MODEL_EDITED(label)`` then each ``(topic, payload)`` follow-up."""
    send = _bus(publish)
    send(events.MODEL_EDITED, {"label": label})
    for topic, payload in follow_ups:
        send(topic, payload)


def announce_unsaved_change(publish: Publish | None = None) -> None:
    """A saved-but-not-undoable change (display settings, UMAP annotations)."""
    _bus(publish)(events.UNSAVED_CHANGE, {})


# ── Samples ───────────────────────────────────────────────────────────


def rename_sample(
    state: FlowState, sample_id: str, name: str, publish: Publish | None = None
) -> bool:
    sample = state.data.experiment.samples.get(sample_id)
    new_name = name.strip()
    if sample is None or not new_name or new_name == sample.display_name:
        return False
    sample.display_name = new_name
    announce(
        "Rename Sample",
        (events.SAMPLE_UPDATED, {"source": "SampleList"}),
        publish=publish,
    )
    return True


def remove_samples(
    state: FlowState, sample_ids: Iterable[str], publish: Publish | None = None
) -> int:
    exp = state.data.experiment
    removed = 0
    for sid in sample_ids:
        if sid in exp.samples:
            exp.remove_sample(sid)
            removed += 1
    if removed:
        announce(
            "Remove Sample" if removed == 1 else "Remove Samples",
            (events.EXPERIMENT_DATA_CHANGED, {"source": "SampleList"}),
            publish=publish,
        )
    return removed


def set_sample_roles(
    state: FlowState,
    sample_ids: Iterable[str],
    role: SampleRole,
    publish: Publish | None = None,
) -> int:
    """Give every listed sample `role`. Returns how many actually changed."""
    changed = []
    for sid in sample_ids:
        sample = state.data.experiment.samples.get(sid)
        if sample is not None and sample.role != role:
            sample.role = role
            changed.append(sid)
    if changed:
        follow_ups = [
            (events.SAMPLE_UPDATED, {"sample_id": sid, "stats": None, "tree": None})
            for sid in changed
        ]
        announce(
            "Change Sample Role" if len(changed) == 1 else "Assign Sample Roles",
            *follow_ups,
            publish=publish,
        )
    return len(changed)


# ── Groups ────────────────────────────────────────────────────────────


def create_group(state: FlowState, name: str, publish: Publish | None = None) -> Group | None:
    clean = name.strip()
    if not clean:
        return None
    group = Group(group_id=str(uuid.uuid4()), name=clean, role=GroupRole.CUSTOM)
    state.data.experiment.add_group(group)
    announce("Create Group", publish=publish)
    return group


def rename_group(
    state: FlowState, group_id: str, name: str, publish: Publish | None = None
) -> bool:
    group = state.data.experiment.groups.get(group_id)
    clean = name.strip()
    if group is None or not clean or clean == group.name:
        return False
    group.name = clean
    announce(
        "Rename Group",
        (events.SAMPLE_UPDATED, {"source": "GroupsPanel"}),
        publish=publish,
    )
    return True


def delete_group(state: FlowState, group_id: str, publish: Publish | None = None) -> bool:
    exp = state.data.experiment
    group = exp.groups.get(group_id)
    if group is None:
        return False
    for sid in group.sample_ids:
        sample = exp.samples.get(sid)
        if sample is not None and group_id in sample.group_ids:
            sample.group_ids.remove(group_id)
    del exp.groups[group_id]
    if state.view.active_group_filter == group_id:
        state.view.active_group_filter = "__all__"
    announce(
        "Delete Group",
        (events.SAMPLE_UPDATED, {"source": "GroupsPanel"}),
        publish=publish,
    )
    return True


def add_samples_to_group(
    state: FlowState,
    group_id: str,
    sample_ids: Iterable[str],
    publish: Publish | None = None,
    source: str = "SampleList",
) -> int:
    exp = state.data.experiment
    group = exp.groups.get(group_id)
    if group is None:
        return 0
    added = 0
    for sid in sample_ids:
        if sid and sid not in group.sample_ids:
            group.sample_ids.append(sid)
            sample = exp.samples.get(sid)
            if sample is not None and group_id not in sample.group_ids:
                sample.group_ids.append(group_id)
            added += 1
    if added:
        announce(
            f"Add to Group '{group.name}'",
            (events.SAMPLE_UPDATED, {"source": source}),
            publish=publish,
        )
    return added


def remove_samples_from_group(
    state: FlowState,
    group_id: str,
    sample_ids: Iterable[str],
    publish: Publish | None = None,
) -> int:
    exp = state.data.experiment
    group = exp.groups.get(group_id)
    if group is None:
        return 0
    removed = 0
    for sid in sample_ids:
        if sid in group.sample_ids:
            group.sample_ids.remove(sid)
            sample = exp.samples.get(sid)
            if sample is not None and group_id in sample.group_ids:
                sample.group_ids.remove(group_id)
            removed += 1
    if removed:
        announce(
            f"Remove from Group '{group.name}'",
            (events.SAMPLE_UPDATED, {"source": "SampleList"}),
            publish=publish,
        )
    return removed


def apply_template(
    state: FlowState, template: WorkflowTemplate, publish: Publish | None = None
) -> None:
    state.data.experiment.apply_template(template)
    announce(
        f"Apply Template '{template.name}'",
        (events.SAMPLE_LOADED, {"template_name": template.name, "source": "WorkspaceRibbon"}),
        publish=publish,
    )


# ── Compensation ──────────────────────────────────────────────────────


def set_compensation(
    state: FlowState,
    matrix: CompensationMatrix | None,
    label: str,
    publish: Publish | None = None,
) -> None:
    """Replace the compensation matrix (doesn't touch loaded event data)."""
    state.data.compensation = matrix
    announce(label, (events.COMPENSATION_APPLIED, {}), publish=publish)


@dataclass(frozen=True)
class CompensationResult:
    changed: int = 0
    already_compensated: int = 0
    no_data: int = 0


def apply_compensation_to_all(
    state: FlowState, publish: Publish | None = None, label: str = "Apply Compensation"
) -> CompensationResult:
    """Compensate every loaded, not-yet-compensated sample with the current matrix."""
    comp = state.data.compensation
    if comp is None:
        return CompensationResult()
    exp = state.data.experiment
    applied = already = no_data = 0
    for sample in exp.samples.values():
        if sample.fcs_data is None:
            no_data += 1
            continue
        if sample.is_compensated:
            already += 1
            continue
        try:
            sample.fcs_data.events = apply_compensation(sample.fcs_data, comp)
        except Exception as exc:  # one bad sample never blocks the rest
            logger.warning("Compensation failed for %s: %s", sample.display_name, exc)
            continue
        sample.fcs_data.is_compensated = True
        sample.is_compensated = True
        applied += 1
    sync_experiment(exp)
    if applied:
        announce(label, (events.COMPENSATION_APPLIED, {}), publish=publish)
    return CompensationResult(applied, already, no_data)


def toggle_compensation(
    state: FlowState, publish: Publish | None = None
) -> tuple[int, bool | None]:
    """Turn compensation on/off for every sample with a raw-data backup.

    The target is the opposite of the first eligible sample's current state.
    Returns ``(samples toggled, new state or None if nothing was eligible)``.
    """
    exp = state.data.experiment
    toggled = 0
    target: bool | None = None
    for sample in exp.samples.values():
        fcs = sample.fcs_data
        if fcs is None or fcs.raw_events is None:
            continue
        if target is None:
            target = not fcs.is_compensated
        if target:
            if state.data.compensation is None:
                continue
            fcs.events = apply_compensation(fcs, state.data.compensation)
            fcs.is_compensated = True
            sample.is_compensated = True
        else:
            fcs.events = fcs.raw_events.copy()
            fcs.is_compensated = False
            sample.is_compensated = False
        toggled += 1
    sync_experiment(exp)
    if toggled:
        announce(
            "Turn Compensation On" if target else "Turn Compensation Off",
            (events.COMPENSATION_APPLIED, {}),
            publish=publish,
        )
    return toggled, target


# ── UMAP runs ─────────────────────────────────────────────────────────


def add_umap_run(state: FlowState, results: dict[str, Any], publish: Publish | None = None) -> str:
    """Store a finished UMAP run; returns its ``sample::node`` key."""
    key = f"{results['sample_id']}::{results.get('node_id') or 'root'}"
    state.data.umap_results.setdefault(key, []).append(results)
    _bus(publish)(events.UMAP_COMPLETED, {})
    return key


def delete_umap_run(
    state: FlowState, key: str, run_index: int, publish: Publish | None = None
) -> bool:
    runs = state.data.umap_results.get(key)
    if runs is None or not 0 <= run_index < len(runs):
        return False
    runs.pop(run_index)
    announce("Delete UMAP Run", publish=publish)
    return True
