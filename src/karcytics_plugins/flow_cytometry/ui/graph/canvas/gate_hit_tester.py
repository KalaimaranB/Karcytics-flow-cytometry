"""What a click on a gating plot lands on: a gate, the selected gate's handle, or its body.

Only the *selected* gate exposes handles and a body to drag, which keeps
overlapping gates unambiguous: a gate is selected first (the top-most under
the click, or Alt+click to cycle), so a drag never grabs whichever gate
happens to lie underneath.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import numpy as np

from ....analysis.gating import Gate, QuadrantSubGate, RangeGate
from ..flow_services import OverlayArtists
from ..gate_editor import RECTANGLE_HANDLE_ORDER

HANDLE_RADIUS_PX = 8.0  # a constant screen size, whatever the zoom or axis scale


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


def overlay_artists(bundle: OverlayArtists | None) -> Iterator[Any]:
    """Every matplotlib artist in one gate's overlay bundle."""
    if bundle is None:
        return
    if bundle.patch is not None:
        yield bundle.patch
    yield from bundle.extra_artists or ()
    if bundle.label_text is not None:
        yield bundle.label_text
    yield from (bundle.handles or {}).values()


class GateHitTester:
    """Hit tests against one canvas's gate overlays (coordinates in plot space)."""

    def __init__(self, canvas: Any) -> None:
        self._canvas = canvas

    def gates_at(self, x: float, y: float) -> list[str]:
        """Overlay keys (gate ids) under the point, bottom-most first (draw order)."""
        px, py = self._canvas.ax.transData.transform((x, y))
        return [
            key
            for key, info in self._canvas.gate_overlays.items()
            if artist_contains_point(info["patch"], px, py)
        ]

    def node_id_for(self, gate_id: str) -> str | None:
        """The displayed gate node drawing ``gate_id``."""
        for node in self._canvas.gate_nodes:
            if node.gate is not None and node.gate.gate_id == gate_id:
                return node.node_id
        return None

    def selected_gate(self) -> Gate | None:
        """The gate of the selected node (``_selected_gate_id`` is a node id)."""
        selected = self._canvas.selected_node_id
        if not selected:
            return None
        for node in self._canvas.gate_nodes:
            if node.node_id == selected and node.gate is not None:
                return node.gate
        return None

    def edit_handle_at(self, x: float, y: float) -> tuple[Gate, str] | None:
        """The selected gate and which of its handles is within reach of the point."""
        gate = self.selected_gate()
        if gate is None:
            return None
        handles = self._canvas.gate_editor.get_handles(gate)
        if not handles:
            return None
        target = gate.parent if isinstance(gate, QuadrantSubGate) else gate
        x_only = isinstance(target, RangeGate)
        order = RECTANGLE_HANDLE_ORDER if hasattr(target, "x_min") else list(handles)

        to_px = self._canvas.ax.transData.transform
        mouse_x, mouse_y = to_px((x, y))
        best_key, best_distance = None, HANDLE_RADIUS_PX
        for key in order:
            if key not in handles:
                continue
            hx, hy = to_px(handles[key])
            distance = abs(hx - mouse_x) if x_only else float(np.hypot(hx - mouse_x, hy - mouse_y))
            if distance <= best_distance:
                best_key, best_distance = key, distance
        return (gate, best_key) if best_key is not None else None

    def overlay_key_for(self, gate: Gate) -> str | None:
        """Which overlay entry draws ``gate``.

        A quadrant's crosshair is drawn once, keyed by whichever of its four
        sub-gates came first, not necessarily the one selected: match by parent.
        """
        overlays = self._canvas.gate_overlays
        if gate.gate_id in overlays:
            return gate.gate_id
        if isinstance(gate, QuadrantSubGate):
            for key, info in overlays.items():
                other = info.get("gate")
                if isinstance(other, QuadrantSubGate) and other.parent is gate.parent:
                    return key
        return None

    def selected_body_at(self, x: float, y: float) -> Gate | None:
        """The selected gate, if the point is inside its body (to move it whole).

        A range's body is its shaded span, tested from its bounds; a quadrant has
        no body (its centre handle is the move).
        """
        gate = self.selected_gate()
        if gate is None:
            return None
        key = self.overlay_key_for(gate)
        info = self._canvas.gate_overlays.get(key) if key else None
        patch = info.get("patch") if info else None
        if patch is None:
            return None
        target = gate.parent if isinstance(gate, QuadrantSubGate) else gate
        if isinstance(target, RangeGate):
            raw_x = self._canvas.coordinate_mapper.inverse_transform_x(np.array([x]))[0]
            return gate if target.low <= raw_x <= target.high else None
        if not hasattr(patch, "contains_point"):
            return None
        px, py = self._canvas.ax.transData.transform((x, y))
        return gate if artist_contains_point(patch, px, py) else None
