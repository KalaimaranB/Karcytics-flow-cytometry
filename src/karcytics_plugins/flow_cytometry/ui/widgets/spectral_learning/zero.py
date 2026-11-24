"""Step 2, Setting the Zero: say where an unstained control's threshold belongs,
then drag the crosshair just past the edge of the unstained cloud.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from karcytics_sdk.plugin.theme_fallback import Colors

from .scenes import unstained_cloud
from .slide import (
    Slide,
    choices,
    ghost_arrow,
    ghost_label,
    ghost_line,
    ghost_rect,
    heading,
    label_axes,
    scatter_frame,
    verdict,
)

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.lines import Line2D

    from .deck import SpectralLearningTab

CROSSHAIR_START = 800.0  # far past the cloud: the learner drags it in
CROSSHAIR_DONE = 220.0  # where a finished slide shows it
STRAGGLERS = 5  # cells that may still sit past the lines (1% of the cloud's 500)
TOO_FAR = 300.0  # past this on either axis the threshold no longer hugs the cloud
GRAB = 50.0  # how close a press must be to the crosshair to pick it up
CLOUD_CENTRE = 100.0
WRONG_HINT = (
    "Not quite — placing the threshold through the middle of the cloud would still call"
    " half the true negatives 'positive'. The threshold needs to clear the whole cloud."
)


class ZeroSlide(Slide):
    title = "Setting the Zero"

    def __init__(self, deck: SpectralLearningTab) -> None:
        super().__init__(deck)
        self.predicted = False
        self._dragging = False
        self._lines: tuple[Line2D, Line2D, Line2D] | None = None  # crosshair, h, v
        self._at: tuple[float, float] | None = None  # the crosshair, once it is drawn
        self._cloud = unstained_cloud()

    def render(self, ax: Axes) -> str:
        pair = self.deck.pair
        label_axes(ax, "Unstained Cells", f"{pair.label_a} Detector", f"{pair.label_b} Detector")
        ax.scatter(*self._cloud, color=Colors.FG_SECONDARY, alpha=0.5, s=10)
        self._lines = None
        if not self.predicted:
            self._at = None
        else:
            if self.done:
                self._at = (CROSSHAIR_DONE, CROSSHAIR_DONE)
            elif self._at is None:
                self._at = (CROSSHAIR_START, CROSSHAIR_START)
            x, y = self._at  # a missed drop stays where it was, for another try
            self._lines = (
                ax.plot(
                    [x],
                    [y],
                    marker="+",
                    color=Colors.FG_PRIMARY,
                    markersize=20,
                    markeredgewidth=2,
                )[0],
                ax.axhline(y, color=Colors.BORDER, ls="--"),
                ax.axvline(x, color=Colors.BORDER, ls="--"),
            )
        scatter_frame(ax)
        return self._html()

    def _html(self) -> str:
        html = heading('Finding "Zero"') + (
            '<p>Before we can fix spillover, we need to know what "zero" looks like. Cells'
            " have a natural background glow called autofluorescence — even with absolutely no"
            " dye, they produce a faint signal. We run an <b>Unstained Control</b> (a sample"
            " with no dyes at all) to measure this baseline.</p>"
            "<p>The threshold is a pair of lines: anything above or right of them is called"
            " positive.</p>"
        )
        if not self.predicted:
            return html + choices(
                [
                    ("predict_wrong", "A) At the center of the cloud"),
                    ("predict_correct", "B) Past the edge, so every negative cell falls below it"),
                ]
            )
        html += verdict(
            "Right — a threshold through the middle of the cloud would call half your true"
            " negatives 'positive'."
        )
        if self.done:
            html += verdict(
                "Every unstained cell now sits below and left of your lines, and the lines hug"
                " the cloud. On a stained sample, anything past them is signal: real, or"
                " leaked from another dye, which is what the next steps fix."
            )
        return html

    def instruction(self) -> str:
        if not self.predicted:
            return (
                "Quick check first: should the threshold sit at the CENTER of the unstained"
                " cloud, or PAST its edge? Click A or B in the text below."
            )
        return (
            "Press on the <b>✚ crosshair</b> (top right of the plot) and drag it down and left"
            " until its dashed lines sit <b>just past the edge</b> of the grey cloud, with every"
            " grey dot below and left of them. Then let go."
        )

    def show_me(self, ax: Axes) -> str:
        if not self.predicted:
            ghost_line(ax, [CLOUD_CENTRE, CLOUD_CENTRE], [0, 400])
            ghost_label(ax, CLOUD_CENTRE + 150, 450, "a line through the centre…")
            return (
                "Picture a threshold on the dashed line through the cloud's centre. Every cell"
                " to its right would be called positive, and that's half of cells with no dye"
                " at all."
            )
        low = self._edge()
        ghost_rect(ax, low, low, TOO_FAR, TOO_FAR, "drop ✚ here")
        if self._at is not None:
            target = (low + TOO_FAR) / 2
            ghost_arrow(ax, self._at, (target, target))
        return (
            f"Drag the crosshair along the arrow into the dashed square (about {low:.0f}–"
            f"{TOO_FAR:.0f} on both axes): past the cloud's edge, but not far past it."
        )

    def on_link(self, link: str) -> None:
        if self.predicted:
            return
        self.predicted = link == "predict_correct"
        self.wrong_hint = None if self.predicted else WRONG_HINT
        self.deck.refresh()

    def on_press(self, x: float, y: float) -> None:
        at = self._at
        if at is None or self.done:
            return
        self._dragging = abs(x - at[0]) < GRAB and abs(y - at[1]) < GRAB
        if not self._dragging:
            self.wrong_hint = "Press right on the ✚ crosshair to pick it up, then drag."
            self.deck.refresh()

    def on_drag(self, x: float, y: float) -> None:
        if not self._dragging or self._lines is None:
            return
        self._at = (x, y)
        cross, h_line, v_line = self._lines
        cross.set_data([x], [y])
        h_line.set_ydata([y, y])
        v_line.set_xdata([x, x])
        self.deck.redraw()

    def on_release(self) -> None:
        if not self._dragging or self._at is None:
            return
        self._dragging = False
        self.wrong_hint = self._judge(*self._at)
        if self.wrong_hint is None:
            self.finish()
        else:
            self.deck.refresh()

    def _edge(self) -> float:
        """The lowest threshold (same on both axes) that ``_judge`` accepts as clear."""
        # A cell is past the lines when its larger reading is; allow STRAGGLERS of them.
        return float(np.sort(np.maximum(*self._cloud))[-(STRAGGLERS + 1)])

    def _judge(self, x: float, y: float) -> str | None:
        """None when the threshold clears the cloud and hugs it; otherwise what's wrong."""
        cells_x, cells_y = self._cloud
        past = int(np.count_nonzero((cells_x > x) | (cells_y > y)))
        if past > STRAGGLERS:
            return (
                f"{past} grey cells still sit above or right of your lines: they'd be called"
                " positive. Move the crosshair further up and right, past the cloud's edge."
            )
        if x > TOO_FAR or y > TOO_FAR:
            return (
                "That clears the cloud, but sits far past its edge: dim cells that really carry"
                " dye would be called negative. Bring it in until it just clears the cloud."
            )
        return None
