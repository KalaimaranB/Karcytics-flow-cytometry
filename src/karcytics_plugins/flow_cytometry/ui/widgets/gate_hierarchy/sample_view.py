"""SampleViewWidget — custom-painted node-link chart for one sample.

Single Responsibility: render TreeNodeRects and handle mouse events.
Delegates all layout geometry to NodeTreeEngine.
Delegates all tooltip display to HoverCard.
"""

from __future__ import annotations

from karcytics_sdk.plugin.components import BioMenu
from karcytics_sdk.plugin.theme_fallback import Colors, Fonts
from PyQt6.QtCore import QPoint, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QWheelEvent,
)
from PyQt6.QtWidgets import QSizePolicy, QWidget

from .hover_card import HoverCard
from .node_tree_engine import TreeNodeRect

# Depth-level colour palette (matches HoverCard and AllSamplesModel)
_PALETTE = [
    QColor("#7c4dff"),  # 0 root    — purple
    QColor("#00bcd4"),  # 1 depth 1 — teal
    QColor("#42a5f5"),  # 2 depth 2 — blue
    QColor("#ffa726"),  # 3 depth 3 — orange
    QColor("#ef5350"),  # 4 depth 4 — pink/red
    QColor("#66bb6a"),  # 5 depth 5 — green
]
_RADIUS = 6  # corner radius


class SampleViewWidget(QWidget):
    """Custom painter node-link flowchart widget.

    Signals:
        node_clicked(node_id):         Single click selects a population.
        node_double_clicked(node_id):  Double click opens a new graph.
        rename_requested(node_id):     Via context menu.
        delete_requested(node_id):     Via context menu.
    """

    node_clicked = pyqtSignal(str)
    node_double_clicked = pyqtSignal(str)
    rename_requested = pyqtSignal(str)
    delete_requested = pyqtSignal(str)
    propagate_requested = pyqtSignal(str)

    def __init__(self, state, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self._state = state
        self._rects: list[TreeNodeRect] = []
        self._node_map: dict[str, TreeNodeRect] = {}
        self._selected_id: str | None = None
        self._hovered_id: str | None = None
        self._hover_card = HoverCard(self)

        self._scale = 1.0
        self._is_panning = False
        self._pan_start_pos = QPoint()

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.setMinimumHeight(200)
        self.setMinimumWidth(200)

    def _apply_theme_styles(self) -> None:
        """Dynamically refresh colors when theme changes."""
        self.update()

    # ── Public API ────────────────────────────────────────────────────

    def set_rects(self, rects: list[TreeNodeRect]) -> None:
        """Replace the rect list and repaint."""
        self._rects = rects
        self._node_map = {r.node_id: r for r in rects}
        self._selected_id = None
        self._hover_card.hide()

        if rects:
            # Rects from NodeTreeEngine are 0-based (left edge = 0, top already padded).
            tree_w = max(r.x + r.width / 2 for r in rects)
            tree_h = max(r.y + r.height / 2 for r in rects)
            self._tree_width = tree_w
        else:
            self._tree_width = 0.0
            tree_h = 200.0

        # Allow the widget to grow but not shrink below what the tree needs
        self.setMinimumSize(
            int((self._tree_width + 40) * self._scale), int((tree_h + 40) * self._scale)
        )
        self.update()

    def set_selected(self, node_id: str | None) -> None:
        self._selected_id = node_id
        self.update()

    def rename_node(self, node_id: str, new_name: str) -> None:
        """Update one node's label in place without recomputing layout.

        Node width is a fixed constant in NodeTreeEngine (not name-dependent),
        so a rename never changes geometry — only the painted label changes.
        """
        for r in self._rects:
            if r.node_id == node_id:
                r.name = new_name
                self.update()
                return

    def clear(self) -> None:
        self._rects = []
        self._node_map = {}
        self._selected_id = None
        self._hover_card.hide()
        self.update()

    # ── Painting ──────────────────────────────────────────────────────

    def paintEvent(self, _event) -> None:
        if not self._rects:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(self._scale, self._scale)

        # Compute horizontal centering offset so the tree sits in the middle
        # of the available widget width.  NodeTreeEngine produces 0-based coords
        # (leftmost node left-edge = 0), so we simply shift right by half the
        # remaining space.
        tree_w = getattr(self, "_tree_width", 0.0)
        unscaled_width = self.width() / self._scale
        x_offset = max(0.0, (unscaled_width - tree_w) / 2.0)

        # 1. Draw connections (bezier curves)
        pen_line = QPen(QColor(Colors.BORDER), 2)
        painter.setPen(pen_line)

        for r in self._rects:
            for parent_id in r.parent_ids:
                if parent_id in self._node_map:
                    p = self._node_map[parent_id]
                    start_x = p.x + x_offset
                    start_y = p.y + p.height / 2
                    end_x = r.x + x_offset
                    end_y = r.y - r.height / 2

                    path = QPainterPath()
                    path.moveTo(start_x, start_y)
                    ctrl1_x = start_x
                    ctrl1_y = start_y + (end_y - start_y) / 2
                    ctrl2_x = end_x
                    ctrl2_y = start_y + (end_y - start_y) / 2
                    path.cubicTo(ctrl1_x, ctrl1_y, ctrl2_x, ctrl2_y, end_x, end_y)
                    painter.drawPath(path)

        # 2. Draw nodes
        for r in self._rects:
            px_x = int(r.x - r.width / 2 + x_offset)
            px_y = int(r.y - r.height / 2)
            px_w = int(r.width)
            px_h = int(r.height)

            rect_f = QRectF(px_x, px_y, px_w, px_h)

            # Fill colour
            fill = _PALETTE[r.color_index % len(_PALETTE)]

            # Hover highlight: lighten slightly
            if r.node_id == self._hovered_id:
                fill = fill.lighter(120)

            # Background fill
            path = QPainterPath()
            path.addRoundedRect(rect_f, _RADIUS, _RADIUS)

            # Use a dark background with colored top border, or solid color?
            # A sleek professional look: Dark block, colored left rim
            painter.fillPath(path, QColor(Colors.BG_DARK))

            # Top accent rim
            rim_rect = QRectF(px_x, px_y, px_w, 6)
            rim_path = QPainterPath()
            rim_path.addRoundedRect(rim_rect, _RADIUS, _RADIUS)
            # Clip the bottom edge of the rim to make it flush
            painter.fillPath(rim_path, fill)
            painter.fillRect(QRectF(px_x, px_y + 3, px_w, 3), fill)

            # Outline
            if r.node_id == self._selected_id:
                painter.setPen(QPen(QColor(Colors.FG_PRIMARY), 2))
            else:
                painter.setPen(QPen(QColor(Colors.BORDER), 1))
            painter.drawPath(path)

            self._draw_label(painter, r, rect_f, fill)

        painter.end()

    def _draw_label(
        self, painter: QPainter, r: TreeNodeRect, rect_f: QRectF, fill_color: QColor
    ) -> None:
        text_color = QColor(Colors.FG_PRIMARY)

        # Name line
        name_font = QFont(
            Fonts.FAMILY_UI if hasattr(Fonts, "FAMILY_UI") else "sans-serif",
            11,
            QFont.Weight.Bold,
        )
        painter.setFont(name_font)
        painter.setPen(text_color)
        fm = QFontMetrics(name_font)
        padding_left = 12
        available = int(r.width) - padding_left - 4

        name = fm.elidedText(r.name, Qt.TextElideMode.ElideRight, available)

        # Percentage & Count line
        pct_font = QFont(Fonts.FAMILY_UI if hasattr(Fonts, "FAMILY_UI") else "sans-serif", 10)
        pct_font.setWeight(QFont.Weight.Normal)
        pct_str = f"{r.pct_parent:.1f}% ({r.count:,})"

        # Vertically centre both lines together
        fm_name = QFontMetrics(name_font)
        fm_pct = QFontMetrics(pct_font)
        total_h = fm_name.height() + 2 + fm_pct.height()
        top_y = rect_f.top() + (rect_f.height() - total_h) / 2 + fm_name.ascent()

        painter.setFont(name_font)
        painter.setPen(text_color)
        painter.drawText(int(rect_f.left() + padding_left), int(top_y), name)

        pct_color = QColor(Colors.FG_SECONDARY)
        painter.setFont(pct_font)
        painter.setPen(pct_color)
        painter.drawText(
            int(rect_f.left() + padding_left),
            int(top_y + fm_name.descent() + 2 + fm_pct.ascent()),
            pct_str,
        )

    # ── Mouse events ──────────────────────────────────────────────────

    def _rect_at(self, pos: QPoint) -> TreeNodeRect | None:
        tree_w = getattr(self, "_tree_width", 0.0)
        unscaled_width = self.width() / self._scale
        x_offset = max(0.0, (unscaled_width - tree_w) / 2.0)

        pos_x = pos.x() / self._scale
        pos_y = pos.y() / self._scale

        for r in self._rects:
            rx = r.x - r.width / 2 + x_offset
            ry = r.y - r.height / 2

            if rx <= pos_x <= rx + r.width and ry <= pos_y <= ry + r.height:
                return r
        return None

    # ── Zoom and Pan ──────────────────────────────────────────────────

    def set_scale(self, scale: float) -> None:
        self._scale = max(0.1, min(scale, 3.0))
        tree_h = max((r.y + r.height / 2 for r in self._rects), default=200.0)
        self.setMinimumSize(
            int((self._tree_width + 40) * self._scale), int((tree_h + 40) * self._scale)
        )
        self.update()

    def zoom_in(self) -> None:
        self.set_scale(self._scale * 1.15)

    def zoom_out(self) -> None:
        self.set_scale(self._scale / 1.15)

    def fit_view(self) -> None:
        tree_w = getattr(self, "_tree_width", 0.0)
        tree_h = max((r.y + r.height / 2 for r in self._rects), default=200.0)

        scroll_area = self.parentWidget()
        if scroll_area and scroll_area.parentWidget():
            # parentWidget() is the QScrollArea's viewport, parentWidget().parentWidget() is the QScrollArea
            scroll_area = scroll_area.parentWidget()
            if scroll_area:
                vw = scroll_area.width() - 20
                vh = scroll_area.height() - 20

                scale_x = vw / (tree_w + 40) if tree_w > 0 else 1.0
                scale_y = vh / (tree_h + 40) if tree_h > 0 else 1.0

                self.set_scale(min(scale_x, scale_y))

    def wheelEvent(self, event: QWheelEvent | None) -> None:
        if event is None:
            return
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            if event.angleDelta().y() > 0:
                self.zoom_in()
            else:
                self.zoom_out()
            event.accept()
        else:
            super().wheelEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_F:
            self.fit_view()
            event.accept()
        else:
            super().keyPressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent | None) -> None:
        if event is None:
            return
        if self._is_panning:
            delta = event.globalPosition().toPoint() - self._pan_start_pos
            self._pan_start_pos = event.globalPosition().toPoint()

            scroll_area = self.parentWidget()
            if scroll_area and scroll_area.parentWidget():
                scroll_area = scroll_area.parentWidget()
                from PyQt6.QtWidgets import QScrollArea

                if isinstance(scroll_area, QScrollArea):
                    hs = scroll_area.horizontalScrollBar()
                    vs = scroll_area.verticalScrollBar()
                    if hs:
                        hs.setValue(hs.value() - delta.x())
                    if vs:
                        vs.setValue(vs.value() - delta.y())
            event.accept()
            return

        hit = self._rect_at(event.pos())
        if hit:
            if self._hovered_id != hit.node_id:
                self._hovered_id = hit.node_id
                self.update()

                # Count how many samples have this gate
                total = len(self._state.data.experiment.samples)
                gated = sum(
                    1
                    for s in self._state.data.experiment.samples.values()
                    if s.gate_tree.find_node_by_id(hit.node_id) is not None
                )

                self._hover_card.show_for(
                    hit,
                    event.globalPosition().toPoint(),
                    samples_gated=gated,
                    total_samples=total,
                )
        elif self._hovered_id is not None:
            self._hovered_id = None
            self._hover_card.hide()
            self.update()

    def leaveEvent(self, _event) -> None:
        self._hovered_id = None
        self._hover_card.hide()
        self.update()

    def mousePressEvent(self, event: QMouseEvent | None) -> None:
        if event is None:
            return
        if event.button() == Qt.MouseButton.MiddleButton or (
            event.button() == Qt.MouseButton.LeftButton
            and event.modifiers() == Qt.KeyboardModifier.AltModifier
        ):
            self._is_panning = True
            self._pan_start_pos = event.globalPosition().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return

        hit = self._rect_at(event.pos())
        if hit:
            self._selected_id = hit.node_id
            self.update()

            is_right_click = event.button() == Qt.MouseButton.RightButton or (
                event.button() == Qt.MouseButton.LeftButton
                and event.modifiers() & Qt.KeyboardModifier.ControlModifier
            )

            if is_right_click:
                self._show_context_menu(event.pos())
                event.accept()
                return
            if event.button() == Qt.MouseButton.LeftButton:
                self.node_clicked.emit(hit.node_id)

        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent | None) -> None:
        if event is None:
            return
        if self._is_panning:
            self._is_panning = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent | None) -> None:
        if event is None:
            return
        hit = self._rect_at(event.pos())
        if hit:
            self.node_double_clicked.emit(hit.node_id)

    def _show_context_menu(self, pos: QPoint) -> None:
        hit = self._rect_at(pos)
        if not hit:
            return

        menu = BioMenu(self)

        action_rename = menu.addAction("Rename Gate")
        action_delete = menu.addAction("Delete Gate")

        sid = self._state.view.current_sample_id
        action_propagate = None
        if sid:
            sample = self._state.data.experiment.samples.get(sid)
            if sample and len(sample.group_ids) > 1:
                menu.addSeparator()
                action_propagate = menu.addAction("Propagate Gate to All Groups")

        # Ensure root node cannot be deleted or renamed if necessary, but UI handles that via node logic
        if not hit.parent_ids:
            if action_delete:
                action_delete.setEnabled(False)
            if action_rename:
                action_rename.setEnabled(False)
            if action_propagate:
                action_propagate.setEnabled(False)

        action = menu.exec(self.mapToGlobal(pos))

        # Defer signal emissions so the context menu is fully torn down by Qt
        # before any follow-up dialog (e.g. QInputDialog for rename) is shown.
        # Without this the menu briefly re-appears after the dialog closes.
        from PyQt6.QtCore import QTimer

        node_id = hit.node_id  # capture before any closure captures `hit`
        if action == action_rename:
            QTimer.singleShot(0, lambda: self.rename_requested.emit(node_id))
        elif action == action_delete:
            QTimer.singleShot(0, lambda: self.delete_requested.emit(node_id))
        elif action_propagate and action == action_propagate:
            QTimer.singleShot(0, lambda: self.propagate_requested.emit(node_id))
