"""Tiny bar histogram for inline previews (no matplotlib).

Paints with QPainter and reads theme colours at paint time, so it follows
theme changes without registering a stylesheet.
"""

from __future__ import annotations

import numpy as np
from karcytics_sdk.plugin.theme_fallback import Colors
from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFontMetrics, QPainter
from PyQt6.QtWidgets import QSizePolicy, QWidget

_TICK_GAP = 3


class MiniHistogram(QWidget):
    """Draws pre-binned counts, or a centered message when there's no data.

    Optionally draws ``reference`` counts (same bins) as grey bars behind,
    and labels the x axis with ``ticks`` — ``(fraction along axis, label)``.
    Each series is scaled to its own peak so a small population stays
    readable in front of the whole sample.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._counts = np.zeros(0)
        self._reference: np.ndarray | None = None
        self._ticks: tuple[tuple[float, str], ...] = ()
        self._legend: tuple[str, str] | None = None
        self._message = ""
        self.setMinimumHeight(104)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_counts(
        self,
        counts: np.ndarray,
        reference: np.ndarray | None = None,
        ticks: tuple[tuple[float, str], ...] = (),
        legend: tuple[str, str] | None = None,
    ) -> None:
        """``legend`` names the (blue counts, grey reference) series."""
        self._counts = np.asarray(counts, dtype=float)
        self._reference = None if reference is None else np.asarray(reference, dtype=float)
        self._ticks = ticks
        self._legend = legend if reference is not None else None
        self._message = "" if len(self._counts) else "No valid events to show"
        self.update()

    def set_message(self, message: str) -> None:
        self._counts = np.zeros(0)
        self._reference = None
        self._ticks = ()
        self._legend = None
        self._message = message
        self.update()

    @property
    def legend(self) -> tuple[str, str] | None:
        return self._legend

    @property
    def ticks(self) -> tuple[tuple[float, str], ...]:
        return self._ticks

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

        line_h = QFontMetrics(painter.font()).height()
        label_h = line_h + _TICK_GAP if self._ticks else 0
        legend_h = line_h if self._legend else 0
        inner = rect.adjusted(4, 4 + legend_h, -4, -4 - label_h)
        painter.setPen(Qt.PenStyle.NoPen)
        grey = QColor(Colors.FG_SECONDARY)
        grey.setAlpha(90)
        blue = QColor(Colors.ACCENT_PRIMARY)
        if self._reference is not None and len(self._reference) == len(self._counts):
            self._draw_bars(painter, inner, self._reference, grey)
        self._draw_bars(painter, inner, self._counts, blue)
        if self._ticks:
            self._draw_ticks(painter, inner)
        if self._legend:
            entries = ((blue, self._legend[0]), (grey, self._legend[1]))
            self._draw_legend(painter, rect.adjusted(8, 3, -8, 0), entries)
        painter.end()

    @staticmethod
    def _draw_legend(
        painter: QPainter, area: QRectF, entries: tuple[tuple[QColor, str], ...]
    ) -> None:
        """One row across the top: ■ population   ■ whole sample."""
        metrics = QFontMetrics(painter.font())
        swatch = metrics.ascent() - 2
        x, y = area.left(), area.top()
        for color, label in entries:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawRect(QRectF(x, y + 2, swatch, swatch))
            painter.setPen(QColor(Colors.FG_PRIMARY))
            painter.drawText(int(x + swatch + 4), int(y + metrics.ascent()), label)
            x += swatch + 4 + metrics.horizontalAdvance(label) + 14

    @staticmethod
    def _draw_bars(painter: QPainter, inner: QRectF, counts: np.ndarray, color: QColor) -> None:
        peak = float(counts.max()) if len(counts) else 0.0
        if peak <= 0:
            return
        bar_w = inner.width() / len(counts)
        painter.setBrush(color)
        for i, count in enumerate(counts):
            if count <= 0:
                continue
            h = inner.height() * count / peak
            painter.drawRect(
                QRectF(inner.left() + i * bar_w, inner.bottom() - h, max(bar_w - 1, 1), h)
            )

    def _draw_ticks(self, painter: QPainter, inner: QRectF) -> None:
        metrics = QFontMetrics(painter.font())
        painter.setPen(QColor(Colors.FG_SECONDARY))
        baseline = inner.bottom() + _TICK_GAP + metrics.ascent()
        for frac, label in self._ticks:
            x = inner.left() + frac * inner.width()
            painter.drawLine(int(x), int(inner.bottom()), int(x), int(inner.bottom() + _TICK_GAP))
            w = metrics.horizontalAdvance(label)
            left = min(max(x - w / 2, inner.left()), inner.right() - w)
            painter.drawText(int(left), int(baseline), label)
