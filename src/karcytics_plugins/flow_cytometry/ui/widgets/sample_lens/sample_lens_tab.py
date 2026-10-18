"""Sample Lens tab: one sample, every population, checked against a clustering.

Composition only — state lives in :class:`SampleLensModel`, each area of the
tab is its own widget:

* sidebar: sample, clustering run, gating hierarchy, audit findings
* main: the selected population's gating path (live, editable plots), the
  run's UMAP coloured by population vs by cluster, and the population across
  every sample.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from karcytics_sdk.plugin.components import (
    BioCaptionLabel,
    BioComboBox,
    BioScrollArea,
    BioStatusLabel,
    HeaderLabel,
    PrimaryButton,
    SecondaryButton,
    repopulate_combo,
)
from karcytics_sdk.plugin.theme_fallback import theme_manager
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QSplitter, QVBoxLayout, QWidget

from ....analysis.sample_lens import Finding
from ._style import Pill, card, palette_color, section_header
from .across_samples import AcrossSamples
from .findings_panel import FindingsPanel
from .gating_path import GatingPathStrip
from .lens_model import Proposal, RunRef, SampleLensModel
from .population_list import PopulationList
from .run_map import RunMap

if TYPE_CHECKING:
    from ....analysis.experiment import Sample
    from ....analysis.population_service import PopulationService
    from ....analysis.services.umap_service import UmapService
    from ....analysis.state import FlowState

SIDEBAR_WIDTH = 340
POPULATIONS_HEIGHT = 280
_RUN_SEP = "|"


def _run_data(ref: RunRef) -> str:
    # Plain strings round-trip through QComboBox item data reliably; dataclasses don't.
    return f"{ref.key}{_RUN_SEP}{ref.index}"


def _run_ref(data: str | None) -> RunRef | None:
    if not data:
        return None
    key, index = data.rsplit(_RUN_SEP, 1)
    return RunRef(key, int(index))


class SampleLensTab(QWidget):
    def __init__(  # noqa: PLR0913
        self,
        state: FlowState,
        population_service: PopulationService,
        umap_service: UmapService,
        controller: Any,
        axis_manager: Any,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("SampleLensTab")
        self._model = SampleLensModel(
            state, population_service, umap_service, controller, axis_manager
        )
        self._emphasis: tuple[int, ...] = ()
        self._proposal: Proposal | None = None

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        theme_manager.apply_style(self, "QWidget#SampleLensTab { background: {BG_DARK}; }")
        root.addWidget(self._build_sidebar())
        root.addWidget(self._build_main(state, controller, axis_manager), 1)

        self._model.changed.connect(self._render)
        self._model.run_progress.connect(self._on_run_progress)

    # ── Layout ─────────────────────────────────────────────────────────

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("lens_sidebar")
        sidebar.setFixedWidth(SIDEBAR_WIDTH)
        theme_manager.apply_style(
            sidebar,
            "QWidget#lens_sidebar { background: {BG_DARKEST}; border-right: 1px solid {BORDER}; }",
        )
        outer = QVBoxLayout(sidebar)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = BioScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        layout.addWidget(section_header("Sample"))
        self._sample_combo = BioComboBox()
        self._sample_combo.setObjectName("SampleLensSampleCombo")
        self._sample_combo.currentIndexChanged.connect(
            lambda _i: self._model.set_sample(self._sample_combo.currentData())
        )
        layout.addWidget(self._sample_combo)

        layout.addSpacing(6)
        layout.addWidget(
            section_header(
                "Clustering run",
                "The lens compares your gates with an unsupervised clustering (UMAP + HDBSCAN) "
                "of the same events. Pick an existing run, or run one on the population selected "
                "below — usually your last clean-up gate (e.g. Live singlets).",
            )
        )
        self._run_combo = BioComboBox()
        self._run_combo.setObjectName("SampleLensRunCombo")
        self._run_combo.currentIndexChanged.connect(
            lambda _i: self._model.set_run(_run_ref(self._run_combo.currentData()))
        )
        layout.addWidget(self._run_combo)
        self._run_btn = PrimaryButton("Run UMAP + clustering")
        self._run_btn.setObjectName("SampleLensRunButton")
        self._run_btn.clicked.connect(lambda: self._model.run_umap(self._model.selected_node_id))
        layout.addWidget(self._run_btn)
        self._run_status = BioStatusLabel("")
        layout.addWidget(self._run_status)

        layout.addSpacing(6)
        layout.addWidget(
            section_header(
                "Populations",
                "Click a population to see its gating path and samples. Bold populations are "
                "the final ones the lens judges; italic ones (UMAP exports, logic nodes) it "
                "leaves out.",
            )
        )
        self._populations = PopulationList()
        self._populations.setObjectName("SampleLensHierarchy")
        self._populations.setMinimumHeight(POPULATIONS_HEIGHT)
        self._populations.population_clicked.connect(self._model.select)
        layout.addWidget(self._populations)

        layout.addSpacing(6)
        layout.addWidget(
            section_header(
                "Audit findings",
                "Where your final populations and the clusters disagree. Clustering is a second "
                "opinion, not ground truth: a finding is a prompt to look. Click one to see it.",
            )
        )
        self._findings = FindingsPanel()
        self._findings.setObjectName("SampleLensFindings")
        self._findings.finding_clicked.connect(self._on_finding_clicked)
        self._findings.fix_requested.connect(self._on_fix_requested)
        layout.addWidget(self._findings)
        layout.addStretch()

        scroll.setWidget(content)
        outer.addWidget(scroll)
        return sidebar

    def _build_main(self, state: FlowState, controller: Any, axis_manager: Any) -> QWidget:
        main = QWidget()
        layout = QVBoxLayout(main)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)
        layout.addWidget(HeaderLabel("Sample Lens"))
        self._scope_caption = BioCaptionLabel("")
        self._scope_caption.setObjectName("SampleLensScope")
        layout.addWidget(self._scope_caption)

        layout.addWidget(self._build_proposal_bar())
        self._path = GatingPathStrip(state, controller, axis_manager)
        self._path.setObjectName("SampleLensPath")
        layout.addWidget(self._path)

        lower = QSplitter(Qt.Orientation.Horizontal)
        self._map = RunMap()
        self._map.setObjectName("SampleLensMap")
        self._map.cluster_clicked.connect(self._on_cluster_clicked)
        lower.addWidget(self._map)
        self._across = AcrossSamples()
        self._across.setObjectName("SampleLensAcross")
        lower.addWidget(self._across)
        lower.setStretchFactor(0, 1)
        lower.setStretchFactor(1, 1)
        layout.addWidget(lower, 1)
        return main

    def _build_proposal_bar(self) -> QWidget:
        self._proposal_bar = card("lens_proposal_bar", "BG_MEDIUM")
        row = QHBoxLayout(self._proposal_bar)
        row.setContentsMargins(12, 8, 12, 8)
        row.setSpacing(8)
        self._proposal_pills = [Pill(), Pill(tone="accent"), Pill(), Pill()]
        for pill in self._proposal_pills:
            row.addWidget(pill)
        row.addStretch()
        cancel = SecondaryButton("Cancel")
        cancel.clicked.connect(self._close_proposal)
        row.addWidget(cancel)
        self._accept_btn = PrimaryButton("Add gates to tree")
        self._accept_btn.setObjectName("SampleLensAcceptProposal")
        self._accept_btn.clicked.connect(self._accept_proposal)
        row.addWidget(self._accept_btn)
        self._proposal_bar.hide()
        return self._proposal_bar

    # ── Lifecycle ──────────────────────────────────────────────────────

    def showEvent(self, event: Any) -> None:  # noqa: N802 - Qt override
        super().showEvent(event)
        self._populate_samples()
        self._model.set_active(True)

    def hideEvent(self, event: Any) -> None:  # noqa: N802 - Qt override
        self._model.set_active(False)
        super().hideEvent(event)

    def _populate_samples(self) -> None:
        samples = self._model.samples()
        current = self._model.sample_id or self._model.default_sample_id()
        repopulate_combo(
            self._sample_combo,
            [(s.display_name, s.sample_id) for s in samples],
            restore_data=current,
        )
        self._model.set_sample(self._sample_combo.currentData())

    # ── Rendering ──────────────────────────────────────────────────────

    def _render(self) -> None:
        model = self._model
        sample = model.sample

        runs = model.runs()
        repopulate_combo(
            self._run_combo,
            [
                (ref.label(run, model.population_name(run.get("node_id"))), _run_data(ref))
                for ref, run in runs
            ],
            restore_data=_run_data(model.run_ref) if model.run_ref else None,
        )
        self._run_btn.setText(
            f"Run UMAP + clustering on {model.population_name(model.selected_node_id)}"
        )
        self._run_btn.setEnabled(sample is not None)

        scope = model.scope
        colors = (
            {p.path: palette_color(i) for i, p in enumerate(scope.final_populations)}
            if scope
            else {}
        )
        selected_path = model.selected_path()
        color = colors.get(selected_path or "", palette_color(0))

        self._populations.show_populations(
            sample,
            {p.path for p in scope.final_populations} if scope else set(),
            model.selected_node_id,
        )
        self._scope_caption.setText(self._scope_text())
        self._findings.show_findings(model.findings, *self._empty_findings_text())
        if self._proposal is not None and self._proposal.sample_id != model.sample_id:
            self._proposal = None  # proposed for another sample
        self._proposal_bar.setVisible(self._proposal is not None)
        if self._proposal is not None and sample is not None:
            self._show_proposal(sample, self._proposal)
        else:
            events = model.events(sample) if sample is not None else None
            self._path.show_population(
                sample,
                events,
                model.node(model.selected_node_id) if model.selected_node_id else None,
                color,
            )
        self._map.show_scope(scope, colors, selected_path, model.findings, self._emphasis)
        name = model.population_name(model.selected_node_id) if model.selected_node_id else None
        self._across.show_checks(name, model.checks, model.sample_id)

    def _scope_text(self) -> str:
        model, scope = self._model, self._model.scope
        if model.sample is None:
            return "Load samples in the Workspace tab to use the lens."
        if scope is None:
            return (
                "No clustering run for this sample yet. Backgating and Across samples work "
                "without one: click a population. For audit findings, select the population to "
                "cluster (usually your clean-up gate) and press “Run UMAP + clustering”."
            )
        population = model.population_name(scope.run.get("node_id"))
        return (
            f"Judging {len(scope.final_populations)} final populations on {scope.n:,} events of "
            f"{population} ({model.sample.display_name}), sampled by the selected run."
        )

    def _empty_findings_text(self) -> tuple[str, str]:
        scope = self._model.scope
        if scope is None:
            return (
                "No run yet",
                "Findings need a clustering run. Backgating and Across samples work without one.",
            )
        if not scope.has_clusters:
            return (
                "No clusters",
                "This run was made without clustering; run one with the button above.",
            )
        return "No disagreements", "Every cluster maps cleanly onto your final populations."

    # ── Handlers ───────────────────────────────────────────────────────

    def _on_finding_clicked(self, finding: Finding) -> None:
        self._emphasis = finding.clusters
        node = self._model.node_for_path(finding.population) if finding.population else None
        if node is not None:
            self._model.select(node.node_id)  # re-renders
        else:
            self._render()

    def _on_cluster_clicked(self, cluster: int) -> None:
        self._emphasis = (cluster,)
        self._render()

    def _show_proposal(self, sample: Sample, proposal: Proposal) -> None:
        steps = proposal.steps
        if not steps:
            texts = ["No gates found", "", "", ""]
        else:
            last = steps[-1]
            texts = [
                f"{len(steps)} gate{'s' if len(steps) > 1 else ''}",
                f"F1 {last.f1:.2f}",
                f"Precision {last.precision:.0%}",
                f"Recall {last.recall:.0%}",
            ]
        for pill, text in zip(self._proposal_pills, texts, strict=True):
            pill.setText(text)
            pill.setVisible(bool(text))
        self._accept_btn.setEnabled(bool(steps))
        events = self._model.events(sample)
        if events is not None:
            self._path.show_proposal(sample, events, proposal, palette_color(proposal.cluster))

    def _on_fix_requested(self, finding: Finding) -> None:
        self._emphasis = finding.clusters
        self._proposal = self._model.propose(finding.clusters[0])
        self._render()

    def _accept_proposal(self) -> None:
        proposal, self._proposal = self._proposal, None
        if proposal is not None:
            self._model.add_proposal(proposal)  # re-renders

    def _close_proposal(self) -> None:
        self._proposal = None
        self._render()

    def _on_run_progress(self, running: bool, text: str) -> None:
        self._run_btn.setEnabled(not running)
        self._run_status.setText(text)
