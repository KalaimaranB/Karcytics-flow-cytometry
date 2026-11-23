"""Step 4, One Rule for Every Cell: work out that compensation takes a fixed fraction
of each cell's own first-dye reading, then apply it to a true double-positive.

Three uncompensated cells: dim and bright single-positives (pure leak above the
autofluorescence floor) and a double-positive.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from karcytics_sdk.plugin.theme_fallback import Colors

from .slide import AnswerBox, Slide, choices, heading, hint, label_axes, task

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from .scenes import TeachingPair

FLOOR = 40.0  # autofluorescence: where a cell with none of the second dye sits
DP_SIGNAL = 350.0  # Cell 3's genuine second-dye signal above the floor
DOUBLE_POSITIVE = 3  # the cell number of the true double-positive
TOLERANCE = 10.0  # units allowed off in the typed compensated value
RULE_HINTS = {
    "s4_same": (
        "Spillover is a fraction of each cell's own light. Cell 2 is three times as bright,"
        " so it leaked three times as much: compare how far each sits above the floor."
    ),
    "s4_floor": (
        "Compensation can't see which cells 'should' be negative; it applies one rule to"
        " every event. Cell 3 is why that matters."
    ),
}


def three_cells(pct: float) -> list[tuple[float, float]]:
    """The three uncompensated cells, rounded as displayed."""
    slope = pct / 100.0
    return [
        (300.0, round(FLOOR + slope * 300)),
        (900.0, round(FLOOR + slope * 900)),
        (750.0, round(FLOOR + slope * 750 + DP_SIGNAL)),
    ]


def compensated_dp(pct: float, cells: list[tuple[float, float]]) -> float:
    """Cell 3's compensated reading, from the numbers the learner is shown
    (the % to one decimal, the readings as whole numbers).
    """
    x3, y3 = cells[2]
    return y3 - round(pct, 1) / 100.0 * x3


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
    if abs(guess - y3) <= TOLERANCE:
        return "That's the raw reading: nothing has been subtracted yet."
    if abs(guess - (y3 - x3)) <= TOLERANCE:
        return (
            f"You subtracted all of Cell 3's {label_a} reading ({x3:.0f}). Only "
            f"{pct:.1f}% of it leaked, so subtract {pct:.1f}% × {x3:.0f}."
        )
    if abs(guess - FLOOR) <= TOLERANCE:
        return (
            "Compensation doesn't send every cell to the floor. It only removes the part "
            f"of the reading {label_a} explains."
        )
    return (
        f"Not quite: subtract {pct:.1f}% of Cell 3's own {label_a} reading ({x3:.0f}) "
        f"from its {label_b} reading ({y3:.0f})."
    )


def plot_cells(
    ax: Axes, cells: list[tuple[float, float]], pct: float, show_pure: bool, show_dp: bool
) -> None:
    """The three cells, each with its compensation arrow once it has been worked out."""
    slope = pct / 100.0
    top = max(600.0, cells[2][1] * 1.2)
    ax.axhline(FLOOR, color=Colors.BORDER, ls="--")
    ax.text(20, FLOOR + top * 0.015, "autofluorescence floor", color=Colors.FG_DISABLED, fontsize=8)
    for i, (x, y) in enumerate(cells, start=1):
        is_dp = i == DOUBLE_POSITIVE
        corrected = y - slope * x
        moved = show_dp if is_dp else show_pure
        color = Colors.ACCENT_PRIMARY if is_dp else Colors.ACCENT_WARNING
        ax.scatter([x], [y], color=color, s=140, alpha=0.35 if moved else 0.9, zorder=4)
        ax.annotate(
            f"Cell {i}", xy=(x, y), xytext=(x - 60, y + top * 0.05), color=color, fontsize=9
        )
        if moved:
            ax.annotate(
                "",
                xy=(x, corrected),
                xytext=(x, y),
                arrowprops={"arrowstyle": "->", "color": color, "lw": 1.5},
            )
            ax.text(x + 15, (y + corrected) / 2, f"−{slope * x:.0f}", color=color, fontsize=8)
            ax.scatter([x], [corrected], color=color, s=140, edgecolor="white", zorder=5)
    ax.set_xlim(0, 1000)
    ax.set_ylim(0, top)


class OneRuleSlide(Slide):
    title = "One Rule for Every Cell"

    def __init__(self, deck) -> None:
        super().__init__(deck)
        self.rule_found = False  # picked "in proportion to its first-dye brightness"
        self.wrong_hint: str | None = None

    def render(self, ax: Axes) -> str:
        pair = self.deck.pair
        cells = three_cells(pair.pct)
        if self.done:
            title = "Three Cells, Compensated"
        elif self.rule_found:
            title = "Cells 1 and 2 Compensated"
        else:
            title = "Three Cells, Before Compensation"
        label_axes(ax, title, f"{pair.label_a} Detector", f"{pair.label_b} Detector")
        plot_cells(ax, cells, pair.pct, show_pure=self.rule_found, show_dp=self.done)
        if self.rule_found and not self.done:
            self.deck.ask("Compensated value", self._check_cell_3)
        return self._html(pair, cells)

    def _html(self, pair: TeachingPair, cells: list[tuple[float, float]]) -> str:
        a, b, pct = pair.label_a, pair.label_b, pair.pct
        rows = "".join(
            f"<tr><td>Cell {i}</td><td>{x:.0f}</td><td>{y:.0f}</td></tr>"
            for i, (x, y) in enumerate(cells, start=1)
        )
        html = heading("Applying the Math") + (
            f"<p>Step 3 measured the leak: {pct:.1f}% of {a}'s light lands in {b}'s detector."
            f" Compensation has to undo that for every cell, and it never knows in advance which"
            f' cells "should" be {b}-negative.</p>'
            "<p>Here are three cells from a stained sample, before compensation. The dashed line"
            f" is the <b>autofluorescence floor</b> from Step 2: where a cell with no {b} at all"
            " belongs.</p>"
            f'<table cellpadding="3"><tr><td></td><td><b>{a}</b></td><td><b>{b}</b></td></tr>'
            f"{rows}</table>"
        )
        if not self.rule_found:
            return (
                html
                + task(
                    f"Action Required: Cells 1 and 2 carry no {b} at all. How much must"
                    f" compensation take off each one's {b} reading?"
                )
                + choices(
                    [
                        ("s4_same", "A) The same amount from both"),
                        (
                            "s4_proportional",
                            f"B) More from Cell 2, in proportion to its {a} brightness",
                        ),
                        ("s4_floor", "C) Whatever it takes to bring each down to the floor"),
                    ]
                )
                + hint(self.wrong_hint)
            )
        (x1, _y1), (x2, _y2), (x3, y3) = cells
        html += task(
            f"Right: the leak is a fraction of each cell's own {a} light. {pct:.1f}% of"
            f" {x1:.0f} is {pct / 100 * x1:.0f}; {pct:.1f}% of {x2:.0f} is"
            f" {pct / 100 * x2:.0f}. Both cells land on the floor."
        )
        if not self.done:
            return html + task(
                f"Action Required: Cell 3 reads {x3:.0f} for {a} and {y3:.0f} for {b}. Apply"
                f" the same rule: what is its compensated {b} reading?"
            )
        return (
            html
            + task(
                f"Exactly: {y3:.0f} − {pct:.1f}% × {x3:.0f} ≈ {compensated_dp(pct, cells):.0f}."
                f" Cell 3 stays well above the floor: most of its {b} signal was never leaked"
                f" {a} light. It's a real double-positive."
            )
            + f"<p>Compensation removes only the part of a reading that {a} explains. It doesn't"
            " erase real signal, and it doesn't push cells to the floor. Skip it, and Cell 2's"
            f" leaked light reads as {b} it doesn't have.</p>"
        )

    def on_link(self, link: str) -> None:
        if self.rule_found:
            return
        self.rule_found = link == "s4_proportional"
        self.wrong_hint = (
            None
            if self.rule_found
            else RULE_HINTS.get(link, "Not quite: think about where the leaked light comes from.")
        )
        self.deck.refresh()

    def _check_cell_3(self, box: AnswerBox) -> None:
        guess = box.number("250")
        if guess is None:
            return
        pair = self.deck.pair
        verdict = grade_dp_answer(
            guess, pair.pct, three_cells(pair.pct), pair.label_a, pair.label_b
        )
        if verdict is None:
            self.finish()
        else:
            box.show_error(verdict)
