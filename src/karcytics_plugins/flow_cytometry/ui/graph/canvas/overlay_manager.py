"""OverlayManager — handles transient UI overlays on the canvas."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from karcytics_sdk.plugin import get_logger
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel

from ..flow_canvas import GateDrawingMode

if TYPE_CHECKING:
    from ..flow_canvas import FlowCanvas

logger = get_logger(__name__, "flow_cytometry")

_PLOT_BG = "#FFFFFF"


class OverlayManager:
    """Manages instructions, loading, error states, and empty states on the canvas."""

    _INSTRUCTION_MAP = {
        GateDrawingMode.RECTANGLE: "Click and drag to draw a rectangle",
        GateDrawingMode.POLYGON: "Click to add points, double-click to close",
        GateDrawingMode.ELLIPSE: "Click and drag to draw an ellipse",
        GateDrawingMode.QUADRANT: "Click to place the crosshair",
        GateDrawingMode.RANGE: "Click and drag horizontally",
    }

    def __init__(self, canvas: FlowCanvas) -> None:
        self.canvas = canvas
        self._instruction_text: Any | None = None

        # Loading overlay
        self._loading_label = QLabel("  ⟳  Rendering…  ", self.canvas)
        self._loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._loading_label.setStyleSheet(
            "background: rgba(18, 18, 30, 200);"
            "color: #58a6ff;"
            "font-size: 13px;"
            "font-weight: 600;"
            "border-radius: 8px;"
            "padding: 6px 14px;"
        )
        self._loading_label.setVisible(False)
        self._loading_label.raise_()

    def resize_loading(self, width: int, height: int) -> None:
        """Keep the loading overlay centered over the canvas."""
        lw, lh = 160, 36
        x = max(0, (width - lw) // 2)
        y = max(0, (height - lh) // 2)
        self._loading_label.setGeometry(x, y, lw, lh)

    def show_loading(self, text: str | None = None) -> None:
        """Show the loading overlay, keeping it on top.

        The render it covers is asynchronous, so the label paints on the next
        turn of the event loop. Pumping events here instead made every
        pending canvas render on the spot, one after another, freezing a
        window of several plots for the whole batch.
        """
        if text is not None:
            self._loading_label.setText(f"  {text}  ")
        self.resize_loading(self.canvas.width(), self.canvas.height())
        self._loading_label.setVisible(True)
        self._loading_label.raise_()

    def hide_loading(self) -> None:
        """Hide the loading overlay."""
        self._loading_label.setVisible(False)

    def show_empty(self) -> None:
        """Display an empty-state message."""
        logger.info("OverlayManager: showing empty state")
        self.canvas._ax.clear()
        # ax.clear() just invalidated every artist that was on the axes —
        # drop stale references so nothing later tries to .remove() them.
        self.canvas._guide_poly_patch = None
        if hasattr(self.canvas, "_guide_patches"):
            self.canvas._guide_patches.clear()
        self._instruction_text = None
        self.canvas._ax.set_facecolor(_PLOT_BG)
        self.canvas._ax.text(
            0.5,
            0.5,
            "Load FCS data to visualize",
            transform=self.canvas._ax.transAxes,
            ha="center",
            va="center",
            fontsize=12,
            color="#333333",
            alpha=0.6,
        )
        self.canvas._ax.set_xticks([])
        self.canvas._ax.set_yticks([])
        self.canvas.apply_margins()
        self.canvas.draw()

    def show_error(self, msg: str) -> None:
        """Display an error message on the canvas."""
        logger.error(f"OverlayManager.show_error: {msg}")
        self.canvas._ax.clear()
        # ax.clear() just invalidated every artist that was on the axes —
        # drop stale references so nothing later tries to .remove() them.
        self.canvas._guide_poly_patch = None
        if hasattr(self.canvas, "_guide_patches"):
            self.canvas._guide_patches.clear()
        self._instruction_text = None
        self.canvas._ax.set_facecolor(_PLOT_BG)
        self.canvas._ax.text(
            0.5,
            0.5,
            f"⚠ {msg}",
            transform=self.canvas._ax.transAxes,
            ha="center",
            va="center",
            fontsize=11,
            color="#FF5252",
        )
        self.canvas._ax.set_xticks([])
        self.canvas._ax.set_yticks([])
        self.canvas.draw()

    def show_instruction(self, mode: GateDrawingMode) -> None:
        """Show a drawing instruction overlay on the axes."""
        self.hide_instruction()
        text = self._INSTRUCTION_MAP.get(mode)
        if text:
            self._instruction_text = self.canvas._ax.text(
                0.5,
                0.02,
                text,
                transform=self.canvas._ax.transAxes,
                ha="center",
                va="bottom",
                fontsize=10,
                color="#333333",
                alpha=0.7,
                bbox=dict(
                    boxstyle="round,pad=0.3",
                    facecolor="#FFFFFFCC",
                    edgecolor="#CCCCCC",
                    linewidth=0.5,
                ),
                zorder=30,
            )
            self.canvas.draw_idle()

    def update_instruction(self, text: str) -> None:
        """Update the instruction text content in-place."""
        if self._instruction_text is not None:
            self._instruction_text.set_text(text)
        else:
            self._instruction_text = self.canvas._ax.text(
                0.5,
                0.02,
                text,
                transform=self.canvas._ax.transAxes,
                ha="center",
                va="bottom",
                fontsize=10,
                color="#333333",
                alpha=0.7,
                bbox=dict(
                    boxstyle="round,pad=0.3",
                    facecolor="#FFFFFFCC",
                    edgecolor="#CCCCCC",
                    linewidth=0.5,
                ),
                zorder=30,
            )

    def hide_instruction(self) -> None:
        """Remove the instruction text overlay."""
        if self._instruction_text is not None:
            try:
                self._instruction_text.remove()
            except (ValueError, AttributeError, NotImplementedError):
                pass
            self._instruction_text = None
            self.canvas.draw_idle()
