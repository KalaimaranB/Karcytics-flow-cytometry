"""A titled list of labelled bars: variance explained, loadings, pair scores, BIC.

One widget for every "how was this chosen" list, so they all read the same.
"""

from __future__ import annotations

from karcytics_sdk.plugin.components import BioCaptionLabel
from karcytics_sdk.plugin.theme_fallback import Colors, theme_manager
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPaintEvent
from PySide6.QtWidgets import QVBoxLayout, QWidget

from ....analysis.autogate.models import BarSection
from ..panel_style import section_header

ROW_HEIGHT = 22
LABEL_WIDTH = 92
VALUE_WIDTH = 46


class _Bars(QWidget):
    def __init__(self, section: BarSection) -> None:
        super().__init__()
        self._section = section
        self.setFixedHeight(ROW_HEIGHT * len(section.bars))
        self.setMinimumWidth(LABEL_WIDTH + VALUE_WIDTH + 60)
        theme_manager.connect(self.update)

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 - Qt override
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        s = self._section
        track_w = self.width() - LABEL_WIDTH - VALUE_WIDTH - 12
        for i, bar in enumerate(s.bars):
            y = i * ROW_HEIGHT
            chosen = i in s.highlight
            font = QFont(self.font())
            font.setBold(chosen)
            p.setFont(font)
            text_color = QColor(
                Colors.FG_PRIMARY if chosen or not s.highlight else Colors.FG_SECONDARY
            )
            p.setPen(text_color)
            label_rect = QRectF(0, y, LABEL_WIDTH - 6, ROW_HEIGHT)
            label = p.fontMetrics().elidedText(
                bar.label, Qt.TextElideMode.ElideRight, LABEL_WIDTH - 6
            )
            p.drawText(
                label_rect, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), label
            )

            track = QRectF(LABEL_WIDTH, y + 6, track_w, ROW_HEIGHT - 12)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(Colors.BG_MEDIUM))
            p.drawRoundedRect(track, 3, 3)
            if s.signed:
                mid = track.center().x()
                width = abs(bar.value) * track.width() / 2
                left = mid if bar.value >= 0 else mid - width
                p.setBrush(
                    QColor(Colors.ACCENT_PRIMARY if bar.value >= 0 else Colors.ACCENT_WARNING)
                )
                p.drawRoundedRect(QRectF(left, track.top(), width, track.height()), 3, 3)
                p.setPen(QColor(Colors.FG_DISABLED))
                p.drawLine(int(mid), int(track.top()) - 2, int(mid), int(track.bottom()) + 2)
            else:
                bright = chosen or not s.highlight
                p.setBrush(QColor(Colors.ACCENT_PRIMARY if bright else Colors.BG_LIGHT))
                width = max(0.0, min(bar.value, 1.0)) * track.width()
                p.drawRoundedRect(QRectF(track.left(), track.top(), width, track.height()), 3, 3)

            p.setPen(text_color)
            value_rect = QRectF(self.width() - VALUE_WIDTH, y, VALUE_WIDTH, ROW_HEIGHT)
            p.drawText(
                value_rect,
                int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight),
                bar.text,
            )


class BarList(QWidget):
    def __init__(self, section: BarSection, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(section_header(section.title))
        layout.addWidget(_Bars(section))
        if section.note:
            layout.addWidget(BioCaptionLabel(section.note))
