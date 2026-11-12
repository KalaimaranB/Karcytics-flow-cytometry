"""Step 4 of Learning Compensation, "One Rule for Every Cell": its cells, grading and plot.

Three uncompensated cells: dim and bright single-positives (pure leak above
the autofluorescence floor) and a true double-positive. The learner works out
that compensation takes off a fixed fraction of each cell's own first-dye
reading, then applies it to the double-positive.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from karcytics_sdk.plugin.theme_fallback import Colors

if TYPE_CHECKING:
    from matplotlib.axes import Axes

SLIDE4_FLOOR = 40.0  # autofluorescence: where a cell with none of the second dye sits
SLIDE4_DP_SIGNAL = 350.0  # Cell 3's genuine second-dye signal above the floor
DOUBLE_POSITIVE = 3  # the cell number of the true double-positive
SLIDE4_TOLERANCE = 10.0  # units allowed off in the typed compensated value


def slide4_cells(pct: float) -> list[tuple[float, float]]:
    """Three uncompensated cells, rounded as displayed: dim and bright
    single-positives (pure leak above the floor) and a true double-positive.
    """
    slope = pct / 100.0
    return [
        (300.0, round(SLIDE4_FLOOR + slope * 300)),
        (900.0, round(SLIDE4_FLOOR + slope * 900)),
        (750.0, round(SLIDE4_FLOOR + slope * 750 + SLIDE4_DP_SIGNAL)),
    ]


def slide4_expected_dp(pct: float, cells: list[tuple[float, float]]) -> float:
    """Cell 3's compensated reading, from the numbers the learner is shown
    (the % to one decimal, the readings as whole numbers).
    """
    x3, y3 = cells[2]
    return y3 - round(pct, 1) / 100.0 * x3


def grade_slide4_answer(
    guess: float,
    pct: float,
    cells: list[tuple[float, float]],
    label_a: str = "the first dye",
    label_b: str = "the second dye",
) -> str | None:
    """None when right; otherwise feedback aimed at the likely mistake."""
    expected = slide4_expected_dp(pct, cells)
    if abs(guess - expected) <= SLIDE4_TOLERANCE:
        return None
    x3, y3 = cells[2]
    if abs(guess - y3) <= SLIDE4_TOLERANCE:
        return "That's the raw reading: nothing has been subtracted yet."
    if abs(guess - (y3 - x3)) <= SLIDE4_TOLERANCE:
        return (
            f"You subtracted all of Cell 3's {label_a} reading ({x3:.0f}). Only "
            f"{pct:.1f}% of it leaked, so subtract {pct:.1f}% × {x3:.0f}."
        )
    if abs(guess - SLIDE4_FLOOR) <= SLIDE4_TOLERANCE:
        return (
            "Compensation doesn't send every cell to the floor. It only removes the part "
            f"of the reading {label_a} explains."
        )
    return (
        f"Not quite: subtract {pct:.1f}% of Cell 3's own {label_a} reading ({x3:.0f}) "
        f"from its {label_b} reading ({y3:.0f})."
    )


def slide4_plot(
    ax: Axes, cells: list[tuple[float, float]], pct: float, show_pure: bool, show_dp: bool
) -> None:
    """The three cells, each with its compensation arrow once it has been worked out."""
    slope = pct / 100.0
    top = max(600.0, cells[2][1] * 1.2)
    ax.axhline(SLIDE4_FLOOR, color=Colors.BORDER, ls="--")
    ax.text(
        20,
        SLIDE4_FLOOR + top * 0.015,
        "autofluorescence floor",
        color=Colors.FG_DISABLED,
        fontsize=8,
    )
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
