"""The audit's findings as clickable cards."""

from __future__ import annotations

from typing import Any

from karcytics_sdk.plugin.components import (
    BioCaptionLabel,
    ModuleCard,
    SecondaryButton,
    SubtitleLabel,
)
from karcytics_sdk.plugin.theme_fallback import theme_manager
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ....analysis.sample_lens import Finding, FindingKind

_ICON = {FindingKind.MISSED: "◯", FindingKind.MERGES: "⊕", FindingKind.CUTS: "✂"}


class _FindingCard(ModuleCard):
    clicked = Signal(object)
    fix_requested = Signal(object)

    def __init__(
        self,
        finding: Finding | None,
        title: str = "",
        detail: str = "",
        agreement: str = "",
        number: int = 0,
    ) -> None:
        super().__init__()
        self._finding = finding
        if finding is not None:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(10)

        icon = QLabel("✓" if finding is None else _ICON[finding.kind])
        icon.setFixedWidth(18)
        if number:  # the same number labels this finding's rings on the map
            badge = QLabel(str(number))
            badge.setObjectName("SampleLensFindingNumber")
            badge.setFixedSize(20, 20)
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            theme_manager.apply_style(
                badge,
                "QLabel#SampleLensFindingNumber { color: {BG_DARKEST}; background: "
                "{ACCENT_WARNING}; border-radius: 10px; font-size: 11px; font-weight: bold; }",
            )
            layout.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
        icon.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        tone = "ACCENT_SUCCESS" if finding is None else "ACCENT_WARNING"
        theme_manager.apply_style(icon, f"color: {{{tone}}}; font-size: 15px; background: none;")
        layout.addWidget(icon)

        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(SubtitleLabel(finding.title if finding else title))
        text.addWidget(BioCaptionLabel(finding.detail if finding else detail))
        if agreement:
            other = QLabel(agreement)
            other.setObjectName("SampleLensAgreement")
            other.setWordWrap(True)
            tone = "ACCENT_SUCCESS" if agreement.startswith("Also") else "FG_SECONDARY"
            theme_manager.apply_style(
                other, f"color: {{{tone}}}; font-size: 11px; font-style: italic; background: none;"
            )
            text.addWidget(other)
        if finding is not None and finding.kind is FindingKind.MISSED:
            fix = SecondaryButton("Propose gates")
            fix.setObjectName("SampleLensProposeButton")
            fix.clicked.connect(lambda: self.fix_requested.emit(finding))
            text.addWidget(fix, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addLayout(text, 1)

    def mousePressEvent(self, event: Any) -> None:  # noqa: N802 - Qt override
        if self._finding is not None:
            self.clicked.emit(self._finding)
        super().mousePressEvent(event)


class FindingsPanel(QWidget):
    finding_clicked = Signal(object)
    fix_requested = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(8)

    def show_findings(
        self,
        findings: list[Finding],
        empty_title: str,
        empty_detail: str,
        agreements: list[str] | None = None,
    ) -> None:
        """One card per finding; ``agreements`` (per finding) says what other runs think."""
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.hide()  # deleteLater lands next event-loop turn; don't paint until then
                widget.deleteLater()
        notes = agreements or [""] * len(findings)
        cards = [
            _FindingCard(f, agreement=a, number=i)
            for i, (f, a) in enumerate(zip(findings, notes, strict=True), start=1)
        ] or [_FindingCard(None, empty_title, empty_detail)]
        for card in cards:
            card.clicked.connect(self.finding_clicked)
            card.fix_requested.connect(self.fix_requested)
            self._layout.addWidget(card)
