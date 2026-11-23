"""Step 2, Setting the Zero: say where an unstained control's threshold belongs,
then drag the crosshair past the edge of the unstained cloud.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from karcytics_sdk.plugin.theme_fallback import Colors

from .scenes import unstained_cloud
from .slide import Slide, choices, heading, hint, label_axes, scatter_frame, task

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.lines import Line2D

CROSSHAIR_START = 800.0  # far past the cloud: the learner drags it in
CROSSHAIR_DONE = 200.0  # where a finished slide shows it
CLEAR_OF_CLOUD = (150.0, 250.0)  # the threshold has to land in here on both axes
GRAB = 50.0  # how close a press must be to the crosshair to pick it up
WRONG_HINT = (
    "Not quite — placing the threshold through the middle of the cloud would still call"
    " half the true negatives 'positive'. The threshold needs to clear the whole cloud."
)


class ZeroSlide(Slide):
    title = "Setting the Zero"

    def __init__(self, deck) -> None:
        super().__init__(deck)
        self.predicted = False
        self.wrong_hint: str | None = None
        self._dragging = False
        self._lines: tuple[Line2D, Line2D, Line2D] | None = None  # crosshair, h, v
        self._at: tuple[float, float] | None = None  # the crosshair, once it is drawn

    def render(self, ax: Axes) -> str:
        label_axes(ax, "Unstained Cells", "Detector 1", "Detector 2")
        ax.scatter(*unstained_cloud(), color=Colors.FG_SECONDARY, alpha=0.5, s=10)
        self._lines = self._at = None
        if self.predicted:
            at = CROSSHAIR_DONE if self.done else CROSSHAIR_START
            self._at = (at, at)
            self._lines = (
                ax.plot(
                    [at],
                    [at],
                    marker="+",
                    color=Colors.FG_PRIMARY,
                    markersize=20,
                    markeredgewidth=2,
                )[0],
                ax.axhline(at, color=Colors.BORDER, ls="--"),
                ax.axvline(at, color=Colors.BORDER, ls="--"),
            )
        scatter_frame(ax)
        return self._html()

    def _html(self) -> str:
        html = heading('Finding "Zero"') + (
            '<p>Before we can fix spillover, we need to know what "zero" looks like. Cells'
            " have a natural background glow called autofluorescence — even with absolutely no"
            " dye, they produce a faint signal. We run an <b>Unstained Control</b> (a sample"
            " with no dyes at all) to measure this baseline.</p>"
        )
        if not self.predicted:
            return (
                html
                + task(
                    "Quick check first: should the threshold sit at the CENTER of the"
                    " unstained cloud, or PAST its edge?"
                )
                + choices(
                    [
                        ("predict_wrong", "A) At the center of the cloud"),
                        (
                            "predict_correct",
                            "B) Past the edge, so every negative cell falls below it",
                        ),
                    ]
                )
                + hint(self.wrong_hint)
            )
        if not self.done:
            return html + task(
                "Right — a threshold through the middle of the cloud would call half your true"
                " negatives 'positive'. Now drag the crosshair so ALL of these unstained cells"
                " fall in the bottom-left quadrant."
            )
        return html

    def on_link(self, link: str) -> None:
        if self.predicted:
            return
        self.predicted = link == "predict_correct"
        self.wrong_hint = None if self.predicted else WRONG_HINT
        self.deck.refresh()

    def on_press(self, x: float, y: float) -> None:
        at = self._at
        if at is not None and not self.done:
            self._dragging = abs(x - at[0]) < GRAB and abs(y - at[1]) < GRAB

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
        if not self._dragging:
            return
        self._dragging = False
        at = self._at
        low, high = CLEAR_OF_CLOUD
        if at is not None and all(low < v < high for v in at):
            self.finish()
        # Otherwise it stays where it was dropped, for another try.
