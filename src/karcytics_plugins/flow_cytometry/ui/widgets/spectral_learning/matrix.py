"""Step 7, Building the Compensation Matrix: which control tube measures one dye's
leak, and how many tubes the whole panel needs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from karcytics_sdk.plugin.theme_fallback import Colors, get_contrast_text_color
from matplotlib.colors import to_hex

from .scenes import dye_label, overlap_matrix, spectral_dyes
from .slide import AnswerBox, Slide, choices, heading, hint, task

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
        self.wrong_hint: str | None = None

    def render(self, ax: Axes) -> str:
        names = spectral_dyes(self.deck.fluors)
        self._draw_matrix(ax, names)
        if self.tube_found and not self.done:
            self.deck.ask("Enter a number", self._check_tube_count)
        return self._html(self.deck.pair, len(names))

    def _draw_matrix(self, ax: Axes, names: list[str]) -> None:
        matrix = overlap_matrix(self.deck.fluors, names)
        labels = [dye_label(self.deck.fluors, name) for name in names]
        ax.set_title("Real Compensation Matrix (% overlap)", color=Colors.FG_PRIMARY, pad=15)
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
            " row and one column per dye, where each cell is how much that dye's signal spills"
            ' into every other detector. "Compensate All" back in Step 5 is really just this'
            " matrix, inverted and applied to every event at once.</p>"
            "<p>Two rules decide which control tubes you actually need to run to fill that"
            " matrix in:</p>"
            '<p><b>1. An unstained control</b> — sets the true "zero" (autofluorescence)'
            " shared by every column, exactly like the threshold you dragged back in Step 2.</p>"
            "<p><b>2. One single-stain tube per dye</b> — stained with ONLY that dye, nothing"
            " else.</p>"
        )
        a, b = pair.label_a, pair.label_b
        if not self.tube_found:
            return (
                html
                + task(
                    f"Action Required: you want to measure exactly how much {a} leaks into"
                    f" {b}'s detector. Which control tube gives you that?"
                )
                + choices(
                    [
                        ("mc_unstained", "A) Unstained cells only"),
                        ("mc_single", f"B) Cells stained with {a} only"),
                        ("mc_both", f"C) Cells stained with both {a} and {b}"),
                        ("mc_full", "D) The fully-stained panel (all dyes)"),
                    ]
                )
                + hint(self.wrong_hint)
            )
        if not self.done:
            return (
                html
                + task(
                    "Right — a single-stain tube is the only sample where 100% of any off-peak"
                    " signal can be blamed on that one dye. Mix in a second dye, or the whole"
                    " panel, and you can no longer tell which dye caused what you're seeing."
                )
                + task(
                    f"Action Required: your panel has {n_dyes} dyes loaded. Counting one"
                    " single-stain tube per dye, PLUS the unstained control, how many total"
                    " tubes do you need to run before you can build the compensation matrix?"
                )
            )
        return html + task(
            f"Exactly — {n_dyes} dyes need {n_dyes + 1} tubes. The heatmap on the right IS that"
            " matrix: every cell is a real overlap % measured from the panel's own emission"
            " spectra, and inverting this exact grid is what 'Compensate All' does under the"
            " hood."
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
