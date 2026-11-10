"""Events on a 2-D view with the gates a split would make, drawn with QPainter.

Everything arrives in plot units (0-1 on each axis), so the plot needs no
scales. One widget serves the large Build plot and the small ones on the
Apply and Compare pages (``compact``).
"""

from __future__ import annotations

from karcytics_sdk.plugin.theme_fallback import Colors, Fonts, theme_manager
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPaintEvent, QPen, QPolygonF
from PySide6.QtWidgets import QSizePolicy, QWidget

from ....analysis.autogate.models import PlotData, Region
from ..panel_style import palette_color

EVENT_ALPHA = 110
LINE_POINTS = 2  # an outline of two points is a line (a cut on another sample)


class ProposalPlot(QWidget):
    def __init__(self, *, compact: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._compact = compact
        self._plot: PlotData | None = None
        self._dashed = True
        self._empty_text = "No proposal yet"
        width, height = (160, 140) if compact else (280, 240)
        self.setMinimumSize(width, height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        theme_manager.connect(self.update)

    def set_plot(self, plot: PlotData | None, *, dashed: bool = True, empty_text: str = "") -> None:
        """Show ``plot``; ``dashed`` draws the gates as proposals rather than accepted gates."""
        self._plot, self._dashed = plot, dashed
        if empty_text:
            self._empty_text = empty_text
        self.update()

    def has_plot(self) -> bool:
        return self._plot is not None

    # ── Painting ──────────────────────────────────────────────────────

    def _frame(self) -> QRectF:
        left, bottom = (14, 18) if self._compact else (30, 34)
        top, right = (6, 6) if self._compact else (10, 12)
        return QRectF(left, top, self.width() - left - right, self.height() - top - bottom)

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 - Qt override
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(Colors.BG_DARKEST))
        if self._plot is None:
            p.setPen(QColor(Colors.FG_SECONDARY))
            p.drawText(
                self.rect().adjusted(12, 12, -12, -12),
                int(Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap),
                self._empty_text,
            )
            return
        rect = self._frame()
        self._draw_axes(p, rect)
        self._draw_events(p, rect)
        self._draw_cuts(p, rect)
        for region in self._plot.ghosts:
            self._draw_outline(p, rect, region, QColor(Colors.FG_SECONDARY), ghost=True)
        for i, region in enumerate(self._plot.regions):
            color = QColor(palette_color(i)) if region.is_main else QColor(Colors.FG_SECONDARY)
            self._draw_outline(p, rect, region, color)

    def _font(self, size: int, bold: bool = False) -> QFont:
        font = QFont(self.font())
        font.setPixelSize(size)
        font.setBold(bold)
        return font

    @staticmethod
    def _at(rect: QRectF, x: float, y: float) -> QPointF:
        return QPointF(rect.left() + x * rect.width(), rect.bottom() - y * rect.height())

    def _draw_axes(self, p: QPainter, rect: QRectF) -> None:
        assert self._plot is not None
        p.setPen(QPen(QColor(Colors.BORDER), 1))
        p.drawLine(rect.bottomLeft(), rect.bottomRight())
        p.drawLine(rect.bottomLeft(), rect.topLeft())
        p.setPen(QColor(Colors.FG_SECONDARY))
        p.setFont(self._font(10 if self._compact else Fonts.SIZE_SMALL))
        metrics = p.fontMetrics()
        x_text = metrics.elidedText(
            self._plot.x_label, Qt.TextElideMode.ElideRight, int(rect.width())
        )
        p.drawText(
            QRectF(rect.left(), rect.bottom() + 2, rect.width(), self.height() - rect.bottom() - 2),
            Qt.AlignmentFlag.AlignCenter,
            x_text,
        )
        p.save()
        p.translate(2, rect.center().y())
        p.rotate(-90)
        y_text = metrics.elidedText(
            self._plot.y_label, Qt.TextElideMode.ElideRight, int(rect.height())
        )
        p.drawText(
            QRectF(-rect.height() / 2, 0, rect.height(), rect.left() - 4),
            Qt.AlignmentFlag.AlignCenter,
            y_text,
        )
        p.restore()

    def _draw_events(self, p: QPainter, rect: QRectF) -> None:
        assert self._plot is not None
        color = QColor(Colors.FG_SECONDARY)  # neutral events, so the coloured gates stand out
        color.setAlpha(EVENT_ALPHA)
        p.setPen(QPen(color, 1.6 if self._compact else 2.0))
        xs = rect.left() + self._plot.points[:, 0] * rect.width()
        ys = rect.bottom() - self._plot.points[:, 1] * rect.height()
        p.drawPoints(QPolygonF([QPointF(float(x), float(y)) for x, y in zip(xs, ys, strict=True)]))

    def _draw_cuts(self, p: QPainter, rect: QRectF) -> None:
        assert self._plot is not None
        p.setPen(
            QPen(QColor(Colors.ACCENT_WARNING), 1.5 if self._compact else 2, Qt.PenStyle.DashLine)
        )
        for axis, pos in self._plot.cuts:
            if axis == "x":
                p.drawLine(self._at(rect, pos, 0), self._at(rect, pos, 1))
            else:
                p.drawLine(self._at(rect, 0, pos), self._at(rect, 1, pos))

    def _draw_outline(
        self, p: QPainter, rect: QRectF, region: Region, color: QColor, ghost: bool = False
    ) -> None:
        o = region.outline
        points = [self._at(rect, o[i], o[i + 1]) for i in range(0, len(o) - 1, 2)]
        if not points:
            return
        pen = QPen(color, 1.2 if ghost or self._compact else 2.0)
        if ghost or self._dashed:
            pen.setStyle(Qt.PenStyle.DashLine)
        fill = QColor(color)
        fill.setAlpha(0 if ghost or not region.is_main else 22)
        p.setPen(pen)
        p.setBrush(fill)
        if len(points) == LINE_POINTS:
            p.drawLine(points[0], points[1])
            return
        p.drawPolygon(QPolygonF(points))
        if not ghost and (region.is_main or not self._compact):
            top = min(points, key=lambda pt: pt.y())
            left = min(pt.x() for pt in points)
            p.setPen(color)
            p.setFont(self._font(10 if self._compact else 12, bold=region.is_main))
            at = QPointF(max(left, rect.left() + 2), max(top.y() - 6, rect.top() + 12))
            p.drawText(at, f"{region.name} · {region.fraction:.0%}")
