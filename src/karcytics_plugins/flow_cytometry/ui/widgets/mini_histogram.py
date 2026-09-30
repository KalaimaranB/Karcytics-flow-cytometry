"""Tiny bar histogram for inline previews (no matplotlib).

Paints with QPainter and reads theme colours at paint time, so it follows
theme changes without registering a stylesheet.
"""

from __future__ import annotations

import numpy as np
from karcytics_sdk.plugin.theme_fallback import Colors
from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QSizePolicy, QWidget


class MiniHistogram(QWidget):
    """Draws pre-binned counts, or a centered message when there's no data."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._counts = np.zeros(0)
        self._message = ""
        self.setMinimumHeight(72)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_counts(self, counts: np.ndarray) -> None:
        self._counts = np.asarray(counts, dtype=float)
        self._message = "" if len(self._counts) else "No valid events to show"
        self.update()

    def set_message(self, message: str) -> None:
        self._counts = np.zeros(0)
        self._message = message
        self.update()

    @property
    def message(self) -> str:
        return self._message

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(QColor(Colors.BORDER))
        painter.setBrush(QColor(Colors.BG_DARK))
        painter.drawRoundedRect(rect, 4, 4)

        peak = float(self._counts.max()) if len(self._counts) else 0.0
        if peak <= 0:
            painter.setPen(QColor(Colors.FG_SECONDARY))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._message)
            painter.end()
            return

        inner = rect.adjusted(4, 4, -4, -4)
        bar_w = inner.width() / len(self._counts)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(Colors.ACCENT_PRIMARY))
        for i, count in enumerate(self._counts):
            if count <= 0:
                continue
            h = inner.height() * count / peak
            painter.drawRect(
                QRectF(inner.left() + i * bar_w, inner.bottom() - h, max(bar_w - 1, 1), h)
            )
        painter.end()
