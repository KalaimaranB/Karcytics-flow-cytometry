"""Group Preview Panel — shows low-res renders of all samples in a group.

Refactored to use AxisManager, PopulationService, and RenderTask.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any, cast

from karcytics_sdk.plugin import CentralEventBus, get_logger
from karcytics_sdk.plugin.runtime_services import task_scheduler
from karcytics_sdk.plugin.theme_fallback import Colors
from PyQt6.QtCore import QPointF, Qt, QTimer
from PyQt6.QtGui import QColor, QImage, QPainter, QPen, QPixmap, QPolygonF
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from karcytics_plugins.flow_cytometry.analysis import events
from karcytics_plugins.flow_cytometry.analysis.constants import (
    GATE_DRAWING_COLOR,
    PREVIEW_THUMBNAIL_SIZE,
)
from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.ui.graph.flow_services import CoordinateMapper

logger = get_logger(__name__, "flow_cytometry")

# Distinct from `None` (which means "render this peer's root population") —
# signals that a peer sample has no population matching the active one at all.
_NO_MATCH = object()

# Cache of previously-rendered thumbnails, keyed by (sample_id, *current_params) —
# see PreviewThumbnail.request_render. Lets navigating back to a population you've
# already visited in this session repaint instantly instead of re-submitting a
# background render for every peer sample. Bounded (oldest-first eviction) since
# each entry holds a real pixmap.
_GroupPreviewCache: OrderedDict[tuple, tuple] = OrderedDict()
_GROUP_PREVIEW_CACHE_MAX = 300


def _gate_geom_hash(gate) -> tuple | None:  # noqa: PLR0911
    """Cheap geometry fingerprint so resizing a gate invalidates cached renders
    that only key on gate_id (which doesn't change when bounds move).
    """
    if not gate:
        return None
    if hasattr(gate, "vertices"):
        return tuple(gate.vertices)
    if hasattr(gate, "x_min"):
        return (gate.x_min, gate.x_max, gate.y_min, gate.y_max)
    if hasattr(gate, "center"):
        return (gate.center, gate.width, gate.height)
    if hasattr(gate, "x_mid"):
        return (gate.x_mid, gate.y_mid)
    if hasattr(gate, "low"):
        return (gate.low, gate.high)
    return None


class PreviewThumbnail(QFrame):
    """A single sample thumbnail in the preview grid."""

    def __init__(
        self,
        sample_id: str,
        state: FlowState,
        axis_manager: Any | None = None,
        population_service: Any | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self._sample_id = sample_id
        self._state = state
        self._axis_manager = axis_manager
        self._population_service = population_service
        self._last_params: Any | None = None
        self._current_task_id: str | None = None
        self._pending_cache_key: tuple | None = None

        # Overlay caching
        self._base_pixmap: QPixmap | None = None
        self._x_range: tuple[float, float] | None = None
        self._y_range: tuple[float, float] | None = None

        self._setup_ui()

        # Connect to global signals ONLY ONCE
        task_scheduler.task_finished.connect(self._on_global_task_finished)
        task_scheduler.task_error.connect(self._on_global_task_error)
        self.destroyed.connect(self._cleanup)

    def _cleanup(self) -> None:
        try:
            task_scheduler.task_finished.disconnect(self._on_global_task_finished)
            task_scheduler.task_error.disconnect(self._on_global_task_error)
        except (TypeError, RuntimeError):
            pass

    def _setup_ui(self):
        self.setFixedWidth(PREVIEW_THUMBNAIL_SIZE[0] + 8)
        self.setMinimumHeight(PREVIEW_THUMBNAIL_SIZE[1] + 24)
        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        self.setStyleSheet(
            f"background: {Colors.BG_DARK}; border: 1px solid {Colors.BORDER}; border-radius: 4px;"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        self._img = QLabel()
        self._img.setFixedSize(*PREVIEW_THUMBNAIL_SIZE)
        self._img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._img.setScaledContents(True)  # Enable High-DPI scaling
        self._img.setStyleSheet("background: white; border: 1px solid #DDDDDD;")
        layout.addWidget(self._img)

        sample = self._state.data.experiment.samples.get(self._sample_id)
        display_name = sample.display_name if sample else self._sample_id
        self._name = QLabel(display_name)
        self._name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._name.setWordWrap(True)
        layout.addWidget(self._name)

        self.refresh_styles()

    def refresh_styles(self) -> None:
        """Dynamically refresh colors when theme changes."""
        self.setStyleSheet(
            f"background: {Colors.BG_DARK}; border: 1px solid {Colors.BORDER}; border-radius: 4px;"
        )
        self._name.setStyleSheet(f"color: {Colors.FG_SECONDARY}; font-size: 9px; padding: 2px;")

    _apply_theme_styles = refresh_styles

    def clear_preview(self) -> None:
        """Revert the displayed pixmap to the clean base image, discarding any temp-gate overlay."""
        if self._base_pixmap:
            self._img.setPixmap(self._base_pixmap)
            self._img.update()

    def show_unavailable(self) -> None:
        """Show a disabled placeholder — this sample has no equivalent population."""
        self._current_task_id = None
        self._base_pixmap = None
        self._x_range = None
        self._y_range = None
        self._last_params = None  # don't let a stale dedup key block a future real render
        self._img.setPixmap(QPixmap())
        self._img.setText("Not gated\non this sample")
        self._img.setStyleSheet(
            f"background: {Colors.BG_DARK}; border: 1px solid {Colors.BORDER};"
            f" color: {Colors.FG_DISABLED}; font-size: 9px;"
        )

    def _restore_img_style(self) -> None:
        self._img.setStyleSheet("background: white; border: 1px solid #DDDDDD;")

    def preview_temp_gate(self, temp_gate) -> None:  # noqa: PLR0915
        """Draw a temporary gate over the cached base pixmap instantly."""
        if not self._base_pixmap or not self._x_range or not self._y_range:
            return

        x_param = self._state.view.active_x_param
        y_param = self._state.view.active_y_param

        if temp_gate.x_param != x_param or not self._axis_manager:
            return

        x_scale = self._axis_manager.get_scale(x_param)
        y_scale = self._axis_manager.get_scale(y_param) if y_param else None

        mapper = CoordinateMapper(x_scale, y_scale)

        try:
            import numpy as np

            x_min_disp = mapper.transform_x(np.array([self._x_range[0]]))[0]
            x_max_disp = mapper.transform_x(np.array([self._x_range[1]]))[0]
            x_disp_span = x_max_disp - x_min_disp

            y_min_disp, y_max_disp, y_disp_span = 0, 0, 1
            if y_scale and self._y_range:
                y_min_disp = mapper.transform_y(np.array([self._y_range[0]]))[0]
                y_max_disp = mapper.transform_y(np.array([self._y_range[1]]))[0]
                y_disp_span = y_max_disp - y_min_disp

            overlay = self._base_pixmap.copy()
            w, h = overlay.width(), overlay.height()

            def to_px(x_data, y_data):
                xd = mapper.transform_x(np.array([x_data]))[0]
                px = (xd - x_min_disp) / x_disp_span * w
                if y_scale:
                    yd = mapper.transform_y(np.array([y_data]))[0]
                    # Qt Y goes down, so we invert
                    py = h - ((yd - y_min_disp) / y_disp_span * h)
                else:
                    py = 0
                return px, py

            painter = QPainter(overlay)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            pen = QPen(QColor(GATE_DRAWING_COLOR), 2, Qt.PenStyle.DashLine)
            painter.setPen(pen)

            if hasattr(temp_gate, "vertices"):
                pts = [QPointF(*to_px(v[0], v[1])) for v in temp_gate.vertices]
                if len(pts) > 1:
                    painter.drawPolyline(QPolygonF(pts))
                if len(pts) > 2:  # noqa: PLR2004
                    painter.drawLine(pts[-1], pts[0])  # Close polygon
            elif hasattr(temp_gate, "x_min"):
                px1, py1 = to_px(temp_gate.x_min, temp_gate.y_max)  # top-left
                px2, py2 = to_px(temp_gate.x_max, temp_gate.y_min)  # bottom-right
                painter.drawRect(int(px1), int(py1), int(px2 - px1), int(py2 - py1))
            elif hasattr(temp_gate, "low") and hasattr(temp_gate, "high"):
                px1, _ = to_px(temp_gate.low, 0)
                px2, _ = to_px(temp_gate.high, 0)
                painter.fillRect(
                    int(px1), 0, int(px2 - px1), h, QColor(GATE_DRAWING_COLOR).lighter(150)
                )
            elif hasattr(temp_gate, "center"):
                cx, cy = temp_gate.center
                cpx, cpy = to_px(cx, cy)

                # Approximate width/height in pixels
                x2, _ = to_px(cx + temp_gate.width / 2, cy)
                _, y2 = to_px(cx, cy + temp_gate.height / 2)

                painter.drawEllipse(QPointF(cpx, cpy), abs(x2 - cpx), abs(y2 - cpy))
            elif hasattr(temp_gate, "low"):
                px1, _ = to_px(temp_gate.low, 0)
                px2, _ = to_px(temp_gate.high, 0)
                painter.drawLine(int(px1), 0, int(px1), h)
                painter.drawLine(int(px2), 0, int(px2), h)
            elif hasattr(temp_gate, "x_mid"):
                cpx, cpy = to_px(temp_gate.x_mid, temp_gate.y_mid)
                painter.drawLine(int(cpx), 0, int(cpx), h)
                painter.drawLine(0, int(cpy), w, int(cpy))

            painter.end()
            self._img.setPixmap(overlay)
            self._img.update()
        except Exception as e:
            logger.error(f"Overlay drawing failed: {e}")

    def request_render(  # noqa: PLR0912, PLR0915
        self,
        active_sample_id: str | None = None,
        active_node_id: str | None = None,
        peer_node_id: str | None = None,
    ):
        """Submit a background render task for this thumbnail."""
        x_param = self._state.view.active_x_param
        y_param = self._state.view.active_y_param
        plot_type = self._state.view.active_plot_type

        # Use AxisManager to get current scales (synced with main canvas)
        assert self._axis_manager is not None
        x_scale = self._axis_manager.get_scale(x_param, active_sample_id)
        assert self._axis_manager is not None
        y_scale = self._axis_manager.get_scale(y_param, active_sample_id)

        # Get the effective bounds for the active sample so ALL thumbnails share the exact same scale.
        # If the user hasn't manually overridden the bounds (min_val is None), we must explicitly
        # calculate the active sample's auto-range so that we don't pass None to RenderTask
        # (which would cause RenderTask to auto-range on each thumbnail's individual data).
        x_range = None
        if x_scale.min_val is not None and x_scale.max_val is not None:
            x_range = (x_scale.min_val, x_scale.max_val)
        elif active_sample_id:
            try:
                sample = self._state.data.experiment.samples.get(active_sample_id)
                if (
                    sample and sample.fcs_data is not None and x_param in sample.fcs_data.events  # type: ignore
                ):
                    data = sample.fcs_data.events[x_param]  # type: ignore
                    assert self._axis_manager is not None
                    x_range = self._axis_manager.calculate_range(data, x_param, active_sample_id)
            except Exception as e:
                logger.error(f"Group preview x_range calc failed: {e}")

        y_range = None
        if y_scale.min_val is not None and y_scale.max_val is not None:
            y_range = (y_scale.min_val, y_scale.max_val)
        elif y_param and active_sample_id:
            try:
                sample = self._state.data.experiment.samples.get(active_sample_id)
                if (
                    sample and sample.fcs_data is not None and y_param in sample.fcs_data.events  # type: ignore
                ):
                    data = sample.fcs_data.events[y_param]  # type: ignore
                    assert self._axis_manager is not None
                    y_range = self._axis_manager.calculate_range(data, y_param, active_sample_id)
            except Exception as e:
                logger.error(f"Group preview y_range calc failed: {e}")

        gate_id = None

        gates_to_show = []
        # Get the node for THIS thumbnail's sample to show its actual gates (including tailoring)
        if peer_node_id:
            assert self._population_service is not None
            peer_node = self._population_service.find_node(self._sample_id, peer_node_id)
        else:
            assert self._population_service is not None
            peer_node = self._population_service.get_root_node(self._sample_id)

        if peer_node:
            logger.info(
                f"GroupPreviewPanel: active_node={peer_node.name}, children={len(peer_node.children)}"
            )
            for child in peer_node.children:
                if child.gate:
                    gates_to_show.append(child.gate)
                    logger.info(
                        f"GroupPreviewPanel: added gate {child.gate.gate_id} ({child.gate.x_param}/{child.gate.y_param}) to gates_to_show (current axes: {x_param}/{y_param})"
                    )

        logger.info(
            f"GroupPreviewPanel: submitting RenderTask for {self._sample_id} with {len(gates_to_show)} gates"
        )

        # Cache invalidation check. geom_key fingerprints gate *bounds*, not just
        # gate_id, so resizing an existing gate (same id, new coordinates) still
        # invalidates any cached render of it.
        geom_key = tuple(_gate_geom_hash(g) for g in gates_to_show)
        scale_key = (x_scale.min_val, x_scale.max_val, y_scale.min_val, y_scale.max_val)
        gate_ids_key = tuple(g.gate_id for g in gates_to_show)
        fmo_sample_id = self._state.view.active_fmo_sample_id

        # We need the render config in the cache key so changes to UI settings (like FMO colors) invalidate the cache
        rc = self._state.view.render_config
        rc_key = str(rc.to_dict())

        current_params = (
            x_param,
            y_param,
            peer_node_id,
            gate_id,
            geom_key,
            scale_key,
            plot_type,
            active_sample_id,
            active_node_id,
            gate_ids_key,
            fmo_sample_id,
            rc_key,
        )
        if current_params == self._last_params:
            return
        self._last_params = current_params

        cache_key = (self._sample_id, *current_params)
        cached = _GroupPreviewCache.get(cache_key)
        if cached is not None:
            _GroupPreviewCache.move_to_end(cache_key)
            pixmap, x_rng, y_rng = cached
            self._current_task_id = None
            self._base_pixmap = pixmap
            self._x_range = x_rng
            self._y_range = y_rng
            self._restore_img_style()
            self._img.setPixmap(pixmap)
            return

        # Configure and submit RenderTask
        from ..graph.render_task import RenderTask

        task = RenderTask()
        w, h = PREVIEW_THUMBNAIL_SIZE[0] * 2, PREVIEW_THUMBNAIL_SIZE[1] * 2

        # Pass quality settings to RenderTask
        rc = self._state.view.render_config

        # Subplots are much smaller than the main plot, so we scale down the maximum events
        # proportionally to maintain visual density parity with the main plot.
        # Use roughly 15% of the main plot's event limit.
        subplot_event_ratio = 0.15
        max_events = int(rc.max_events * subplot_event_ratio)

        # Point size 0.5 is usually good for thumbnails
        point_size = 0.5

        rc_dict = rc.to_dict()
        rc_dict["show_gate_labels"] = False
        rc_dict["show_axis_labels"] = False

        task.configure(
            sample_id=self._sample_id,
            peer_node_id=peer_node_id,
            x_param=x_param,
            y_param=y_param,
            x_scale=x_scale,
            y_scale=y_scale,
            x_range=x_range,
            y_range=y_range,
            width_px=w,
            height_px=h,
            plot_type=plot_type,
            max_events=max_events,
            quality_multiplier=1.0,  # Thumbnails always use 1.0 grid mult for speed
            gates=gates_to_show,
            selected_gate_id=self._state.view.current_gate_id,
            s=point_size,
            render_config=rc_dict,
            fmo_sample_id=self._state.view.active_fmo_sample_id,
        )

        self._pending_cache_key = cache_key
        worker = task_scheduler.submit(task, self._state)
        self._current_task_id = getattr(
            worker, "task_id", ""
        )  # submit() returns the worker; the ID is on .task_id

    def _on_global_task_finished(self, tid: str, results: dict) -> None:
        try:
            if str(tid) == str(getattr(self, "_current_task_id", None)):
                self._on_render_done(results)
        except RuntimeError:
            pass

    def _on_global_task_error(self, tid: str, error_msg: str) -> None:
        try:
            if str(tid) == str(getattr(self, "_current_task_id", None)):
                logger.warning(f"Render error for {self._sample_id}: {error_msg}")
        except RuntimeError:
            pass

    def _on_render_done(self, results: dict) -> None:
        """Called on the UI thread when the off-thread render completes."""
        if "error" in results:
            logger.warning(f"Render error for {self._sample_id}: {results['error']}")
            return

        buf = results.get("image_data")
        if not buf:
            logger.warning(f"PreviewThumbnail: Received empty buffer for {self._sample_id}")
            return

        w, h = results["width"], results["height"]
        logger.info(f"PreviewThumbnail: Received {len(buf)} bytes for {self._sample_id} ({w}x{h})")

        # Force a copy of the buffer so it doesn't get garbage collected
        try:
            # Use RGBA8888 to correctly map the RGBA buffer from Matplotlib
            # (RGB32 incorrectly swaps red and blue channels on little-endian systems)
            qimg = QImage(buf, w, h, QImage.Format.Format_RGBA8888).copy()
            self._base_pixmap = QPixmap.fromImage(qimg)
            self._restore_img_style()
            self._img.setPixmap(self._base_pixmap)

            # Save range for fast QPainter overlay
            self._x_range = results.get("x_range")
            self._y_range = results.get("y_range")

            self._img.update()

            if self._pending_cache_key is not None:
                _GroupPreviewCache[self._pending_cache_key] = (
                    self._base_pixmap,
                    self._x_range,
                    self._y_range,
                )
                _GroupPreviewCache.move_to_end(self._pending_cache_key)
                while len(_GroupPreviewCache) > _GROUP_PREVIEW_CACHE_MAX:
                    _GroupPreviewCache.popitem(last=False)
                self._pending_cache_key = None
        except Exception as e:
            logger.error(f"Failed to load image buffer for {self._sample_id}: {e}")


class GroupPreviewPanel(QWidget):
    """Panel showing previews for all samples in a group."""

    def __init__(
        self,
        state: FlowState,
        sample_id: str | None = None,
        axis_manager: Any | None = None,
        population_service: Any | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._state = state
        self._axis_manager = axis_manager
        self._population_service = population_service
        self._current_sample_id: str | None = sample_id
        self._current_node_id: str | None = None
        self._thumbnails: dict[str, PreviewThumbnail] = {}
        self._setup_ui()
        self._setup_events()

        # Throttle timer for real-time gate previews
        from ...analysis.constants import PREVIEW_THROTTLE_MS

        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(PREVIEW_THROTTLE_MS)
        self._preview_timer.timeout.connect(self._do_throttled_refresh)
        self._pending_temp_gate = None
        self._is_alive = True

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._hdr = QLabel("👥 Group Preview")
        self._hdr.setStyleSheet(f"color: {Colors.FG_SECONDARY}; font-size: 10px; font-weight: 700;")
        layout.addWidget(self._hdr)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setStyleSheet(f"background: {Colors.BG_DARKEST};")

        self._container = QWidget()
        self._container.setStyleSheet(f"background: {Colors.BG_DARKEST};")
        self._grid = QGridLayout(self._container)
        self._grid.setContentsMargins(4, 4, 4, 4)
        self._grid.setSpacing(12)
        self._grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        self._scroll.setWidget(self._container)
        layout.addWidget(self._scroll)
        self.setMinimumHeight(200)
        self.setObjectName("GroupPreviewPanel")

        self.refresh_styles()

    def refresh_styles(self) -> None:
        """Dynamically refresh colors when theme changes."""
        self._scroll.setStyleSheet(f"background: {Colors.BG_DARKEST};")
        self._container.setStyleSheet(f"background: {Colors.BG_DARKEST};")
        for thumb in self._thumbnails.values():
            thumb.refresh_styles()

    _apply_theme_styles = refresh_styles

    def _on_event_refresh(self, data: dict | None = None) -> None:
        self._refresh_all()

    def _on_event_rebuild(self, data: dict | None = None) -> None:
        self._rebuild()

    def _setup_events(self) -> None:
        CentralEventBus.subscribe(events.AXIS_PARAMS_CHANGED, self._on_event_refresh)
        CentralEventBus.subscribe(events.AXIS_RANGE_CHANGED, self._on_event_refresh)
        CentralEventBus.subscribe(events.TRANSFORM_CHANGED, self._on_event_refresh)
        CentralEventBus.subscribe(events.GATE_CREATED, self._on_event_rebuild)
        CentralEventBus.subscribe(events.GATES_CREATED, self._on_event_rebuild)
        CentralEventBus.subscribe(events.GATE_MODIFIED, self._on_event_refresh)
        CentralEventBus.subscribe(events.GATE_DELETED, self._on_event_rebuild)
        CentralEventBus.subscribe(events.DISPLAY_MODE_CHANGED, self._on_event_refresh)
        CentralEventBus.subscribe(events.FMO_CHANGED, self._on_event_refresh)
        CentralEventBus.subscribe(events.RENDER_CONFIG_CHANGED, self._on_event_refresh)
        CentralEventBus.subscribe(events.GATE_PREVIEW, self._on_gate_preview)
        # Hook both closeEvent (explicit close) and destroyed (parent-driven deletion)
        self.destroyed.connect(self._cleanup)

    def _cleanup(self) -> None:
        """Unsubscribe from global events to prevent calls on a deleted C++ widget."""
        if not self._is_alive:
            return
        self._is_alive = False
        # Stop the timer before unsubscribing — avoids any pending timeout callbacks
        try:
            self._preview_timer.stop()
        except RuntimeError:
            pass
        CentralEventBus.unsubscribe(events.AXIS_PARAMS_CHANGED, self._on_event_refresh)
        CentralEventBus.unsubscribe(events.AXIS_RANGE_CHANGED, self._on_event_refresh)
        CentralEventBus.unsubscribe(events.TRANSFORM_CHANGED, self._on_event_refresh)
        CentralEventBus.unsubscribe(events.GATE_CREATED, self._on_event_rebuild)
        CentralEventBus.unsubscribe(events.GATES_CREATED, self._on_event_rebuild)
        CentralEventBus.unsubscribe(events.GATE_MODIFIED, self._on_event_refresh)
        CentralEventBus.unsubscribe(events.GATE_DELETED, self._on_event_rebuild)
        CentralEventBus.unsubscribe(events.DISPLAY_MODE_CHANGED, self._on_event_refresh)
        CentralEventBus.unsubscribe(events.FMO_CHANGED, self._on_event_refresh)
        CentralEventBus.unsubscribe(events.RENDER_CONFIG_CHANGED, self._on_event_refresh)
        CentralEventBus.unsubscribe(events.GATE_PREVIEW, self._on_gate_preview)

    def closeEvent(self, event) -> None:
        """Ensure event-bus subscriptions are torn down before Qt deletes children."""
        self._cleanup()
        super().closeEvent(event)

    def _on_gate_preview(self, data: dict) -> None:
        """Handle real-time gate drawing preview."""
        if not self._is_alive:
            return
        self._pending_temp_gate = data.get("gate")
        try:
            if not self._preview_timer.isActive():
                self._preview_timer.start()
        except RuntimeError:
            # C++ QTimer was deleted before Python GC ran; clean up and bail out
            self._cleanup()

    def _do_throttled_refresh(self) -> None:
        """Execute the refresh with the latest pending preview gate."""
        if self._pending_temp_gate:
            # Fast path overlay via QPainter
            for thumb in self._thumbnails.values():
                thumb.preview_temp_gate(self._pending_temp_gate)
        else:
            # Preview cleared (gate committed or the naming dialog was cancelled).
            # Revert to the clean base image immediately — request_render()'s own
            # dedup cache would otherwise silently skip re-rendering when nothing
            # in the gate tree actually changed (e.g. on cancel), leaving the
            # dashed preview overlay stuck on screen indefinitely.
            for thumb in self._thumbnails.values():
                thumb.clear_preview()
            self._refresh_all()

        self._pending_temp_gate = None

    def update_context(self, sample_id: str | None, node_id: str | None) -> None:
        if sample_id == self._current_sample_id and node_id == self._current_node_id:
            self._refresh_all()
            return
        self._current_sample_id = sample_id
        self._current_node_id = node_id
        self._rebuild()

    def _rebuild(self) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item:
                w = item.widget()
                if w:
                    w.deleteLater()
        self._thumbnails.clear()

        if not self._current_sample_id:
            self._hdr.setText("👥 Group Preview")
            return

        sample = self._state.data.experiment.samples.get(self._current_sample_id)
        if not sample:
            self._hdr.setText("👥 Group Preview")
            return

        peers = []
        gid = None
        if sample.group_ids:
            gid = list(sample.group_ids)[0]
            self._hdr.setText(f"👥 Group Preview — {gid}")
            peers = [
                s
                for s in self._state.data.experiment.samples.values()
                if gid in s.group_ids and s.sample_id != self._current_sample_id
            ]

        # Fallback: if no group peers, show all other samples in experiment
        if not peers:
            self._hdr.setText("👥 Group Preview — All Samples")
            logger.info(
                "GroupPreviewPanel._rebuild: no group peers found, falling back to all samples."
            )
            peers = [
                s
                for s in self._state.data.experiment.samples.values()
                if s.sample_id != self._current_sample_id
            ]

        logger.info(
            f"GroupPreviewPanel._rebuild: found {len(peers)} samples to preview (group={gid})"
        )
        for i, p in enumerate(peers):
            thumb = PreviewThumbnail(
                p.sample_id,
                self._state,
                axis_manager=self._axis_manager,
                population_service=self._population_service,
            )
            self._thumbnails[p.sample_id] = thumb
            self._grid.addWidget(thumb, i // 2, i % 2)
            peer_node_id = self._get_parallel_node(
                self._current_sample_id, self._current_node_id, p.sample_id
            )
            if peer_node_id is _NO_MATCH:
                thumb.show_unavailable()
            else:
                thumb.request_render(
                    self._current_sample_id, self._current_node_id, cast("str | None", peer_node_id)
                )

    def _refresh_all(self) -> None:
        for thumb in self._thumbnails.values():
            peer_node_id = self._get_parallel_node(
                self._current_sample_id, self._current_node_id, thumb._sample_id
            )
            if peer_node_id is _NO_MATCH:
                thumb.show_unavailable()
            else:
                thumb.request_render(
                    self._current_sample_id, self._current_node_id, cast("str | None", peer_node_id)
                )

    def _get_parallel_node(
        self,
        source_sample_id: str | None,
        source_node_id: str | None,
        target_sample_id: str,
    ) -> str | None | object:
        """Find the equivalent gate node ID in another sample by name path.

        Returns `_NO_MATCH` (rather than `None`) when the peer has no population
        corresponding to the active one — distinct from `None`, which legitimately
        means "render this peer's root population".
        """
        if not source_sample_id or not source_node_id:
            return None

        source_sample = self._state.data.experiment.samples.get(source_sample_id)
        target_sample = self._state.data.experiment.samples.get(target_sample_id)
        if not source_sample or not target_sample:
            return None

        curr_node = source_sample.gate_tree.find_node_by_id(source_node_id)
        if not curr_node:
            return None

        path = []
        c = curr_node
        while c and not c.is_root:
            path.append(c.name)
            c = c.parents[0] if c.parents else None  # type: ignore
        path.reverse()

        t_node = target_sample.gate_tree
        for p_name in path:
            matched = False
            for child in t_node.children:
                if child.name == p_name:
                    t_node = child
                    matched = True
                    break
            if not matched:
                # No equivalent population on this peer (e.g. a gate that was
                # never propagated). Falling through and returning the ancestor
                # we got stuck at would silently render the WRONG population's
                # data in the peer's tile, labeled as if it were this one.
                return _NO_MATCH

        if t_node and not t_node.is_root:
            return t_node.node_id
        return None
