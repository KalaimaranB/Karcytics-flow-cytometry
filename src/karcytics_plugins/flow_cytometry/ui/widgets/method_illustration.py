"""A fit, shown step by step on real events.

Draws a ``FitIllustration`` in four steps — what the tube recorded, an
ordinary fit, the robust fit, and the spill removed — animating the two
that move, so the mechanism can be watched rather than read.
"""

from __future__ import annotations

import numpy as np
from karcytics_sdk.plugin.components import SecondaryButton
from karcytics_sdk.plugin.theme_fallback import Colors
from matplotlib.figure import Figure
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from karcytics_plugins.flow_cytometry.ui.graph._mpl_compat import LockedFigureCanvas
from karcytics_plugins.flow_cytometry.ui.widgets.matrix_sources import FitIllustration

STEP_RECORDED, STEP_PLAIN_FIT, STEP_ROBUST_FIT, STEP_REMOVED = range(4)
_LAST_STEP = STEP_REMOVED

_FRAMES_PER_STEP = 18
_FRAME_MS = 40
_HOLD_MS = 1400  # pause on each finished step while playing

_EVENT_COLOR = "#2188FF"
_IGNORED_COLOR = "#777777"
_PLAIN_COLOR = "#FFB74D"
_ROBUST_COLOR = "#7EE787"
_PLOT_BG = "#FFFFFF"
_CANVAS_HEIGHT = 320
# The view is clipped here so a handful of extreme events don't flatten the rest.
_VIEW_PERCENTILE = 99.0


def pass_wheel_to_page(widget: QWidget) -> None:
    """Let the wheel scroll the page ``widget`` sits in, instead of ``widget``.

    Otherwise the page can't be scrolled with the pointer over a plot, a
    table that shows all its rows, or a combo (which would also change its
    selection — a setting — as the page went by).
    """

    def _ignore(event: QWheelEvent | None) -> None:
        if event is not None:
            event.ignore()

    widget.wheelEvent = _ignore  # type: ignore[method-assign, assignment]


class FitIllustrationView(QWidget):
    """Steps through one fit: Back / Next move a step, Play runs them all."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._fit: FitIllustration | None = None
        self._step = STEP_RECORDED
        self._progress = 1.0  # how far the current step's motion has got, 0..1
        self._playing = False
        self._setup_ui()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    # ── UI ────────────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._figure = Figure(figsize=(6, 3.2), facecolor=Colors.BG_DARKEST, layout="constrained")
        self.canvas = LockedFigureCanvas(self._figure)
        self.canvas.setFixedHeight(_CANVAS_HEIGHT)
        pass_wheel_to_page(self.canvas)  # nothing to zoom here
        self._ax = self._figure.add_subplot(111)
        layout.addWidget(self.canvas)

        self._caption = QLabel()
        self._caption.setWordWrap(True)
        self._caption.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self._caption)

        controls = QHBoxLayout()
        self._btn_back = SecondaryButton("◀ Back")
        self._btn_back.clicked.connect(lambda: self.go_to(self._step - 1))
        self._btn_next = SecondaryButton("Next ▶")
        self._btn_next.clicked.connect(lambda: self.go_to(self._step + 1, animate=True))
        self._btn_play = SecondaryButton("▶ Play")
        self._btn_play.clicked.connect(self.play)
        self._step_label = QLabel()
        for widget in (self._btn_back, self._btn_next, self._btn_play, self._step_label):
            controls.addWidget(widget)
        controls.addStretch()
        layout.addLayout(controls)

    # ── Public API ────────────────────────────────────────────────────

    @property
    def step(self) -> int:
        return self._step

    def show_fit(self, fit: FitIllustration | None) -> None:
        """Start over on ``fit`` (None clears the picture)."""
        self._stop()
        self._fit = fit
        self._step, self._progress = STEP_RECORDED, 1.0
        self._redraw()

    def go_to(self, step: int, animate: bool = False) -> None:
        """Show ``step``, finished — or, with ``animate``, play its motion."""
        self._stop()
        self._enter(step, animate)

    def play(self) -> None:
        """Run every step from the start, pausing on each."""
        self._stop()
        self._playing = True
        self._enter(STEP_RECORDED, animate=False)
        self._timer.start(_HOLD_MS)

    # ── Stepping ──────────────────────────────────────────────────────

    def _enter(self, step: int, animate: bool) -> None:
        self._step = int(np.clip(step, STEP_RECORDED, _LAST_STEP))
        moves = self._step in (STEP_ROBUST_FIT, STEP_REMOVED)
        self._progress = 0.0 if animate and moves else 1.0
        self._redraw()
        if self._progress < 1.0:
            self._timer.start(_FRAME_MS)

    def _tick(self) -> None:
        if self._progress < 1.0:
            self._progress = min(1.0, self._progress + 1.0 / _FRAMES_PER_STEP)
            self._redraw()
            if self._progress >= 1.0 and self._playing:
                self._timer.start(_HOLD_MS)  # hold the finished step
            elif self._progress >= 1.0:
                self._timer.stop()
        elif self._playing and self._step < _LAST_STEP:
            self._enter(self._step + 1, animate=True)
            if self._progress >= 1.0:
                self._timer.start(_HOLD_MS)
        else:
            self._stop()

    def _stop(self) -> None:
        self._timer.stop()
        self._playing = False

    # ── Drawing ───────────────────────────────────────────────────────

    def _redraw(self) -> None:
        fit = self._fit
        self._ax.clear()
        self._ax.set_facecolor(_PLOT_BG)
        for button in (self._btn_back, self._btn_next, self._btn_play):
            button.setEnabled(fit is not None)
        if fit is None:
            self._ax.set_axis_off()
            self._caption.setText("")
            self._step_label.setText("")
            self.canvas.draw_idle()
            return
        self._btn_back.setEnabled(self._step > STEP_RECORDED)
        self._btn_next.setEnabled(self._step < _LAST_STEP)

        removed = self._progress if self._step == STEP_REMOVED else 0.0
        y = fit.y - removed * fit.slope * fit.x
        show_weights = self._step >= STEP_ROBUST_FIT
        colors = np.where(fit.ignored & show_weights, _IGNORED_COLOR, _EVENT_COLOR)
        self._ax.scatter(fit.x, y, s=4, c=colors, alpha=0.5, linewidths=0, rasterized=True)

        x_max = float(np.percentile(fit.x, _VIEW_PERCENTILE))
        line_x = np.array([0.0, x_max])
        if self._step == STEP_PLAIN_FIT or (self._step == STEP_ROBUST_FIT and self._progress < 1):
            self._ax.plot(
                line_x,
                fit.plain_slope * line_x,
                color=_PLAIN_COLOR,
                lw=2,
                ls="--",
                label=f"ordinary fit: slope {fit.plain_slope:.3f}",
            )
        if self._step >= STEP_ROBUST_FIT:
            slope = fit.plain_slope + (fit.slope - fit.plain_slope) * (
                self._progress if self._step == STEP_ROBUST_FIT else 1.0
            )
            slope *= 1.0 - removed
            label = (
                f"robust fit: slope {fit.slope:.3f}" if not removed else "after removing the spill"
            )
            self._ax.plot(line_x, slope * line_x, color=_ROBUST_COLOR, lw=2.5, label=label)
        if show_weights and fit.ignored.any():
            self._ax.scatter([], [], s=12, c=_IGNORED_COLOR, label="largely ignored by the fit")

        # One fixed view for every step, so only the data appears to move.
        y_low, y_high = np.percentile(fit.y, [100 - _VIEW_PERCENTILE, _VIEW_PERCENTILE])
        pad = 0.08 * max(y_high - y_low, 1.0)
        self._ax.set_xlim(min(0.0, float(fit.x.min())), x_max)
        self._ax.set_ylim(min(y_low, 0.0) - pad, y_high + pad)
        self._ax.axhline(0.0, color="#BBBBBB", lw=0.8, zorder=0)
        self._ax.set_xlabel(f"{fit.other} detector (the dye that leaks)")
        self._ax.set_ylabel(f"{fit.missing} detector\n(this tube has no {fit.missing} dye)")
        self._ax.set_title(f"{fit.tube}" + (" — made-up data" if fit.example else ""), fontsize=10)
        if self._ax.get_legend_handles_labels()[0]:
            self._ax.legend(fontsize=8, loc="upper left")
        self._style()

        self._caption.setText(self._caption_text(fit))
        self._step_label.setText(f"Step {self._step + 1} of {_LAST_STEP + 1}")
        self.canvas.draw_idle()

    def _style(self) -> None:
        self._ax.tick_params(colors=Colors.FG_PRIMARY, labelsize=8)
        for label in (self._ax.xaxis.label, self._ax.yaxis.label, self._ax.title):
            label.set_color(Colors.FG_PRIMARY)
            label.set_fontsize(9)
        for spine in self._ax.spines.values():
            spine.set_color(Colors.BORDER)

    def _caption_text(self, fit: FitIllustration) -> str:
        missing, other = fit.missing, fit.other
        ignored = float(np.mean(fit.ignored))
        return {
            STEP_RECORDED: (
                f"<b>1 · What the tube recorded.</b> {fit.tube} has no {missing} dye, yet its "
                f"{missing} detector still reads signal, and the reading climbs with {other}. "
                f"That climb is {other}'s light leaking in. (Each dot is one event; the share "
                "of the remaining dyes is already taken out so this one leak can be seen.)"
            ),
            STEP_PLAIN_FIT: (
                "<b>2 · An ordinary fit.</b> A straight line through every event measures the "
                f"climb: slope {fit.plain_slope:.3f}. But a few events are bright in the "
                f"{missing} detector for other reasons (dead cells, aggregates), and they pull "
                "the line towards them."
            ),
            STEP_ROBUST_FIT: (
                "<b>3 · The robust fit.</b> Events far from the line are given little weight "
                f"(grey: {ignored:.1%} of this tube) and the line is refitted until it settles: "
                f"slope {fit.slope:.3f}. That is the share of the {other} detector's signal "
                f"that shows up in {missing}."
            ),
            STEP_REMOVED: (
                f"<b>4 · Remove it.</b> Subtracting {fit.slope:.3f} × {other} from every event "
                "lays the cloud flat: the leak is gone, and what is left is noise around zero. "
                "The same is done for every dye and every tube; solving all of those weights "
                "together gives the spillover matrix, so a matrix cell lands close to this "
                "slope but is not always identical to it."
            ),
        }[self._step]
