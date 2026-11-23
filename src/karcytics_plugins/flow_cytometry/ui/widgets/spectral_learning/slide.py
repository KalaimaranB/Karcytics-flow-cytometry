"""What a Learning Compensation slide is, what the deck gives it, and its shared pieces.

A slide renders its plot and returns the explanation panel's HTML, then reacts
to the learner: a link in the panel, a press, drag or release on the plot, an
answer typed into an ``AnswerBox``. It keeps its own task's state; whether its
task is done lives on the deck, which the Academy reads.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, ClassVar, Protocol

from karcytics_sdk.plugin.components import BioLineEdit, PrimaryButton
from karcytics_sdk.plugin.theme_fallback import Colors, theme_manager
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from .scenes import TeachingPair

SCATTER_RANGE = (0, 1000)  # both detectors' range on the simulated-cell slides


class DeckHost(Protocol):
    """The deck, as its slides see it."""

    @property
    def fluors(self) -> dict[str, dict[str, Any]]: ...

    @property
    def pair(self) -> TeachingPair: ...

    def is_done(self, slide: Slide) -> bool: ...

    def complete(self, slide: Slide) -> None:
        """Mark ``slide``'s task done (the deck then lets the learner move on)."""

    def refresh(self) -> None:
        """Render the current slide again: plot, explanation and controls."""

    def redraw(self) -> None:
        """Repaint the plot after a slide moved its own artists (a drag)."""

    def ask(self, placeholder: str, on_submit: Callable[[AnswerBox], None]) -> AnswerBox: ...

    def add_button(self, text: str, on_click: Callable[[], None]) -> None: ...

    def set_readout(self, text: str) -> None: ...

    def start_ticks(self, interval_ms: int) -> None:
        """Call the current slide's ``on_tick`` every ``interval_ms`` until ``stop_ticks``."""

    def stop_ticks(self) -> None: ...


class Slide:
    """One step of the deck. Subclasses implement ``render`` and the hooks they need."""

    title: ClassVar[str] = ""

    def __init__(self, deck: DeckHost) -> None:
        self.deck = deck

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


def task(text: str) -> str:
    """What the learner has to do next, or the verdict on what they did."""
    return f"<p style='color: {Colors.ACCENT_SUCCESS}; font-weight: bold;'>{text}</p>"


def hint(text: str | None) -> str:
    """Feedback on a wrong attempt (nothing when there is none)."""
    return f"<p style='color: {Colors.ACCENT_DANGER};'>{text}</p>" if text else ""


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


def legend(ax: Axes, **kwargs: Any) -> None:
    ax.legend(
        facecolor=Colors.BG_DARKEST,
        edgecolor=Colors.BORDER,
        labelcolor=Colors.FG_PRIMARY,
        fontsize=8,
        **kwargs,
    )
