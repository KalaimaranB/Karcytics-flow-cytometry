"""Node Canvas - View layer for the Pipeline feature."""

from typing import Any

from karcytics_sdk.plugin.rendering.graphics_scene import (
    DirtyTrackingGraphicsScene,
    DirtyTrackingGraphicsView,
)
from karcytics_sdk.plugin.theme_fallback import Colors
from PyQt6.QtCore import QPointF, QRect, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QKeyEvent, QMouseEvent, QPainter, QPen, QPolygonF, QWheelEvent
from PyQt6.QtWidgets import (
    QGraphicsView,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from karcytics_plugins.flow_cytometry.analysis.state import FlowState

from .canvas_manager import CanvasManager


class _CanvasGraphicsView(DirtyTrackingGraphicsView):
    """Infinite panning and zooming view for the node canvas.

    Defaults to MinimalViewportUpdate (via DirtyTrackingGraphicsView) instead
    of the FullViewportUpdate this used to force on every single node/edge
    change — see NodeItem.set_orientation()'s prepareGeometryChange() fix,
    which the previous FullViewportUpdate mode silently masked a missing
    instance of.
    """

    def __init__(self, scene: DirtyTrackingGraphicsScene, parent: QWidget | None = None) -> None:
        super().__init__(scene, parent)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)

        self._is_panning = False
        self._pan_start_pos = QPointF()

        self._apply_theme_styles()

    def _apply_theme_styles(self) -> None:
        """Dynamically refresh colors when theme changes."""
        self.setBackgroundBrush(QColor(Colors.BG_DARKEST))
        self._grid_size = 40
        self._grid_pen = QPen(QColor(Colors.BORDER), 1)
        vp = self.viewport()
        if vp:
            vp.update()
        self._pan_start_pos = QPointF()

    def drawBackground(self, painter: QPainter | None, rect: QRectF | None) -> None:
        """Draw the infinite dot grid background."""
        if painter is None or rect is None:
            return
        super().drawBackground(painter, rect)
        painter.setPen(self._grid_pen)

        left = int(rect.left()) - (int(rect.left()) % self._grid_size)
        top = int(rect.top()) - (int(rect.top()) % self._grid_size)

        # Draw a dot grid
        points = []
        for x in range(left, int(rect.right()), self._grid_size):
            for y in range(top, int(rect.bottom()), self._grid_size):
                points.append(QPointF(x, y))

        painter.drawPoints(QPolygonF(points))

    def wheelEvent(self, event: QWheelEvent | None) -> None:
        """Zoom in/out with the scroll wheel."""
        if event is None:
            return
        zoom_in_factor = 1.15
        zoom_out_factor = 1.0 / zoom_in_factor

        # Check angle delta to determine zoom direction
        if event.angleDelta().y() > 0:
            zoom_factor = zoom_in_factor
        else:
            zoom_factor = zoom_out_factor

        current_zoom = self.transform().m11()
        if zoom_factor > 1.0 and current_zoom >= 3.0:  # noqa: PLR2004
            return
        if zoom_factor < 1.0 and current_zoom <= 0.1:  # noqa: PLR2004
            return

        self.scale(zoom_factor, zoom_factor)

    def zoom_in(self) -> None:
        if self.transform().m11() < 3.0:  # noqa: PLR2004
            self.scale(1.2, 1.2)

    def zoom_out(self) -> None:
        if self.transform().m11() > 0.1:  # noqa: PLR2004
            self.scale(1.0 / 1.2, 1.0 / 1.2)

    def mousePressEvent(self, event: QMouseEvent | None) -> None:
        """Middle click or Space+Left click to pan."""
        if event is None:
            return
        if event.button() == Qt.MouseButton.MiddleButton:
            self._is_panning = True
            self._pan_start_pos = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent | None) -> None:
        if event is None:
            return
        if self._is_panning:
            delta = event.position() - self._pan_start_pos
            self._pan_start_pos = event.position()

            # Map delta to scene coordinates relative to view scale
            hs = self.horizontalScrollBar()
            vs = self.verticalScrollBar()
            if hs:
                hs.setValue(hs.value() - int(delta.x()))
            if vs:
                vs.setValue(vs.value() - int(delta.y()))

            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent | None) -> None:
        if event is None:
            return
        if event.button() == Qt.MouseButton.MiddleButton:
            self._is_panning = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class NodeCanvas(QWidget):
    """The central widget for the Node Canvas view."""

    node_double_clicked = pyqtSignal(str)
    node_removed = pyqtSignal(str)  # node_id
    connection_requested = pyqtSignal(str, str, str)  # sample_id, source_id, target_id
    connection_removed = pyqtSignal(str, str, str)  # sample_id, source_id, target_id

    def __init__(self, state: FlowState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PipelineCanvas")
        self.state = state
        self._setup_ui()

        self.current_sample_id: Any | None = None

        # Initialize the manager which builds and updates the scene
        self._manager = CanvasManager(self.state, self._scene)
        self._manager.node_double_clicked.connect(self.node_double_clicked.emit)
        self._manager.node_delete_requested.connect(self._confirm_and_delete_node)
        self._manager.connection_requested.connect(
            lambda src, tgt: (
                self.connection_requested.emit(self.current_sample_id, src, tgt)
                if self.current_sample_id
                else None
            )
        )
        self._manager.connection_removed.connect(
            lambda src, tgt: (
                self.connection_removed.emit(self.current_sample_id, src, tgt)
                if self.current_sample_id
                else None
            )
        )

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._scene = DirtyTrackingGraphicsScene(self)
        # Give the scene a large initial rect to allow panning around
        self._scene.setSceneRect(-5000, -5000, 10000, 10000)

        self._view = _CanvasGraphicsView(self._scene)
        layout.addWidget(self._view)

        # ── Overlay Controls ──
        overlay_layout = QHBoxLayout(self._view)
        overlay_layout.setAlignment(Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight)
        overlay_layout.setContentsMargins(0, 0, 16, 16)
        overlay_layout.setSpacing(8)

        btn_style = (
            f"QPushButton {{"
            f"  background: {Colors.BG_MEDIUM};"
            f"  color: {Colors.FG_PRIMARY};"
            f"  border: 1px solid {Colors.BORDER};"
            f"  border-radius: 4px;"
            f"  padding: 6px 12px;"
            f"}}"
            f"QPushButton:hover {{"
            f"  background: {Colors.BG_LIGHT};"
            f"  border: 1px solid {Colors.ACCENT_PRIMARY};"
            f"}}"
        )

        self.btn_zoom_in = QPushButton("Zoom In (+)")
        self.btn_zoom_in.setStyleSheet(btn_style)
        self.btn_zoom_in.clicked.connect(self._view.zoom_in)

        self.btn_zoom_out = QPushButton("Zoom Out (-)")
        self.btn_zoom_out.setStyleSheet(btn_style)
        self.btn_zoom_out.clicked.connect(self._view.zoom_out)

        self.btn_fit = QPushButton("Fit View (F)")
        self.btn_fit.setStyleSheet(btn_style)
        self.btn_fit.clicked.connect(self.center_on_nodes)

        self.btn_pan = QPushButton("Pan Tool")
        self.btn_pan.setCheckable(True)
        self.btn_pan.setStyleSheet(btn_style)
        self.btn_pan.toggled.connect(self._on_pan_toggled)

        overlay_layout.addWidget(self.btn_pan)
        overlay_layout.addWidget(self.btn_zoom_out)
        overlay_layout.addWidget(self.btn_zoom_in)
        overlay_layout.addWidget(self.btn_fit)

        self._apply_theme_styles()

    def _apply_theme_styles(self) -> None:
        """Dynamically refresh colors when theme changes."""
        from PyQt6.QtGui import QColor

        self.setStyleSheet(f"background: {Colors.BG_DARKEST};")
        if hasattr(self, "_view"):
            self._view.setBackgroundBrush(QColor(Colors.BG_DARKEST))
        btn_style = (
            f"QPushButton {{"
            f"  background: {Colors.BG_MEDIUM};"
            f"  color: {Colors.FG_PRIMARY};"
            f"  border: 1px solid {Colors.BORDER};"
            f"  border-radius: 4px;"
            f"  padding: 6px 12px;"
            f"}}"
            f"QPushButton:hover {{"
            f"  background: {Colors.BG_LIGHT};"
            f"  border: 1px solid {Colors.ACCENT_PRIMARY};"
            f"}}"
        )
        for btn in (
            getattr(self, "btn_zoom_in", None),
            getattr(self, "btn_zoom_out", None),
            getattr(self, "btn_fit", None),
            getattr(self, "btn_pan", None),
        ):
            if btn:
                btn.setStyleSheet(btn_style)
            self._view._apply_theme_styles()

    def _on_pan_toggled(self, checked: bool) -> None:
        if checked:
            self._view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        else:
            self._view.setDragMode(QGraphicsView.DragMode.NoDrag)

    def set_sample(self, sample_id: str) -> None:
        """Switch the canvas to display a specific sample."""
        from PyQt6.QtCore import QTimer

        self.current_sample_id = sample_id
        self._manager.load_sample(sample_id)
        QTimer.singleShot(50, self.center_on_nodes)

    def set_orientation(self, orientation: str) -> None:
        """Update the canvas orientation (horizontal/vertical)."""
        from PyQt6.QtCore import QTimer

        self._manager.set_orientation(orientation)
        QTimer.singleShot(50, self.center_on_nodes)

    def center_on_nodes(self) -> None:
        """Auto-frame the view to fit the current nodes."""
        rect = self._scene.itemsBoundingRect()
        if not rect.isNull():
            # Pad the rect a bit so nodes aren't touching edges
            margin = 50.0
            rect.adjust(-margin, -margin, margin, margin)
            self._view.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)

    def get_tutorial_target_rects(self, step: Any) -> list[QRect]:
        """Academy duck-typing hook (see AcademyStepDriver._collect_canvas_target_rects
        in the SDK): lets a tutorial step spotlight specific named pipeline
        nodes by real gate-tree node name, via
        step.metadata["pipeline_highlight_node_names"] — individual nodes
        are QGraphicsItems, not QWidgets, so they're otherwise invisible to
        the driver's normal findChildren(QWidget, ...) spotlight lookup.
        """
        names = (getattr(step, "metadata", None) or {}).get("pipeline_highlight_node_names")
        if not names:
            return []
        wanted = {n.lower() for n in names}
        matching_items = [
            item for item in self._manager._node_items.values() if item.name.lower() in wanted
        ]
        if not matching_items:
            return []

        viewport = self._view.viewport()
        if viewport is None:
            return []

        union_rect = matching_items[0].sceneBoundingRect()
        for item in matching_items[1:]:
            union_rect = union_rect.united(item.sceneBoundingRect())

        # Bring the requested nodes into view first if they aren't already —
        # e.g. right after adding a new AND node widens the layout enough
        # that earlier nodes can fall outside the current viewport. Reuses
        # center_on_nodes()'s own padding/fit logic, just scoped to only the
        # nodes this step actually cares about.
        visible_scene_rect = self._view.mapToScene(viewport.rect()).boundingRect()
        if not visible_scene_rect.contains(union_rect):
            margin = 50.0
            self._view.fitInView(
                union_rect.adjusted(-margin, -margin, margin, margin),
                Qt.AspectRatioMode.KeepAspectRatio,
            )

        rects = []
        for item in matching_items:
            view_rect = self._view.mapFromScene(item.sceneBoundingRect()).boundingRect()
            top_left_global = viewport.mapToGlobal(view_rect.topLeft())
            rects.append(QRect(top_left_global, view_rect.size()))
        return rects

    def _confirm_and_delete_node(self, node_id: str) -> None:
        """Prompt confirmation if the node has child populations, then delete."""
        if not self.current_sample_id or not node_id:
            return

        sample = self.state.data.experiment.samples.get(self.current_sample_id)
        if not sample or not sample.gate_tree:
            return

        node = sample.gate_tree.find_node_by_id(node_id)
        if not node or node.is_root:
            return

        # Check if the node has any child populations
        child_names: list[str] = []

        def _collect_child_names(cur) -> None:
            for ch in cur.children:
                child_names.append(ch.name)
                _collect_child_names(ch)

        _collect_child_names(node)

        if child_names:
            from PyQt6.QtWidgets import QMessageBox

            msg_box = QMessageBox(self)
            msg_box.setIcon(QMessageBox.Icon.Warning)
            msg_box.setWindowTitle(
                "Delete Logic Node" if node.is_logic_node else "Delete Population"
            )
            max_display = 6
            count = len(child_names)
            children_str = "\n".join(f"• {c}" for c in child_names[:max_display])
            if count > max_display:
                children_str += f"\n... and {count - max_display} more"

            msg_box.setText(
                f"Deleting '{node.name}' will also delete all of its {count} child population{'s' if count != 1 else ''}:\n\n"
                f"{children_str}\n\n"
                f"Are you sure you want to continue?"
            )
            msg_box.setStandardButtons(
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            msg_box.setDefaultButton(QMessageBox.StandardButton.No)

            if msg_box.exec() != QMessageBox.StandardButton.Yes:
                return

        self.node_removed.emit(node_id)

    def keyPressEvent(self, event: QKeyEvent | None) -> None:
        if event is None:
            return
        if event.key() == Qt.Key.Key_F:
            self.center_on_nodes()
            event.accept()
        elif event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            from .items.edge_item import EdgeItem
            from .items.node_item import NodeItem

            for item in self._scene.selectedItems():
                if isinstance(item, EdgeItem):
                    self._manager.connection_removed.emit(
                        item.source_node.node_id, item.target_node.node_id
                    )
                elif isinstance(item, NodeItem):
                    self._confirm_and_delete_node(item.node_id)
            event.accept()
        else:
            super().keyPressEvent(event)
