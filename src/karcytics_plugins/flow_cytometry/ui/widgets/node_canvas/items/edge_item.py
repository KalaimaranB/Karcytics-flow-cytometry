"""Graphical representation of a wire between two nodes."""

from karcytics_sdk.plugin.theme_fallback import Colors
from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QGraphicsPathItem, QStyleOptionGraphicsItem, QWidget


class EdgeItem(QGraphicsPathItem):
    """A bezier curve connecting the output of one NodeItem to the input of another."""

    def __init__(self, source_node, target_node, parent=None):
        super().__init__(parent)
        self.source_node = source_node
        self.target_node = target_node
        self.is_logic_edge = getattr(target_node, "is_logic_node", False)
        self._orientation = "vertical"

        self.setZValue(-1)  # Draw lines under the nodes

        # Styling
        self._pen = QPen(QColor(Colors.FG_DISABLED), 2)
        self._pen.setStyle(Qt.PenStyle.SolidLine)
        self._pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        self.setPen(self._pen)

        self.setFlag(QGraphicsPathItem.GraphicsItemFlag.ItemIsSelectable, True)

        self.update_position()

    def itemChange(self, change, value):
        if change == QGraphicsPathItem.GraphicsItemChange.ItemSelectedHasChanged:
            if value:
                self._pen.setColor(QColor(Colors.ACCENT_PRIMARY))
                self._pen.setWidth(3)
            else:
                self._pen.setColor(QColor(Colors.FG_DISABLED))
                self._pen.setWidth(2)
            self.setPen(self._pen)
        return super().itemChange(change, value)

    def set_orientation(self, orientation: str) -> None:
        self._orientation = orientation
        self.update_position()

    def update_position(self) -> None:
        """Recalculate the bezier curve based on the current positions of connected nodes."""
        if not self.source_node or not self.target_node:
            return

        start_pos = self.source_node.get_output_port_pos()
        end_pos = self.target_node.get_input_port_pos()

        # Calculate bezier control points for a smooth S-curve
        if self._orientation == "vertical":
            dist = abs(end_pos.y() - start_pos.y())
            control_offset = max(dist * 0.5, 40.0)  # Ensure minimum curve tightness

            ctrl1 = QPointF(start_pos.x(), start_pos.y() + control_offset)
            ctrl2 = QPointF(end_pos.x(), end_pos.y() - control_offset)
        else:
            dist = abs(end_pos.x() - start_pos.x())
            control_offset = max(dist * 0.5, 40.0)  # Ensure minimum curve tightness

            ctrl1 = QPointF(start_pos.x() + control_offset, start_pos.y())
            ctrl2 = QPointF(end_pos.x() - control_offset, end_pos.y())

        path = QPainterPath(start_pos)
        path.cubicTo(ctrl1, ctrl2, end_pos)

        self.setPath(path)

    def paint(
        self,
        painter: QPainter | None,
        option: QStyleOptionGraphicsItem | None,
        widget: QWidget | None = None,
    ) -> None:
        if painter is None:
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        super().paint(painter, option, widget)
