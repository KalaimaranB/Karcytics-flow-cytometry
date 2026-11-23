"""Step 5, Compensate All: predict where a slanted population lands, then watch
compensation straighten it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from karcytics_sdk.plugin.theme_fallback import Colors

from .scenes import uncompensated_scene
from .slide import Slide, heading, label_axes, legend, scatter_frame, task

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.collections import PathCollection

SCENE_SEED = 99
LANDING = (600.0, 100.0)  # where the single-positive population really ends up
FLOOR_Y = 100.0  # its compensated level on the second detector
THRESHOLD = 200.0
TICK_MS = 30
STEP = 0.02  # of the animation per tick: 50 ticks, about 1.5 s


class CompensateSlide(Slide):
    title = "Compensate All"

    def __init__(self, deck) -> None:
        super().__init__(deck)
        self.prediction: tuple[float, float] | None = None
        self.progress = 0.0  # 0 → 1 through the animation
        self.animating = False
        self._cells: PathCollection | None = None
        self._x = self._y = np.empty(0)  # the population before compensation

    def render(self, ax: Axes) -> str:
        label_axes(ax, "Applying Compensation", "Detector 1", "Detector 2")
        scene = uncompensated_scene(self.deck.pair.pct, seed=SCENE_SEED)
        self._x, self._y = scene["p1_x"], scene["p1_y"]
        ax.scatter(scene["bg_x"], scene["bg_y"], color=Colors.FG_SECONDARY, alpha=0.3, s=10)
        self._cells = ax.scatter(
            self._x, self._compensated_y(), color=Colors.ACCENT_SUCCESS, alpha=0.6, s=15
        )
        scatter_frame(ax, THRESHOLD)
        if self.prediction is not None:
            ax.scatter(
                *self.prediction,
                marker="x",
                color=Colors.BORDER_FOCUS,
                s=150,
                label="Your prediction",
            )
            if self.progress >= 1.0:
                ax.scatter(
                    *LANDING, marker="*", color=Colors.ACCENT_WARNING, s=200, label="Actual result"
                )
                legend(ax)
            if not self.done and not self.animating:
                self.deck.add_button("⚙️ Compensate All", self._start)
        return self._html()

    def _html(self) -> str:
        html = heading("Compensate All") + (
            "<p>We don't correct cells one at a time — real software uses matrix inversion to"
            ' apply this subtraction to millions of events at once, instantly "straightening'
            ' out" every slanted population.</p>'
        )
        if self.prediction is None:
            step = (
                "Action Required: Before pressing the button, click where you predict the WHOLE"
                " population will end up."
            )
        elif self.animating:
            step = "Compensating..."
        elif not self.done:
            step = "Now click 'Compensate All' and watch."
        else:
            step = "Compare your prediction (X) to where it really landed."
        return html + task(step)

    def _compensated_y(self) -> np.ndarray:
        eased = 1 - (1 - self.progress) ** 2  # fast at first, settling at the end
        return self._y * (1 - eased) + FLOOR_Y * eased

    def on_press(self, x: float, y: float) -> None:
        if self.prediction is None:
            self.prediction = (x, y)
            self.deck.refresh()

    def _start(self) -> None:
        self.animating = True
        self.progress = 0.0
        self.deck.start_ticks(TICK_MS)
        self.deck.refresh()

    def on_tick(self) -> None:
        self.progress = min(1.0, self.progress + STEP)
        if self.progress >= 1.0:
            self.animating = False
            self.deck.stop_ticks()
            self.finish()
            return
        if self._cells is not None:
            self._cells.set_offsets(np.column_stack([self._x, self._compensated_y()]))
            self.deck.redraw()

    def leave(self) -> None:
        if self.animating:  # cut short: it starts over next time
            self.animating = False
            self.progress = 0.0
