"""Gate Drawing State Machine (FSM).

Encapsulates the logic for interactive gate creation (mouse press, motion, release).
This extracts the complex state management from FlowCanvas, making it
easier to add new interactive gate types.
"""

from __future__ import annotations

from enum import Enum, auto
from typing import TYPE_CHECKING

from karcytics_sdk.plugin import get_logger
from matplotlib.patches import Ellipse as MplEllipse
from matplotlib.patches import Rectangle as MplRectangle

from ...analysis.constants import GATE_DRAWING_COLOR

logger = get_logger(__name__, "flow_cytometry")

if TYPE_CHECKING:
    from .flow_canvas import FlowCanvas


class DrawingState(Enum):
    IDLE = auto()
    DRAWING = auto()  # Dragging for Rect/Ellipse/Range
    POLYGON = auto()  # Adding points one by one
    EDITING = auto()  # Dragging a handle or the body of the selected gate


class GateDrawingFSM:
    """Manages the interactive drawing process for different gate types."""

    def __init__(self, canvas: FlowCanvas):
        self.canvas = canvas
        self.state = DrawingState.IDLE
        self._drag_start: tuple[float, float] | None = None
        self._rubber_band: object | None = None
        self._polygon_vertices: list[tuple[float, float]] = []
        self._polygon_artists: list[object] = []
        self._crosshair_artists: list[object] = []
        self._instruction_text: object | None = None

        # ── Gate editing (drag handles / body-move on the selected gate) ──
        self._edit_target = None  # Gate being edited
        self._edit_handle_key: str | None = None
        self._edit_anchor: dict | None = None  # pre-drag geometry snapshot
        self._edit_press: tuple[float, float] | None = None  # press point, display space
        self._edit_preview_info: dict | None = None  # last-drawn preview artists bundle

    def handle_press(self, x: float, y: float, mode: str, alt_cycle: bool = False):
        """Handle mouse press event.

        `alt_cycle`: Alt is held — the user's intent is "select the next
        gate under the cursor" (to reach one fully occluded by another),
        not to grab a handle/body of whatever is already selected, so this
        skips straight to cycle-select instead of the usual
        handle -> body -> select fallthrough.
        """
        logger.info(f"FSM press: mode={mode}, x={x:.2f}, y={y:.2f}, state={self.state}")
        if mode == "none":
            if alt_cycle:
                self.canvas._try_select_gate(x, y, alt_cycle=True)
                return

            edit_hit = self.canvas._try_hit_edit_handle(x, y)
            if edit_hit is not None:
                gate, handle_key = edit_hit
                self._start_edit(gate, handle_key, x, y)
                return

            body_gate = self.canvas._try_hit_selected_gate_body(x, y)
            if body_gate is not None:
                from .gate_editor import MOVE_HANDLE

                self._start_edit(body_gate, MOVE_HANDLE, x, y)
                return

            self.canvas._try_select_gate(x, y)
            return

        if mode == "polygon":
            self.state = DrawingState.POLYGON
            self._polygon_vertices.append((x, y))
            self._draw_polygon_progress()
            return

        if mode == "quadrant":
            self._clear_quadrant_crosshair(blit=False)
            self.canvas._finalize_quadrant(x, y)
            return

        # For drag-based gates
        self.state = DrawingState.DRAWING
        self._drag_start = (x, y)

    def handle_motion(self, x: float, y: float, mode: str):
        """Handle mouse motion (rubber-banding, polygon preview, or quadrant crosshair)."""
        if self.state == DrawingState.DRAWING and self._drag_start is not None:
            x0, y0 = self._drag_start
            self._draw_rubber_band(x0, y0, x, y, mode)
        elif self.state == DrawingState.EDITING:
            self._apply_edit_preview(x, y)
        elif self.state == DrawingState.POLYGON and self._polygon_vertices:
            self._draw_polygon_progress(current_mouse=(x, y))
        elif mode == "quadrant":
            self._draw_quadrant_crosshair(x, y)
        elif self._crosshair_artists:
            # Tool switched away from Quadrant — clear any leftover preview.
            self._clear_quadrant_crosshair()

    def handle_release(self, x: float, y: float, mode: str):
        """Handle mouse release (finalization)."""
        if self.state == DrawingState.EDITING:
            self._finish_edit()
            return

        if self.state != DrawingState.DRAWING or self._drag_start is None:
            return

        x0, y0 = self._drag_start
        self.state = DrawingState.IDLE
        self._drag_start = None
        self._clear_rubber_band()

        # Check if drag was significant
        if abs(x - x0) < 1e-6 and abs(y - y0) < 1e-6:  # noqa: PLR2004
            return

        self.canvas._finalize_drag_gate(x0, y0, x, y, mode)

    def handle_dblclick(self, x: float, y: float, mode: str):
        """Handle double click (polygon completion)."""
        if mode == "polygon" and len(self._polygon_vertices) >= 3:  # noqa: PLR2004
            self.canvas._finalize_polygon(list(self._polygon_vertices))
            self._polygon_vertices.clear()
            self._clear_polygon_progress()
            self.state = DrawingState.IDLE

    def cancel(self):
        """Cancel current drawing operation."""
        if self.state == DrawingState.EDITING and self._edit_target is not None:
            # Restore the in-memory gate — motion handling mutated it
            # directly (no modify_gate() call yet), so a cancel must undo
            # that or the visual would stay stuck at the abandoned drag
            # position with nothing to trigger a refresh.
            self.canvas._gate_editor.restore(self._edit_target, self._edit_anchor or {})
            self.canvas.refresh_gates()
        self._reset_edit_state()

        self.state = DrawingState.IDLE
        self._drag_start = None
        self._polygon_vertices.clear()
        self._clear_rubber_band(blit=True)
        self._clear_polygon_progress(blit=True)
        self._clear_quadrant_crosshair(blit=True)

    # ── Gate editing (drag handles / body-move) ────────────────────────

    def _start_edit(self, gate, handle_key: str, x: float, y: float) -> None:
        self.state = DrawingState.EDITING
        self._edit_target = gate
        self._edit_handle_key = handle_key
        self._edit_anchor = self.canvas._gate_editor.snapshot(gate)
        self._edit_press = (x, y)
        self._edit_preview_info = None
        self.canvas._begin_gate_edit_preview(gate)

    def _reset_edit_state(self) -> None:
        self._edit_target = None
        self._edit_handle_key = None
        self._edit_anchor = None
        self._edit_press = None
        self._edit_preview_info = None

    def _finish_edit(self) -> None:
        canvas = self.canvas
        self.state = DrawingState.IDLE
        gate = self._edit_target
        anchor = self._edit_anchor
        self._reset_edit_state()

        if gate is not None and anchor is not None and canvas._gate_editor.changed(gate, anchor):
            canvas._commit_gate_edit(gate, anchor)

    def _apply_edit_preview(self, x: float, y: float) -> None:  # noqa: PLR0912, PLR0915
        """Live-drag preview: mutate the real Gate object in place and redraw
        only its overlay via the blit fast-path — never calls modify_gate(),
        which is the entire performance strategy (the expensive recompute
        stats / propagate path fires exactly once, in _finish_edit).
        """

        def _on_busy() -> None:
            self._pending_edit_args = (x, y)
            if not getattr(self, "_edit_timer_active", False):
                self._edit_timer_active = True
                from PyQt6.QtCore import QTimer

                def _retry() -> None:
                    self._edit_timer_active = False
                    if hasattr(self, "_pending_edit_args"):
                        self._apply_edit_preview(*self._pending_edit_args)

                QTimer.singleShot(15, _retry)

        def _action() -> None:
            canvas = self.canvas
            ax = canvas._ax
            gate = self._edit_target
            handle_key = self._edit_handle_key
            if gate is None or handle_key is None or self._edit_anchor is None:
                return

            canvas._gate_editor.apply_drag(
                gate, handle_key, x, y, self._edit_anchor, self._edit_press
            )

            cb = canvas._fig.stale_callback
            canvas._fig.stale_callback = None
            try:
                if self._edit_preview_info:
                    for artist in canvas._iter_overlay_artists(self._edit_preview_info["artists"]):
                        try:
                            artist.remove()
                        except Exception:
                            pass
                        if artist in canvas._gate_artists:
                            canvas._gate_artists.remove(artist)

                new_artists = canvas._gate_overlay_renderer.render_gate(ax, gate, is_selected=True)
            finally:
                canvas._fig.stale_callback = cb
                canvas._fig.stale = False
                ax.stale = False

            if new_artists:
                info = {"patch": new_artists.patch, "gate": gate, "artists": new_artists}
                self._edit_preview_info = info
                canvas._gate_overlay_artists[gate.gate_id] = info
                canvas._gate_artists.extend(canvas._iter_overlay_artists(new_artists))

            if (
                getattr(canvas, "_use_cache", False)
                and getattr(canvas, "_canvas_bitmap_cache", None) is not None
            ):
                canvas._fig.canvas.restore_region(canvas._canvas_bitmap_cache)  # type: ignore
                if new_artists:
                    for artist in canvas._iter_overlay_artists(new_artists):
                        ax.draw_artist(artist)  # type: ignore
                canvas._fig.canvas.blit(ax.bbox)  # type: ignore
                canvas._fig.canvas.flush_events()  # type: ignore
            else:
                canvas.draw_idle()

            try:
                from karcytics_sdk.plugin import CentralEventBus

                from ...analysis import events

                CentralEventBus.publish(events.GATE_PREVIEW, {"gate": self._edit_target})
            except Exception as e:
                logger.debug(f"Failed to publish edit preview: {e}")

        self.canvas.raster_lock.try_run(_action, _on_busy)

    # ── Internal Drawing Helpers ──────────────────────────────────────

    def _draw_rubber_band(self, x0: float, y0: float, x1: float, y1: float, mode: str):  # noqa: PLR0912, PLR0915
        def _on_busy() -> None:
            # Defer the draw if the lock is held, using a single debounced timer
            self._pending_rubber_args = (x0, y0, x1, y1, mode)
            if not getattr(self, "_rubber_timer_active", False):
                self._rubber_timer_active = True
                from PyQt6.QtCore import QTimer

                def _retry() -> None:
                    self._rubber_timer_active = False
                    if hasattr(self, "_pending_rubber_args"):
                        self._draw_rubber_band(*self._pending_rubber_args)

                QTimer.singleShot(15, _retry)

        def _action() -> None:  # noqa: PLR0915
            ax = self.canvas._ax

            # Clear old rubber band inside the same lock acquisition
            if self._rubber_band:
                cb = self.canvas._fig.stale_callback
                self.canvas._fig.stale_callback = None
                try:
                    self._rubber_band.remove()  # type: ignore
                except Exception:
                    pass
                finally:
                    self.canvas._fig.stale_callback = cb
                    self.canvas._fig.stale = False
                    ax.stale = False
                self._rubber_band = None

            color = GATE_DRAWING_COLOR
            if mode == "rectangle":
                self._rubber_band = MplRectangle(
                    (min(x0, x1), min(y0, y1)),
                    abs(x1 - x0),
                    abs(y1 - y0),
                    linewidth=1.0,
                    edgecolor=color,
                    facecolor=color,
                    alpha=0.1,
                    linestyle="--",
                    zorder=100,
                    animated=True,
                )
            elif mode == "ellipse":
                cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
                w, h = abs(x1 - x0), abs(y1 - y0)
                self._rubber_band = MplEllipse(
                    (cx, cy),
                    w,
                    h,
                    linewidth=1.0,
                    edgecolor=color,
                    facecolor=color,
                    alpha=0.1,
                    linestyle="--",
                    zorder=100,
                    animated=True,
                )
            elif mode == "range":
                ylim = ax.get_ylim()
                self._rubber_band = MplRectangle(
                    (min(x0, x1), ylim[0]),
                    abs(x1 - x0),
                    ylim[1] - ylim[0],
                    linewidth=1.0,
                    edgecolor=color,
                    facecolor=color,
                    alpha=0.1,
                    linestyle="--",
                    zorder=100,
                    animated=True,
                )

            if self._rubber_band:
                cb = self.canvas._fig.stale_callback
                self.canvas._fig.stale_callback = None
                try:
                    ax.add_patch(self._rubber_band)  # type: ignore
                finally:
                    self.canvas._fig.stale_callback = cb
                    self.canvas._fig.stale = False
                    ax.stale = False

                if (
                    getattr(self.canvas, "_use_cache", False)
                    and getattr(self.canvas, "_canvas_bitmap_cache", None) is not None
                ):
                    self.canvas._fig.canvas.restore_region(  # type: ignore
                        self.canvas._canvas_bitmap_cache
                    )
                    ax.draw_artist(self._rubber_band)  # type: ignore
                    self.canvas._fig.canvas.blit(ax.bbox)
                    self.canvas._fig.canvas.flush_events()
                else:
                    self.canvas.draw_idle()

            # Publish temporary gate for subplots
            try:
                from karcytics_sdk.plugin import CentralEventBus

                from ...analysis import events

                temp_gate = None
                if mode == "rectangle":
                    temp_gate = self.canvas._gate_factory.create_rectangle(x0, y0, x1, y1)
                elif mode == "ellipse":
                    temp_gate = self.canvas._gate_factory.create_ellipse(x0, y0, x1, y1)  # type: ignore
                elif mode == "range":
                    temp_gate = self.canvas._gate_factory.create_range(x0, x1)  # type: ignore

                if temp_gate:
                    CentralEventBus.publish(events.GATE_PREVIEW, {"gate": temp_gate})
            except Exception as e:
                logger.debug(f"Failed to publish drag preview: {e}")

        self.canvas.raster_lock.try_run(_action, _on_busy)

    def _clear_rubber_band(self, blit: bool = True):
        def _on_busy() -> None:
            if not getattr(self, "_clear_rubber_timer_active", False):
                self._clear_rubber_timer_active = True
                from PyQt6.QtCore import QTimer

                def _retry() -> None:
                    self._clear_rubber_timer_active = False
                    self._clear_rubber_band(blit)

                QTimer.singleShot(10, _retry)

        def _action() -> None:
            if self._rubber_band:
                cb = self.canvas._fig.stale_callback
                self.canvas._fig.stale_callback = None
                try:
                    self._rubber_band.remove()  # type: ignore
                except Exception:
                    pass
                finally:
                    self.canvas._fig.stale_callback = cb
                    self.canvas._fig.stale = False
                    self.canvas._ax.stale = False

                self._rubber_band = None

                if blit:
                    if (
                        getattr(self.canvas, "_use_cache", False)
                        and getattr(self.canvas, "_canvas_bitmap_cache", None) is not None
                    ):
                        self.canvas._fig.canvas.restore_region(  # type: ignore
                            self.canvas._canvas_bitmap_cache
                        )
                        self.canvas._fig.canvas.blit(self.canvas._ax.bbox)
                        self.canvas._fig.canvas.flush_events()
                    else:
                        self.canvas.draw_idle()

        self.canvas.raster_lock.try_run(_action, _on_busy)

    def _draw_quadrant_crosshair(self, x: float, y: float):  # noqa: PLR0915
        """Live preview of where a Quadrant gate's threshold lines would sit."""

        def _on_busy() -> None:
            self._pending_crosshair_args = (x, y)
            if not getattr(self, "_crosshair_timer_active", False):
                self._crosshair_timer_active = True
                from PyQt6.QtCore import QTimer

                def _retry() -> None:
                    self._crosshair_timer_active = False
                    if hasattr(self, "_pending_crosshair_args"):
                        self._draw_quadrant_crosshair(*self._pending_crosshair_args)

                QTimer.singleShot(15, _retry)

        def _action() -> None:
            ax = self.canvas._ax

            # Clear old crosshair inside the same lock acquisition
            if self._crosshair_artists:
                cb = self.canvas._fig.stale_callback
                self.canvas._fig.stale_callback = None
                try:
                    for artist in self._crosshair_artists:
                        try:
                            artist.remove()  # type: ignore
                        except Exception:
                            pass
                finally:
                    self.canvas._fig.stale_callback = cb
                    self.canvas._fig.stale = False
                    ax.stale = False
                self._crosshair_artists.clear()

            color = GATE_DRAWING_COLOR
            cb = self.canvas._fig.stale_callback
            self.canvas._fig.stale_callback = None
            try:
                vline = ax.axvline(
                    x,
                    color=color,
                    linestyle="--",
                    linewidth=1.2,
                    alpha=0.6,
                    zorder=100,
                    animated=True,
                )
                hline = ax.axhline(
                    y,
                    color=color,
                    linestyle="--",
                    linewidth=1.2,
                    alpha=0.6,
                    zorder=100,
                    animated=True,
                )
                self._crosshair_artists.extend([vline, hline])
            finally:
                self.canvas._fig.stale_callback = cb
                self.canvas._fig.stale = False
                ax.stale = False

            if (
                getattr(self.canvas, "_use_cache", False)
                and getattr(self.canvas, "_canvas_bitmap_cache", None) is not None
            ):
                self.canvas._fig.canvas.restore_region(  # type: ignore
                    self.canvas._canvas_bitmap_cache
                )
                for artist in self._crosshair_artists:
                    ax.draw_artist(artist)  # type: ignore
                self.canvas._fig.canvas.blit(ax.bbox)
                self.canvas._fig.canvas.flush_events()
            else:
                self.canvas.draw_idle()

            # Publish temporary quadrant for subplots
            try:
                from karcytics_sdk.plugin import CentralEventBus

                from ...analysis import events

                temp_gate = self.canvas._gate_factory.create_quadrant(x, y)
                if temp_gate:
                    CentralEventBus.publish(events.GATE_PREVIEW, {"gate": temp_gate})
            except Exception as e:
                logger.debug(f"Failed to publish quadrant preview: {e}")

        self.canvas.raster_lock.try_run(_action, _on_busy)

    def _clear_quadrant_crosshair(self, blit: bool = True):
        def _on_busy() -> None:
            if not getattr(self, "_clear_crosshair_timer_active", False):
                self._clear_crosshair_timer_active = True
                from PyQt6.QtCore import QTimer

                def _retry() -> None:
                    self._clear_crosshair_timer_active = False
                    self._clear_quadrant_crosshair(blit)

                QTimer.singleShot(10, _retry)

        def _action() -> None:
            if self._crosshair_artists:
                cb = self.canvas._fig.stale_callback
                self.canvas._fig.stale_callback = None
                try:
                    for artist in self._crosshair_artists:
                        try:
                            artist.remove()  # type: ignore
                        except Exception:
                            pass
                finally:
                    self.canvas._fig.stale_callback = cb
                    self.canvas._fig.stale = False
                    self.canvas._ax.stale = False

                self._crosshair_artists.clear()

                if blit:
                    if (
                        getattr(self.canvas, "_use_cache", False)
                        and getattr(self.canvas, "_canvas_bitmap_cache", None) is not None
                    ):
                        self.canvas._fig.canvas.restore_region(  # type: ignore
                            self.canvas._canvas_bitmap_cache
                        )
                        self.canvas._fig.canvas.blit(self.canvas._ax.bbox)
                        self.canvas._fig.canvas.flush_events()
                    else:
                        self.canvas.draw_idle()

        self.canvas.raster_lock.try_run(_action, _on_busy)

    def _draw_polygon_progress(self, current_mouse=None):  # noqa: PLR0915
        if not self._polygon_vertices:
            return

        pts = list(self._polygon_vertices)
        if current_mouse:
            pts.append(current_mouse)

        def _on_busy() -> None:
            self._pending_polygon_mouse = current_mouse
            if not getattr(self, "_polygon_timer_active", False):
                self._polygon_timer_active = True
                from PyQt6.QtCore import QTimer

                def _retry() -> None:
                    self._polygon_timer_active = False
                    if hasattr(self, "_pending_polygon_mouse"):
                        self._draw_polygon_progress(self._pending_polygon_mouse)

                QTimer.singleShot(10, _retry)

        def _action() -> None:
            ax = self.canvas._ax

            # Clear old artists within the same lock acquisition
            if self._polygon_artists:
                cb = self.canvas._fig.stale_callback
                self.canvas._fig.stale_callback = None
                try:
                    for artist in self._polygon_artists:
                        try:
                            artist.remove()  # type: ignore
                        except Exception:
                            pass
                finally:
                    self.canvas._fig.stale_callback = cb
                    self.canvas._fig.stale = False
                    ax.stale = False
                self._polygon_artists.clear()

            cb = self.canvas._fig.stale_callback
            self.canvas._fig.stale_callback = None
            try:
                if len(pts) > 1:
                    xs = [p[0] for p in pts]
                    ys = [p[1] for p in pts]
                    # Once there are enough vertices to form a polygon, also draw
                    # the closing segment back to the first vertex so the main
                    # plot previews the finished gate, matching the subplots
                    # (see GroupPreviewPanel.preview_temp_gate).
                    if len(pts) > 2:  # noqa: PLR2004
                        xs.append(pts[0][0])
                        ys.append(pts[0][1])
                    (line,) = ax.plot(
                        xs,
                        ys,
                        color=GATE_DRAWING_COLOR,
                        linestyle="--",
                        linewidth=2.0,
                        alpha=0.8,
                        zorder=100,
                        animated=True,
                    )
                    self._polygon_artists.append(line)

                if len(self._polygon_vertices) > 0:
                    xs = [p[0] for p in self._polygon_vertices]
                    ys = [p[1] for p in self._polygon_vertices]
                    dots = ax.scatter(
                        xs,
                        ys,
                        color=GATE_DRAWING_COLOR,
                        s=25,
                        alpha=0.8,
                        zorder=101,
                        animated=True,
                    )
                    self._polygon_artists.append(dots)
            finally:
                self.canvas._fig.stale_callback = cb
                self.canvas._fig.stale = False
                ax.stale = False

            if (
                getattr(self.canvas, "_use_cache", False)
                and getattr(self.canvas, "_canvas_bitmap_cache", None) is not None
            ):
                self.canvas._fig.canvas.restore_region(self.canvas._canvas_bitmap_cache)  # type: ignore
                for artist in self._polygon_artists:
                    ax.draw_artist(artist)  # type: ignore
                self.canvas._fig.canvas.blit(ax.bbox)
                self.canvas._fig.canvas.flush_events()
            else:
                self.canvas.draw_idle()

            # Publish temporary polygon for subplots
            try:
                from karcytics_sdk.plugin import CentralEventBus

                from ...analysis import events

                temp_gate = self.canvas._gate_factory.create_polygon(pts)
                CentralEventBus.publish(events.GATE_PREVIEW, {"gate": temp_gate})
            except Exception as e:
                logger.debug(f"Failed to publish polygon preview: {e}")

        self.canvas.raster_lock.try_run(_action, _on_busy)

    def _clear_polygon_progress(self, blit: bool = True):
        def _on_busy() -> None:
            if not getattr(self, "_clear_polygon_timer_active", False):
                self._clear_polygon_timer_active = True
                from PyQt6.QtCore import QTimer

                def _retry() -> None:
                    self._clear_polygon_timer_active = False
                    self._clear_polygon_progress(blit)

                QTimer.singleShot(10, _retry)

        def _action() -> None:
            if self._polygon_artists:
                cb = self.canvas._fig.stale_callback
                self.canvas._fig.stale_callback = None
                try:
                    for artist in self._polygon_artists:
                        try:
                            artist.remove()  # type: ignore
                        except Exception:
                            pass
                finally:
                    self.canvas._fig.stale_callback = cb
                    self.canvas._fig.stale = False
                    self.canvas._ax.stale = False

            self._polygon_artists.clear()

            if blit:
                if (
                    getattr(self.canvas, "_use_cache", False)
                    and getattr(self.canvas, "_canvas_bitmap_cache", None) is not None
                ):
                    self.canvas._fig.canvas.restore_region(  # type: ignore
                        self.canvas._canvas_bitmap_cache
                    )
                    self.canvas._fig.canvas.blit(self.canvas._ax.bbox)
                    self.canvas._fig.canvas.flush_events()
                else:
                    self.canvas.draw_idle()

        self.canvas.raster_lock.try_run(_action, _on_busy)
