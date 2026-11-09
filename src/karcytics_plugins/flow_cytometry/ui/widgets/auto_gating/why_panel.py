"""Why this gate: everything recorded about where an auto gate came from.

Reads one ``GateStory``. The methods paragraph can be copied for a paper.
"""

from __future__ import annotations

import numpy as np
from karcytics_sdk.plugin.components import (
    BioCaptionLabel,
    BioScrollArea,
    SecondaryButton,
    SubtitleLabel,
)
from karcytics_sdk.plugin.theme_fallback import Colors, Fonts, theme_manager
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPainterPath, QPaintEvent, QPen
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ....analysis.autogate import method
from ....analysis.autogate.models import GateStory
from ..panel_style import Pill, card, clear_layout, section_header
from .bar_list import BarList

DENSITY_HEIGHT = 120


class _DensityStrip(QWidget):
    """The events' density along the split axis, with the cut at its valley."""

    def __init__(self) -> None:
        super().__init__()
        self._density: np.ndarray | None = None
        self._valley = 0.5
        self._axis = ""
        self.setFixedHeight(DENSITY_HEIGHT)
        theme_manager.connect(self.update)

    def set_density(self, density: np.ndarray, valley: float, axis: str) -> None:
        self._density, self._valley, self._axis = density, valley, axis
        self.update()

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 - Qt override
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(Colors.BG_DARKEST))
        if self._density is None or not len(self._density):
            return
        rect = QRectF(8, 8, self.width() - 16, self.height() - 30)
        xs = np.linspace(rect.left(), rect.right(), len(self._density))
        ys = rect.bottom() - self._density * rect.height()
        path = QPainterPath(QPointF(rect.left(), rect.bottom()))
        for x, y in zip(xs, ys, strict=True):
            path.lineTo(float(x), float(y))
        path.lineTo(rect.right(), rect.bottom())
        fill = QColor(Colors.ACCENT_PRIMARY)
        fill.setAlpha(60)
        p.setPen(QPen(QColor(Colors.ACCENT_PRIMARY), 1.5))
        p.setBrush(fill)
        p.drawPath(path)
        cut = rect.left() + self._valley * rect.width()
        pen = QPen(QColor(Colors.ACCENT_WARNING), 2, Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.drawLine(QPointF(cut, rect.top()), QPointF(cut, rect.bottom()))
        p.setPen(QColor(Colors.FG_SECONDARY))
        p.drawText(
            QRectF(rect.left(), rect.bottom() + 4, rect.width(), 18),
            Qt.AlignmentFlag.AlignCenter,
            self._axis,
        )
        p.setPen(QColor(Colors.ACCENT_WARNING))
        p.drawText(QPointF(cut + 6, rect.top() + 12), "cut at the valley")


class WhyPanel(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._story: GateStory | None = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 12, 0, 0)
        scroll = BioScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(12)

        header = QHBoxLayout()
        self._title = SubtitleLabel("Click an auto gate in the gating tree")
        self._title.setObjectName("AutoGateWhyTitle")
        self._method = Pill("", "accent")
        header.addWidget(self._title)
        header.addWidget(self._method)
        header.addStretch()
        layout.addLayout(header)

        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(self._build_facts_card(), 1)
        row.addWidget(self._build_split_card(), 1)
        layout.addLayout(row)
        layout.addWidget(self._build_methods_card())
        layout.addStretch()
        scroll.setWidget(content)
        outer.addWidget(scroll)
        self.show_story(None)

    def _build_facts_card(self) -> QWidget:
        facts_card = card("AutoGateFactsCard")
        facts_layout = QVBoxLayout(facts_card)
        facts_layout.setContentsMargins(14, 14, 14, 14)
        facts_layout.addWidget(section_header("Where it came from"))
        self._facts = QGridLayout()
        self._facts.setHorizontalSpacing(16)
        self._facts.setVerticalSpacing(6)
        facts_layout.addLayout(self._facts)
        facts_layout.addStretch()
        return facts_card

    def _build_split_card(self) -> QWidget:
        split_card = card("AutoGateSplitCard")
        split_layout = QVBoxLayout(split_card)
        split_layout.setContentsMargins(14, 14, 14, 14)
        split_layout.addWidget(section_header("The split"))
        self._density = _DensityStrip()
        split_layout.addWidget(self._density)
        self._sections = QVBoxLayout()
        self._sections.setSpacing(14)
        split_layout.addLayout(self._sections)
        split_layout.addStretch()
        return split_card

    def _build_methods_card(self) -> QWidget:
        text_card = card("AutoGateMethodsCard")
        text_layout = QVBoxLayout(text_card)
        text_layout.setContentsMargins(14, 14, 14, 14)
        text_layout.addWidget(
            section_header(
                "For your methods section",
                "A description of how this gate was made, ready to paste.",
            )
        )
        self._methods_text = QLabel("")
        self._methods_text.setWordWrap(True)
        self._methods_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        theme_manager.apply_style(
            self._methods_text, f"color: {{FG_PRIMARY}}; font-size: {Fonts.SIZE_NORMAL}px;"
        )
        text_layout.addWidget(self._methods_text)
        buttons = QHBoxLayout()
        copy = SecondaryButton("Copy")
        copy.setObjectName("AutoGateCopyMethods")
        copy.clicked.connect(self._copy)
        buttons.addWidget(copy)
        buttons.addStretch()
        text_layout.addLayout(buttons)
        self._edits = BioCaptionLabel("")
        text_layout.addWidget(self._edits)
        return text_card

    def show_story(self, story: GateStory | None) -> None:
        self._story = story
        clear_layout(self._facts)
        clear_layout(self._sections)
        self._method.setVisible(story is not None)
        if story is None:
            self._title.setText("Click a population in the gating tree to see why it was gated")
            self._methods_text.setText("")
            self._edits.setText("")
            return
        self._title.setText(story.gate)
        self._method.setText(method(story.method_key).name)
        for row, (label, value) in enumerate(story.facts):
            key = BioCaptionLabel(label)
            val = QLabel(value)
            val.setWordWrap(True)
            theme_manager.apply_style(
                val, f"color: {{FG_PRIMARY}}; font-size: {Fonts.SIZE_NORMAL}px;"
            )
            self._facts.addWidget(key, row, 0, Qt.AlignmentFlag.AlignTop)
            self._facts.addWidget(val, row, 1)
        self._facts.setColumnStretch(1, 1)
        self._density.set_density(story.density, story.valley_at, story.split_axis)
        for section in story.sections:
            self._sections.addWidget(BarList(section))
        self._methods_text.setText(story.methods_text)
        self._edits.setText(" ".join(story.edits))

    def _copy(self) -> None:
        if self._story is not None:
            QGuiApplication.clipboard().setText(self._story.methods_text)
