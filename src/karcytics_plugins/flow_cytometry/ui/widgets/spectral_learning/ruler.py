"""Step 3, Measure the Leak: drag a ruler along a single-stain cloud, then type
the spillover % it implies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from karcytics_sdk.plugin.theme_fallback import Colors

from .scenes import leaked_single_stain, rise_run_slope
from .slide import AnswerBox, Slide, ghost_line, label_axes, page, scatter_frame

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.lines import Line2D

    from .deck import SpectralLearningTab
    from .scenes import TeachingPair

PCT_TOLERANCE = 4.0  # percentage points a typed answer may be off what the ruler implies
SLOPE_TOLERANCE = 0.08  # how far the ruler's slope may be from the real spillover
MIN_RUN = 150.0  # ends closer than this in x make a very noise-sensitive reading
CLOUD_SEED = 7
ZONE_PERCENTILES = (5, 95)  # the dim and bright markers sit on the cloud's own spread
ZONE_LABEL_Y = 950


class RulerSlide(Slide):
    title = "Measure the Leak"

    def __init__(self, deck: SpectralLearningTab) -> None:
        super().__init__(deck)
        self.points: list[tuple[float, float]] = []  # the ruler's ends, as placed
        self.measured = False  # the ruler's slope is close to the real spillover
        self._dragging = False
        self._line: Line2D | None = None
        self._zone = (0.0, 0.0)  # the dim and bright markers' x

    def render(self, ax: Axes) -> str:
        pair = self.deck.pair
        if not self.measured:
            self.points = []  # coming back to the slide never shows an old attempt
        label_axes(
            ax,
            f"{pair.label_a} Single Stain → {pair.label_b} Detector",
            f"{pair.label_a} Detector",
            f"{pair.label_b} Detector",
        )
        x, y = leaked_single_stain(pair.pct, seed=CLOUD_SEED)
        ax.scatter(x, y, color=Colors.DNA_SECONDARY, alpha=0.5, s=15)
        dim, bright = np.percentile(x, ZONE_PERCENTILES)
        self._zone = (float(dim), float(bright))
        if not self.measured:
            for at, text, side in ((dim, "← dim", "left"), (bright, "bright →", "right")):
                ax.axvline(at, color=Colors.FG_DISABLED, lw=1, ls="--", alpha=0.5)
                ax.text(
                    at, ZONE_LABEL_Y, text, ha=side, va="top", color=Colors.FG_DISABLED, fontsize=8
                )
        colour = Colors.ACCENT_SUCCESS if self.measured else Colors.BORDER_FOCUS
        self._line = ax.plot([], [], color=colour, lw=2, marker="o", ms=8, zorder=5)[0]
        self._show_ruler()
        scatter_frame(ax)
        if self.measured and not self.done:
            self.deck.ask("Enter % (e.g. 15)", self._check_percent)
        return self._html(pair)

    def _html(self, pair: TeachingPair) -> str:
        return page(
            "Doing the Math",
            f"<p>We run a <b>Single Stain Control</b>: a sample stained with ONLY"
            f" {pair.label_a}. If there were no spillover, these cells would form a flat"
            f" horizontal line. Because {pair.label_b}'s detector is picking up leaked"
            f" {pair.label_a} signal, the population slants upward instead.</p>"
            f"<p>To measure exactly how severe the leak is, we need the <b>slope</b> of that"
            f" slant — for every unit of true brightness in {pair.label_a}'s detector (the Run),"
            f" how much false brightness appears in {pair.label_b}'s detector (the Rise)?</p>",
            "Good measurement! Your ruler follows the slant." if self.measured else None,
            f"Correct — that's what your ruler measurement implies. This panel's real spillover"
            f" is {pair.pct:.1f}%; a two-point ruler reading off individual cells won't always"
            " land on that exact number, and that's expected."
            if self.done
            else None,
        )

    def instruction(self) -> str:
        if not self.measured:
            return (
                "Draw a ruler along the slanted cloud: press on the <b>middle</b> of the cloud"
                " at the <b>← dim</b> dashed line, hold, drag along the cloud's centre to the"
                " <b>bright →</b> dashed line, and let go."
            )
        return (
            "Your ruler's reading is just under the text panel (Slope ≈ %). Type that percentage"
            " (Rise ÷ Run × 100) into the box and press <b>Submit</b>."
        )

    def show_me(self, ax: Axes) -> str:
        if not self.measured:
            slope = self.deck.pair.pct / 100.0
            dim, bright = self._zone
            ghost_line(ax, [dim, bright], [dim * slope, bright * slope])
            return (
                "Trace the dashed line: press on its left dot, drag to its right dot, release."
                " Keep both ends in the middle of the cloud, not along its top or bottom edge."
            )
        self.deck.guide.point_at_answer_area()
        _rise, _run, slope = self._reading()
        return (
            f"Your readout says Slope {slope:.3f}. As a percentage that's {slope:.3f} × 100,"
            " so type the number shown after ≈."
        )

    def _show_ruler(self) -> None:
        """Draw the ruler as placed so far (one end on the first click) and read it out."""
        if self._line is None:
            return
        self._line.set_data([p[0] for p in self.points], [p[1] for p in self.points])
        if self.points:
            rise, run, slope = self._reading()
            self.deck.set_readout(
                f"Rise: {rise:.0f}   Run: {run:.0f}   Slope: {slope:.3f}   (≈ {slope * 100:.1f}%)"
            )

    def _reading(self) -> tuple[float, float, float]:
        (x0, y0), (x1, y1) = self.points[0], self.points[-1]
        return rise_run_slope(x0, y0, x1, y1)

    def on_press(self, x: float, y: float) -> None:
        if self.measured:
            return
        # A free-form drag: the ruler starts exactly where the click is, no snapping.
        self.points = [(x, y)]
        self._dragging = True
        self._show_ruler()
        self.deck.redraw()

    def on_drag(self, x: float, y: float) -> None:
        if not self._dragging:
            return
        self.points = [self.points[0], (x, y)]
        self._show_ruler()
        self.deck.redraw()

    def on_release(self) -> None:
        if not self._dragging:
            return
        self._dragging = False
        if len(self.points) < 2:  # noqa: PLR2004 - a ruler has two ends
            return
        _rise, run, slope = self._reading()
        if abs(run) < MIN_RUN:
            self.wrong_hint = "Drag your two points further apart for a reliable reading."
        elif abs(slope - self.deck.pair.pct / 100.0) <= SLOPE_TOLERANCE:
            self.measured = True
            self.wrong_hint = None
        else:
            way = "steeper" if slope > self.deck.pair.pct / 100.0 else "flatter"
            self.wrong_hint = (
                f"Not quite: your ruler is {way} than the cloud's slant. Start and end it in the"
                " middle of the cloud, at the dim and bright dashed lines."
            )
        self.deck.refresh()

    def _check_percent(self, box: AnswerBox) -> None:
        # Graded against what the learner's own ruler implies (the prompt asks for
        # that), not the true %: the ruler's ends are noisy cells, so an honest
        # reading can sit outside the tolerance of the truth.
        guess = box.number("15")
        if guess is None:
            return
        if abs(guess - self._reading()[2] * 100) <= PCT_TOLERANCE:
            self.finish()
        else:
            box.show_error("Not quite — type the percentage from the readout above (Slope × 100).")
