"""Step 6, Gate the Cleaned Data: drag a rectangle around the double-positives."""

from __future__ import annotations

from typing import TYPE_CHECKING

from karcytics_sdk.plugin.theme_fallback import Colors
from matplotlib import patches

from .scenes import compensated_scene, point_in_rect
from .slide import Slide, ghost_arrow, ghost_rect, heading, label_axes, scatter_frame, verdict

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from .deck import SpectralLearningTab

SCENE_SEED = 99
DOUBLE_POSITIVES = (600.0, 600.0)  # the population's centre: the gate must hold it
BACKGROUND = (100.0, 100.0)  # and must leave this out
THRESHOLD = 200.0
GHOST_GATE = (400.0, 400.0, 850.0, 850.0)  # Show me's rectangle around the double-positives
MIN_SIDE = 20.0  # a gate narrower than this was a click, not a drag


class GateSlide(Slide):
    title = "Gate the Cleaned Data"

    def __init__(self, deck: SpectralLearningTab) -> None:
        super().__init__(deck)
        self.gate: tuple[float, float, float, float] | None = None  # x0, y0, x1, y1
        self._dragging = False
        self._rect: patches.Rectangle | None = None

    def render(self, ax: Axes) -> str:
        label_axes(ax, "Compensated Sample", "Detector 1", "Detector 2")
        scene = compensated_scene(seed=SCENE_SEED)
        ax.scatter(scene["bg_x"], scene["bg_y"], color=Colors.FG_SECONDARY, alpha=0.3, s=10)
        for key in ("p1", "p2"):
            ax.scatter(
                scene[f"{key}_x"], scene[f"{key}_y"], color=Colors.ACCENT_SUCCESS, alpha=0.6, s=15
            )
        ax.scatter(scene["dp_x"], scene["dp_y"], color=Colors.BORDER_FOCUS, alpha=0.9, s=15)
        scatter_frame(ax, THRESHOLD)
        self._rect = patches.Rectangle(
            (0, 0),
            0,
            0,
            facecolor=Colors.BORDER_FOCUS,
            edgecolor=Colors.BORDER_FOCUS,
            alpha=0.2,
            lw=2,
            visible=False,
        )
        ax.add_patch(self._rect)
        self._show_gate()
        html = heading("Reading the Result") + (
            "<p>This is the corrected data — single positives now sit flat on their own axes"
            " instead of slanting, so the true Double Positive population is clearly separated"
            " from noise.</p>"
            "<p>Just like the Cells gate you drew earlier, we isolate it by drawing a gate"
            " around it. The <b>blue</b> cluster at the top right is the Double Positives; the"
            " green clusters are single positives, and the grey cells are negative.</p>"
        )
        if not self.done:
            return html
        return html + verdict("Nicely gated — that's a clean population, ready for analysis.")

    def instruction(self) -> str:
        return (
            "Gate the <b>blue</b> cluster (top right): press just above-left of it, hold,"
            " drag to just below-right of it so the box surrounds it, and let go."
        )

    def show_me(self, ax: Axes) -> str:
        x0, y0, x1, y1 = GHOST_GATE
        ghost_rect(ax, x0, y0, x1, y1, "gate goes here")
        ghost_arrow(ax, (x0, y1), (x1, y0))
        return (
            "Press at the dashed box's top-left corner, drag along the arrow to its"
            " bottom-right corner, and release."
        )

    def _show_gate(self) -> None:
        if self._rect is None or self.gate is None:
            return
        x0, y0, x1, y1 = self.gate
        self._rect.set_bounds(min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))
        self._rect.set_visible(True)

    def on_press(self, x: float, y: float) -> None:
        if self.done:
            return
        self.gate = (x, y, x, y)
        self._dragging = True

    def on_drag(self, x: float, y: float) -> None:
        if not self._dragging or self.gate is None:
            return
        self.gate = (*self.gate[:2], x, y)
        self._show_gate()
        self.deck.redraw()

    def on_release(self) -> None:
        # Judged on the gate as last drawn, so a release off the plot still counts.
        if not self._dragging or self.gate is None:
            return
        self._dragging = False
        self.wrong_hint = self._judge(*self.gate)
        if self.wrong_hint is None:
            self.finish()
        else:
            self.deck.refresh()

    @staticmethod
    def _judge(x0: float, y0: float, x1: float, y1: float) -> str | None:
        """None for a gate around the double-positives alone; otherwise what's wrong."""
        if abs(x1 - x0) < MIN_SIDE or abs(y1 - y0) < MIN_SIDE:
            return "That was a click, not a drag: hold the mouse button down while you move."
        if point_in_rect(*BACKGROUND, x0, y0, x1, y1):
            return (
                "Your gate reaches into the grey negative cells at the bottom left. Keep it"
                " above and right of the dashed lines."
            )
        if not point_in_rect(*DOUBLE_POSITIVES, x0, y0, x1, y1):
            return "Your gate misses the blue cluster: draw the box around it, at the top right."
        return None
