"""Step 5, Same Rule, Every Cell: compensation takes the same percentage of every
cell's own first-dye reading off its second-dye reading.

Three cells from a stained sample, drawn as bars of their second-detector
reading: a dim cell with only the first dye, a bright one with only the first
dye, and one that really carries both. A bar is split into background, real
signal and spillover once its spillover has been worked out:

1. Worked example: the dim cell, done in full.
2. A rule question: how much spillover does the bright cell carry?
3. Half done: the learner types the bright cell's spillover.
4. Alone: the learner works out what's left of the "really both" cell.

The arithmetic uses the whole-number % ("≈ 20%"), so every sum works out.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from karcytics_sdk.plugin.theme_fallback import Colors

from .calculator import Calculator, format_result
from .scenes import short_name
from .slide import AnswerBox, Slide, choices, ghost_arrow, ghost_label, page

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from .deck import SpectralLearningTab
    from .scenes import TeachingPair

FLOOR = 40.0  # background (autofluorescence): what a cell with none of the second dye reads
DP_SIGNAL = 350.0  # the "really both" cell's real second-dye signal
FIRST_DYE = (300.0, 900.0, 750.0)  # dim, bright, really both: their first-dye readings
TOLERANCE = 10.0  # units allowed off in a typed reading
BAR_WIDTH = 0.55
RULE_HINTS = {
    "s4_same": (
        "Spillover is a fraction of each cell's own light. The bright cell gives off three"
        " times as much of the first dye, so three times as much of it spills."
    ),
    "s4_floor": (
        "Compensation can't see which cells 'should' be negative; it applies one rule to"
        " every cell. The 'really both' cell is why that matters."
    ),
}
STAGE_RULE, STAGE_BRIGHT, STAGE_BOTH = "rule", "bright", "both"


def whole_pct(pct: float) -> int:
    """The spillover the slide calculates with: the % rounded to a whole number."""
    return max(1, round(pct))


def three_cells(pct: float) -> list[tuple[float, float]]:
    """(first-dye reading, second-dye reading) of the dim, bright and really-both cells."""
    share = whole_pct(pct) / 100.0
    dim, bright, both = FIRST_DYE
    return [
        (dim, round(FLOOR + share * dim)),
        (bright, round(FLOOR + share * bright)),
        (both, round(FLOOR + share * both + DP_SIGNAL)),
    ]


def spillover(pct: float, first_dye: float) -> float:
    return whole_pct(pct) / 100.0 * first_dye


def compensated_dp(pct: float, cells: list[tuple[float, float]]) -> float:
    """The really-both cell's second-dye reading once its spillover is taken off."""
    x3, y3 = cells[2]
    return y3 - spillover(pct, x3)


def cell_names(pair: TeachingPair) -> tuple[str, str, str]:
    a, b = short_name(pair.label_a), short_name(pair.label_b)
    return (f"{a}-only, dim", f"{a}-only, bright", f"{a} + {b}, really both")


def grade_dp_answer(
    guess: float,
    pct: float,
    cells: list[tuple[float, float]],
    label_a: str = "the first dye",
    label_b: str = "the second dye",
) -> str | None:
    """None when right; otherwise feedback aimed at the likely mistake."""
    if abs(guess - compensated_dp(pct, cells)) <= TOLERANCE:
        return None
    x3, y3 = cells[2]
    p = whole_pct(pct)
    if abs(guess - y3) <= TOLERANCE:
        return "That's the reading before compensation: nothing has been taken off yet."
    if abs(guess - spillover(pct, x3)) <= TOLERANCE:
        return (
            f"That's the spillover itself ({p}% × {x3:.0f}). Now take it off the cell's"
            f" {label_b} reading ({y3:.0f})."
        )
    if abs(guess - (y3 - x3)) <= TOLERANCE:
        return (
            f"You took off all of its {label_a} reading ({x3:.0f}). Only {p}% of it spills,"
            f" so take off {p}% × {x3:.0f}."
        )
    if abs(guess - FLOOR) <= TOLERANCE:
        return (
            "Compensation doesn't send every cell to the background. It only removes the part"
            f" of the reading that {label_a} explains."
        )
    return (
        f"Not quite: {y3:.0f} − ({p}% × {x3:.0f}). Work out the spillover in the 🧮 first,"
        " then subtract it."
    )


def grade_bright_spillover(guess: float, pct: float) -> str | None:
    """None when right; otherwise feedback aimed at the likely mistake."""
    dim, bright, _both = FIRST_DYE
    expected = spillover(pct, bright)
    if abs(guess - expected) <= TOLERANCE:
        return None
    p = whole_pct(pct)
    if abs(guess - spillover(pct, dim)) <= TOLERANCE:
        return (
            "That's the dim cell's spillover. The bright cell gives off more light, so more spills."
        )
    if abs(guess - bright) <= TOLERANCE:
        return f"That's its whole first-dye reading. Only {p}% of it spills: {p}% × {bright:.0f}."
    return f"Not quite: {p}% of {bright:.0f}. Type {bright:.0f} × {p}% into the 🧮."


class OneRuleSlide(Slide):
    title = "Same Rule, Every Cell"

    def __init__(self, deck: SpectralLearningTab) -> None:
        super().__init__(deck)
        self.stage = STAGE_RULE

    # ── drawing ──

    def render(self, ax: Axes) -> str:
        pair = self.deck.pair
        cells = three_cells(pair.pct)
        solved = (True, self.stage == STAGE_BOTH or self.done, self.done)
        self._plot_bars(ax, pair, cells, solved)
        if not self.done and self.stage == STAGE_BRIGHT:
            self.deck.ask("Spillover in units", self._check_bright)
            self.deck.add_control(Calculator())
        elif not self.done and self.stage == STAGE_BOTH:
            self.deck.ask("What's left", self._check_both)
            self.deck.add_control(Calculator())
        return self._html(pair, cells)

    def _plot_bars(
        self,
        ax: Axes,
        pair: TeachingPair,
        cells: list[tuple[float, float]],
        solved: tuple[bool, bool, bool],
    ) -> None:
        names = cell_names(pair)
        b = short_name(pair.label_b)
        top = max(cells[2][1], cells[1][1]) * 1.25
        for i, ((x, y), is_solved) in enumerate(zip(cells, solved, strict=True)):
            if not is_solved:
                ax.bar(i, y, BAR_WIDTH, color=Colors.FG_SECONDARY, alpha=0.6)
                ax.text(
                    i, y / 2, "?", ha="center", va="center", color=Colors.FG_PRIMARY, fontsize=16
                )
            else:
                spilled = spillover(pair.pct, x)
                real = y - FLOOR - spilled
                ax.bar(
                    i, FLOOR, BAR_WIDTH, color=Colors.BORDER, label="background" if i == 0 else None
                )
                ax.bar(
                    i,
                    real,
                    BAR_WIDTH,
                    bottom=FLOOR,
                    color=Colors.ACCENT_PRIMARY,
                    label=f"real {b} signal" if real > 1 and i == 2 else None,  # noqa: PLR2004 - the really-both cell
                )
                ax.bar(
                    i,
                    spilled,
                    BAR_WIDTH,
                    bottom=FLOOR + real,
                    color=Colors.ACCENT_WARNING,
                    alpha=0.35,
                    hatch="//",
                    edgecolor=Colors.ACCENT_WARNING,
                    label="spillover (taken off)" if i == 0 else None,
                )
                ax.text(
                    i + BAR_WIDTH / 2 + 0.04,
                    FLOOR + real + spilled / 2,
                    f"−{spilled:.0f}",
                    va="center",
                    color=Colors.ACCENT_WARNING,
                    fontsize=9,
                    fontweight="bold",
                )
            ax.text(
                i, y + top * 0.02, f"{y:.0f}", ha="center", color=Colors.FG_PRIMARY, fontsize=10
            )
        ax.set_xticks(range(3))
        ax.set_xticklabels(
            [
                f"{name}\n{short_name(pair.label_a)} reads {x:.0f}"
                for name, (x, _y) in zip(names, cells, strict=True)
            ],
            color=Colors.FG_SECONDARY,
            fontsize=8,
        )
        ax.set_xlim(-0.6, 2.9)
        ax.set_ylim(0, top)
        ax.set_title(f"Three Cells: Their {pair.label_b} Reading", color=Colors.FG_PRIMARY, pad=15)
        ax.set_ylabel(f"{pair.label_b} Detector", color=Colors.FG_SECONDARY, fontsize=10)
        ax.legend(
            facecolor=Colors.BG_DARKEST,
            edgecolor=Colors.BORDER,
            labelcolor=Colors.FG_PRIMARY,
            fontsize=8,
            loc="upper left",
        )

    def _html(self, pair: TeachingPair, cells: list[tuple[float, float]]) -> str:
        a, b = short_name(pair.label_a), short_name(pair.label_b)
        p = whole_pct(pair.pct)
        names = cell_names(pair)
        (x1, y1), (x2, y2), (x3, y3) = cells
        body = (
            f"<p>You measured the spillover: about <b>{p}%</b> of {a}'s light lands in {b}'s"
            f" detector. Compensation takes that much off <b>every</b> cell, and it never knows"
            f" in advance which cells really carry {b}.</p>"
            f"<p>The bars are three cells' {b} readings. The grey base is the"
            " <b>background</b> every cell has, even with no dye (Step 2).</p>"
            "<table cellpadding='6' style='background: rgba(128,128,128,0.15);'><tr><td>"
            f"<b>Worked example: the {names[0]} cell</b><br>"
            f"It reads {x1:.0f} for {a} and {y1:.0f} for {b}.<br>"
            f"Spillover = {p}% of its {a} reading = {p}% × {x1:.0f} ="
            f" <b>{format_result(spillover(pair.pct, x1))}</b>.<br>"
            f"What's left = {y1:.0f} − {format_result(spillover(pair.pct, x1))} ="
            f" <b>{format_result(y1 - spillover(pair.pct, x1))}</b>: just the background. It"
            f" never had any {b}."
            "</td></tr></table>"
        )
        if self.stage == STAGE_RULE and not self.done:
            return page(
                "Applying the Spillover",
                body
                + choices(
                    [
                        (
                            "s4_same",
                            f"A) The same as the dim cell: {format_result(spillover(pair.pct, x1))}",
                        ),
                        (
                            "s4_proportional",
                            f"B) Three times as much: it's three times as bright in {a}",
                        ),
                        ("s4_floor", "C) Whatever it takes to bring it down to the background"),
                    ]
                ),
            )
        bright = (
            f"Right: spillover is a share of each cell's own {a} light. The {names[1]} cell:"
            f" {p}% × {x2:.0f} = {format_result(spillover(pair.pct, x2))}, leaving"
            f" {format_result(y2 - spillover(pair.pct, x2))}, the background again."
            if self.stage == STAGE_BOTH or self.done
            else f"Right: spillover is a share of each cell's own {a} light."
        )
        both = None
        if self.done:
            both = (
                f"Exactly: {y3:.0f} − {p}% × {x3:.0f} = {format_result(compensated_dp(pair.pct, cells))}."
                f" This cell stays well above the background: most of its {b} reading was real."
                f" Compensation removes only what {a} explains. It never erases real signal, and"
                f" without it the {names[1]} cell would look like it carries {b}."
            )
        return page("Applying the Spillover", body, bright, both)

    # ── the learner's moves ──

    def instruction(self) -> str:
        pair = self.deck.pair
        a, b = short_name(pair.label_a), short_name(pair.label_b)
        names = cell_names(pair)
        x2, _y2 = three_cells(pair.pct)[1]
        x3, y3 = three_cells(pair.pct)[2]
        p = whole_pct(pair.pct)
        if self.stage == STAGE_RULE:
            return (
                f"Read the worked example (the {names[0]} cell). The {names[1]} cell is three"
                f" times as bright in {a}. How much spillover does it carry? Click A, B or C at"
                " the bottom of the text."
            )
        if self.stage == STAGE_BRIGHT:
            return (
                f"Your turn, half done: the {names[1]} cell reads {x2:.0f} for {a}. Its"
                f" spillover is {p}% of that. Type the spillover in the box and press"
                " <b>Submit</b> (🧮 helps)."
            )
        return (
            f"On your own: the {names[2]} cell reads {x3:.0f} for {a} and {y3:.0f} for {b}."
            f" Take off its spillover and type what's left of its {b} reading."
        )

    def show_me(self, ax: Axes) -> str:
        pair = self.deck.pair
        cells = three_cells(pair.pct)
        p = whole_pct(pair.pct)
        a = short_name(pair.label_a)
        if self.stage == STAGE_RULE:
            for i in (0, 1):
                x, y = cells[i]
                ghost_label(ax, i, y + max(c[1] for c in cells) * 0.12, f"{a} reads {x:.0f}")
            return (
                f"Spillover is {p}% of each cell's own {a} reading. The bright cell reads"
                f" {cells[1][0]:.0f}, three times the dim cell's {cells[0][0]:.0f}."
            )
        self.deck.guide.point_at_answer_area()
        if self.stage == STAGE_BRIGHT:
            x2, y2 = cells[1]
            ghost_arrow(ax, (1.45, y2), (1.45, y2 - spillover(pair.pct, x2)))
            return f"Type <b>{x2:.0f} × {p}%</b> into the 🧮, then type its answer in the box."
        x3, y3 = cells[2]
        ghost_arrow(ax, (2.45, y3), (2.45, y3 - spillover(pair.pct, x3)))
        return (
            f"First the spillover: <b>{x3:.0f} × {p}%</b> in the 🧮. Then take that away from"
            f" {y3:.0f}: <b>{y3:.0f} − (that number)</b>."
        )

    def on_link(self, link: str) -> None:
        if self.stage != STAGE_RULE:
            return
        if link == "s4_proportional":
            self.stage = STAGE_BRIGHT
            self.wrong_hint = None
        else:
            self.wrong_hint = RULE_HINTS.get(
                link, "Not quite: think about where the spilled light comes from."
            )
        self.deck.refresh()

    def _check_bright(self, box: AnswerBox) -> None:
        guess = box.number("90")
        if guess is None:
            return
        problem = grade_bright_spillover(guess, self.deck.pair.pct)
        if problem is None:
            self.stage = STAGE_BOTH
            self.deck.refresh()
        else:
            box.show_error(problem)

    def _check_both(self, box: AnswerBox) -> None:
        guess = box.number("250")
        if guess is None:
            return
        pair = self.deck.pair
        problem = grade_dp_answer(
            guess, pair.pct, three_cells(pair.pct), pair.label_a, pair.label_b
        )
        if problem is None:
            self.finish()
        else:
            box.show_error(problem)
