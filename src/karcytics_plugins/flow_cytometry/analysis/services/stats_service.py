"""Service for managing background statistics computation."""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from typing import TYPE_CHECKING

from karcytics_sdk.plugin import get_logger
from karcytics_sdk.plugin.runtime_services import task_scheduler

from ..statistics_analysis import StatisticsAnalysis

if TYPE_CHECKING:
    from ..state import FlowState

logger = get_logger(__name__, "flow_cytometry")


class StatsService:
    """Handles submission and application of population statistics."""

    @staticmethod
    def recompute_all_stats(
        state: FlowState,
        sample_id: str,
        callback: Callable | None = None,
        node_ids: list[str] | None = None,
    ) -> str | None:
        """Submit a background task to recompute gate statistics for a sample.

        Args:
            state: The FlowState.
            sample_id: Target sample ID.
            callback: Called with the task's result dict when it finishes.
            node_ids: When given, scopes recompute to just these nodes and
                their descendants (see `DagEvaluator.evaluate_scoped`)
                instead of the whole tree.
        """
        sample = state.data.experiment.samples.get(sample_id)
        if sample is None:
            logger.warning(f"StatsService: sample {sample_id} not found")
            return None
        if sample.fcs_data is None:
            logger.warning(f"StatsService: sample {sample_id} has no FCS data")
            return None

        analyzer = StatisticsAnalysis()
        analyzer.target_sample_id = sample_id
        analyzer.target_node_ids = node_ids

        worker = task_scheduler.submit(analyzer, state)
        task_id = getattr(worker, "task_id", "")
        logger.info(f"StatsService: submitted task {task_id} for sample {sample_id}")

        if callback:
            # Use task_scheduler.task_finished so we get the callback AFTER
            # the scheduler's own _on_task_finished fires and before cleanup
            # disconnects worker.finished.
            def _on_finished(finished_task_id: str, results: dict):
                if finished_task_id == task_id:
                    with contextlib.suppress(TypeError, RuntimeError):
                        task_scheduler.task_finished.disconnect(_on_finished)
                    callback(results)

            task_scheduler.task_finished.connect(_on_finished)

        return task_id
