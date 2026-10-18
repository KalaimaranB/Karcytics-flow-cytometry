"""State behind the Sample Lens tab: which sample, which run, which population.

Widgets read from here and call its commands; they never compute anything
themselves. Any gate change anywhere in the app (drawn, dragged, propagated,
renamed, deleted) triggers one debounced refresh, so the lens always reflects
the current gates.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

import numpy as np
from karcytics_sdk.plugin import CentralEventBus, get_logger
from karcytics_sdk.plugin.timing import Debouncer
from PySide6.QtCore import QObject, Signal

from ....analysis import events as flow_events
from ....analysis.clustering import method_of
from ....analysis.flowsom_analysis import recut_run
from ....analysis.population_matching import populations
from ....analysis.sample_lens import (
    Finding,
    ProposedGate,
    RunScope,
    SampleCheck,
    audit,
    build_scope,
    check_across,
    propose_gates,
)
from ....analysis.sample_lens.synthesis import match_scores
from ....analysis.services import experiment_edits
from ....analysis.services.umap_service import UmapParams

if TYPE_CHECKING:
    import pandas as pd

    from ....analysis.experiment import Sample
    from ....analysis.gating import GateNode
    from ....analysis.population_service import PopulationService
    from ....analysis.services.umap_service import UmapService
    from ....analysis.state import FlowState

logger = get_logger(__name__, "flow_cytometry")

REFRESH_MS = 250
RUN_NAME = "Sample Lens"
_GATE_TOPICS = (
    flow_events.GATE_CREATED,
    flow_events.GATES_CREATED,
    flow_events.GATE_MODIFIED,
    flow_events.GATE_DELETED,
    flow_events.GATE_RENAMED,
    flow_events.PROPAGATION_COMPLETE,
    flow_events.SAMPLE_LOADED,
    flow_events.STATE_RESTORED,
    flow_events.UMAP_COMPLETED,
)


@dataclass(frozen=True)
class RunRef:
    key: str  # "sample::node" in state.data.umap_results
    index: int

    def label(self, run: dict[str, Any], population: str) -> str:
        name = run.get("name") or f"Run {self.index + 1}"
        method = method_of(run)
        if method.recuttable:
            name += f" · {method.name} k={run.get('k')}"
        clusters = "" if run.get("clusters") is not None else " · no clusters"
        return f"{name} · {population} · {len(run.get('indices', [])):,} events{clusters}"


@dataclass(frozen=True)
class Proposal:
    """Gates proposed for one cluster of the current run."""

    sample_id: str
    clusters: tuple[int, ...]
    label: str  # the clusters in a sentence ("cluster 3", "metaclusters M1 and M8")
    events: pd.DataFrame  # the run's events
    target: np.ndarray  # which of them are the cluster
    steps: list[ProposedGate]  # a chain: each gate is meant as the previous one's child
    left_out: frozenset[int] = frozenset()  # steps the user unticked

    def kept(self, i: int) -> bool:
        return i not in self.left_out

    def toggled(self, i: int, keep: bool) -> Proposal:
        return replace(self, left_out=self.left_out - {i} if keep else self.left_out | {i})

    @property
    def chosen(self) -> list[ProposedGate]:
        return [step for i, step in enumerate(self.steps) if self.kept(i)]

    def walk(self) -> list[tuple[np.ndarray, tuple[float, float, float] | None]]:
        """Per step: the events the kept steps above it leave, and its scores.

        The scores (F1, precision, recall) are of the kept gates down to that
        step; a step that was left out has none.
        """
        out = []
        current = np.ones(len(self.events), dtype=bool)
        for i, step in enumerate(self.steps):
            before, scores = current, None
            if self.kept(i):
                current = current & step.gate.contains(self.events)
                scores = match_scores(current, self.target)
            out.append((before, scores))
        return out


SCATTER_CHANNELS = ("FSC-A", "SSC-A")


class SampleLensModel(QObject):
    """Everything the lens shows, kept current."""

    changed = Signal()  # sample, run, populations, findings or checks changed
    run_progress = Signal(bool, str)  # running, status text
    _run_finished = Signal(object)  # results dict, delivered on this object's thread

    def __init__(
        self,
        state: FlowState,
        population_service: PopulationService,
        umap_service: UmapService,
        controller: Any,
        axis_manager: Any,
    ) -> None:
        super().__init__()
        self._state = state
        self._population_service = population_service
        self._umap_service = umap_service
        self._controller = controller
        self._axis_manager = axis_manager

        self.sample_id: str | None = None
        self.run_ref: RunRef | None = None
        self.selected_node_id: str | None = None
        self.scope: RunScope | None = None
        self.findings: list[Finding] = []
        self.checks: list[SampleCheck] = []
        self._chosen_runs: dict[str, RunRef] = {}  # sample -> run picked for it

        self._active = False
        self._debouncer = Debouncer(self.refresh)
        self._run_finished.connect(self._on_run_finished)
        self._on_gates_changed = lambda _data=None: self._schedule()
        for topic in _GATE_TOPICS:
            CentralEventBus.subscribe(topic, self._on_gates_changed)
        self.destroyed.connect(self._cleanup)

    def _cleanup(self) -> None:
        for topic in _GATE_TOPICS:
            CentralEventBus.unsubscribe(topic, self._on_gates_changed)

    # ── Queries ────────────────────────────────────────────────────────

    def samples(self) -> list[Sample]:
        return [s for s in self._state.data.experiment.samples.values() if s.has_data]

    def default_sample_id(self) -> str | None:
        """The sample the rest of the app is on, to open the lens on."""
        return self._state.view.current_sample_id

    @property
    def sample(self) -> Sample | None:
        return self._state.data.experiment.samples.get(self.sample_id or "")

    def events(self, sample: Sample) -> pd.DataFrame | None:
        """The sample's root events, with derived columns synced."""
        return self._population_service.get_gated_events(sample.sample_id)

    def runs(self) -> list[tuple[RunRef, dict[str, Any]]]:
        """UMAP runs of the current sample, oldest first."""
        prefix = f"{self.sample_id}::"
        return [
            (RunRef(key, i), run)
            for key, runs in self._state.data.umap_results.items()
            if key.startswith(prefix)
            for i, run in enumerate(runs)
        ]

    @property
    def run(self) -> dict[str, Any] | None:
        if self.run_ref is None:
            return None
        runs = self._state.data.umap_results.get(self.run_ref.key, [])
        return runs[self.run_ref.index] if self.run_ref.index < len(runs) else None

    def population_name(self, node_id: str | None) -> str:
        node = self.node(node_id)
        return node.name if node is not None and node_id else "All Events"

    def node(self, node_id: str | None) -> GateNode | None:
        sample = self.sample
        if sample is None:
            return None
        return sample.gate_tree.find_node_by_id(node_id) if node_id else sample.gate_tree

    def selected_path(self) -> str | None:
        sample = self.sample
        if sample is None or self.selected_node_id is None:
            return None
        return next(
            (path for path, node in populations(sample) if node.node_id == self.selected_node_id),
            None,
        )

    def node_for_path(self, path: str) -> GateNode | None:
        sample = self.sample
        return dict(populations(sample)).get(path) if sample is not None else None

    # ── Commands ───────────────────────────────────────────────────────

    def set_active(self, active: bool) -> None:
        """Only compute while the tab is visible; catch up when it is shown."""
        self._active = active
        if active:
            self.refresh()

    def set_sample(self, sample_id: str | None) -> None:
        if sample_id == self.sample_id:
            return
        self.sample_id = sample_id
        self.selected_node_id = None
        runs = self.runs()
        chosen = self._chosen_runs.get(sample_id or "")
        if chosen is not None and any(ref == chosen for ref, _ in runs):
            self.run_ref = chosen  # back to the run picked for this sample before
        else:
            clustered = [ref for ref, run in runs if run.get("clusters") is not None]
            candidates = clustered or [ref for ref, _ in runs]
            self.run_ref = candidates[-1] if candidates else None
        self.refresh()

    def set_run(self, ref: RunRef | None) -> None:
        self.run_ref = ref
        if self.sample_id is not None and ref is not None:
            self._chosen_runs[self.sample_id] = ref
        self.refresh()

    def select(self, node_id: str | None) -> None:
        self.selected_node_id = node_id
        self.refresh()

    def recut(self, k: int) -> None:
        """Re-cut the current run (FlowSOM) into ``k`` metaclusters and re-audit."""
        run = self.run
        if run is None or not method_of(run).recuttable or run.get("k") == k:
            return
        recut_run(run, k)
        experiment_edits.announce_unsaved_change()
        self.refresh()

    def run_umap(self, node_id: str | None) -> None:
        """UMAP + HDBSCAN on ``node_id``'s population of the current sample."""
        if self.sample_id is None:
            return
        params = UmapParams(
            target_sample_id=self.sample_id,
            target_node_id=node_id,
            name=RUN_NAME,
            run_hdbscan=True,
        )
        self.run_progress.emit(
            True, f"Running UMAP + clustering on {self.population_name(node_id)}…"
        )
        self._umap_service.run_analysis(
            params,
            on_done=self._run_finished.emit,
            on_error_cb=lambda msg: self._run_finished.emit({"error": msg}),
        )

    def propose(self, clusters: tuple[int, ...]) -> Proposal | None:
        """Rectangle gates on the run's channels (+ scatter) that recover ``clusters``."""
        sample, scope = self.sample, self.scope
        events = self.events(sample) if sample is not None else None
        if sample is None or scope is None or scope.clusters is None or events is None:
            return None
        run_events = events.iloc[scope.rows]
        # The channels the run clustered on (older runs don't say: then all of them).
        markers = scope.run.get("channels") or list(run_events.columns)
        channels = [ch for ch in [*SCATTER_CHANNELS, *markers] if ch in run_events.columns]
        scales = {
            ch: self._axis_manager.get_scale(ch, sample.sample_id) for ch in dict.fromkeys(channels)
        }
        target = np.isin(scope.clusters, clusters)
        steps = propose_gates(run_events, target, scales) if len(scales) >= 2 else []  # noqa: PLR2004
        label = method_of(scope.run).clusters_label(clusters)
        return Proposal(sample.sample_id, clusters, label, run_events, target, steps)

    def add_proposal(self, proposal: Proposal) -> None:
        """Add the kept steps of the chain to the tree, under the run's population."""
        parent_id = self.scope.run.get("node_id") if self.scope is not None else None
        chosen = proposal.chosen
        last = len(chosen) - 1
        label = proposal.label[:1].upper() + proposal.label[1:]
        for i, step in enumerate(chosen):
            name = label if i == last else f"{label} · pre-gate {i + 1}"
            parent_id = self._controller.add_gate(
                step.gate, proposal.sample_id, name=name, parent_node_id=parent_id
            )
            if parent_id is None:
                logger.warning("Sample Lens: adding proposed gate %d failed", i + 1)
                break
        self.selected_node_id = parent_id
        self.refresh()

    def _on_run_finished(self, results: dict[str, Any]) -> None:
        if "error" in results:
            self.run_progress.emit(False, f"UMAP failed: {results['error']}")
            return
        key = experiment_edits.add_umap_run(self._state, results)
        self.run_progress.emit(False, "")
        self.set_run(RunRef(key, len(self._state.data.umap_results[key]) - 1))

    def _schedule(self) -> None:
        if self._active:
            self._debouncer.trigger(REFRESH_MS)

    def refresh(self) -> None:
        """Recompute the scope, findings and cross-sample checks from current state."""
        self.scope, self.findings, self.checks = None, [], []
        sample = self.sample
        events = self.events(sample) if sample is not None else None
        run = self.run
        if sample is not None and events is not None and run is not None:
            try:
                self.scope = build_scope(sample, run, events)
                self.findings = audit(self.scope)
            except (KeyError, ValueError) as exc:  # e.g. a gate on a channel this sample lacks
                logger.warning("Sample Lens: can't evaluate run on %s: %s", sample.sample_id, exc)
        path = self.selected_path()
        if path is not None:
            self.checks = check_across(self._sample_events(), path)
        self.changed.emit()

    def _sample_events(self) -> list[tuple[Sample, pd.DataFrame]]:
        """The samples to compare across: controls are left out, unless one is open."""
        pairs = []
        for sample in self.samples():
            if sample.role.is_control and sample.sample_id != self.sample_id:
                continue
            events = self.events(sample)
            if events is not None:
                pairs.append((sample, events))
        return pairs
