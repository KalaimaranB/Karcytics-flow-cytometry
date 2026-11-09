"""Build: one proposed split at a time, with how its view was chosen and why.

Accept / Adjust / Next view / Reject are only signals; the tab decides what
they do.
"""

from __future__ import annotations

from karcytics_sdk.plugin.components import (
    BioCaptionLabel,
    BioScrollArea,
    BioStatusLabel,
    PrimaryButton,
    SecondaryButton,
    SubtitleLabel,
)
from karcytics_sdk.plugin.theme_fallback import Fonts, theme_manager
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ....analysis.autogate import method
from ....analysis.autogate.models import Proposal
from ..panel_style import Pill, card, clear_layout
from .bar_list import BarList
from .proposal_plot import ProposalPlot

VIEW_PANEL_MIN_WIDTH, VIEW_PANEL_MAX_WIDTH = 230, 300
EMPTY_TEXT = "Pick a population and press “Propose next split”."


class BuildPage(QWidget):
    accept_clicked = Signal()
    adjust_clicked = Signal()
    next_view_clicked = Signal()
    reject_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 12, 0, 0)
        layout.setSpacing(12)

        header = QHBoxLayout()
        self._title = SubtitleLabel("No proposal yet")
        self._title.setObjectName("AutoGateProposalTitle")
        self._method = Pill("", "accent")
        self._meta = BioCaptionLabel("")
        header.addWidget(self._title)
        header.addWidget(self._method)
        header.addWidget(self._meta, 1)
        layout.addLayout(header)

        body = QHBoxLayout()
        body.setSpacing(12)
        body.addWidget(self._build_view_card())
        body.addWidget(self._build_plot_card(), 1)
        layout.addLayout(body, 1)
        self.show_proposal(None)

    def _build_view_card(self) -> QWidget:
        view_card = card("AutoGateViewCard")
        view_card.setMinimumWidth(VIEW_PANEL_MIN_WIDTH)
        view_card.setMaximumWidth(VIEW_PANEL_MAX_WIDTH)
        view_layout = QVBoxLayout(view_card)
        view_layout.setContentsMargins(0, 0, 0, 0)
        scroll = BioScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._sections = QWidget()
        self._sections_layout = QVBoxLayout(self._sections)
        self._sections_layout.setContentsMargins(14, 14, 14, 14)
        self._sections_layout.setSpacing(16)
        scroll.setWidget(self._sections)
        view_layout.addWidget(scroll)
        return view_card

    def _build_plot_card(self) -> QWidget:
        plot_card = card("AutoGatePlotCard")
        plot_layout = QVBoxLayout(plot_card)
        plot_layout.setContentsMargins(14, 14, 14, 14)
        plot_layout.setSpacing(10)
        self._plot = ProposalPlot()
        self._plot.setObjectName("AutoGateProposalPlot")
        self._plot.set_plot(None, empty_text=EMPTY_TEXT)
        plot_layout.addWidget(self._plot, 1)
        self._reason = QLabel("")
        self._reason.setObjectName("AutoGateReason")
        self._reason.setWordWrap(True)
        theme_manager.apply_style(
            self._reason,
            "QLabel#AutoGateReason { color: {FG_PRIMARY}; background: {BG_DARKEST};"
            " border: 1px solid {BORDER}; border-left: 4px solid {ACCENT_PRIMARY};"
            f" border-radius: 6px; padding: 8px 12px; font-size: {Fonts.SIZE_NORMAL}px; }}",
        )
        self._reason.hide()
        plot_layout.addWidget(self._reason)
        plot_layout.addLayout(self._build_actions())
        self._status = BioStatusLabel("")
        self._status.setObjectName("AutoGateBuildStatus")
        plot_layout.addWidget(self._status)
        return plot_card

    def _build_actions(self) -> QHBoxLayout:
        actions = QHBoxLayout()
        self._accept = PrimaryButton("Accept")
        self._accept.setObjectName("AutoGateAcceptButton")
        self._adjust = SecondaryButton("Adjust")
        self._adjust.setToolTip("Move the proposed gates on the plot before accepting them.")
        self._next = SecondaryButton("Next-best view")
        self._next.setToolTip("Propose the split on the runner-up view instead.")
        self._next.setObjectName("AutoGateNextViewButton")
        self._reject = SecondaryButton("Reject")
        for button, signal in (
            (self._accept, self.accept_clicked),
            (self._adjust, self.adjust_clicked),
            (self._next, self.next_view_clicked),
            (self._reject, self.reject_clicked),
        ):
            button.clicked.connect(signal)
            actions.addWidget(button)
        actions.addStretch()
        return actions

    def show_proposal(self, proposal: Proposal | None) -> None:
        clear_layout(self._sections_layout)
        has = proposal is not None
        for button in (self._accept, self._adjust, self._next, self._reject):
            button.setEnabled(has)
        self._method.setVisible(has)
        self._reason.setVisible(has)
        self._status.setText("")
        if proposal is None:
            self._title.setText("No proposal yet")
            self._meta.setText("")
            self._plot.set_plot(None, empty_text=EMPTY_TEXT)
            self._sections_layout.addWidget(
                BioCaptionLabel("How the view was chosen appears here.")
            )
            self._sections_layout.addStretch()
            return
        info = method(proposal.method_key)
        self._title.setText(f"Proposed split of {proposal.parent}")
        self._method.setText(info.name)
        self._meta.setText(f"{proposal.n_events:,} events · not added yet")
        n = len(proposal.plot.main_names)
        self._accept.setText(f"Accept · add {n} gates")
        self._next.setVisible(not info.user_picks_axes)
        self._plot.set_plot(proposal.plot)
        self._reason.setText(proposal.reason)
        for section in proposal.view_sections:
            self._sections_layout.addWidget(BarList(section))
        self._sections_layout.addStretch()

    def show_status(self, text: str) -> None:
        self._status.setText(text)
