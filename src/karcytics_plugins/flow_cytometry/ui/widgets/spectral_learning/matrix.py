"""Step 7, Building the Compensation Matrix: which control tube measures one dye's
leak, and how many tubes the whole panel needs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from karcytics_sdk.plugin.theme_fallback import Colors, get_contrast_text_color
from matplotlib import patches
from matplotlib.colors import to_hex

from .scenes import dye_label, spectral_dyes, spill_matrix
from .slide import AnswerBox, Slide, choices, heading, verdict

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from .deck import SpectralLearningTab
    from .scenes import TeachingPair

TUBE_HINTS = {
    "mc_unstained": "Unstained tells you the baseline, not how much this dye spills anywhere.",
    "mc_both": (
        "With both dyes present you can't tell which one is responsible for the signal you see."
    ),
    "mc_full": (
        "With every dye mixed together there's no way to isolate any single dye's contribution."
    ),
}


class MatrixSlide(Slide):
    title = "Building the Compensation Matrix"

    def __init__(self, deck: SpectralLearningTab) -> None:
        super().__init__(deck)
        self.tube_found = False  # picked the single-stain tube
        self._names: list[str] = []

    def render(self, ax: Axes) -> str:
        names = self._names = spectral_dyes(self.deck.fluors)
        self._draw_matrix(ax, names)
        if self.tube_found and not self.done:
            self.deck.ask("Enter a number", self._check_tube_count)
        return self._html(self.deck.pair, len(names))

    def _draw_matrix(self, ax: Axes, names: list[str]) -> None:
        matrix = spill_matrix(self.deck.fluors, names)
        labels = [dye_label(self.deck.fluors, name) for name in names]
        ax.set_title("Estimated Spillover Matrix (%)", color=Colors.FG_PRIMARY, pad=15)
        ax.set_xlabel("Detector", color=Colors.FG_SECONDARY, fontsize=9)
        ax.set_ylabel("Dye", color=Colors.FG_SECONDARY, fontsize=9)
        image = ax.imshow(matrix, cmap="viridis", vmin=0, vmax=100)
        ax.set_xticks(range(len(names)))
        ax.set_yticks(range(len(names)))
        ax.set_xticklabels(labels, color=Colors.FG_SECONDARY, fontsize=8, rotation=45, ha="right")
        ax.set_yticklabels(labels, color=Colors.FG_SECONDARY, fontsize=8)
        # Each number is read against its own cell's colour (viridis runs from
        # dark purple to bright yellow), not the theme's background.
        cells = image.to_rgba(matrix)
        for i in range(len(names)):
            for j in range(len(names)):
                r, g, b, _alpha = cells[i, j]
                cell = to_hex((float(r), float(g), float(b)))
                ax.text(
                    j,
                    i,
                    f"{matrix[i, j]:.0f}",
                    ha="center",
                    va="center",
                    color=get_contrast_text_color(cell),
                    fontsize=7,
                )

    def _html(self, pair: TeachingPair, n_dyes: int) -> str:
        html = heading("What It Takes to Build the Matrix") + (
            "<p>Every slide so far measured spillover for ONE pair of dyes. A real panel has"
            " many — correcting all of them at once needs a full <b>compensation matrix</b>: one"
            " row per dye and one column per detector, where each cell is how much of that dye's"
            ' signal lands in that detector. "Compensate All" back in Step 5 is really just this'
            " matrix, inverted and applied to every event at once.</p>"
            "<p>Two rules decide which control tubes you actually need to run to fill that"
            " matrix in:</p>"
            '<p><b>1. An unstained control</b> — sets the true "zero" (autofluorescence)'
            " shared by every column, exactly like the threshold you dragged back in Step 2.</p>"
            "<p><b>2. One single-stain tube per dye</b> — stained with ONLY that dye, nothing"
            " else.</p>"
            "<p><i>You won't always run these yourself: many cytometers save a matrix in the"
            " FCS files, built from single stains run on the instrument (the Academy's tutorial"
            " files carry one). FMO tubes are a different control, for setting gates.</i></p>"
        )
        a, b = pair.label_a, pair.label_b
        if not self.tube_found:
            return html + choices(
                [
                    ("mc_unstained", "A) Unstained cells only"),
                    ("mc_single", f"B) Cells stained with {a} only"),
                    ("mc_both", f"C) Cells stained with both {a} and {b}"),
                    ("mc_full", "D) The fully-stained panel (all dyes)"),
                ]
            )
        html += verdict(
            "Right — a single-stain tube is the only sample where 100% of any off-peak"
            " signal can be blamed on that one dye. Mix in a second dye, or the whole"
            " panel, and you can no longer tell which dye caused what you're seeing."
        )
        if not self.done:
            return html
        return html + verdict(
            f"Exactly — {n_dyes} dyes need {n_dyes + 1} tubes. The heatmap on the right is that"
            " matrix, estimated from your dyes' real spectra and the lasers that excite them."
            " Single-stain tubes measure the same grid on your own cytometer, and inverting it"
            " is what 'Compensate All' does under the hood."
        )

    def instruction(self) -> str:
        pair = self.deck.pair
        if not self.tube_found:
            return (
                f"You want to measure exactly how much {pair.label_a} leaks into"
                f" {pair.label_b}'s detector. Which control tube gives you that? Click A–D at"
                " the bottom of the text below."
            )
        return (
            f"Your panel has {len(self._names)} dyes loaded. Counting one single-stain tube"
            " per dye, PLUS the unstained control, how many tubes do you need? Type the number"
            " in the box and press <b>Submit</b>."
        )

    def show_me(self, ax: Axes) -> str:
        pair = self.deck.pair
        n = len(self._names)
        if not self.tube_found:
            i, j = self._names.index(pair.dye_a), self._names.index(pair.dye_b)
            self._outline(ax, j - 0.5, i - 0.5, 1, 1)
            return (
                f"The outlined square is {pair.label_a}'s light in {pair.label_b}'s detector. To"
                f" be sure the light came from {pair.label_a}, the tube must contain"
                f" {pair.label_a} and nothing else."
            )
        self._outline(ax, -0.5, -0.5, n, 1)
        return (
            f"Each row of the heatmap is one dye ({n} rows), and each needs its own single-stain"
            f" tube: {n} tubes. Then add the unstained control."
        )

    @staticmethod
    def _outline(ax: Axes, x: float, y: float, width: float, height: float) -> None:
        ax.add_patch(
            patches.Rectangle(
                (x, y), width, height, fill=False, edgecolor=Colors.ACCENT_WARNING, lw=3, ls="--"
            )
        )

    def on_link(self, link: str) -> None:
        if self.tube_found:
            return
        self.tube_found = link == "mc_single"
        self.wrong_hint = (
            None
            if self.tube_found
            else TUBE_HINTS.get(
                link, "Not quite — think about which tube isolates ONE dye's contribution."
            )
        )
        self.deck.refresh()

    def _check_tube_count(self, box: AnswerBox) -> None:
        tubes = box.whole_number()
        if tubes is None:
            return
        if tubes == len(spectral_dyes(self.deck.fluors)) + 1:
            self.finish()
        else:
            box.show_error("Not quite — count one tube per dye, plus the unstained control.")
