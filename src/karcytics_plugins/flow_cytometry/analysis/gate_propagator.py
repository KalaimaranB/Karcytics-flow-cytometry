"""Gate propagator — background worker for cross-sample gate updates.

When a gate is drawn or modified on one sample, the ``GatePropagator``
re-applies the full gate tree to every other sample in the same group,
recomputing statistics (count, %parent, %total) for each population.

This runs on a background thread via TaskScheduler so the UI stays responsive
during batch computation. A 200ms debounce timer prevents redundant recalculations
while the user is still dragging a gate handle.
"""

from __future__ import annotations

import threading
from typing import Any

from karcytics_sdk.plugin import CentralEventBus, get_logger

from . import events
from .experiment import Sample
from .propagation_worker import _PropagationWorker
from .state import FlowState

logger = get_logger(__name__, "flow_cytometry")


class GatePropagator:
    """Debounced gate propagation manager using TaskScheduler.

    Publishes:
        events.SAMPLE_UPDATED(sample_id, stats, tree):
            Emitted after a single sample's stats are recomputed.
        events.PROPAGATION_COMPLETE:
            Emitted when all samples have been updated.
    """

    DEBOUNCE_MS = 200

    def __init__(
        self, state: FlowState, task_scheduler: Any | None = None, _parent: object | None = None
    ) -> None:
        self._state = state
        self._task_scheduler = task_scheduler
        self._lock = threading.Lock()

        # Debounce timer
        self._timer: threading.Timer | None = None

        # Pending request
        self._pending_gate_id: str | None = None
        self._pending_source_id: str | None = None

        self._active_task_id: str | None = None

        if self._task_scheduler is not None:
            if hasattr(self._task_scheduler, "task_finished"):
                self._task_scheduler.task_finished.connect(self._on_task_finished)
            if hasattr(self._task_scheduler, "task_error"):
                self._task_scheduler.task_error.connect(self._on_task_error)

    def request_propagation(self, gate_id: str, source_sample_id: str) -> None:
        """Request gate propagation with debouncing."""
        with self._lock:
            self._pending_gate_id = gate_id
            self._pending_source_id = source_sample_id
            self._cross_group_override = False

            if self._timer is not None:
                self._timer.cancel()

            self._timer = threading.Timer(self.DEBOUNCE_MS / 1000.0, self._execute_propagation)
            self._timer.start()

    def request_cross_group_propagation(self, gate_id: str, source_sample_id: str) -> None:
        """Request gate propagation bypassing the active group filter."""
        with self._lock:
            self._pending_gate_id = gate_id
            self._pending_source_id = source_sample_id
            self._cross_group_override = True

            if self._timer is not None:
                self._timer.cancel()

            self._timer = threading.Timer(self.DEBOUNCE_MS / 1000.0, self._execute_propagation)
            self._timer.start()

    def cancel_pending(self) -> None:
        """Drop any queued or running propagation without applying its result.

        Called whenever the model is replaced wholesale (undo/redo, loading a
        workflow): a result computed from the old source tree would
        otherwise land a moment later and overwrite the restored targets.
        """
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            self._pending_source_id = None
        self._active_task_id = None

    def _execute_propagation(self) -> None:
        """Actually run the propagation logic after debouncing."""
        try:
            with self._lock:
                source_id = self._pending_source_id

            if source_id is None:
                return

            current_state = self._state

            source = current_state.data.experiment.samples.get(source_id)
            if source is None:
                return

            tree_dict = source.gate_tree.to_dict()
            targets = self._find_targets(source_id, current_state)

            worker = _PropagationWorker()
            worker.configure(tree_dict, targets)

            if self._task_scheduler is not None:
                worker_obj = self._task_scheduler.submit(worker, current_state)
                task_id = worker_obj.task_id
                self._active_task_id = task_id

                logger.info(
                    "Propagating gates from '%s' to %d samples via TaskScheduler.",
                    source.display_name,
                    len(targets),
                )
            else:
                logger.warning("No task_scheduler available for propagation.")
        except Exception as e:
            logger.error(f"Error in _execute_propagation: {e}", exc_info=True)
            CentralEventBus.publish(
                events.PROPAGATION_COMPLETE,
                {"total": 0, "succeeded": 0, "failed": 0, "errors": {}, "fatal": str(e)},
            )

    def _on_task_finished(self, _task_id: str, results: dict):
        logger.info(
            f"GatePropagator received task_finished for {_task_id}. Active is {self._active_task_id}"
        )
        if _task_id == self._active_task_id:
            self._on_propagation_finished(_task_id, results)

    def _on_task_error(self, _task_id: str, error_msg: str):
        logger.error(
            f"GatePropagator received task_error for {_task_id}: {error_msg}. Active is {self._active_task_id}"
        )
        if _task_id == self._active_task_id:
            self._on_propagation_error(_task_id, error_msg)

    def _on_propagation_finished(self, _task_id: str, results: dict) -> None:
        """Handle successful propagation task completion."""
        self._active_task_id = None
        propagation_results = results.get("propagation_results", {})
        logger.info(f"_on_propagation_finished: {len(propagation_results)} results received.")

        # Per-sample failures are already isolated by _PropagationWorker.run()
        # (one sample erroring never aborts the others) — this only makes
        # those failures visible to the UI instead of log-only.
        errors: dict[str, str] = {}

        for sid, res in propagation_results.items():
            if "error" in res:
                errors[sid] = res["error"]
                logger.warning(f"Propagator error for {sid}: {res['error']}")
                continue

            tree = res.get("tree")
            logger.info(
                f"Propagation successful for {sid}: tree root count = {tree.statistics.get('count') if tree else 'NO TREE'}"
            )

            sample = self._state.data.experiment.samples.get(sid)
            if sample is not None:
                sample.gate_tree = res["tree"]

        for sid, res in propagation_results.items():
            if "error" not in res:
                CentralEventBus.publish(
                    events.SAMPLE_UPDATED,
                    {"sample_id": sid, "stats": res["stats"], "tree": res["tree"]},
                )

        total = len(propagation_results)
        CentralEventBus.publish(
            events.PROPAGATION_COMPLETE,
            {
                "total": total,
                "succeeded": total - len(errors),
                "failed": len(errors),
                "errors": errors,
            },
        )
        logger.debug("Gate propagation complete.")

    def _on_propagation_error(self, _task_id: str, error_msg: str) -> None:
        """Internal callback for propagation error."""
        logger.error(f"Gate propagation task failed: {error_msg}")
        CentralEventBus.publish(
            events.PROPAGATION_COMPLETE,
            {"total": 0, "succeeded": 0, "failed": 0, "errors": {}, "fatal": error_msg},
        )

    def _find_targets(self, source_id: str, state: FlowState) -> list[Sample]:
        """Find all target samples for propagation."""
        source = state.data.experiment.samples.get(source_id)
        if source is None:
            return []

        target_ids: set[str] = set()

        cross_group = getattr(self, "_cross_group_override", False)
        active_group_id = getattr(state.view, "active_group_filter", "__all__")

        if cross_group:
            for group_id in source.group_ids:
                group = state.data.experiment.groups.get(group_id)
                if group:
                    target_ids.update(group.sample_ids)
        elif active_group_id != "__all__":
            group = state.data.experiment.groups.get(active_group_id)
            if group and source_id in group.sample_ids:
                target_ids.update(group.sample_ids)
        else:
            # Propagate to all samples
            target_ids = set(state.data.experiment.samples.keys())

        target_ids.discard(source_id)

        return [
            state.data.experiment.samples[sid]
            for sid in target_ids
            if sid in state.data.experiment.samples
            and state.data.experiment.samples[sid].fcs_data is not None
        ]

    def cleanup(self) -> None:
        """Clean up resources."""
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
