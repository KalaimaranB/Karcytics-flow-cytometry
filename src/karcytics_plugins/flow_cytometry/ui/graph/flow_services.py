"""Service classes for FlowCanvas — separation of concerns.

This module extracts key responsibilities from FlowCanvas into focused,
testable service classes following SOLID principles:

- CoordinateMapper: Transform/inverse-transform coordinates
- GateFactory: Create gate objects from drawing parameters
- PlotRenderer: Render plot data (scatter, histogram, contour, etc.)
- GateOverlayRenderer: Render gate overlays as matplotlib artists
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass
from typing import Any

import numpy as np
from karcytics_sdk.plugin import get_logger
from matplotlib.axes import Axes
from matplotlib.lines import Line2D
from matplotlib.patches import (
    Ellipse as MplEllipse,
)
from matplotlib.patches import (
    FancyBboxPatch,
)
from matplotlib.patches import (
    Polygon as MplPolygon,
)
from matplotlib.patches import (
    Rectangle as MplRectangle,
)

from karcytics_plugins.flow_cytometry.analysis._utils import BiexponentialParameters
from karcytics_plugins.flow_cytometry.analysis.constants import (
    GATE_COLOR_PALETTE,
    GATE_SELECTED_COLOR,
    OVERLAY_COLORS,
)
from karcytics_plugins.flow_cytometry.analysis.gating import (
    EllipseGate,
    Gate,
    PolygonGate,
    QuadrantGate,
    RangeGate,
    RectangleGate,
)
from karcytics_plugins.flow_cytometry.analysis.scaling import AxisScale
from karcytics_plugins.flow_cytometry.analysis.transforms import (
    TransformType,
    apply_transform,
    invert_transform,
)

logger = get_logger(__name__, "flow_cytometry")

# Maximum absolute coordinate value accepted by matplotlib text rendering without
# triggering FT_Render_Glyph raster overflow crashes.
_LABEL_COORD_OVERFLOW_LIMIT: float = 1e10


class CoordinateMapper:
    """Transform/inverse-transform coordinates using axis scales and transforms.

    Centralizes all coordinate mapping logic, making it:
    - Testable without UI
    - Reusable in other renderers
    - Easy to modify transformation pipeline
    """

    def __init__(self, x_scale: AxisScale, y_scale: AxisScale | None = None):
        """Initialize mapper with axis scales.

        Args:
            x_scale: Scale configuration for X-axis (transform type, parameters)
            y_scale: Scale configuration for Y-axis
        """
        self.x_scale = x_scale
        self.y_scale = y_scale

    def update_scales(self, x_scale: AxisScale, y_scale: AxisScale | None = None) -> None:
        """Update axis scales (called when axes change)."""
        self.x_scale = x_scale
        self.y_scale = y_scale

    @staticmethod
    def _biexp_kwargs(scale: AxisScale) -> dict:
        """Biexponential params for exact coordinate mapping (never dithered).

        BiexponentialParameters defaults enable_dithering to True, which is
        meant for the raw per-event data arrays of a density/scatter plot
        (it randomly jitters values by +/-0.5 to avoid integer "barcode"
        banding). CoordinateMapper instead computes exact positions — axis
        limits, gate boundaries, click coordinates — where the same input
        must always map to the same output. Forcing it off here keeps
        transform_point() and transform_x()/transform_y() consistent for
        the same value, and keeps gate/axis geometry stable across renders.
        """
        kwargs = BiexponentialParameters(scale).to_dict()
        kwargs["enable_dithering"] = False
        return kwargs

    def transform_x(self, x: np.ndarray) -> np.ndarray:
        """Transform X coordinates for display."""
        x_kwargs = (
            self._biexp_kwargs(self.x_scale)
            if self.x_scale.transform_type == TransformType.BIEXPONENTIAL
            else {}
        )
        return apply_transform(x, self.x_scale.transform_type, **x_kwargs)

    def transform_y(self, y: np.ndarray) -> np.ndarray:
        """Transform Y coordinates for display."""
        if self.y_scale is None:
            return y
        y_kwargs = (
            self._biexp_kwargs(self.y_scale)
            if self.y_scale.transform_type == TransformType.BIEXPONENTIAL
            else {}
        )
        return apply_transform(y, self.y_scale.transform_type, **y_kwargs)

    def inverse_transform_x(self, x: np.ndarray) -> np.ndarray:
        """Inverse-transform X coordinates (display → data space)."""
        x_kwargs = (
            self._biexp_kwargs(self.x_scale)
            if self.x_scale.transform_type == TransformType.BIEXPONENTIAL
            else {}
        )
        return invert_transform(x, self.x_scale.transform_type, **x_kwargs)

    def inverse_transform_y(self, y: np.ndarray) -> np.ndarray:
        """Inverse-transform Y coordinates (display → data space)."""
        if self.y_scale is None:
            return y
        y_kwargs = (
            self._biexp_kwargs(self.y_scale)
            if self.y_scale.transform_type == TransformType.BIEXPONENTIAL
            else {}
        )
        return invert_transform(y, self.y_scale.transform_type, **y_kwargs)

    def transform_point(self, x: float, y: float) -> tuple[float, float]:
        """Transform a single point (data → display space)."""
        return (
            self.transform_x(np.array([x]))[0],
            self.transform_y(np.array([y]))[0],
        )

    def untransform_point(self, x: float, y: float) -> tuple[float, float]:
        """Untransform a single point (display → data space)."""
        return (
            self.inverse_transform_x(np.array([x]))[0],
            self.inverse_transform_y(np.array([y]))[0],
        )


class GateFactory:
    """Create gate objects from drawing parameters.

    Extracts gate creation logic from FlowCanvas, enabling:
    - Unit testing of gate instantiation
    - Consistent gate initialization
    - Separation of UI drawing from business logic
    """

    def __init__(
        self,
        x_param: str,
        y_param: str,
        x_scale: AxisScale,
        y_scale: AxisScale,
        coordinate_mapper: CoordinateMapper,
    ):
        """Initialize factory with parameters and coordinate mapper.

        Args:
            x_param: Name of X-axis parameter (e.g., 'FSC-A')
            y_param: Name of Y-axis parameter (e.g., 'SSC-A')
            x_scale: Scale configuration for X-axis
            y_scale: Scale configuration for Y-axis
            coordinate_mapper: CoordinateMapper for transformations
        """
        self.x_param = x_param
        self.y_param = y_param
        self.x_scale = x_scale
        self.y_scale = y_scale
        self.mapper = coordinate_mapper

    def update_params(self, x_param: str, y_param: str) -> None:
        """Update axis parameters (called when axes change)."""
        self.x_param = x_param
        self.y_param = y_param

    def update_scales(self, x_scale: AxisScale, y_scale: AxisScale) -> None:
        """Update axis scales (called when scales change)."""
        self.x_scale = x_scale
        self.y_scale = y_scale
        self.mapper.update_scales(x_scale, y_scale)

    def create_rectangle(self, x0: float, y0: float, x1: float, y1: float) -> RectangleGate:
        """Create a RectangleGate from display coordinates.

        Args:
            x0, y0: First corner in display space
            x1, y1: Opposite corner in display space

        Returns:
            RectangleGate with coordinates in data space
        """
        # Normalize coordinates
        min_x, max_x = min(x0, x1), max(x0, x1)
        min_y, max_y = min(y0, y1), max(y0, y1)

        # Transform to data space
        rx0, rx1 = self.mapper.inverse_transform_x(np.array([min_x, max_x]))
        ry0, ry1 = self.mapper.inverse_transform_y(np.array([min_y, max_y]))

        gate = RectangleGate(
            x_param=self.x_param,
            y_param=self.y_param,
            x_min=rx0,
            x_max=rx1,
            y_min=ry0,
            y_max=ry1,
            x_scale=self.x_scale.copy(),
            y_scale=self.y_scale.copy(),
        )
        logger.info("Rectangle gate created: %s", gate)
        return gate

    def create_polygon(self, display_vertices: list[tuple[float, float]]) -> PolygonGate:
        """Create a PolygonGate from display coordinates.

        Args:
            display_vertices: List of (x, y) points in display space

        Returns:
            PolygonGate with coordinates in data space
        """
        if len(display_vertices) < 3:  # noqa: PLR2004
            raise ValueError("Polygon requires at least 3 vertices")

        pts_x = np.array([v[0] for v in display_vertices])
        pts_y = np.array([v[1] for v in display_vertices])

        raw_x = self.mapper.inverse_transform_x(pts_x)
        raw_y = self.mapper.inverse_transform_y(pts_y)
        raw_vertices = list(zip(raw_x, raw_y, strict=False))

        gate = PolygonGate(
            x_param=self.x_param,
            y_param=self.y_param,
            vertices=raw_vertices,
            x_scale=self.x_scale.copy(),
            y_scale=self.y_scale.copy(),
        )
        logger.info("Polygon gate created: %s (%d vertices)", gate, len(gate.vertices))
        return gate

    def create_ellipse(self, x0: float, y0: float, x1: float, y1: float) -> EllipseGate:
        """Create an EllipseGate from bounding box in display coordinates.

        Args:
            x0, y0: First corner of bounding box in display space
            x1, y1: Opposite corner of bounding box in display space

        Returns:
            EllipseGate with center/width/height in data space
        """
        # Calculate center and half-axes in display space
        cx = (x0 + x1) / 2
        cy = (y0 + y1) / 2
        w = abs(x1 - x0) / 2
        h = abs(y1 - y0) / 2

        # Transform center
        rcx = self.mapper.inverse_transform_x(np.array([cx]))[0]
        rcy = self.mapper.inverse_transform_y(np.array([cy]))[0]

        # Transform half-axes (measure from center)
        rx_w = abs(self.mapper.inverse_transform_x(np.array([cx + w]))[0] - rcx)
        ry_h = abs(self.mapper.inverse_transform_y(np.array([cy + h]))[0] - rcy)

        gate = EllipseGate(
            x_param=self.x_param,
            y_param=self.y_param,
            center=(rcx, rcy),
            width=rx_w,
            height=ry_h,
            angle=0.0,
            x_scale=self.x_scale.copy(),
            y_scale=self.y_scale.copy(),
        )
        logger.info("Ellipse gate created: %s", gate)
        return gate

    def create_quadrant(self, x: float, y: float) -> QuadrantGate:
        """Create a QuadrantGate at display coordinates.

        Args:
            x, y: Midpoint in display space

        Returns:
            QuadrantGate with midpoint in data space
        """
        rx, ry = self.mapper.untransform_point(x, y)

        gate = QuadrantGate(
            x_param=self.x_param,
            y_param=self.y_param,
            x_mid=rx,
            y_mid=ry,
            x_scale=self.x_scale.copy(),
            y_scale=self.y_scale.copy(),
        )
        logger.info("Quadrant gate created: %s at (%.2f, %.2f)", gate, x, y)
        return gate

    def create_range(self, x0: float, x1: float) -> RangeGate:
        """Create a RangeGate from display coordinates.

        Args:
            x0, x1: Range bounds in display space

        Returns:
            RangeGate with bounds in data space
        """
        min_x, max_x = min(x0, x1), max(x0, x1)
        rx0, rx1 = self.mapper.inverse_transform_x(np.array([min_x, max_x]))

        gate = RangeGate(
            x_param=self.x_param,
            low=rx0,
            high=rx1,
            x_scale=self.x_scale.copy(),
        )
        logger.info("Range gate created: %s", gate)
        return gate


def resolve_gate_color(gate: Gate, is_selected: bool = False) -> str:
    """Deterministic color for a gate, stable across the main plot and all subplots.

    Colors are derived from the gate's own id (not its position in whatever
    list happens to be rendering it), so the same gate always gets the same
    color regardless of which panel — main plot, group-preview thumbnail, or
    node-graph thumbnail — draws it.
    """
    if is_selected:
        return GATE_SELECTED_COLOR
    key_gate = getattr(gate, "parent", None) or gate
    key = getattr(key_gate, "gate_id", None) or str(id(key_gate))
    index = zlib.crc32(key.encode()) % len(GATE_COLOR_PALETTE)
    return GATE_COLOR_PALETTE[index]


@dataclass
class OverlayArtists:
    """Group of matplotlib artists for a single gate overlay."""

    patch: MplRectangle | MplPolygon | MplEllipse | FancyBboxPatch | Line2D
    label_text: Line2D | None = None
    handles: dict[str, Line2D] | None = None
    extra_artists: list[Any] | None = None


class GateOverlayRenderer:
    """Render gates as matplotlib artists on axes.

    Extracts gate rendering logic, enabling:
    - Rendering gates in different contexts (plots, thumbnails, exports)
    - Decoupling from matplotlib backend details
    - Testable rendering without matplotlib display
    """

    # Color scheme for gate overlays
    OVERLAY_COLORS = OVERLAY_COLORS

    def __init__(
        self,
        coordinate_mapper: CoordinateMapper,
        linewidth: float = 2.5,
        show_labels: bool = True,
    ):
        """Initialize renderer with coordinate mapper.

        Args:
            coordinate_mapper: CoordinateMapper for display-space calculations
            linewidth: Base thickness for gate lines
            show_labels: Whether to draw text labels on gates
        """
        self.mapper = coordinate_mapper
        self.linewidth = linewidth
        self.show_labels = show_labels
        self._gate_editor = None  # lazily constructed — see _get_gate_editor()

    def _get_gate_editor(self):
        """Lazily import/construct GateEditor to avoid a circular import.

        gate_editor.py imports CoordinateMapper from this module, so this
        module cannot import GateEditor at module scope.
        """
        if self._gate_editor is None:
            from .gate_editor import GateEditor

            self._gate_editor = GateEditor(self.mapper)
        return self._gate_editor

    def _render_handle_markers(
        self,
        ax: Axes,
        positions: dict[str, tuple[float, float]],
        color: str,
    ) -> dict[str, Line2D]:
        """Draw one small square marker per handle position, only called when selected."""
        markers: dict[str, Line2D] = {}
        for key, (hx, hy) in positions.items():
            (marker,) = ax.plot(
                [hx],
                [hy],
                marker="s",
                markersize=7,
                markerfacecolor="white",
                markeredgecolor=color,
                markeredgewidth=1.5,
                linestyle="none",
                zorder=1002,
            )
            markers[key] = marker
        return markers

    def render_gate(
        self,
        ax: Axes,
        gate: Gate,
        is_selected: bool = False,
        color: str | None = None,
    ) -> OverlayArtists | None:
        """Generic entry point for rendering any gate type using OCP dispatch."""
        from .gate_registry import GateRegistry

        # Check if there is a specialized renderer registered
        type_key = type(gate).__name__.lower().replace("gate", "")
        handler = GateRegistry.get_overlay_renderer(type_key)

        if handler:
            return handler(self, ax, gate, is_selected, color)

        # Fallback to internal methods for core gates
        method_name = f"render_{type_key}"
        if hasattr(self, method_name):
            return getattr(self, method_name)(ax, gate, is_selected, color)

        # If it's a QuadrantSubGate, render its parent QuadrantGate instead
        if type_key == "quadrantsub" and hasattr(gate, "parent"):
            return self.render_quadrant(ax, gate.parent, is_selected, color)

        logger.warning(f"No renderer found for gate type: {type(gate)}")
        return None

    def render_rectangle(
        self,
        ax: Axes,
        gate: RectangleGate,
        is_selected: bool = False,
        color: str | None = None,
    ) -> OverlayArtists:
        """Render RectangleGate on axes."""
        x_min = self.mapper.transform_x(np.array([gate.x_min]))[0]
        x_max = self.mapper.transform_x(np.array([gate.x_max]))[0]
        y_min = self.mapper.transform_y(np.array([gate.y_min]))[0]
        y_max = self.mapper.transform_y(np.array([gate.y_max]))[0]

        width = x_max - x_min
        height = y_max - y_min

        edge_color = color if color else resolve_gate_color(gate, is_selected)
        patch = MplRectangle(
            (x_min, y_min),
            width,
            height,
            linewidth=self.linewidth if not is_selected else self.linewidth * 1.5,
            edgecolor=edge_color,
            facecolor="none",
            zorder=1000,
        )
        ax.add_patch(patch)

        label_text = self._create_label(ax, gate, (x_min + x_max) / 2, (y_min + y_max) / 2)

        handles = None
        if is_selected:
            positions = self._get_gate_editor().get_handles(gate)
            handles = self._render_handle_markers(ax, positions, edge_color)

        return OverlayArtists(patch=patch, label_text=label_text, handles=handles)

    def render_polygon(
        self,
        ax: Axes,
        gate: PolygonGate,
        is_selected: bool = False,
        color: str | None = None,
    ) -> OverlayArtists:
        """Render PolygonGate on axes."""
        vertices_x = np.array([v[0] for v in gate.vertices])
        vertices_y = np.array([v[1] for v in gate.vertices])

        display_x = self.mapper.transform_x(vertices_x)
        display_y = self.mapper.transform_y(vertices_y)
        display_verts = list(zip(display_x, display_y, strict=False))

        edge_color = color if color else resolve_gate_color(gate, is_selected)
        patch = MplPolygon(
            display_verts,
            linewidth=self.linewidth if not is_selected else self.linewidth * 1.5,
            edgecolor=edge_color,
            facecolor="none",
            closed=True,
            zorder=1000,
        )
        ax.add_patch(patch)

        center_x = np.mean(display_x)
        center_y = np.mean(display_y)
        label_text = self._create_label(ax, gate, center_x, center_y)

        handles = None
        if is_selected:
            positions = self._get_gate_editor().get_handles(gate)
            handles = self._render_handle_markers(ax, positions, edge_color)

        return OverlayArtists(patch=patch, label_text=label_text, handles=handles)

    def render_ellipse(
        self,
        ax: Axes,
        gate: EllipseGate,
        is_selected: bool = False,
        color: str | None = None,
    ) -> OverlayArtists:
        """Render EllipseGate on axes."""
        cx, cy = gate.center
        display_cx = self.mapper.transform_x(np.array([cx]))[0]
        display_cy = self.mapper.transform_y(np.array([cy]))[0]

        display_w = abs(self.mapper.transform_x(np.array([cx + gate.width]))[0] - display_cx)
        display_h = abs(self.mapper.transform_y(np.array([cy + gate.height]))[0] - display_cy)

        edge_color = color if color else resolve_gate_color(gate, is_selected)
        patch = MplEllipse(
            (display_cx, display_cy),
            2 * display_w,
            2 * display_h,
            angle=gate.angle,
            linewidth=self.linewidth if not is_selected else self.linewidth * 1.5,
            edgecolor=edge_color,
            facecolor="none",
            zorder=1000,
        )
        ax.add_patch(patch)

        label_text = self._create_label(ax, gate, display_cx, display_cy)

        handles = None
        if is_selected:
            positions = self._get_gate_editor().get_handles(gate)
            handles = self._render_handle_markers(ax, positions, edge_color)

        return OverlayArtists(patch=patch, label_text=label_text, handles=handles)

    def render_quadrant(
        self,
        ax: Axes,
        gate: QuadrantGate,
        is_selected: bool = False,
        color: str | None = None,
    ) -> OverlayArtists:
        """Render QuadrantGate on axes (four lines through midpoint)."""
        x_mid = self.mapper.transform_x(np.array([gate.x_mid]))[0]
        y_mid = self.mapper.transform_y(np.array([gate.y_mid]))[0]

        xlim = ax.get_xlim()
        ylim = ax.get_ylim()

        edge_color = color if color else resolve_gate_color(gate, is_selected)
        lw = self.linewidth if not is_selected else self.linewidth * 1.5

        # Create cross-hair lines
        h_line = ax.plot([xlim[0], xlim[1]], [y_mid, y_mid], color=edge_color, linewidth=lw)[0]
        v_line = ax.plot([x_mid, x_mid], [ylim[0], ylim[1]], color=edge_color, linewidth=lw)[0]

        label_text = self._create_label(ax, gate, x_mid, y_mid)

        handles = None
        if is_selected:
            positions = self._get_gate_editor().get_handles(gate)
            handles = self._render_handle_markers(ax, positions, edge_color)

        return OverlayArtists(
            patch=h_line, label_text=label_text, handles=handles, extra_artists=[v_line]
        )

    def render_range(
        self,
        ax: Axes,
        gate: RangeGate,
        is_selected: bool = False,
        color: str | None = None,
    ) -> OverlayArtists:
        """Render RangeGate on axes (vertical bar on x-axis)."""
        x_low = self.mapper.transform_x(np.array([gate.low]))[0]
        x_high = self.mapper.transform_x(np.array([gate.high]))[0]
        ylim = ax.get_ylim()

        edge_color = color if color else resolve_gate_color(gate, is_selected)
        lw = self.linewidth if not is_selected else self.linewidth * 1.5

        # Create range bar as a fully closed rectangle so the boundary reads clearly
        left_line = ax.plot([x_low, x_low], [ylim[0], ylim[1]], color=edge_color, linewidth=lw)[0]
        right_line = ax.plot([x_high, x_high], [ylim[0], ylim[1]], color=edge_color, linewidth=lw)[
            0
        ]
        bottom_line = ax.plot([x_low, x_high], [ylim[0], ylim[0]], color=edge_color, linewidth=lw)[
            0
        ]
        top_line = ax.plot([x_low, x_high], [ylim[1], ylim[1]], color=edge_color, linewidth=lw)[0]

        # Draw a shaded region to highlight the gate range
        span = ax.axvspan(x_low, x_high, facecolor=edge_color, alpha=0.15, zorder=999)

        label_x = (x_low + x_high) / 2
        label_text = self._create_label(ax, gate, label_x, ylim[0])

        handles = None
        if is_selected:
            # get_handles_range returns a y=0.0 placeholder (hit-testing for
            # range ignores y entirely — the line spans the full plot height)
            # so pick a real on-screen y here, at the vertical midpoint.
            y_marker = (ylim[0] + ylim[1]) / 2
            positions = {
                key: (hx, y_marker)
                for key, (hx, _hy) in self._get_gate_editor().get_handles(gate).items()
            }
            handles = self._render_handle_markers(ax, positions, edge_color)

        return OverlayArtists(
            patch=left_line,
            label_text=label_text,
            handles=handles,
            extra_artists=[right_line, bottom_line, top_line, span],
        )

    def _create_label(self, ax: Axes, gate: Gate, x: float, y: float) -> Line2D | None:
        """Create text label for gate."""
        if not self.show_labels:
            return None

        # Prevent matplotlib FT_Render_Glyph raster overflow crashes
        if (
            not (np.isfinite(x) and np.isfinite(y))
            or abs(x) > _LABEL_COORD_OVERFLOW_LIMIT
            or abs(y) > _LABEL_COORD_OVERFLOW_LIMIT
        ):
            return None

        try:
            label = getattr(gate, "name", None) or type(gate).__name__
            text = ax.text(
                x,
                y,
                label,
                fontsize=9,
                color="black",
                bbox=dict(
                    boxstyle="round,pad=0.3",
                    facecolor="#FFFFFFCC",
                    edgecolor="#CCCCCC",
                    linewidth=0.5,
                ),
                ha="center",
                va="center",
                zorder=1001,
            )
            return text  # type: ignore
        except Exception as e:
            logger.warning("Failed to create gate label: %s", e)
            return None
