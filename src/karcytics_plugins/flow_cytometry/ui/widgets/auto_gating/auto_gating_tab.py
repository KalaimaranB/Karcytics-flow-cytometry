"""Auto Gating tab: split a population into ordinary gates, one transparent step at a time.

Composition only. The sidebar holds the user's choices, the pages draw what
the engine returns, and the gating tree reads the sample's real tree. The tab
turns choices into a ``StepRequest``, hands it to the engine, and hands an
accepted proposal to the committer; it knows nothing about how a split is found.

* sidebar: group, reference sample, population, channels, method, stopping rules
* main: Build | Why this gate | Apply to group | Compare methods
* right: the gating tree, with a proposal's populations dashed under their parent
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

from karcytics_sdk.plugin.components import BioScrollArea, HeaderLabel
from karcytics_sdk.plugin.theme_fallback import theme_manager
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QHBoxLayout, QTabWidget, QVBoxLayout, QWidget

from ....analysis.autogate import StepRequest, method
from ....analysis.fcs_io import (
    get_channel_marker_label,
    get_fluorescence_channels,
    get_scatter_channels,
)
from .apply_page import ApplyPage
from .build_page import BuildPage
from .compare_page import ComparePage
from .gating_tree import GatingTreePanel, population_items
from .setup_sidebar import SetupSidebar
from .why_panel import WhyPanel

if TYPE_CHECKING:
    from collections.abc import Generator

    from ....analysis.autogate import AutoGateEngine, ProposalCommitter
    from ....analysis.autogate.models import MethodOutcome, Proposal
    from ....analysis.experiment import Sample
    from ....analysis.state import FlowState

ALL_SAMPLES = "all"
BUILD, WHY, APPLY, COMPARE = range(4)
_TABS_QSS = (
    "QTabWidget { background: transparent; }"
    " QTabWidget::pane { border: 1px solid {BORDER}; border-radius: 4px; background: {BG_DARK}; }"
    " QTabBar::tab { background: {BG_MEDIUM}; color: {FG_SECONDARY}; padding: 8px 16px;"
    " border: 1px solid {BORDER}; border-bottom: none; border-top-left-radius: 4px;"
    " border-top-right-radius: 4px; margin-right: 2px; }"
    " QTabBar::tab:selected { background: {BG_DARK}; color: {FG_PRIMARY}; font-weight: bold; }"
    " QTabBar::tab:hover:!selected { background: {BG_LIGHT}; }"
)


def _padded(page: QWidget) -> QWidget:
    host = QWidget()
    layout = QVBoxLayout(host)
    layout.setContentsMargins(12, 0, 12, 12)
    layout.addWidget(page)
    return host


@contextmanager
def _busy() -> Generator[None]:
    QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    try:
        yield
    finally:
        QGuiApplication.restoreOverrideCursor()


class AutoGatingTab(QWidget):
    open_tab_requested = Signal(object)  # MainTab

    def __init__(
        self,
        state: FlowState,
        engine: AutoGateEngine,
        committer: ProposalCommitter,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("AutoGatingTab")
        self._state = state
        self._engine = engine
        self._committer = committer
        self._proposal: Proposal | None = None
        self._view_rank = 0
        self._stale_pages: set[int] = set()  # pages to recompute when next shown

        # Everything sits in a scroll area. The centre stack is as wide as its
        # widest page's minimum, even while that page is hidden, so this tab
        # must not demand more than the others: when the window is narrower
        # than its content, only this tab scrolls.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = BioScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        content.setObjectName("AutoGatingContent")
        theme_manager.apply_style(content, "QWidget#AutoGatingContent { background: {BG_DARK}; }")
        root = QHBoxLayout(content)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        scroll.setWidget(content)
        outer.addWidget(scroll)
        theme_manager.apply_style(self, "QWidget#AutoGatingTab { background: {BG_DARK}; }")

        self._sidebar = SetupSidebar()
        root.addWidget(self._sidebar)
        root.addWidget(self._build_main(), 1)
        self._tree = GatingTreePanel(state)
        self._tree.population_clicked.connect(self._on_population_clicked)
        self._tree.open_tab_requested.connect(self.open_tab_requested)
        root.addWidget(self._tree)

        self._sidebar.group_changed.connect(self._on_group_changed)
        self._sidebar.sample_changed.connect(self._on_sample_changed)
        self._sidebar.choices_changed.connect(self._on_choices_changed)
        self._sidebar.propose_clicked.connect(self._on_propose)

    def _build_main(self) -> QWidget:
        main = QWidget()
        layout = QVBoxLayout(main)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)
        layout.addWidget(HeaderLabel("Auto Gating"))
        self._tabs = QTabWidget()
        self._tabs.setObjectName("AutoGateTabs")
        tab_bar = self._tabs.tabBar()
        if tab_bar is not None:
            tab_bar.setObjectName("AutoGateTabBar")
        theme_manager.apply_style(self._tabs, _TABS_QSS)
        self._build = BuildPage()
        self._build.accept_clicked.connect(self._on_accept)
        self._build.next_view_clicked.connect(self._on_next_view)
        self._build.reject_clicked.connect(self._on_reject)
        self._why = WhyPanel()
        self._apply = ApplyPage()
        self._compare = ComparePage()
        self._compare.use_clicked.connect(self._on_use_method)
        for page, title in (
            (self._build, "Build"),
            (self._why, "Why this gate"),
            (self._apply, "Apply to group"),
            (self._compare, "Compare methods"),
        ):
            self._tabs.addTab(_padded(page), title)
        self._tabs.currentChanged.connect(self._refresh_page)
        layout.addWidget(self._tabs, 1)
        return main

    # ── The experiment ────────────────────────────────────────────────

    def _group_samples(self) -> list[Sample]:
        exp = self._state.data.experiment
        group_id = self._sidebar.group_id()
        group = exp.groups.get(group_id) if group_id not in (None, ALL_SAMPLES) else None
        ids = group.sample_ids if group is not None else list(exp.samples)
        return [exp.samples[sid] for sid in ids if sid in exp.samples]

    def _reference_sample(self) -> Sample | None:
        return self._state.data.experiment.samples.get(self._sidebar.sample_id())

    def _group_name(self) -> str:
        group = self._state.data.experiment.groups.get(self._sidebar.group_id())
        return group.name if group is not None else "All samples"

    def refresh_samples(self) -> None:
        """Fill the sidebar from the experiment; called whenever the tab is shown."""
        groups = [
            (f"{g.name} · {g.size} samples", gid)
            for gid, g in self._state.data.experiment.groups.items()
        ]
        self._sidebar.set_groups(groups or [("All samples", ALL_SAMPLES)])
        self._on_group_changed()

    def _on_group_changed(self) -> None:
        samples = sorted(self._group_samples(), key=lambda s: s.role.is_control)  # panels first
        self._sidebar.set_samples([(s.display_name, s.sample_id) for s in samples])
        self._on_sample_changed()

    def _on_sample_changed(self) -> None:
        sample = self._reference_sample()
        self._sidebar.set_populations(population_items(sample))
        fcs = sample.fcs_data if sample is not None else None
        scatter = get_scatter_channels(fcs) if fcs else []
        markers = get_fluorescence_channels(fcs) if fcs else []
        channels = (
            [(get_channel_marker_label(fcs, ch), ch) for ch in scatter + markers] if fcs else []
        )
        self._sidebar.set_channels(channels, start_unticked=frozenset(scatter))
        self._on_choices_changed()

    # ── Requests ──────────────────────────────────────────────────────

    def _request(self) -> StepRequest:
        node_id, _name = self._sidebar.population()
        key = self._sidebar.method_key()
        x, y = self._sidebar.axes() if method(key).user_picks_axes else ("", "")
        min_events, min_valley = self._sidebar.stopping_rules()
        return StepRequest(
            method_key=key,
            sample_id=self._sidebar.sample_id() or "",
            node_id=node_id,
            channels=self._sidebar.channels(),
            group=tuple(s.sample_id for s in self._group_samples()),
            x_channel=x,
            y_channel=y,
            view_rank=self._view_rank,
            min_events=min_events,
            min_valley=min_valley,
        )

    def _on_choices_changed(self) -> None:
        self._view_rank = 0
        if self._proposal is not None:
            self._propose()  # keep showing a proposal for what is now picked
        else:
            self._show(None)

    def _on_propose(self) -> None:
        self._view_rank = 0
        self._propose()

    def _propose(self) -> None:
        with _busy():
            result = self._engine.propose(self._request())
        if isinstance(result, str):
            self._show(None, result)
        else:
            self._show(result)

    def _show(self, proposal: Proposal | None, message: str = "") -> None:
        self._proposal = proposal
        self._build.show_proposal(proposal, message)
        self._show_tree()
        self._stale_pages = {APPLY, COMPARE}
        self._refresh_page(self._tabs.currentIndex())

    def _show_tree(self) -> None:
        node_id, _name = self._sidebar.population()
        proposal = self._proposal
        regions = tuple(r for r in proposal.plot.regions if r.is_main) if proposal else ()
        events = proposal.n_events if proposal else 0
        self._tree.show_tree(self._reference_sample(), node_id, regions, node_id, events)

    def _refresh_page(self, index: int) -> None:
        """Recompute the Apply or Compare page if it is showing and out of date."""
        if index not in self._stale_pages:
            return
        self._stale_pages.discard(index)
        if index == APPLY:
            preview = None
            if self._proposal is not None:
                with _busy():
                    preview = self._engine.preview_group(self._proposal, self._request())
            self._apply.show_preview(preview, self._group_name())
        elif index == COMPARE:
            request = self._request()
            _node, name = self._sidebar.population()
            outcomes: tuple[MethodOutcome, ...] = ()
            if request.sample_id and len(request.channels) > 1:
                with _busy():
                    outcomes = self._engine.compare(request)
            self._compare.show_outcomes(outcomes, name)

    # ── Actions ───────────────────────────────────────────────────────

    def _on_accept(self) -> None:
        proposal = self._proposal
        if proposal is None:
            return
        with _busy():
            added = self._committer.accept(proposal)
        names = ", ".join(r.name for r in proposal.gated)
        self._proposal = None
        self._sidebar.set_populations(population_items(self._reference_sample()))
        self._show(None, "Added. Click a population in the tree to split it next.")
        self._build.show_status(
            f"Added {len(added)} gate{'s' if len(added) != 1 else ''} under {proposal.parent}: {names}. "
            f"They go to every sample in {self._group_name()}, and undo works as usual."
        )

    def _on_next_view(self) -> None:
        self._view_rank += 1
        self._propose()

    def _on_reject(self) -> None:
        self._show(None, "Rejected. Nothing was added.")

    def _on_use_method(self, key: str) -> None:
        self._sidebar.set_method(key)
        self._tabs.setCurrentIndex(BUILD)
        self._on_propose()

    def _on_population_clicked(self, node_id: str | None) -> None:
        """A population picked in the tree: split it next, and show why it is there."""
        sample = self._reference_sample()
        self._sidebar.set_population(node_id)  # re-proposes if a proposal was showing
        if sample is None or node_id is None:
            self._why.show_story(None)
            return
        node = sample.gate_tree.find_node_by_id(node_id)
        story = self._engine.story(sample.sample_id, node_id)
        self._why.show_story(story, node.name if node is not None else "")
        if self._proposal is None:
            self._show_tree()
