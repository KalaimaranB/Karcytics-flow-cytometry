"""GateEditor — edit-handle geometry, hit-testing, and drag application.

Parallels ``GateFactory`` (creation) and ``GateOverlayRenderer`` (rendering):
one class, one method-pair per gate type, dispatched through ``GateRegistry``
for OCP extension. All math is done in display space via the injected
``CoordinateMapper`` so gate-type code never re-derives the data<->display
transform pipeline. Kept free of any matplotlib ``Axes`` dependency (like
``GateFactory``) — axis-spanning visual placement (e.g. where along a range
gate's vertical line to draw its handle marker) is a rendering concern that
belongs to ``GateOverlayRenderer``, not here.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from karcytics_sdk.plugin import get_logger

from karcytics_plugins.flow_cytometry.analysis.gating import (
    EllipseGate,
    Gate,
    PolygonGate,
    QuadrantGate,
    QuadrantSubGate,
    RangeGate,
    RectangleGate,
)

from .flow_services import CoordinateMapper
from .gate_registry import GateRegistry

logger = get_logger(__name__, "flow_cytometry")

# Deterministic hit-test precedence for rectangle handles so a degenerate
# (near-zero-size) gate resolves ties consistently rather than arbitrarily.
# Exported for FlowCanvas, which owns pixel-space hit-testing (see
# hit_test_handles below for why that can't live in this class).
RECTANGLE_HANDLE_ORDER = ["nw", "ne", "sw", "se", "n", "s", "e", "w"]

# Sentinel handle key meaning "drag the whole gate body" rather than a
# specific resize handle — produced by FlowCanvas body hit-testing, not by
# GateEditor.hit_test_handles (which only ever returns real handle keys).
MOVE_HANDLE = "__move__"


class GateEditor:
    """Computes edit handles for the selected gate and applies drags to it."""

    def __init__(self, coordinate_mapper: CoordinateMapper) -> None:
        self.mapper = coordinate_mapper

    # ── Dispatch ──────────────────────────────────────────────────────

    def get_handles(self, gate: Gate) -> dict[str, tuple[float, float]]:
        """Handle positions in display space, keyed by handle id.

        Registry override -> ``get_handles_{type}`` method -> QuadrantSubGate
        resolves to its parent, mirroring GateOverlayRenderer.render_gate's
        dispatch shape exactly.
        """
        if isinstance(gate, QuadrantSubGate):
            return self.get_handles_quadrant(gate.parent)

        type_key = type(gate).__name__.lower().replace("gate", "")
        handler = GateRegistry.get_edit_handler(type_key)
        if handler:
            return handler(self, gate)

        method_name = f"get_handles_{type_key}"
        if hasattr(self, method_name):
            return getattr(self, method_name)(gate)

        return {}

    # Note: no hit_test_handles() here — a pixel-space hit radius (so the
    # click target stays a constant screen size regardless of zoom/axis
    # scale) needs `ax.transData`, which is a matplotlib Axes concept this
    # class deliberately has no dependency on (mirrors GateFactory). That
    # hit-testing lives in GateHitTester.edit_handle_at instead, which
    # converts get_handles()'s positions to pixels before comparing.

    def apply_drag(
        self,
        gate: Gate,
        handle_key: str,
        x_disp: float,
        y_disp: float,
        anchor: dict[str, Any],
        press_disp: tuple[float, float] | None = None,
    ) -> None:
        """Mutate `gate` in place from the anchor snapshot + current pointer position.

        `anchor` is a pure geometry snapshot from `snapshot()` — every key in
        it is a real attribute name on the target gate. `press_disp` (the
        pointer position at drag-start, in display space) is required only
        for MOVE_HANDLE drags, which need a delta rather than an absolute
        position.
        """
        target = gate.parent if isinstance(gate, QuadrantSubGate) else gate

        type_key = type(target).__name__.lower().replace("gate", "")
        handler = GateRegistry.get_edit_handler(type_key)
        if handler:
            handler(self, target, handle_key, x_disp, y_disp, anchor, press_disp)
            return

        if isinstance(target, RectangleGate):
            self._apply_drag_rectangle(target, handle_key, x_disp, y_disp, anchor, press_disp)
        elif isinstance(target, RangeGate):
            self._apply_drag_range(target, handle_key, x_disp, anchor, press_disp)
        elif isinstance(target, EllipseGate):
            self._apply_drag_ellipse(target, handle_key, x_disp, y_disp, anchor, press_disp)
        elif isinstance(target, PolygonGate):
            self._apply_drag_polygon(target, handle_key, x_disp, y_disp, anchor, press_disp)
        elif isinstance(target, QuadrantGate):
            self._apply_drag_quadrant(target, x_disp, y_disp)
        else:
            logger.debug("No edit-drag handler for gate type: %s", type(target))

    # ── Drag lifecycle helpers ───────────────────────────────────────

    def snapshot(self, gate: Gate) -> dict[str, Any]:
        """Capture the mutable geometry fields needed to restore/diff later."""
        target = gate.parent if isinstance(gate, QuadrantSubGate) else gate
        if isinstance(target, RectangleGate):
            return {
                "x_min": target.x_min,
                "x_max": target.x_max,
                "y_min": target.y_min,
                "y_max": target.y_max,
            }
        if isinstance(target, RangeGate):
            return {"low": target.low, "high": target.high}
        if isinstance(target, QuadrantGate):
            return {"x_mid": target.x_mid, "y_mid": target.y_mid}
        if isinstance(target, EllipseGate):
            return {"center": target.center, "width": target.width, "height": target.height}
        if isinstance(target, PolygonGate):
            return {"vertices": list(target.vertices)}
        return {}

    def restore(self, gate: Gate, anchor: dict[str, Any]) -> None:
        """Reset `gate` back to its pre-drag anchor state (drag cancellation)."""
        target = gate.parent if isinstance(gate, QuadrantSubGate) else gate
        for key, value in anchor.items():
            setattr(target, key, value)

    def changed(self, gate: Gate, anchor: dict[str, Any]) -> bool:
        return bool(self.diff_kwargs(gate, anchor))

    def diff_kwargs(self, gate: Gate, anchor: dict[str, Any]) -> dict[str, Any]:
        """Attributes that differ from the anchor snapshot — the modify_gate() kwargs."""
        target = gate.parent if isinstance(gate, QuadrantSubGate) else gate
        diff: dict[str, Any] = {}
        for key, old_value in anchor.items():
            new_value = getattr(target, key, old_value)
            if new_value != old_value:
                diff[key] = new_value
        return diff

    # ── Rectangle ─────────────────────────────────────────────────────

    def get_handles_rectangle(self, gate: RectangleGate) -> dict[str, tuple[float, float]]:
        x_min = self.mapper.transform_x(np.array([gate.x_min]))[0]
        x_max = self.mapper.transform_x(np.array([gate.x_max]))[0]
        y_min = self.mapper.transform_y(np.array([gate.y_min]))[0]
        y_max = self.mapper.transform_y(np.array([gate.y_max]))[0]
        x_mid = (x_min + x_max) / 2
        y_mid = (y_min + y_max) / 2
        return {
            "nw": (x_min, y_max),
            "ne": (x_max, y_max),
            "sw": (x_min, y_min),
            "se": (x_max, y_min),
            "n": (x_mid, y_max),
            "s": (x_mid, y_min),
            "e": (x_max, y_mid),
            "w": (x_min, y_mid),
        }

    def _apply_drag_rectangle(
        self,
        gate: RectangleGate,
        handle_key: str,
        x_disp: float,
        y_disp: float,
        anchor: dict[str, Any],
        press_disp: tuple[float, float] | None,
    ) -> None:
        if handle_key == MOVE_HANDLE:
            dx_raw, dy_raw = self._raw_delta(x_disp, y_disp, press_disp)
            x_min = anchor["x_min"] + dx_raw
            x_max = anchor["x_max"] + dx_raw
            y_min = anchor["y_min"] + dy_raw
            y_max = anchor["y_max"] + dy_raw
        else:
            x_raw = self.mapper.inverse_transform_x(np.array([x_disp]))[0]
            y_raw = self.mapper.inverse_transform_y(np.array([y_disp]))[0]
            x_min, x_max = anchor["x_min"], anchor["x_max"]
            y_min, y_max = anchor["y_min"], anchor["y_max"]
            if "w" in handle_key:
                x_min = x_raw
            if "e" in handle_key:
                x_max = x_raw
            if "n" in handle_key:
                y_max = y_raw
            if "s" in handle_key:
                y_min = y_raw

        # Corner/edge-swap: dragging a handle past its opposite handle swaps
        # which side is "active" instead of producing an inverted gate.
        if x_min > x_max:
            x_min, x_max = x_max, x_min
        if y_min > y_max:
            y_min, y_max = y_max, y_min

        gate.x_min, gate.x_max = x_min, x_max
        gate.y_min, gate.y_max = y_min, y_max

    # ── Range ─────────────────────────────────────────────────────────

    def get_handles_range(self, gate: RangeGate) -> dict[str, tuple[float, float]]:
        x_low = self.mapper.transform_x(np.array([gate.low]))[0]
        x_high = self.mapper.transform_x(np.array([gate.high]))[0]
        # Y is a placeholder — hit-testing ignores it (see hit_test_handles)
        # and GateOverlayRenderer picks a real on-screen y from the axes'
        # current ylim when placing the visual marker.
        return {"low": (x_low, 0.0), "high": (x_high, 0.0)}

    def _apply_drag_range(
        self,
        gate: RangeGate,
        handle_key: str,
        x_disp: float,
        anchor: dict[str, Any],
        press_disp: tuple[float, float] | None,
    ) -> None:
        if handle_key == MOVE_HANDLE:
            dx_raw, _ = self._raw_delta(x_disp, 0.0, press_disp, y_axis=False)
            low = anchor["low"] + dx_raw
            high = anchor["high"] + dx_raw
        else:
            x_raw = self.mapper.inverse_transform_x(np.array([x_disp]))[0]
            low, high = anchor["low"], anchor["high"]
            if handle_key == "low":
                low = x_raw
            elif handle_key == "high":
                high = x_raw

        if low > high:
            low, high = high, low

        gate.low, gate.high = low, high

    # ── Ellipse ───────────────────────────────────────────────────────

    def get_handles_ellipse(self, gate: EllipseGate) -> dict[str, tuple[float, float]]:
        cx, cy = gate.center
        cx_disp = self.mapper.transform_x(np.array([cx]))[0]
        cy_disp = self.mapper.transform_y(np.array([cy]))[0]
        w_disp = abs(self.mapper.transform_x(np.array([cx + gate.width]))[0] - cx_disp)
        h_disp = abs(self.mapper.transform_y(np.array([cy + gate.height]))[0] - cy_disp)
        return {
            "n": (cx_disp, cy_disp + h_disp),
            "s": (cx_disp, cy_disp - h_disp),
            "e": (cx_disp + w_disp, cy_disp),
            "w": (cx_disp - w_disp, cy_disp),
        }

    def _apply_drag_ellipse(
        self,
        gate: EllipseGate,
        handle_key: str,
        x_disp: float,
        y_disp: float,
        anchor: dict[str, Any],
        press_disp: tuple[float, float] | None,
    ) -> None:
        cx, cy = anchor["center"]
        if handle_key == MOVE_HANDLE:
            dx_raw, dy_raw = self._raw_delta(x_disp, y_disp, press_disp)
            gate.center = (cx + dx_raw, cy + dy_raw)
            return

        x_raw = self.mapper.inverse_transform_x(np.array([x_disp]))[0]
        y_raw = self.mapper.inverse_transform_y(np.array([y_disp]))[0]
        width, height = anchor["width"], anchor["height"]
        if handle_key in ("e", "w"):
            width = abs(x_raw - cx)
        if handle_key in ("n", "s"):
            height = abs(y_raw - cy)
        gate.width, gate.height = width, height

    # ── Polygon ───────────────────────────────────────────────────────

    def get_handles_polygon(self, gate: PolygonGate) -> dict[str, tuple[float, float]]:
        if not gate.vertices:
            return {}
        vx = np.array([v[0] for v in gate.vertices])
        vy = np.array([v[1] for v in gate.vertices])
        disp_x = self.mapper.transform_x(vx)
        disp_y = self.mapper.transform_y(vy)
        return {f"v{i}": (float(disp_x[i]), float(disp_y[i])) for i in range(len(gate.vertices))}

    def _apply_drag_polygon(
        self,
        gate: PolygonGate,
        handle_key: str,
        x_disp: float,
        y_disp: float,
        anchor: dict[str, Any],
        press_disp: tuple[float, float] | None,
    ) -> None:
        anchor_vertices: list[tuple[float, float]] = anchor["vertices"]

        if handle_key == MOVE_HANDLE:
            dx_raw, dy_raw = self._raw_delta(x_disp, y_disp, press_disp)
            gate.vertices = [(vx + dx_raw, vy + dy_raw) for vx, vy in anchor_vertices]
            return

        if not handle_key.startswith("v"):
            return
        try:
            idx = int(handle_key[1:])
        except ValueError:
            return
        if not (0 <= idx < len(anchor_vertices)):
            return

        x_raw = self.mapper.inverse_transform_x(np.array([x_disp]))[0]
        y_raw = self.mapper.inverse_transform_y(np.array([y_disp]))[0]
        vertices = list(anchor_vertices)
        vertices[idx] = (float(x_raw), float(y_raw))
        gate.vertices = vertices

    # ── Quadrant ──────────────────────────────────────────────────────

    def get_handles_quadrant(self, gate: QuadrantGate) -> dict[str, tuple[float, float]]:
        x_mid = self.mapper.transform_x(np.array([gate.x_mid]))[0]
        y_mid = self.mapper.transform_y(np.array([gate.y_mid]))[0]
        return {"center": (x_mid, y_mid)}

    def _apply_drag_quadrant(self, gate: QuadrantGate, x_disp: float, y_disp: float) -> None:
        gate.x_mid = self.mapper.inverse_transform_x(np.array([x_disp]))[0]
        gate.y_mid = self.mapper.inverse_transform_y(np.array([y_disp]))[0]

    # ── Internal helpers ──────────────────────────────────────────────

    def _raw_delta(
        self,
        x_disp: float,
        y_disp: float,
        press_disp: tuple[float, float] | None,
        y_axis: bool = True,
    ) -> tuple[float, float]:
        """Raw-data-space (dx, dy) between `press_disp` and the current point."""
        if press_disp is None:
            return 0.0, 0.0
        px_disp, py_disp = press_disp
        x_raw = self.mapper.inverse_transform_x(np.array([x_disp, px_disp]))
        dx_raw = float(x_raw[0] - x_raw[1])
        dy_raw = 0.0
        if y_axis:
            y_raw = self.mapper.inverse_transform_y(np.array([y_disp, py_disp]))
            dy_raw = float(y_raw[0] - y_raw[1])
        return dx_raw, dy_raw
