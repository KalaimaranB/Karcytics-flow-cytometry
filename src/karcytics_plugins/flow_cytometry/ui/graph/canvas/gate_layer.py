"""Gate layer rendering for FlowCanvas."""

from __future__ import annotations

from typing import TYPE_CHECKING

from karcytics_sdk.plugin import get_logger

if TYPE_CHECKING:
    from ..flow_canvas import FlowCanvas

logger = get_logger(__name__, "flow_cytometry")


class GateLayerRenderer:
    """Handles rendering of gate overlays and labels."""

    def __init__(self, canvas: FlowCanvas) -> None:
        self.canvas = canvas

    def render(self) -> None:
        """Draw gate overlays on top of the cached data layer."""
        canvas = self.canvas
        from karcytics_sdk.plugin.rendering.lock import MPL_RASTER_LOCK

        if not MPL_RASTER_LOCK.acquire(blocking=False):
            from PyQt6.QtCore import QTimer

            QTimer.singleShot(50, self.render)
            return

        try:
            # Remove previous gate artists
            for artist in canvas._gate_artists:
                try:
                    artist.remove()
                except (ValueError, AttributeError, NotImplementedError):
                    pass
            canvas._gate_artists.clear()
            canvas._gate_patches.clear()

            # Draw new gate overlays
            self._redraw_gate_overlays()

            # Re-show instruction text if a tool is active
            from ..flow_canvas import GateDrawingMode

            if canvas._drawing_mode != GateDrawingMode.NONE:
                canvas._show_instruction(canvas._drawing_mode)

            canvas.draw_idle()
        finally:
            MPL_RASTER_LOCK.release()

    def _redraw_gate_overlays(self) -> None:  # noqa: PLR0912
        """Draw all active gate overlays on the axes."""
        canvas = self.canvas
        ax = canvas._ax
        canvas._gate_patches.clear()
        canvas._gate_overlay_artists.clear()

        recorded_geometries = set()
        from ..flow_canvas import DisplayMode

        # Determine if we are in a 1D display mode
        _1d_modes = (DisplayMode.HISTOGRAM, DisplayMode.CDF)
        is_1d_mode = canvas._display_mode in _1d_modes

        # Only RangeGate makes sense on a 1D plot. Import lazily to avoid circular deps.
        from ....analysis.gating import RangeGate

        for gate in canvas._active_gates:
            # On 1D plots, skip any gate that isn't a RangeGate
            if is_1d_mode and not isinstance(gate, RangeGate):
                continue

            # Only draw gates that belong on these axes
            if gate.x_param != canvas._x_param:
                continue
            # For 2D gates also check y_param. RangeGate always has y_param=None
            # (it's a 1D gate) — that means "matches any Y axis", same as the
            # subplot/thumbnail renderer (see render_task.py), so it must not be
            # filtered out here just because a Y channel happens to be active.
            gate_y_param = getattr(gate, "y_param", None)
            if not is_1d_mode and gate_y_param is not None and gate_y_param != canvas._y_param:
                continue

            # If it's a subgate, we track its parent to avoid drawing the same crosshairs 4 times
            geometry_id = gate.parent.gate_id if hasattr(gate, "parent") else gate.gate_id
            if geometry_id in recorded_geometries:
                continue
            recorded_geometries.add(geometry_id)

            # canvas._selected_gate_id holds a GateNode.node_id (see
            # FlowCanvas._on_controller_selected), not a Gate.gate_id — the two
            # are independently-generated UUIDs with no relationship. Selection
            # must therefore be resolved via the nodes that wrap this gate's
            # geometry, not via a direct gate_id comparison. For quadrant
            # subgates this also naturally covers all 4 sibling nodes sharing
            # one parent, since they're matched by parent identity below.
            if hasattr(gate, "parent"):
                sharing_nodes = [
                    n
                    for n in canvas._gate_nodes
                    if n.gate and getattr(n.gate, "parent", None) is gate.parent
                ]
            else:
                sharing_nodes = [
                    n for n in canvas._gate_nodes if n.gate and n.gate.gate_id == gate.gate_id
                ]
            if not sharing_nodes:
                continue

            is_selected = any(n.node_id == canvas._selected_gate_id for n in sharing_nodes)

            # Color is resolved by GateOverlayRenderer.render_gate itself (via
            # resolve_gate_color), so it's identical on the main plot and on subplots.
            artists = canvas._gate_overlay_renderer.render_gate(ax, gate, is_selected)

            if artists:
                canvas._gate_overlay_artists[gate.gate_id] = {
                    "patch": artists.patch,
                    "gate": gate,
                    "artists": artists,
                }
                if artists.patch:
                    canvas._gate_artists.append(artists.patch)
                if hasattr(artists, "extra_artists") and artists.extra_artists:
                    for ea in artists.extra_artists:
                        canvas._gate_artists.append(ea)
                if artists.label_text:
                    canvas._gate_artists.append(artists.label_text)
                if artists.handles:
                    for h in artists.handles.values():
                        canvas._gate_artists.append(h)
