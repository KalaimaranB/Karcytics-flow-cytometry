"""Step 5, Compensate All: predict where a slanted population lands, then watch
compensation straighten it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from karcytics_sdk.plugin.theme_fallback import Colors

from .scenes import uncompensated_scene
from .slide import (
    Slide,
    ghost_label,
    ghost_line,
    heading,
    label_axes,
    legend,
    scatter_frame,
    verdict,
)

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.collections import PathCollection

    from .deck import SpectralLearningTab

SCENE_SEED = 99
LANDING = (600.0, 100.0)  # where the single-positive population really ends up
FLOOR_Y = 100.0  # its compensated level on the second detector
THRESHOLD = 200.0
TICK_MS = 30
STEP = 0.02  # of the animation per tick: 50 ticks, about 1.5 s


class CompensateSlide(Slide):
    title = "Compensate All"

    def __init__(self, deck: SpectralLearningTab) -> None:
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
            "<p>The green cells carry only the Detector 1 dye; their slant is leak into"
            " Detector 2. The grey cells are unstained.</p>"
        )
        if self.done:
            html += verdict(
                "Compare your prediction (✕) to where it really landed (★): the cells kept"
                " their Detector 1 brightness and dropped to the unstained level on Detector 2."
            )
        return html

    def instruction(self) -> str:
        if self.prediction is None:
            return (
                "Before compensating, predict: <b>click on the plot</b> where you think the"
                " green slanted population will end up once its leak is removed."
            )
        if self.animating:
            return "Compensating… watch the green cells."
        return (
            "Now press <b>⚙️ Compensate All</b> (the button under the text panel, on the left)"
            " and watch."
        )

    def show_me(self, ax: Axes) -> str:
        if self.prediction is None:
            left, right = float(self._x.min()), float(self._x.max())
            for at in (left, right):
                ghost_line(ax, [at, at], [0, 1000])
            ghost_label(ax, (left + right) / 2, 950, "Detector 1 doesn't change")
            return (
                "Compensation only subtracts leak from Detector 2, so each cell keeps its"
                " Detector 1 position (between the dashed lines). How high on Detector 2 does a"
                " cell with none of the second dye sit? Look at the grey cells."
            )
        self.deck.guide.point_at_answer_area()
        return "The ⚙️ Compensate All button is outlined, under the text panel on the left."

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
