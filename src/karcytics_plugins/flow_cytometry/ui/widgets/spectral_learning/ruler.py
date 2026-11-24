"""Step 3, Measure the Spillover: after a worked example, drag a ruler along a
single-stain cloud and turn its Rise and Run into "for every 100 units of the
first dye, the second detector reads __ extra".
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from karcytics_sdk.plugin.theme_fallback import Colors

from .calculator import Calculator
from .scenes import leaked_single_stain, rise_run_slope, short_name
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
    title = "Measure the Spillover"

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
            self.deck.ask("Extra units per 100 (e.g. 10)", self._check_percent)
            self.deck.add_control(Calculator())
        return self._html(pair)

    def _html(self, pair: TeachingPair) -> str:
        a, b = short_name(pair.label_a), short_name(pair.label_b)
        answer = None
        if self.done:
            measured = self._reading()[2] * 100
            answer = (
                f"Correct: for every 100 units of {a}, {b}'s detector reads about"
                f" {measured:.0f} extra. That number is the spillover, written {measured:.0f}%."
                f" (Worked out from the spectra it's {pair.pct:.0f}%; a ruler on a handful of"
                " cells lands close, not exact.)"
            )
        return page(
            "Measuring Spillover",
            f"<p>A <b>single-stain control</b> is a tube stained with only {a}. With no"
            f" spillover its cells would lie flat on the {b} axis. They slant upward because"
            f" some {a} light lands in {b}'s detector: the brighter the cell, the more lands"
            " there.</p>"
            "<p><b>How steep is the slant?</b> Go along the cloud: how far it climbs is the"
            " <b>Rise</b>, how far it goes across is the <b>Run</b>.</p>"
            "<table cellpadding='6' style='background: rgba(128,128,128,0.15);'><tr><td>"
            "<b>Worked example</b><br>"
            "A ruler climbs <b>50</b> while it goes across <b>500</b>.<br>"
            "50 ÷ 500 = 0.1, and 0.1 × 100 = <b>10</b>.<br>"
            "So for every 100 units of the first dye, the second detector reads"
            " <b>10 extra</b>: that's <b>10% spillover</b>."
            "</td></tr></table>",
            "Good measurement! Your ruler follows the slant." if self.measured else None,
            answer,
        )

    def instruction(self) -> str:
        if not self.measured:
            return (
                "Draw a ruler along the slanted cloud: press on the <b>middle</b> of the cloud"
                " at the <b>← dim</b> dashed line, hold, drag along the cloud's centre to the"
                " <b>bright →</b> dashed line, and let go."
            )
        pair = self.deck.pair
        return (
            "Your ruler's <b>Rise</b> and <b>Run</b> are just under the text panel. Like the"
            " worked example: Rise ÷ Run × 100. Finish the sentence <i>for every 100 units of"
            f" {short_name(pair.label_a)}, {short_name(pair.label_b)}'s detector reads __"
            " extra</i> in the box and press"
            " <b>Submit</b>. The 🧮 can do the sum."
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
        rise, run, slope = self._reading()
        return (
            f"Type <b>{rise:.0f} ÷ {run:.0f}</b> into the 🧮: that gives {slope:.3f}. Now multiply"
            " that by 100 and type the result in the answer box."
        )

    def _show_ruler(self) -> None:
        """Draw the ruler as placed so far (one end on the first click) and read it out."""
        if self._line is None:
            return
        self._line.set_data([p[0] for p in self.points], [p[1] for p in self.points])
        if self.points:
            rise, run, _slope = self._reading()  # the learner works the slope out
            self.deck.set_readout(f"Your ruler:  Rise {rise:.0f}   Run {run:.0f}")

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
            box.show_error(
                "Not quite: Rise ÷ Run × 100, using your ruler's numbers above. Try the 🧮."
            )
