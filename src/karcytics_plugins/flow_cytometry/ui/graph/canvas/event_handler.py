"""Mouse and keyboard event handlers for FlowCanvas."""

from __future__ import annotations

from typing import TYPE_CHECKING

from karcytics_sdk.plugin import get_logger

if TYPE_CHECKING:
    from ..flow_canvas import FlowCanvas

logger = get_logger(__name__, "flow_cytometry")


class _PixelEvent:
    """Minimal mouseevent-like object — Artist.contains() only reads .x/.y."""

    __slots__ = ("x", "y")

    def __init__(self, x: float, y: float) -> None:
        self.x = x
        self.y = y


def artist_contains_point(artist, px: float, py: float) -> bool:
    """Hit-test an arbitrary matplotlib artist at a pixel-space point.

    ``Patch`` subclasses (Rectangle, Ellipse, Polygon) implement
    ``contains_point((px, py))`` directly. ``Line2D`` — used as the overlay
    ``patch`` for RangeGate and QuadrantGate, whose visuals are lines rather
    than filled shapes — has no ``contains_point`` at all, only the generic
    ``Artist.contains(mouseevent)``, which needs an object exposing pixel
    ``.x``/``.y`` attributes rather than a raw coordinate pair.
    """
    if hasattr(artist, "contains_point"):
        return bool(artist.contains_point((px, py)))
    contained, _ = artist.contains(_PixelEvent(px, py))
    return bool(contained)


class CanvasEventHandler:
    """Handles interaction events (mouse, keyboard) for FlowCanvas."""

    def __init__(self, canvas: FlowCanvas) -> None:
        self.canvas = canvas

    def handle_press(self, event) -> None:
        """Handle mouse press."""
        canvas = self.canvas
        if event.inaxes != canvas._ax or event.dblclick:
            return

        logger.info(f"CanvasEventHandler.handle_press: x={event.xdata:.2f}, y={event.ydata:.2f}")
        # matplotlib's own modifier tracking (event.key) is unreliable across
        # backends for a plain button-press with no preceding key event —
        # ask Qt directly instead, same as any other Alt-chord shortcut.
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QApplication

        modifiers = QApplication.keyboardModifiers()
        alt_cycle = bool(modifiers & Qt.KeyboardModifier.AltModifier)
        canvas._fsm.handle_press(
            event.xdata, event.ydata, canvas._drawing_mode.value, alt_cycle=alt_cycle
        )

    def handle_motion(self, event) -> None:
        """Handle mouse movement."""
        canvas = self.canvas
        if event.inaxes != canvas._ax:
            return
        canvas._fsm.handle_motion(event.xdata, event.ydata, canvas._drawing_mode.value)

    def handle_release(self, event) -> None:
        """Handle mouse release."""
        canvas = self.canvas

        # If we are not actively drawing, releasing outside axes shouldn't matter.
        # But if we ARE drawing a drag gate, we want to finalize it where the mouse was released!
        fsm_state = getattr(canvas._fsm, "state", None)
        if fsm_state and fsm_state.name == "DRAWING":
            # Compute data coordinates even if outside axes
            x, y = canvas._ax.transData.inverted().transform((event.x, event.y))
            canvas._fsm.handle_release(x, y, canvas._drawing_mode.value)
            return

        if event.inaxes != canvas._ax:
            # Not actively dragging, so a release landing just outside the
            # axes (e.g. a 1px drift near the plot edge) isn't a cancel
            # gesture — wiping FSM state here would discard an in-progress
            # polygon's vertices even though the press that placed them was
            # valid. Explicit cancellation is handled via the Escape key
            # (see handle_key_press / _cancel_drawing).
            return

        canvas._fsm.handle_release(event.xdata, event.ydata, canvas._drawing_mode.value)

    def handle_dblclick(self, event) -> None:
        """Handle double-click."""
        canvas = self.canvas
        if not event.dblclick or event.inaxes != canvas._ax:
            return
        canvas._fsm.handle_dblclick(event.xdata, event.ydata, canvas._drawing_mode.value)

    def handle_key_press(self, event) -> None:
        """Handle keyboard press."""
        canvas = self.canvas
        from PyQt6.QtCore import Qt as _Qt

        from ..flow_canvas import GateDrawingMode

        if event.key() == _Qt.Key.Key_Escape:
            if canvas._drawing_mode != GateDrawingMode.NONE:
                from ..gate_drawing_fsm import DrawingState

                was_idle = getattr(canvas._fsm, "state", None) == DrawingState.IDLE

                canvas._cancel_drawing()
                canvas._render_gate_layer()

                if was_idle:
                    canvas.drawing_cancelled.emit()

    # ── Finalization methods (called by FSM) ──────────────────────────

    def finalize_drag_gate(self, x0: float, y0: float, x1: float, y1: float, mode: str) -> None:
        """Finalize a gate drawn by dragging."""
        canvas = self.canvas
        if mode == "rectangle":
            gate = canvas._gate_factory.create_rectangle(x0, y0, x1, y1)
            canvas.gate_created.emit(gate)
        elif mode == "ellipse":
            gate = canvas._gate_factory.create_ellipse(x0, y0, x1, y1)  # type: ignore
            canvas.gate_created.emit(gate)
        elif mode == "range":
            gate = canvas._gate_factory.create_range(x0, x1)  # type: ignore
            canvas.gate_created.emit(gate)
        canvas._clear_previews()

    def finalize_polygon(self, vertices: list[tuple[float, float]]) -> None:
        """Finalize a polygon gate."""
        canvas = self.canvas
        gate = canvas._gate_factory.create_polygon(vertices)
        canvas.gate_created.emit(gate)
        canvas._clear_previews()

    def finalize_quadrant(self, x: float, y: float) -> None:
        """Finalize a quadrant gate."""
        canvas = self.canvas
        gate = canvas._gate_factory.create_quadrant(x, y)
        canvas.gate_created.emit(gate)
        canvas._clear_previews()

    def try_select_gate(self, x: float, y: float, alt_cycle: bool = False) -> bool:
        """Check if a click hits any gate overlay and select it.

        `alt_cycle`: instead of always picking the top-most gate under the
        cursor, cycle to the next hit after the currently-selected one (
        wrapping around) — how a user reaches a gate fully occluded by
        another without having to move or delete anything first.
        """
        canvas = self.canvas
        px, py = canvas._ax.transData.transform((x, y))

        # _gate_overlay_artists is populated in draw order (see gate_layer.py's
        # _redraw_gate_overlays), so later entries render on top.
        hits = [
            gate_id
            for gate_id, info in canvas._gate_overlay_artists.items()
            if artist_contains_point(info["patch"], px, py)
        ]

        hit_id = None
        if alt_cycle:
            if hits:
                selected_gate = canvas._find_selected_gate()
                selected_key = selected_gate.gate_id if selected_gate else None
                if selected_key in hits:
                    idx = hits.index(selected_key)
                    hit_id = hits[(idx + 1) % len(hits)]
                else:
                    hit_id = hits[-1]  # no cycle context yet — same as a normal click
        elif hits:
            # Search in reverse so an overlap resolves to the visually
            # top-most gate under the cursor rather than the first
            # (bottom-most) one added.
            hit_id = hits[-1]

        node_id = canvas._find_node_id_for_gate(hit_id) if hit_id else None

        if canvas._controller:
            canvas._controller.select_gate(canvas._sample_id, node_id)  # type: ignore
        else:
            old_selected = canvas._selected_gate_id
            canvas._selected_gate_id = node_id
            if node_id != old_selected:
                canvas._render_gate_layer()
                canvas.gate_selected.emit(node_id)

        return hit_id is not None
