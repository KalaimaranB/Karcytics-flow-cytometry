"""Graphical representation of a Gate population on the canvas."""

from collections.abc import Callable
from typing import Any

from karcytics_sdk.plugin.theme_fallback import Colors, Fonts
from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QImage, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import (
    QGraphicsObject,
    QGraphicsSceneHoverEvent,
    QGraphicsSceneMouseEvent,
    QStyleOptionGraphicsItem,
    QWidget,
)


class NodeItem(QGraphicsObject):
    """A graphical node representing a single population gate."""

    # Emitted when double-clicked
    node_double_clicked = pyqtSignal(str)
    delete_requested = pyqtSignal(str)
    rename_requested = pyqtSignal(str)
    link_delete_requested = pyqtSignal(str, str)  # source_node_id, target_node_id

    # Drag signals
    edge_drag_started = pyqtSignal(str, QPointF)  # node_id, start_pos
    edge_dragged = pyqtSignal(QPointF)  # current_scene_pos
    edge_drag_released = pyqtSignal(str, QPointF)  # source_node_id, release_scene_pos

    # Dimensions
    WIDTH = 200
    HEIGHT = 270
    RADIUS = 8
    PORT_RADIUS = 6

    def __init__(self, node_id: str, name: str, parent=None):
        super().__init__(parent)
        self.node_id = node_id
        self.name = name

        # Data
        self.event_count = 0
        self.parent_percentage = 0.0
        self.is_logic_node = False
        self.is_umap_parent = False
        # Set by CanvasManager._apply_stats_to_item from node.statistics —
        # see DagEvaluator._propagate_estimation for what these mean.
        self.is_estimated = False
        self.is_scale_valid = True
        self.logic_operator = "AND"
        self.parent_names: list[str] = []  # names of real (non-root) parents for logic nodes
        self.per_parent_pcts: dict = {}  # per-parent overlap stats for logic nodes
        # The single real (non-root) parent's own name, for a non-logic
        # node's "% of parent {name}" line — spelled out because the
        # node's *statistical* parent (whatever its % is actually computed
        # against) doesn't always match its edge's visual source at a
        # glance, e.g. a UMAP cluster's edge is drawn from the "UMAP
        # Reduction" container it's grouped under either way.
        self.parent_name: str = ""

        # Set externally by CanvasManager; returns (incoming, outgoing) logic-node
        # links for this node as (node_id, name) pairs, for the context menu.
        self.get_logic_links: (
            Callable[[str], tuple[list[tuple[str, str]], list[tuple[str, str]]]] | None
        ) = None

        # State
        self.x_param: str | None = None
        self.y_param: str | None = None
        self.setFlag(QGraphicsObject.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsObject.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsObject.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setAcceptHoverEvents(True)
        self._is_hovered = False
        self._hovered_port: Any | None = None  # 'input' or 'output'
        self._is_dragging_edge = False
        self._orientation = "vertical"

        self._plot_pixmap: QPixmap | None = None

    def _mark_dirty(self) -> None:
        """Repaint this item, routing through the scene's dirty-tracking when available.

        Falls back to a bare update() when this item isn't attached to a
        DirtyTrackingGraphicsScene (e.g. constructed standalone in a test) —
        scene() is also None until the item is actually added to a scene.
        """
        scene = self.scene()
        if scene is not None and hasattr(scene, "mark_dirty"):
            scene.mark_dirty(self)
        else:
            self.update()

    def set_orientation(self, orientation: str) -> None:
        # boundingRect() depends on _orientation (see below) — must call this
        # before mutating it, or MinimalViewportUpdate can leave stale/clipped
        # pixels where the item's bounds just changed.
        self.prepareGeometryChange()
        self._orientation = orientation
        self._mark_dirty()

    def set_plot_image(self, qimg: QImage) -> None:
        """Set the rendered plot image."""
        from PyQt6.QtGui import QPixmap

        self._plot_pixmap = QPixmap.fromImage(qimg)
        self._mark_dirty()

    def set_plot_error(self) -> None:
        """Set the plot error state to display a No Data message."""
        self._plot_error = True
        self._mark_dirty()

    def clear_plot_image(self) -> None:
        """Discard the rendered plot image, reverting to the blank placeholder."""
        self._plot_pixmap = None
        self._plot_error = False
        self._mark_dirty()

    def boundingRect(self) -> QRectF:
        # Include a little padding for the ports that stick out
        if self._orientation == "vertical":
            return QRectF(0, -self.PORT_RADIUS, self.WIDTH, self.HEIGHT + self.PORT_RADIUS * 2)
        return QRectF(-self.PORT_RADIUS, 0, self.WIDTH + self.PORT_RADIUS * 2, self.HEIGHT)

    def paint(  # noqa: PLR0912, PLR0915
        self,
        painter: QPainter | None,
        option: QStyleOptionGraphicsItem | None,
        widget: QWidget | None = None,
    ) -> None:
        if painter is None:
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Base Card path
        path = QPainterPath()
        path.addRoundedRect(0, 0, self.WIDTH, self.HEIGHT, self.RADIUS, self.RADIUS)

        # Colors
        bg_color = QColor(Colors.BG_MEDIUM)

        if self.is_logic_node:
            if self.logic_operator == "AND":
                accent = QColor(Colors.ACCENT_PRIMARY)
            elif self.logic_operator == "OR":
                accent = QColor(Colors.ACCENT_WARNING)
            elif self.logic_operator == "NOT":
                accent = QColor(Colors.ACCENT_DANGER)
            else:
                accent = QColor(Colors.BG_MEDIUM)

            # Blend 20% accent with 80% BG_MEDIUM
            r = int(accent.red() * 0.2 + bg_color.red() * 0.8)
            g = int(accent.green() * 0.2 + bg_color.green() * 0.8)
            b = int(accent.blue() * 0.2 + bg_color.blue() * 0.8)
            bg_color = QColor(r, g, b)

        if self._is_hovered:
            bg_color = bg_color.lighter(120)

        border_color = QColor(Colors.ACCENT_PRIMARY) if self.isSelected() else QColor(Colors.BORDER)
        border_width = 2 if self.isSelected() else 1

        # Draw Shadow / Body
        painter.setBrush(QBrush(bg_color))
        painter.setPen(QPen(border_color, border_width))
        painter.drawPath(path)

        # Draw Ports
        painter.setPen(Qt.PenStyle.NoPen)

        # Input Port
        in_color = (
            QColor(Colors.ACCENT_PRIMARY).lighter(150)
            if self._hovered_port == "input"
            else QColor(Colors.ACCENT_PRIMARY)
        )
        painter.setBrush(QBrush(in_color))

        in_pos = (
            QPointF(self.WIDTH / 2, 0)
            if self._orientation == "vertical"
            else QPointF(0, self.HEIGHT / 2)
        )

        painter.drawEllipse(
            in_pos,
            self.PORT_RADIUS * (1.5 if self._hovered_port == "input" else 1.0),
            self.PORT_RADIUS * (1.5 if self._hovered_port == "input" else 1.0),
        )

        # Output Port
        out_color = (
            QColor(Colors.ACCENT_PRIMARY).lighter(150)
            if self._hovered_port == "output"
            else QColor(Colors.ACCENT_PRIMARY)
        )
        painter.setBrush(QBrush(out_color))

        out_pos = (
            QPointF(self.WIDTH / 2, self.HEIGHT)
            if self._orientation == "vertical"
            else QPointF(self.WIDTH, self.HEIGHT / 2)
        )

        painter.drawEllipse(
            out_pos,
            self.PORT_RADIUS * (1.5 if self._hovered_port == "output" else 1.0),
            self.PORT_RADIUS * (1.5 if self._hovered_port == "output" else 1.0),
        )

        # Draw Text
        painter.setPen(QColor(Colors.FG_PRIMARY))
        font = QFont(Fonts.FAMILY_UI, Fonts.SIZE_SMALL, QFont.Weight.Bold)
        painter.setFont(font)

        text_rect = QRectF(12, 12, self.WIDTH - 24, 20)
        painter.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self.name,
        )

        # Draw Stats
        if self.is_estimated:
            painter.setPen(
                QColor(Colors.ACCENT_WARNING if self.is_scale_valid else Colors.ACCENT_DANGER)
            )
        else:
            painter.setPen(QColor(Colors.FG_SECONDARY))
        stats_font = QFont(Fonts.FAMILY_UI, Fonts.SIZE_SMALL - 1)
        painter.setFont(stats_font)

        count_str = f"{self.event_count:,}{'*' if self.is_estimated else ''}"
        stats_rect = QRectF(12, 36, self.WIDTH - 24, 60)
        if self.is_logic_node:
            if self.per_parent_pcts:
                # Rich display: total count + per-parent overlap %
                lines = [f"{count_str} events ({self.logic_operator})"]
                for info in self.per_parent_pcts.values():
                    pname = info.get("name", "?")
                    pct = info.get("pct_overlap", 0.0)
                    pc = info.get("parent_count", 0)
                    mark = "*" if info.get("is_scaled") else ""
                    lines.append(f"  {pct:.1f}%{mark} of {pname} ({pc:,})")
                stats_text = "\n".join(lines)
            else:
                lines = [f"{count_str} events intersected"]
                if self.parent_names:
                    lines += ["from:"] + [f"  • {n}" for n in self.parent_names]
                else:
                    lines.append("(no inputs wired yet)")
                stats_text = "\n".join(lines)
        else:
            parent_label = f" {self.parent_name}" if self.parent_name else ""
            stats_text = (
                f"{count_str} events\n{self.parent_percentage:.1f}% of parent{parent_label}"
            )
        painter.drawText(
            stats_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
            stats_text,
        )

        # Draw Plot Pixmap (including for logic nodes which now render FSC/SSC)
        if self._plot_pixmap and not self.is_umap_parent:
            plot_rect = QRectF(10, 100, self.WIDTH - 20, self.HEIGHT - 110)

            # To ensure the pixmap obeys the rounded rectangle bounds if it touches the bottom,
            # we draw it directly. Since we have a margin (10px from edges), it naturally fits
            # inside the rounded boundaries without needing clipping.
            scaled_pixmap = self._plot_pixmap.scaled(
                int(plot_rect.width()),
                int(plot_rect.height()),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )

            # Center the pixmap within the allocated plot_rect
            dx = plot_rect.x() + (plot_rect.width() - scaled_pixmap.width()) / 2
            dy = plot_rect.y() + (plot_rect.height() - scaled_pixmap.height()) / 2
            painter.drawPixmap(QPointF(dx, dy), scaled_pixmap)

            # Draw a subtle border around the plot
            painter.setPen(QPen(QColor(Colors.BORDER), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(QRectF(dx, dy, scaled_pixmap.width(), scaled_pixmap.height()))

            # Draw axis labels
            if self.x_param or self.y_param:
                label_font = QFont(Fonts.FAMILY_UI, 8, QFont.Weight.Bold)
                painter.setFont(label_font)
                fm = painter.fontMetrics()

                pill_bg = QColor(Colors.BG_DARKEST)
                pill_bg.setAlpha(200)
                text_fg = QColor(Colors.FG_PRIMARY)

                # Bottom X-axis label
                if self.x_param:
                    x_text = self.x_param
                    x_tw = fm.horizontalAdvance(x_text)
                    x_th = fm.height()

                    x_cx = dx + scaled_pixmap.width() / 2
                    x_by = dy + scaled_pixmap.height() - 4

                    x_pill_rect = QRectF(x_cx - x_tw / 2 - 4, x_by - x_th, x_tw + 8, x_th)

                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QBrush(pill_bg))
                    painter.drawRoundedRect(x_pill_rect, 3, 3)

                    painter.setPen(QPen(text_fg))
                    painter.drawText(x_pill_rect, Qt.AlignmentFlag.AlignCenter, x_text)

                # Left Y-axis label
                if self.y_param:
                    painter.save()
                    y_text = self.y_param
                    y_tw = fm.horizontalAdvance(y_text)
                    y_th = fm.height()

                    y_cx = dx + 4 + y_th / 2
                    y_cy = dy + scaled_pixmap.height() / 2

                    painter.translate(y_cx, y_cy)
                    painter.rotate(-90)

                    y_pill_rect = QRectF(-y_tw / 2 - 4, -y_th / 2, y_tw + 8, y_th)

                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QBrush(pill_bg))
                    painter.drawRoundedRect(y_pill_rect, 3, 3)

                    painter.setPen(QPen(text_fg))
                    painter.drawText(y_pill_rect, Qt.AlignmentFlag.AlignCenter, y_text)
                    painter.restore()

        elif self.is_umap_parent:
            # Draw Dynamic Dimensionality Projection Icon
            plot_rect = QRectF(10, 70, self.WIDTH - 20, self.HEIGHT - 80)

            painter.setPen(QPen(QColor(Colors.BORDER), 1, Qt.PenStyle.DashLine))
            painter.setBrush(QBrush(QColor(Colors.BG_MEDIUM)))
            painter.drawRoundedRect(plot_rect, 4, 4)

            # Center of the rendering area
            cx = plot_rect.center().x()
            cy = plot_rect.center().y()

            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

            # Helper to create isometric points (30-degree projection)
            import math

            angle = math.radians(30)
            cos_a = math.cos(angle)
            sin_a = math.sin(angle)

            def iso(x: float, y: float, z: float) -> QPointF:
                iso_x = cx + (x - y) * cos_a
                iso_y = cy + (x + y) * sin_a - z
                return QPointF(iso_x, iso_y)

            s = 20  # Cube half-size (width/depth)
            cube_z = 25  # Height of cube above center
            grid_z = -35  # Grid level below center

            # 1. Draw 2D isometric grid (flattened projection)
            painter.setPen(QPen(QColor(Colors.BORDER), 1))
            grid_steps = 4
            step_size = (s * 2) / grid_steps
            # Draw grid lines
            for i in range(grid_steps + 1):
                pos = -s + i * step_size
                painter.drawLine(iso(pos, -s, grid_z), iso(pos, s, grid_z))
                painter.drawLine(iso(-s, pos, grid_z), iso(s, pos, grid_z))

            # 2. Draw projection lines (dashed) connecting cube bottom to grid
            proj_pen = QPen(QColor(Colors.FG_DISABLED), 1, Qt.PenStyle.DashLine)
            painter.setPen(proj_pen)
            painter.drawLine(iso(-s, -s, cube_z - s), iso(-s, -s, grid_z))
            painter.drawLine(iso(s, -s, cube_z - s), iso(s, -s, grid_z))
            painter.drawLine(iso(-s, s, cube_z - s), iso(-s, s, grid_z))
            painter.drawLine(iso(s, s, cube_z - s), iso(s, s, grid_z))

            # 3. Draw 3D Cube
            b1 = iso(-s, -s, cube_z - s)
            b2 = iso(s, -s, cube_z - s)
            b3 = iso(s, s, cube_z - s)
            b4 = iso(-s, s, cube_z - s)

            t1 = iso(-s, -s, cube_z + s)
            t2 = iso(s, -s, cube_z + s)
            t3 = iso(s, s, cube_z + s)
            t4 = iso(-s, s, cube_z + s)

            cube_pen = QPen(QColor(Colors.ACCENT_PRIMARY), 2)
            cube_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(cube_pen)

            # Fill the top face to give it a glassy solidity
            top_path = QPainterPath()
            top_path.moveTo(t1)
            top_path.lineTo(t2)
            top_path.lineTo(t3)
            top_path.lineTo(t4)
            top_path.closeSubpath()

            fill_color = QColor(Colors.ACCENT_PRIMARY)
            fill_color.setAlpha(40)
            painter.setBrush(QBrush(fill_color))
            painter.drawPath(top_path)

            # Remove brush for wireframe lines
            painter.setBrush(Qt.BrushStyle.NoBrush)

            # Bottom edges
            painter.drawLine(b1, b2)
            painter.drawLine(b2, b3)
            painter.drawLine(b3, b4)
            painter.drawLine(b4, b1)

            # Vertical edges
            painter.drawLine(b1, t1)
            painter.drawLine(b2, t2)
            painter.drawLine(b3, t3)
            painter.drawLine(b4, t4)

            painter.restore()
        else:
            # Draw loading or error placeholder
            plot_rect = QRectF(10, 100, self.WIDTH - 20, self.HEIGHT - 110)

            painter.setPen(QPen(QColor(Colors.BORDER), 1, Qt.PenStyle.DashLine))
            painter.setBrush(QBrush(QColor(Colors.BG_MEDIUM)))
            painter.drawRoundedRect(plot_rect, 4, 4)

            painter.setPen(QPen(QColor(Colors.FG_SECONDARY)))
            font = QFont(Fonts.FAMILY_UI, 10, QFont.Weight.Normal)
            painter.setFont(font)

            text_rect = QRectF(
                plot_rect.x(),
                plot_rect.y() + plot_rect.height() / 2 - 20,
                plot_rect.width(),
                40,
            )
            msg = "No Data" if getattr(self, "_plot_error", False) else "Loading plot..."
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, msg)

    def get_input_port_pos(self) -> QPointF:
        """Get scene coordinates of the input port."""
        pos = (
            QPointF(self.WIDTH / 2, 0)
            if self._orientation == "vertical"
            else QPointF(0, self.HEIGHT / 2)
        )
        return self.mapToScene(pos)

    def get_output_port_pos(self) -> QPointF:
        """Get scene coordinates of the output port."""
        pos = (
            QPointF(self.WIDTH / 2, self.HEIGHT)
            if self._orientation == "vertical"
            else QPointF(self.WIDTH, self.HEIGHT / 2)
        )
        return self.mapToScene(pos)

    def _get_port_at(self, pos: QPointF) -> str | None:
        """Return 'input' or 'output' if pos is near a port, else None."""
        # Check input port
        in_pos = (
            QPointF(self.WIDTH / 2, 0)
            if self._orientation == "vertical"
            else QPointF(0, self.HEIGHT / 2)
        )
        if (pos - in_pos).manhattanLength() <= self.PORT_RADIUS * 2:
            return "input"

        # Check output port
        out_pos = (
            QPointF(self.WIDTH / 2, self.HEIGHT)
            if self._orientation == "vertical"
            else QPointF(self.WIDTH, self.HEIGHT / 2)
        )
        if (pos - out_pos).manhattanLength() <= self.PORT_RADIUS * 2:
            return "output"

        return None

    # ── Events ────────────────────────────────────────────────────────

    def hoverEnterEvent(self, event: QGraphicsSceneHoverEvent | None) -> None:
        if event is None:
            return
        self._is_hovered = True
        self._mark_dirty()
        super().hoverEnterEvent(event)

    def hoverMoveEvent(self, event: QGraphicsSceneHoverEvent | None) -> None:
        if event is None:
            return
        port = self._get_port_at(event.pos())
        if port != self._hovered_port:
            self._hovered_port = port
            if port:
                self.setCursor(Qt.CursorShape.CrossCursor)
            else:
                self.unsetCursor()
            self._mark_dirty()
        super().hoverMoveEvent(event)

    def hoverLeaveEvent(self, event: QGraphicsSceneHoverEvent | None) -> None:
        if event is None:
            return
        self._is_hovered = False
        if self._hovered_port:
            self._hovered_port = None
            self.unsetCursor()
        self._mark_dirty()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent | None) -> None:
        if event is None:
            return
        port = self._get_port_at(event.pos())
        if port == "output" and event.button() == Qt.MouseButton.LeftButton:
            self._is_dragging_edge = True
            self.edge_drag_started.emit(self.node_id, self.get_output_port_pos())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QGraphicsSceneMouseEvent | None) -> None:
        if event is None:
            return
        if self._is_dragging_edge:
            self.edge_dragged.emit(event.scenePos())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent | None) -> None:
        if event is None:
            return
        if self._is_dragging_edge:
            self._is_dragging_edge = False
            self.edge_drag_released.emit(self.node_id, event.scenePos())
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QGraphicsSceneMouseEvent | None) -> None:
        if event is None:
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self.node_double_clicked.emit(self.node_id)
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event) -> None:
        if event is None:
            return
        if self.name == "All Events":
            event.accept()
            return

        from karcytics_sdk.plugin.components import BioMenu

        menu = BioMenu()
        rename_action = menu.addAction(
            "✏️  Rename Node" if self.is_logic_node else "✏️  Rename Population"
        )
        delete_action = menu.addAction(
            "🗑️  Delete Node" if self.is_logic_node else "🗑️  Delete Population"
        )

        link_action_map: dict = {}
        if self.get_logic_links is not None:
            incoming, outgoing = self.get_logic_links(self.node_id)
            if incoming or outgoing:
                menu.addSeparator()
            if incoming:
                in_menu = BioMenu(title="🔗 Delete Incoming Link")
                menu.addMenu(in_menu)
                for parent_id, parent_name in incoming:
                    act = in_menu.addAction(f"From: {parent_name}")
                    link_action_map[act] = (parent_id, self.node_id)
            if outgoing:
                out_menu = BioMenu(title="🔗 Delete Outgoing Link")
                menu.addMenu(out_menu)
                for child_id, child_name in outgoing:
                    act = out_menu.addAction(f"To: {child_name}")
                    link_action_map[act] = (self.node_id, child_id)

        action = menu.exec(event.screenPos())
        if action == rename_action:
            self.rename_requested.emit(self.node_id)
        elif action == delete_action:
            self.delete_requested.emit(self.node_id)
        elif action in link_action_map:
            source_id, target_id = link_action_map[action]
            self.link_delete_requested.emit(source_id, target_id)
        event.accept()

    def itemChange(self, change, value):
        if change == QGraphicsObject.GraphicsItemChange.ItemPositionHasChanged:
            # We will catch this in the manager to update edge positions
            pass
        return super().itemChange(change, value)
