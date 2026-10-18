"""Clustering run service — schedules UMAP + HDBSCAN and FlowSOM runs (one at a time)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from karcytics_sdk.plugin import get_logger

from ..flowsom_analysis import FlowsomAnalysis
from ..umap_analysis import UmapAnalysis

if TYPE_CHECKING:
    from karcytics_sdk.plugin import AnalysisBase, AnalysisWorker

    from ..state import FlowState

logger = get_logger(__name__, "flow_cytometry")


@dataclass
class UmapParams:
    """Parameters for UMAP dimensionality reduction."""

    target_sample_id: str
    target_node_id: str | None = None  # None = All Events (no gate filter)
    name: str = ""
    percentage: float = 10.0
    n_neighbors: int = 15
    min_dist: float = 0.1
    n_events: int = 10000
    metric: str = "euclidean"
    random_seed: int = 42
    run_hdbscan: bool = False
    hdbscan_space: str = "high_dim"
    min_cluster_size: int = 100
    channels: list[str] | None = None


@dataclass
class FlowsomParams:
    """Parameters for a FlowSOM run."""

    target_sample_id: str
    target_node_id: str | None = None  # None = All Events (no gate filter)
    name: str = ""
    percentage: float = 100.0
    n_events: int = 0
    xdim: int = 10
    ydim: int = 10
    k: int = 10
    passes: int = 10
    random_seed: int = 42
    channels: list[str] | None = None


class UmapService:
    """Facade for submitting and managing background UMAP tasks using TaskScheduler."""

    def __init__(self, state: FlowState, scheduler: Any):
        self._state = state
        self._scheduler = scheduler
        self._current_worker: AnalysisWorker | None = None
        self._current_task_id: str | None = None

    def run_analysis(
        self,
        params: UmapParams,
        on_done: Callable[[dict], None],
        on_error_cb: Callable[[str], None],
        on_progress: Callable[[int], None] | None = None,
    ) -> None:
        """Cancel any in-flight task, and submit a new UMAP analysis."""
        analyzer = UmapAnalysis()
        analyzer.target_sample_id = params.target_sample_id
        analyzer.target_node_id = params.target_node_id
        analyzer.name = params.name
        analyzer.percentage = params.percentage
        analyzer.n_neighbors = params.n_neighbors
        analyzer.min_dist = params.min_dist
        analyzer.n_events = params.n_events
        analyzer.metric = params.metric
        analyzer.random_seed = params.random_seed
        analyzer.run_hdbscan = params.run_hdbscan
        analyzer.hdbscan_space = params.hdbscan_space
        analyzer.min_cluster_size = params.min_cluster_size
        analyzer.channels = params.channels or []
        self._submit(analyzer, on_done, on_error_cb, on_progress)

    def run_flowsom(
        self,
        params: FlowsomParams,
        on_done: Callable[[dict], None],
        on_error_cb: Callable[[str], None],
        on_progress: Callable[[int], None] | None = None,
    ) -> None:
        """Cancel any in-flight task, and submit a new FlowSOM run."""
        analyzer = FlowsomAnalysis()
        for name, value in vars(params).items():
            setattr(analyzer, name, value)
        analyzer.channels = params.channels or []
        self._submit(analyzer, on_done, on_error_cb, on_progress)

    def _submit(  # noqa: C901
        self,
        analyzer: AnalysisBase,
        on_done: Callable[[dict], None],
        on_error_cb: Callable[[str], None],
        on_progress: Callable[[int], None] | None,
    ) -> None:
        self.cancel()
        try:
            worker = self._scheduler.submit(analyzer, self._state)
            self._current_worker = worker
            task_id = worker.task_id
            self._current_task_id = task_id

            logger.info(
                f"UmapService: Submitted {type(analyzer).__name__} task {self._current_task_id}"
            )

            # Connect signals
            if on_progress:
                worker.progress.connect(on_progress)

            def _on_finished(finished_task_id: str, results: dict):
                if finished_task_id == self._current_task_id:
                    self._current_worker = None
                    self._current_task_id = None
                    try:
                        self._scheduler.task_finished.disconnect(_on_finished)
                        worker.cancelled.disconnect(_on_cancelled)
                    except (TypeError, RuntimeError):
                        pass
                    on_done(results)

            def _on_error(error_task_id: str, error_msg: str):
                if error_task_id == self._current_task_id:
                    self._current_worker = None
                    self._current_task_id = None
                    try:
                        self._scheduler.task_error.disconnect(_on_error)
                        worker.cancelled.disconnect(_on_cancelled)
                    except (TypeError, RuntimeError):
                        pass
                    on_error_cb(error_msg)

            def _on_cancelled():
                if self._current_worker is worker:
                    self._current_worker = None
                    self._current_task_id = None

            self._scheduler.task_finished.connect(_on_finished)
            self._scheduler.task_error.connect(_on_error)
            worker.cancelled.connect(_on_cancelled)

        except Exception as e:
            logger.exception(f"UmapService: Failed to submit task: {e}")
            on_error_cb(str(e))

    def cancel(self) -> None:
        """Cancel any active UMAP task."""
        if self._current_worker:
            logger.info(f"UmapService: Cancelling active task {self._current_task_id}")
            try:
                self._current_worker.cancel()
            except Exception as e:
                logger.error(f"Error during worker cancellation: {e}")
            self._current_worker = None
            self._current_task_id = None
