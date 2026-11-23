"""Node Canvas - View layer for the Pipeline feature."""

from typing import Any

from karcytics_sdk.plugin import BioToggleButton, ZoomControls
from karcytics_sdk.plugin.dialogs import confirm_destructive
from karcytics_sdk.plugin.rendering.graphics_scene import (
    DirtyTrackingGraphicsScene,
    DirtyTrackingGraphicsView,
)
from karcytics_sdk.plugin.theme_fallback import Colors
from PySide6.QtCore import QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QKeyEvent, QMouseEvent, QPainter, QPen, QPolygonF, QWheelEvent
from PySide6.QtWidgets import (
    QDialog,
    QGraphicsView,
    QInputDialog,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from karcytics_plugins.flow_cytometry.analysis.state import FlowState

from ....analysis.scope_resolution import resolve_target_samples
from ..scope_selection_dialog import ScopeSelectionDialog
from .canvas_manager import CanvasManager
from .items.edge_item import EdgeItem
from .items.node_item import NodeItem

MAX_ZOOM = 3.0  # the pipeline canvas's zoom limits, as view scale factors
MIN_ZOOM = 0.1


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

    def drawBackground(self, painter: QPainter | None, rect: QRectF | None) -> None:  # type: ignore[override]
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
        if zoom_factor > 1.0 and current_zoom >= MAX_ZOOM:
            return
        if zoom_factor < 1.0 and current_zoom <= MIN_ZOOM:
            return

        self.scale(zoom_factor, zoom_factor)

    def zoom_in(self) -> None:
        if self.transform().m11() < MAX_ZOOM:
            self.scale(1.2, 1.2)

    def zoom_out(self) -> None:
        if self.transform().m11() > MIN_ZOOM:
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

    node_double_clicked = Signal(str)
    node_removed = Signal(str)  # node_id
    rename_requested = Signal(str, str, object)  # node_id, new_name, target_sample_ids
    connection_requested = Signal(str, str, str)  # sample_id, source_id, target_id
    connection_removed = Signal(str, str, str)  # sample_id, source_id, target_id
    link_delete_requested = Signal(str, str, object)  # source_id, target_id, target_sample_ids

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
        self._manager.node_rename_requested.connect(self._confirm_and_rename_node)
        self._manager.link_delete_requested.connect(self._confirm_and_delete_link)
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
        self.btn_pan = BioToggleButton("Pan Tool")
        self.btn_pan.toggled.connect(self._on_pan_toggled)
        ZoomControls(
            self._view.zoom_in, self._view.zoom_out, self.center_on_nodes, extra=[self.btn_pan]
        ).overlay_on(self._view)

        self._apply_theme_styles()

    def _apply_theme_styles(self) -> None:
        """Dynamically refresh colors when theme changes."""
        self.setStyleSheet(f"background: {Colors.BG_DARKEST};")
        self._view.setBackgroundBrush(QColor(Colors.BG_DARKEST))
        self._view._apply_theme_styles()

    def _on_pan_toggled(self, checked: bool) -> None:
        if checked:
            self._view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        else:
            self._view.setDragMode(QGraphicsView.DragMode.NoDrag)

    def set_sample(self, sample_id: str) -> None:
        """Switch the canvas to display a specific sample."""
        self.current_sample_id = sample_id
        self._manager.load_sample(sample_id)
        QTimer.singleShot(50, self.center_on_nodes)

    def set_orientation(self, orientation: str) -> None:
        """Update the canvas orientation (horizontal/vertical)."""
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

        count = len(child_names)
        if count and not confirm_destructive(
            self,
            "Delete Logic Node" if node.is_logic_node else "Delete Population",
            f"Deleting '{node.name}' also deletes its {count} child "
            f"population{'s' if count != 1 else ''}. Continue?",
            child_names,
        ):
            return

        self.node_removed.emit(node_id)

    def _group_choices_for_sample(self, sample) -> list[tuple[str, str]]:
        """Build the ('all'/group_id, display_name) choices for a scope dialog."""
        experiment = self.state.data.experiment
        group_choices: list[tuple[str, str]] = [("all", "All Samples")]
        for gid in sample.group_ids:
            grp = experiment.groups.get(gid)
            if grp:
                group_choices.append((gid, grp.name))
        return group_choices

    def _confirm_and_rename_node(self, node_id: str) -> None:
        """Prompt for a new name, then a scope, then emit rename_requested."""
        if not self.current_sample_id or not node_id:
            return

        sample = self.state.data.experiment.samples.get(self.current_sample_id)
        if not sample or not sample.gate_tree:
            return

        node = sample.gate_tree.find_node_by_id(node_id)
        if not node or node.is_root:
            return

        dialog_title = "Rename Node" if node.is_logic_node else "Rename Population"

        new_name, ok = QInputDialog.getText(
            self, dialog_title, "Enter new name:", QLineEdit.EchoMode.Normal, node.name
        )
        if not ok or not new_name or new_name == node.name:
            return

        experiment = self.state.data.experiment
        dialog = ScopeSelectionDialog(
            f"Rename '<b>{node.name}</b>' to '<b>{new_name}</b>'?",
            sample.display_name,
            self._group_choices_for_sample(sample),
            self,
            title=dialog_title,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        scope, group_id = dialog.get_scope()
        target_ids = resolve_target_samples(scope, group_id, self.current_sample_id, experiment)

        names = [experiment.samples[s].display_name for s in target_ids if s in experiment.samples]
        if len(target_ids) > 1 and not confirm_destructive(
            self,
            dialog_title,
            f"Rename '{node.name}' to '{new_name}' in {len(names)} samples?",
            names,
        ):
            return

        self.rename_requested.emit(node_id, new_name, target_ids)

    def _confirm_and_delete_link(self, source_node_id: str, target_node_id: str) -> None:
        """Prompt for a scope, warn about affected samples, then emit link_delete_requested."""
        if not self.current_sample_id:
            return

        sample = self.state.data.experiment.samples.get(self.current_sample_id)
        if not sample or not sample.gate_tree:
            return

        source = sample.gate_tree.find_node_by_id(source_node_id)
        target = sample.gate_tree.find_node_by_id(target_node_id)
        if not source or not target:
            return

        experiment = self.state.data.experiment
        dialog = ScopeSelectionDialog(
            f"Delete the connection from '<b>{source.name}</b>' to '<b>{target.name}</b>'?",
            sample.display_name,
            self._group_choices_for_sample(sample),
            self,
            title="Delete Connection",
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        scope, group_id = dialog.get_scope()
        target_ids = resolve_target_samples(scope, group_id, self.current_sample_id, experiment)

        names = [experiment.samples[s].display_name for s in target_ids if s in experiment.samples]
        if not confirm_destructive(
            self,
            "Delete Connection",
            f"Remove the connection '{source.name}' → '{target.name}' "
            f"in {len(names)} sample{'s' if len(names) != 1 else ''}?",
            names,
        ):
            return

        self.link_delete_requested.emit(source_node_id, target_node_id, target_ids)

    def keyPressEvent(self, event: QKeyEvent | None) -> None:
        if event is None:
            return
        if event.key() == Qt.Key.Key_F:
            self.center_on_nodes()
            event.accept()
        elif event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            for item in self._scene.selectedItems():
                if isinstance(item, EdgeItem):
                    if not getattr(item, "is_logic_edge", False):
                        continue
                    self._manager.connection_removed.emit(
                        item.source_node.node_id, item.target_node.node_id
                    )
                elif isinstance(item, NodeItem):
                    self._confirm_and_delete_node(item.node_id)
            event.accept()
        else:
            super().keyPressEvent(event)
