"""Step 4, Find the Level: drag a "% subtracted" slider until a single-stain
cloud stops climbing, then see that the level value is the one measured on
Step 3.

Too little and the cloud still climbs (under-compensated); too much and it
dips below the unstained cells (over-compensated). This is what Course 1 later
asks the learner to judge on real data.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from karcytics_sdk.plugin.theme_fallback import Colors, theme_manager
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QSlider, QVBoxLayout, QWidget

from .scenes import short_name
from .slide import Slide, ghost_label, ghost_line, label_axes, page

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.collections import PathCollection
    from matplotlib.lines import Line2D

    from .deck import SpectralLearningTab
    from .scenes import TeachingPair

SCENE_SEED = 21
FLOOR = 100.0  # where cells without the second dye sit on its detector
LEVEL_TOLERANCE = 1.5  # percentage points either side of the true value that count as level
HOLD_MS = 700  # how long the slider must stay level before the slide counts it
STEPS_PER_POINT = 2  # the slider moves in half-percent steps
MIN_RANGE = 10.0  # % the slider reaches at least, however small the spillover
X_MAX = 1000.0


def level_scene(seed: int = SCENE_SEED) -> dict[str, np.ndarray]:
    """Unstained cells, and single-stained cells before any spillover is added."""
    rng = np.random.default_rng(seed)
    return {
        "neg_x": rng.normal(FLOOR, 30, 250),
        "neg_y": rng.normal(FLOOR, 30, 250),
        "pos_x": rng.uniform(250, 950, 300),
        "pos_noise": rng.normal(0, 20, 300),
    }


def verdict_for(subtracted: float, pct: float) -> str:
    """'under', 'level' or 'over' for a slider value against the true spillover."""
    if abs(subtracted - pct) <= LEVEL_TOLERANCE:
        return "level"
    return "under" if subtracted < pct else "over"


def explanation(pair: TeachingPair, solved: bool) -> str:
    """The slide's text: what compensation does, plus the takeaway once solved."""
    a, b = short_name(pair.label_a), short_name(pair.label_b)
    takeaway = (
        f"Level at about {pair.pct:.0f}%: the spillover you measured with the ruler on"
        f" Step 3. Too little and {a}-only cells still look {b}-positive; too much and"
        f" they dip below cells with no {b} at all. A spillover matrix holds exactly"
        " these values, one per dye and detector."
    )
    return page(
        "Compensation by Hand",
        f"<p>The green cells carry only <b>{a}</b>. They climb on the {b} detector because"
        f" some {a} light lands there. Compensation subtracts a fixed percentage of each"
        f" cell's {a} reading from its {b} reading.</p>"
        f"<p>Pick the right percentage and the green cloud lies flat, level with the grey"
        f" unstained cells: being bright for {a} then says nothing about {b}.</p>",
        takeaway if solved else None,
    )


class LevelSlide(Slide):
    title = "Find the Level"

    def __init__(self, deck: SpectralLearningTab) -> None:
        super().__init__(deck)
        self.subtracted = 0.0  # % of the first dye's reading taken off the second's
        self._scene = level_scene()
        self._cells: PathCollection | None = None
        self._trend: Line2D | None = None
        self._status: QLabel | None = None
        self._slider: QSlider | None = None

    # ── drawing ──

    def _y(self, pct: float) -> np.ndarray:
        """The stained cells' second-detector reading after subtracting ``subtracted``%."""
        x = self._scene["pos_x"]
        return FLOOR + (pct - self.subtracted) / 100.0 * x + self._scene["pos_noise"]

    def render(self, ax: Axes) -> str:
        pair = self.deck.pair
        if self.done:
            self.subtracted = round(pair.pct * STEPS_PER_POINT) / STEPS_PER_POINT
        label_axes(
            ax,
            f"{pair.label_a} Single Stain, Compensated by Hand",
            f"{pair.label_a} Detector",
            f"{pair.label_b} Detector",
        )
        ax.scatter(
            self._scene["neg_x"], self._scene["neg_y"], color=Colors.FG_SECONDARY, alpha=0.4, s=10
        )
        ax.axhline(FLOOR, color=Colors.BORDER, ls="--")
        ax.text(X_MAX * 0.02, FLOOR + 12, "unstained level", color=Colors.FG_DISABLED, fontsize=8)
        self._cells = ax.scatter(
            self._scene["pos_x"], self._y(pair.pct), color=Colors.ACCENT_SUCCESS, alpha=0.6, s=14
        )
        self._trend = ax.plot([], [], color=Colors.ACCENT_SUCCESS, lw=2)[0]
        self._update_trend(pair.pct)
        reach = max(MIN_RANGE, 2 * pair.pct) / 100.0 * X_MAX
        ax.set_xlim(0, X_MAX)
        ax.set_ylim(FLOOR - reach - 60, FLOOR + pair.pct / 100.0 * X_MAX + 150)
        self._add_slider(pair)
        return explanation(pair, solved=self.done)

    def _update_trend(self, pct: float) -> None:
        if self._trend is not None:
            xs = np.array([200.0, 980.0])
            self._trend.set_data(xs, FLOOR + (pct - self.subtracted) / 100.0 * xs)

    def _add_slider(self, pair: TeachingPair) -> None:
        box = QWidget()
        column = QVBoxLayout(box)
        column.setContentsMargins(0, 0, 0, 0)
        self._status = QLabel()
        self._status.setWordWrap(True)
        theme_manager.apply_style(self._status, "color: {FG_PRIMARY}; font-weight: bold;")
        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setObjectName("LevelSlider")
        top = max(MIN_RANGE, 2 * pair.pct)
        self._slider.setRange(0, round(top * STEPS_PER_POINT))
        self._slider.setValue(round(self.subtracted * STEPS_PER_POINT))
        self._slider.setEnabled(not self.done)
        self._slider.valueChanged.connect(self._on_slider)
        column.addWidget(self._status)
        column.addWidget(self._slider)
        self.deck.add_control(box)
        self._show_status(pair)

    def _show_status(self, pair: TeachingPair) -> None:
        if self._status is None:
            return
        state = verdict_for(self.subtracted, pair.pct)
        words = {
            "under": "↗ still climbing: under-compensated",
            "level": "✓ level with the unstained cells",
            "over": "↘ dipping below: over-compensated",
        }[state]
        a, b = short_name(pair.label_a), short_name(pair.label_b)
        self._status.setText(f"Subtracting {self.subtracted:.1f}% of {a} from {b}:  {words}")

    # ── the learner's moves ──

    def instruction(self) -> str:
        return (
            "Drag the <b>slider</b> under the text. Watch the green cloud and its line: find"
            " the % where it lies <b>flat, level with the dashed unstained line</b>, not"
            " climbing and not dipping. Hold it there a moment."
        )

    def show_me(self, ax: Axes) -> str:
        pct = self.deck.pair.pct
        ghost_line(ax, [200.0, 980.0], [FLOOR, FLOOR])
        ghost_label(ax, 590.0, FLOOR - 45, "make the green line lie along here")
        self.deck.guide.point_at_answer_area()
        return (
            f"Your ruler on Step 3 read about {pct:.0f}%. Drag the slider near {pct:.0f}% and"
            " nudge it until the label says level."
        )

    def _on_slider(self, value: int) -> None:
        pair = self.deck.pair
        self.subtracted = value / STEPS_PER_POINT
        if self._cells is not None:
            self._cells.set_offsets(np.column_stack([self._scene["pos_x"], self._y(pair.pct)]))
        self._update_trend(pair.pct)
        self._show_status(pair)
        self.deck.redraw()
        if verdict_for(self.subtracted, pair.pct) == "level":
            self.deck.start_ticks(HOLD_MS)
        else:
            self.deck.stop_ticks()

    def on_tick(self) -> None:
        self.deck.stop_ticks()
        if verdict_for(self.subtracted, self.deck.pair.pct) == "level":
            self.finish()

    def leave(self) -> None:
        self.deck.stop_ticks()
