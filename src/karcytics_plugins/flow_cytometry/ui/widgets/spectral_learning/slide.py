"""What a Learning Compensation slide is, and the pieces several slides share.

A slide renders its plot and returns the explanation panel's HTML, then reacts
to the learner: a link in the panel, a press, drag or release on the plot, an
answer typed into an ``AnswerBox``. It keeps its own task's state; whether its
task is done lives on the deck, which the Academy reads.

What to do next is not part of that HTML: ``instruction`` says it and
``wrong_hint`` says what went wrong, and the deck pins both above the
explanation, where they stay in view however long the text is. ``show_me``
draws the answer's shape on the plot (a target zone, a ghost line) when the
learner presses Show me.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from karcytics_sdk.plugin.components import BioLineEdit, PrimaryButton
from karcytics_sdk.plugin.theme_fallback import Colors, theme_manager
from matplotlib import patches
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from .deck import SpectralLearningTab

SCATTER_RANGE = (0, 1000)  # both detectors' range on the simulated-cell slides


class Slide:
    """One step of the deck. Subclasses implement ``render`` and the hooks they need."""

    title: ClassVar[str] = ""

    def __init__(self, deck: SpectralLearningTab) -> None:
        self.deck = deck
        self.wrong_hint: str | None = None  # what went wrong on the last attempt

    @property
    def done(self) -> bool:
        return self.deck.is_done(self)

    def finish(self) -> None:
        """The task is done: say so and show the slide's closing state."""
        self.deck.complete(self)
        self.deck.refresh()

    def render(self, ax: Axes) -> str:
        """Draw the slide's plot on ``ax`` (cleared and styled) and return its HTML."""
        raise NotImplementedError

    def instruction(self) -> str:
        """What the learner has to do next (asked only while the task isn't done)."""
        raise NotImplementedError

    def show_me(self, ax: Axes) -> str:
        """Draw the answer's shape on the freshly rendered ``ax``; return what to do with it."""
        raise NotImplementedError

    def on_link(self, link: str) -> None:
        """A link in the explanation panel was clicked (multiple-choice answers)."""

    def on_press(self, x: float, y: float) -> None:
        """A mouse press on the plot, in data coordinates."""

    def on_drag(self, x: float, y: float) -> None:
        """The mouse moved over the plot (pressed or not)."""

    def on_release(self) -> None:
        """The mouse was released, on the plot or off it."""

    def on_tick(self) -> None:
        """A tick of an animation the slide started with ``deck.start_ticks``."""

    def leave(self) -> None:
        """The learner moved to another slide."""


class AnswerBox(QWidget):
    """A typed answer with Submit (or Enter), and room under it for feedback."""

    submitted = Signal()

    def __init__(self, placeholder: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.input = BioLineEdit()
        self.input.setPlaceholderText(placeholder)
        self.input.returnPressed.connect(self.submitted)
        submit = PrimaryButton("Submit")
        submit.clicked.connect(self.submitted)
        # Wrapped, and under the input rather than beside it: a long message in
        # the row widened the left panel until the plot was squeezed to a sliver.
        self.error = QLabel()
        self.error.setWordWrap(True)
        theme_manager.apply_style(self.error, "color: {ACCENT_DANGER};")
        self.error.hide()

        row = QHBoxLayout()
        row.addWidget(self.input)
        row.addWidget(submit)
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.addLayout(row)
        column.addWidget(self.error)

    def number(self, example: str) -> float | None:
        """The answer as a number (a trailing % is fine); None, and says so, if it isn't one."""
        try:
            return float(self.input.text().strip().rstrip("%"))
        except ValueError:
            self.show_error(f"Enter a number, e.g. {example}")
            return None

    def whole_number(self) -> int | None:
        try:
            return int(self.input.text().strip())
        except ValueError:
            self.show_error("Enter a whole number.")
            return None

    def show_error(self, message: str) -> None:
        self.error.setText(message)
        self.error.show()


# ── The explanation panel's HTML (colours read at render time, so they follow the theme) ──


def heading(text: str) -> str:
    return f"<h3 style='color: {Colors.BORDER_FOCUS};'>{text}</h3>"


def verdict(text: str) -> str:
    """The verdict on a step the learner got right."""
    return f"<p style='color: {Colors.ACCENT_SUCCESS}; font-weight: bold;'>{text}</p>"


def page(title: str, body: str, *verdicts: str | None) -> str:
    """A slide's explanation: its heading, body, then each verdict earned so far (None: not yet)."""
    return heading(title) + body + "".join(verdict(text) for text in verdicts if text)


def choices(options: list[tuple[str, str]]) -> str:
    """Multiple-choice answers as links; the slide's ``on_link`` receives the href."""
    links = "<br>".join(
        f"<a href='{href}' style='color: {Colors.BORDER_FOCUS};'>{text}</a>"
        for href, text in options
    )
    return f"<p>{links}</p>"


# ── Plot pieces shared by several slides ──


def label_axes(ax: Axes, title: str, x_label: str, y_label: str) -> None:
    ax.set_title(title, color=Colors.FG_PRIMARY, pad=15)
    ax.set_xlabel(x_label, color=Colors.FG_SECONDARY, fontsize=10)
    ax.set_ylabel(y_label, color=Colors.FG_SECONDARY, fontsize=10)


def scatter_frame(ax: Axes, threshold: float | None = None) -> None:
    """The detectors' range, with dashed positivity thresholds when given."""
    if threshold is not None:
        ax.axhline(threshold, color=Colors.BORDER, ls="--")
        ax.axvline(threshold, color=Colors.BORDER, ls="--")
    ax.set_xlim(*SCATTER_RANGE)
    ax.set_ylim(*SCATTER_RANGE)


def ghost_rect(ax: Axes, x0: float, y0: float, x1: float, y1: float, label: str) -> None:
    """A dashed target zone with its label: where Show me says to aim."""
    ax.add_patch(
        patches.Rectangle(
            (x0, y0),
            x1 - x0,
            y1 - y0,
            facecolor=Colors.ACCENT_WARNING,
            edgecolor=Colors.ACCENT_WARNING,
            alpha=0.18,
            lw=2,
            ls="--",
            zorder=6,
        )
    )
    ghost_label(ax, (x0 + x1) / 2, y1, label, va="bottom")


def ghost_line(ax: Axes, xs: list[float], ys: list[float]) -> None:
    """A dashed path for Show me: a line to trace or a drag to make."""
    ax.plot(xs, ys, color=Colors.ACCENT_WARNING, lw=2.5, ls="--", marker="o", ms=9, zorder=6)


def ghost_arrow(ax: Axes, start: tuple[float, float], end: tuple[float, float]) -> None:
    """Show me's drag: from where a handle is to where it should go."""
    ax.annotate(
        "",
        xy=end,
        xytext=start,
        arrowprops={"arrowstyle": "->", "color": Colors.ACCENT_WARNING, "lw": 2.5, "ls": "--"},
        zorder=6,
    )


def ghost_label(ax: Axes, x: float, y: float, text: str, va: str = "center") -> None:
    ax.text(
        x,
        y,
        text,
        ha="center",
        va=va,
        color=Colors.ACCENT_WARNING,
        fontsize=9,
        fontweight="bold",
        zorder=7,
    )


def legend(ax: Axes, **kwargs: Any) -> None:
    ax.legend(
        facecolor=Colors.BG_DARKEST,
        edgecolor=Colors.BORDER,
        labelcolor=Colors.FG_PRIMARY,
        fontsize=8,
        **kwargs,
    )
