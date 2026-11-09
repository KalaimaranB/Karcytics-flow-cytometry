"""Events on a 2-D view with the gates a split would make, drawn with QPainter.

Everything arrives in display units (0-1 on each axis), so the plot needs no
scales. One widget serves the large Build plot and the small ones on the
Apply and Compare pages (``compact``).
"""

from __future__ import annotations

from karcytics_sdk.plugin.theme_fallback import Colors, Fonts, theme_manager
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPaintEvent, QPen, QPolygonF
from PySide6.QtWidgets import QSizePolicy, QWidget

from ....analysis.autogate.models import PlotData, Region, Shape
from ..panel_style import palette_color

EVENT_ALPHA = 120


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
        rect = self._frame()
        if self._plot is None:
            p.setPen(QColor(Colors.FG_SECONDARY))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._empty_text)
            return
        self._draw_axes(p, rect)
        self._draw_events(p, rect)
        for region in self._plot.ghosts:
            self._draw_region(p, rect, region, QColor(Colors.FG_SECONDARY), ghost=True)
        quadrant_drawn = False
        for i, region in enumerate(self._plot.regions):
            color = QColor(palette_color(i))
            if region.shape is Shape.QUADRANT:
                if not quadrant_drawn:
                    self._draw_region(p, rect, region, QColor(Colors.ACCENT_WARNING))
                    quadrant_drawn = True
                self._label_quadrant(p, rect, region, color)
            else:
                self._draw_region(p, rect, region, color)

    def _font(self, size: int, bold: bool = False) -> QFont:
        font = QFont(self.font())
        font.setPixelSize(size)
        font.setBold(bold)
        return font

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

    @staticmethod
    def _at(rect: QRectF, x: float, y: float) -> QPointF:
        return QPointF(rect.left() + x * rect.width(), rect.bottom() - y * rect.height())

    def _pen(self, color: QColor, ghost: bool) -> QPen:
        pen = QPen(color, 1.2 if ghost or self._compact else 2.0)
        if ghost or self._dashed:
            pen.setStyle(Qt.PenStyle.DashLine)
        return pen

    def _draw_region(
        self, p: QPainter, rect: QRectF, region: Region, color: QColor, ghost: bool = False
    ) -> None:
        fill = QColor(color)
        fill.setAlpha(0 if ghost else 22)
        p.setPen(self._pen(color, ghost))
        p.setBrush(fill)
        params = region.params
        anchor: QPointF | None = None
        if region.shape is Shape.ELLIPSE:
            cx, cy, rx, ry, angle = params
            center = self._at(rect, cx, cy)
            p.save()
            p.translate(center)
            p.rotate(-angle)
            p.drawEllipse(QPointF(0, 0), rx * rect.width(), ry * rect.height())
            p.restore()
            anchor = self._at(rect, cx - rx, cy + ry + 0.04)
        elif region.shape is Shape.POLYGON:
            pts = [self._at(rect, params[i], params[i + 1]) for i in range(0, len(params) - 1, 2)]
            p.drawPolygon(QPolygonF(pts))
            top = max(range(len(pts)), key=lambda i: -pts[i].y())
            anchor = QPointF(min(pt.x() for pt in pts), pts[top].y() - 6)
        elif region.shape is Shape.QUADRANT:
            x_cut, y_cut = params[0], params[1]
            path = QPainterPath()
            path.moveTo(self._at(rect, x_cut, 0))
            path.lineTo(self._at(rect, x_cut, 1))
            path.moveTo(self._at(rect, 0, y_cut))
            path.lineTo(self._at(rect, 1, y_cut))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)
        elif region.shape is Shape.RANGE:
            lo, hi = params[0], params[1]
            p.drawRect(QRectF(self._at(rect, lo, 1), self._at(rect, hi, 0)))
            anchor = self._at(rect, lo, 0.96)
        if anchor is not None and not ghost:
            self._label(p, anchor, region, color)

    def _label(self, p: QPainter, at: QPointF, region: Region, color: QColor) -> None:
        if self._compact and not region.is_main:
            return
        p.setPen(color)
        p.setFont(self._font(10 if self._compact else 12, bold=True))
        p.drawText(at, f"{region.name} · {region.fraction:.0%}")

    def _label_quadrant(self, p: QPainter, rect: QRectF, region: Region, color: QColor) -> None:
        q = int(region.params[2])
        right, bottom = q in (1, 3), q in (2, 3)
        flags = (Qt.AlignmentFlag.AlignRight if right else Qt.AlignmentFlag.AlignLeft) | (
            Qt.AlignmentFlag.AlignBottom if bottom else Qt.AlignmentFlag.AlignTop
        )
        main = region.is_main
        if self._compact and not main:
            return  # too little room: a small plot labels only the populations it gates
        p.setPen(color if main else QColor(Colors.FG_SECONDARY))
        p.setFont(self._font(10 if self._compact else 12, bold=main))
        p.drawText(
            rect.adjusted(6, 4, -6, -4), int(flags), f"{region.name} · {region.fraction:.0%}"
        )
