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
from .slide import Slide, heading, hint, label_axes, legend, task

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


class PhysicsSlide(Slide):
    title = "The Physics of Overlap"

    def __init__(self, deck: SpectralLearningTab) -> None:
        super().__init__(deck)
        self.filter_placed = False
        self.wrong_hint: str | None = None
        self._dragging = False
        self._filter_x = FILTER_START
        self._peak_x = FILTER_START  # dye A's peak, found when its curve is drawn
        self._band: list[patches.Rectangle] = []
        self._grip: Text | None = None
        self._heights: dict[str, float] = {}  # each other dye's height inside the band

    def render(self, ax: Axes) -> str:
        pair = self.deck.pair
        placed = self.filter_placed or self.done
        label_axes(ax, "Real Emission Spectra", "Wavelength (nm)", "Normalized Intensity")
        curves = self._plot_curves(ax, pair)
        self._peak_x = float(WAVELENGTHS[np.argmax(curves[pair.dye_a])])
        self._filter_x = self._peak_x if placed else FILTER_START
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
        return self._html(pair, placed)

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

    def _html(self, pair: TeachingPair, placed: bool) -> str:
        html = heading("Detectors, Filters, and Broad Curves") + (
            '<p>A flow cytometer uses detectors covered by colored glass filters to "see" light —'
            " each filter only passes a narrow range of wavelengths through to its detector.</p>"
            "<p>But a fluorescent dye doesn't glow at one exact wavelength. It emits across a"
            " broad, hill-shaped range spanning 100nm or more. Detectors sit under the peak of"
            " one dye's hill, but that hill's shoulders still spill into neighboring detectors —"
            " two dyes with peaks 50nm apart can still overlap by 20-30% or more.</p>"
            "<p>Below are the real emission curves for every dye you loaded. Use the legend to"
            " identify each dye by colour.</p>"
        )
        if not placed:
            return html + task(
                "Action Required: See the <b>◀ drag ▶</b> Detector Filter band on the plot."
                f" Click and drag it onto the peak of <b>{pair.label_a}</b>'s curve, then release."
            )
        if not self.done:
            return (
                html
                + task(
                    f"Action Required: The filter is now sitting on {pair.label_a}'s detector."
                    " Click on whichever OTHER curve is still riding highest inside the shaded"
                    " band — that dye leaks into this detector the most."
                )
                + hint(self.wrong_hint)
            )
        return html + task(
            f"Correct! {pair.label_b} leaks the most into {pair.label_a}'s detector — that's"
            " exactly the pair spillover will hit hardest."
        )

    def on_press(self, x: float, y: float) -> None:
        if not (self.filter_placed or self.done):
            self._dragging = abs(x - self._filter_x) < FILTER_WIDTH
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
        if nearest == self.deck.pair.dye_b and abs(y - self._heights[nearest]) < MARKER_REACH:
            self.wrong_hint = None
            self.finish()
            return
        self.wrong_hint = "Not quite — look for the curve still riding high in the band."
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
        if abs(self._filter_x - self._peak_x) < ON_PEAK:
            self.filter_placed = True
            self.deck.refresh()
