"""The deck's guidance: the "Your turn" strip, the Show me button, and the nudge.

The strip sits above the explanation and always says what the current slide
wants next, what went wrong last time, and what Show me suggested. Show me asks
the slide to draw its move on the plot (or the guide outlines the answer area,
when the move is there); after ``NUDGE_MS`` on an unfinished slide the strip
suggests pressing it.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from karcytics_sdk.plugin.components import SecondaryButton
from karcytics_sdk.plugin.theme_fallback import Colors, theme_manager
from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtWidgets import QFrame, QLabel

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from .slide import Slide

NUDGE_MS = 30_000  # this long on an unfinished slide, and the strip suggests Show me
SHOW_ME = "💡 Show me"
HIDE_HELP = "🙈 Hide help"
STRIP_STYLE = (
    "background: {BG_MEDIUM}; color: {FG_PRIMARY}; border: 2px solid {ACCENT_WARNING};"
    " border-radius: 6px; padding: 10px; font-size: 14px;"
)
ANSWER_AREA_STYLE = (
    "QFrame#LearningAnswerArea {{ border: 2px dashed {colour}; border-radius: 6px; }}"
)


class SlideGuide(QObject):
    """Owns the strip, the Show me button and the nudge; the deck calls ``update`` per render."""

    def __init__(self, on_toggle: Callable[[], None], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._on_toggle = on_toggle  # re-render, so Show me's drawing appears or goes
        self.showing = False  # Show me is on for the current slide
        self.help_text = ""  # what the current slide's Show me said
        self._nudged = False
        self._answer_area: QFrame | None = None
        self._slide: Slide | None = None  # what the strip describes
        self._is_last = False

        self.strip = QLabel()
        self.strip.setObjectName("LearningActionStrip")
        self.strip.setWordWrap(True)
        self.strip.setTextFormat(Qt.TextFormat.RichText)
        theme_manager.apply_style(self.strip, STRIP_STYLE)

        self.button = SecondaryButton(SHOW_ME)
        self.button.setObjectName("LearningShowMeButton")
        self.button.setToolTip("Stuck? Shows on the plot what this step wants you to do.")
        self.button.clicked.connect(self._toggle)

        self.nudge_timer = QTimer(self)
        self.nudge_timer.setSingleShot(True)
        self.nudge_timer.setInterval(NUDGE_MS)
        self.nudge_timer.timeout.connect(self.nudge)

    def frame_answer_area(self, frame: QFrame) -> None:
        """The frame round the readout and answer controls, which Show me can outline."""
        self._answer_area = frame
        frame.setObjectName("LearningAnswerArea")
        self.point_at_answer_area(on=False)

    def point_at_answer_area(self, on: bool = True) -> None:
        if self._answer_area is not None:
            colour = "{ACCENT_WARNING}" if on else "transparent"
            theme_manager.apply_style(self._answer_area, ANSWER_AREA_STYLE.format(colour=colour))

    def reset(self) -> None:
        """A new slide: Show me off, the nudge's countdown starting over."""
        self.showing = False
        self._nudged = False
        self.nudge_timer.stop()

    def draw_help(self, slide: Slide, ax: Axes) -> None:
        """After the slide rendered: let Show me draw on ``ax`` while it's on."""
        if slide.done:
            self.showing = False
        self.help_text = slide.show_me(ax) if self.showing else ""

    def update(self, slide: Slide | None, is_last: bool) -> None:
        """The button, the nudge countdown and the strip, for ``slide`` (None: waiting)."""
        available = slide is not None and not slide.done
        if slide is None:
            self.help_text = ""
        self.button.setEnabled(available)
        self.button.setText(HIDE_HELP if self.showing else SHOW_ME)
        if not available or self.showing:
            self.nudge_timer.stop()
            self._nudged = False
        elif not self._nudged and not self.nudge_timer.isActive():
            self.nudge_timer.start()
        self._slide, self._is_last = slide, is_last
        self._show_strip()

    def nudge(self) -> None:
        self._nudged = True
        self._show_strip()

    def _toggle(self) -> None:
        self.showing = not self.showing
        self._on_toggle()

    def _show_strip(self) -> None:
        slide = self._slide
        if slide is None:
            self.strip.setText("👉 Add at least two fluorophores to begin.")
        elif slide.done:
            self.strip.setText(
                "✅ <b>Deck complete.</b> Cyto will take it from here."
                if self._is_last
                else "✅ <b>Done!</b> Click <b>Next Step →</b> (top right)."
            )
        else:
            self.strip.setText("<br><br>".join(self._pending_lines(slide)))

    def _pending_lines(self, slide: Slide) -> list[str]:
        lines = [f"👉 <b>Your turn:</b> {slide.instruction()}"]
        if slide.wrong_hint:
            lines.append(
                f"<span style='color: {Colors.ACCENT_DANGER};'>✗ {slide.wrong_hint}</span>"
            )
        if self.help_text:
            lines.append(
                f"<span style='color: {Colors.ACCENT_WARNING};'>💡 {self.help_text}</span>"
            )
        elif self._nudged:
            lines.append(
                f"<span style='color: {Colors.FG_SECONDARY};'>Stuck? Press <b>{SHOW_ME}</b>"
                " at the top.</span>"
            )
        return lines
