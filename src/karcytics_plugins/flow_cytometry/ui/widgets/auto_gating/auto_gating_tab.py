"""Auto Gating tab: split a population into ordinary gates, one transparent step at a time.

Composition only. The sidebar holds the user's choices, the pages draw what
the engine returns, and the gating tree reads the sample's real tree. The
tab turns choices into a ``StepRequest`` and hands it to the engine; it
knows nothing about how a split is found.

* sidebar: group, reference sample, population, channels, method, stopping rules
* main: Build | Why this gate | Apply to group | Compare methods
* right: the gating tree, with a proposal's populations under their parent
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from karcytics_sdk.plugin.components import HeaderLabel
from karcytics_sdk.plugin.theme_fallback import theme_manager
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QTabWidget, QVBoxLayout, QWidget

from ....analysis.autogate import AutoGateEngine, StepRequest, method
from ....analysis.autogate.models import Proposal
from ....analysis.fcs_io import get_channel_marker_label, get_fluorescence_channels
from ..panel_style import banner
from .apply_page import ApplyPage
from .build_page import BuildPage
from .compare_page import ComparePage
from .gating_tree import GatingTreePanel, population_items
from .setup_sidebar import SetupSidebar
from .why_panel import WhyPanel

if TYPE_CHECKING:
    from ....analysis.experiment import Sample
    from ....analysis.state import FlowState

ALL_SAMPLES = "all"
DEMO_NOTE = (
    "🚧 <b>Preview.</b> The analysis isn't connected yet: every proposal, percentage and "
    "explanation here is example output, labelled with your markers, so the layout can be "
    "reviewed. Nothing is added to your gates."
)
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


class AutoGatingTab(QWidget):
    open_tab_requested = Signal(object)  # MainTab

    def __init__(
        self, state: FlowState, engine: AutoGateEngine, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("AutoGatingTab")
        self._state = state
        self._engine = engine
        self._proposal: Proposal | None = None
        self._view_rank = 0

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        theme_manager.apply_style(self, "QWidget#AutoGatingTab { background: {BG_DARK}; }")

        self._sidebar = SetupSidebar()
        root.addWidget(self._sidebar)
        root.addWidget(self._build_main(), 1)
        self._tree = GatingTreePanel()
        self._tree.population_clicked.connect(self._on_population_clicked)
        self._tree.open_tab_requested.connect(self.open_tab_requested)
        root.addWidget(self._tree)

        self._sidebar.group_changed.connect(self._on_group_changed)
        self._sidebar.sample_changed.connect(self._on_sample_changed)
        self._sidebar.choices_changed.connect(self._on_choices_changed)
        self._sidebar.propose_clicked.connect(self._on_propose)
        self._sidebar.run_clicked.connect(self._on_run)

    def _build_main(self) -> QWidget:
        main = QWidget()
        layout = QVBoxLayout(main)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)
        layout.addWidget(HeaderLabel("Auto Gating"))
        self._banner = banner("AutoGateDemoBanner", DEMO_NOTE)
        self._banner.setVisible(self._engine.is_demo)
        layout.addWidget(self._banner)

        self._tabs = QTabWidget()
        self._tabs.setObjectName("AutoGateTabs")
        tab_bar = self._tabs.tabBar()
        if tab_bar is not None:
            tab_bar.setObjectName("AutoGateTabBar")
        theme_manager.apply_style(self._tabs, _TABS_QSS)
        self._build = BuildPage()
        self._build.accept_clicked.connect(self._on_accept)
        self._build.adjust_clicked.connect(self._on_adjust)
        self._build.next_view_clicked.connect(self._on_next_view)
        self._build.reject_clicked.connect(self._on_reject)
        self._why = WhyPanel()
        self._apply = ApplyPage()
        self._apply.mode_changed.connect(lambda _adaptive: self._refresh_apply())
        self._compare = ComparePage()
        self._compare.use_clicked.connect(self._on_use_method)
        self._tabs.addTab(_padded(self._build), "Build")
        self._why_page = _padded(self._why)
        self._tabs.addTab(self._why_page, "Why this gate")
        self._tabs.addTab(_padded(self._apply), "Apply to group")
        self._tabs.addTab(_padded(self._compare), "Compare methods")
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
        labels = (
            [get_channel_marker_label(fcs, ch) for ch in get_fluorescence_channels(fcs)]
            if fcs
            else []
        )
        self._sidebar.set_channels(labels)
        self._on_choices_changed()

    # ── Requests ──────────────────────────────────────────────────────

    def _request(self) -> StepRequest:
        _node_id, population = self._sidebar.population()
        key = self._sidebar.method_key()
        x, y = self._sidebar.axes() if method(key).user_picks_axes else ("", "")
        return StepRequest(
            method_key=key,
            population=population or "All Events",
            channels=self._sidebar.channels(),
            samples=tuple((s.display_name, s.role.is_control) for s in self._group_samples()),
            reference=self._sidebar.sample_name(),
            x_channel=x,
            y_channel=y,
            view_rank=self._view_rank,
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
        self._show(self._engine.propose(self._request()))

    def _show(self, proposal: Proposal | None) -> None:
        self._proposal = proposal
        self._build.show_proposal(proposal)
        node_id, _name = self._sidebar.population()
        proposed = proposal.plot.main_names if proposal else ()
        self._tree.show_tree(self._reference_sample(), node_id, proposed)
        self._refresh_apply()
        request = self._request()
        self._compare.show_outcomes(
            self._engine.compare(request) if proposal else (), request.population
        )

    def _refresh_apply(self) -> None:
        preview = (
            self._engine.preview_group(self._request(), self._apply.adaptive())
            if self._proposal is not None
            else None
        )
        self._apply.show_preview(preview, self._group_name())

    # ── Actions ───────────────────────────────────────────────────────

    def _preview_only(self, what: str) -> None:
        self._build.show_status(f"Preview only: {what}")

    def _on_accept(self) -> None:
        if self._proposal is None:
            return
        n = len(self._proposal.plot.main_names)
        samples = len(self._group_samples())
        self._preview_only(
            f"this will add {n} gates under {self._proposal.parent} and copy them to the "
            f"{samples} samples of {self._group_name()}."
        )

    def _on_adjust(self) -> None:
        self._preview_only(
            "this will open the proposed gates on the Gating tab for you to move before accepting."
        )

    def _on_next_view(self) -> None:
        self._view_rank += 1
        self._propose()

    def _on_reject(self) -> None:
        self._show(None)
        self._build.show_status("Rejected. Nothing was added.")

    def _on_run(self) -> None:
        self._propose()
        self._preview_only(
            "this will keep splitting each new population until a stopping rule is met."
        )

    def _on_use_method(self, key: str) -> None:
        self._sidebar.set_method(key)
        self._tabs.setCurrentIndex(0)

    def _on_population_clicked(self, name: str, parent: str) -> None:
        self._why.show_story(self._engine.story(name, parent, self._request()))
        self._tabs.setCurrentWidget(self._why_page)
