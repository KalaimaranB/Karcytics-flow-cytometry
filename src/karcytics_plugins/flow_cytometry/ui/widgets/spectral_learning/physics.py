"""Step 1, The Physics of Overlap: put a detector's filter on one dye's peak, then
find the other dye riding highest inside it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from karcytics_sdk.plugin.theme_fallback import Colors
from matplotlib import patches

from ....analysis.spectral_math import normalise_em_to_grid
from .scenes import dye_label, spectral_dyes
from .slide import (
    Slide,
    ghost_arrow,
    ghost_label,
    ghost_rect,
    label_axes,
    legend,
    page,
)

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.text import Text

    from .deck import SpectralLearningTab
    from .scenes import TeachingPair

WAVELENGTHS = np.linspace(350, 800, 451)  # nm
FILTER_WIDTH = 30.0  # nm: the band drawn, and how close a press must be to grab it
FILTER_START = 575.0  # nm: mid-wavelength, clear of the plot's edge
ON_PEAK = 30.0  # nm: how close to the dye's peak the filter must be dropped
MARKER_REACH = 0.15  # normalised intensity: how close a click must be to the right curve
TOP = 1.1
GHOST_Y = 0.55  # where Show me's drag arrow runs across the plot


class PhysicsSlide(Slide):
    title = "The Physics of Overlap"

    def __init__(self, deck: SpectralLearningTab) -> None:
        super().__init__(deck)
        self.filter_placed = False
        self._dragging = False
        self._filter_x = FILTER_START
        self._peak_x = FILTER_START  # dye A's peak, found when its curve is drawn
        self._band: list[patches.Rectangle] = []
        self._grip: Text | None = None
        self._heights: dict[str, float] = {}  # each other dye's height inside the band
        self._answer: str | None = None  # the dye the learner rightly picked

    def render(self, ax: Axes) -> str:
        pair = self.deck.pair
        placed = self.filter_placed or self.done
        label_axes(ax, "Real Emission Spectra", "Wavelength (nm)", "Normalized Intensity")
        curves = self._plot_curves(ax, pair)
        self._peak_x = float(WAVELENGTHS[np.argmax(curves[pair.dye_a])])
        if placed:  # otherwise it stays where it was last dropped, for another try
            self._filter_x = self._peak_x
        self._draw_filter(ax, placed)
        self._heights = {}
        if placed and not self.done:
            for name, curve in curves.items():
                if name != pair.dye_a:
                    self._heights[name] = float(np.interp(self._peak_x, WAVELENGTHS, curve))
                    ax.plot(
                        self._peak_x,
                        self._heights[name],
                        "o",
                        color=Colors.FG_PRIMARY,
                        ms=6,
                        mfc="none",
                    )
        ax.set_xlim(WAVELENGTHS[0], WAVELENGTHS[-1])
        ax.set_ylim(0, TOP)
        return self._html(pair)

    def _plot_curves(self, ax: Axes, pair: TeachingPair) -> dict[str, np.ndarray]:
        fluors = self.deck.fluors
        curves = {}
        for name in spectral_dyes(fluors):
            curves[name] = normalise_em_to_grid(fluors[name]["em_data"], WAVELENGTHS)
            taught = name in (pair.dye_a, pair.dye_b)
            ax.plot(
                WAVELENGTHS,
                curves[name],
                color=fluors[name].get("color", Colors.FG_SECONDARY),
                lw=3 if taught else 1.5,
                alpha=0.9 if taught else 0.5,
                label=dye_label(fluors, name),
            )
        legend(ax, loc="upper left")
        return curves

    def _draw_filter(self, ax: Axes, placed: bool) -> None:
        left = self._filter_x - FILTER_WIDTH / 2
        colour = Colors.ACCENT_SUCCESS if placed else Colors.FG_SECONDARY
        self._band = [patches.Rectangle((left, 0), FILTER_WIDTH, TOP, facecolor=colour, alpha=0.35)]
        self._grip = None
        if not placed:  # a dashed border and a grip label say the band can be dragged
            self._band.append(
                patches.Rectangle(
                    (left, 0),
                    FILTER_WIDTH,
                    TOP,
                    fill=False,
                    edgecolor=Colors.BORDER_FOCUS,
                    linestyle="--",
                    linewidth=1.5,
                )
            )
            self._grip = ax.text(
                self._filter_x,
                TOP - 0.03,
                "◀ drag ▶",
                ha="center",
                va="top",
                color=Colors.BORDER_FOCUS,
                fontsize=8,
                fontweight="bold",
            )
        for patch in self._band:
            ax.add_patch(patch)

    def _html(self, pair: TeachingPair) -> str:
        correct = None
        if self.done:
            answer = self._answer or pair.dye_b
            leaker = self.deck.fluors.get(answer, {}).get("display_label", answer)
            correct = (
                f"Correct! {leaker} leaks the most into {pair.label_a}'s detector — that's"
                " exactly the kind of overlap compensation has to undo."
            )
        return page(
            "Detectors, Filters, and Broad Curves",
            '<p>A flow cytometer uses detectors covered by colored glass filters to "see" light —'
            " each filter only passes a narrow range of wavelengths through to its detector.</p>"
            "<p>But a fluorescent dye doesn't glow at one exact wavelength. It emits across a"
            " broad, hill-shaped range spanning 100nm or more. Detectors sit under the peak of"
            " one dye's hill, but that hill's shoulders still spill into neighboring detectors —"
            " two dyes with peaks 50nm apart can still overlap by 20-30% or more.</p>"
            "<p>Below are the real emission curves for every dye you loaded. Use the legend to"
            f" identify each dye by colour; the two drawn thickest, <b>{pair.label_a}</b> and"
            f" <b>{pair.label_b}</b>, are the pair this deck works with.</p>",
            correct,
        )

    def instruction(self) -> str:
        label_a = self.deck.pair.label_a
        if not self.filter_placed:
            return (
                "Press inside the dashed <b>◀ drag ▶</b> band on the plot (the detector's"
                f" filter), drag it sideways onto the top of <b>{label_a}</b>'s curve"
                " (thick line, colour in the legend), and let go."
            )
        return (
            f"The filter now sits on {label_a}'s detector. Every other dye has a hollow ○ marker"
            " in the band, at the height its curve reaches there. Click the marker sitting"
            " <b>highest</b>: that dye leaks into this detector the most."
        )

    def show_me(self, ax: Axes) -> str:
        label_a = self.deck.pair.label_a
        if not self.filter_placed:
            ghost_rect(ax, self._peak_x - ON_PEAK, 0, self._peak_x + ON_PEAK, 1.0, "drop here")
            ghost_arrow(ax, (self._filter_x, GHOST_Y), (self._peak_x, GHOST_Y))
            return (
                f"{label_a}'s curve peaks at {self._peak_x:.0f} nm. Drag the band along the"
                " arrow into the dashed zone and release."
            )
        height = self._heights[self._leaker]
        ax.plot(self._peak_x, height, "o", ms=22, mfc="none", mec=Colors.ACCENT_WARNING, mew=2.5)
        ghost_label(ax, self._peak_x + FILTER_WIDTH * 1.4, height, "◀ this one")
        return "Click the circled marker: it's the highest one inside the band."

    @property
    def _leaker(self) -> str:
        """The dye riding highest inside the band (the answer once the filter is placed).

        Normally the teaching pair's other dye; judged from the curves themselves so
        the answer always matches what the learner sees.
        """
        if not self._heights:
            return self.deck.pair.dye_b
        return max(self._heights, key=self._heights.__getitem__)

    def on_press(self, x: float, y: float) -> None:
        if not (self.filter_placed or self.done):
            self._dragging = abs(x - self._filter_x) < FILTER_WIDTH
            if not self._dragging:
                self.wrong_hint = "Press inside the dashed band itself, then drag it sideways."
                self.deck.refresh()
            return
        if self.done or not self._heights:
            return
        # Every marker sits at the band's centre, so match on intensity alone,
        # once the click is inside the band: a few nm of x error would otherwise
        # swamp the comparison that matters.
        if abs(x - self._peak_x) > FILTER_WIDTH:
            self.wrong_hint = "Click inside the shaded detector band."
            self.deck.refresh()
            return
        nearest = min(self._heights, key=lambda name: abs(y - self._heights[name]))
        if nearest == self._leaker and abs(y - self._heights[nearest]) < MARKER_REACH:
            self.wrong_hint = None
            self._answer = nearest
            self.finish()
            return
        self.wrong_hint = (
            "Not quite: that marker isn't the highest. Look for the ○ furthest up inside the band."
        )
        self.deck.refresh()

    def on_drag(self, x: float, y: float) -> None:  # the band moves sideways only
        if not self._dragging:
            return
        self._filter_x = x
        for patch in self._band:
            patch.set_x(x - FILTER_WIDTH / 2)
        if self._grip is not None:
            self._grip.set_x(x)
        self.deck.redraw()

    def on_release(self) -> None:
        if not self._dragging:
            return
        self._dragging = False
        off_by = self._filter_x - self._peak_x
        if abs(off_by) < ON_PEAK:
            self.filter_placed = True
            self.wrong_hint = None
        else:
            side, way = ("right", "left") if off_by > 0 else ("left", "right")
            self.wrong_hint = (
                f"Dropped {abs(off_by):.0f} nm to the {side} of {self.deck.pair.label_a}'s peak"
                f" ({self._peak_x:.0f} nm). Drag it further {way}, onto the top of the curve."
            )
        self.deck.refresh()
