"""The Learning Compensation deck: seven slides, each needing a real action.

Each slide asks the learner to measure, predict, correct, gate or reason
through a control-design question, rather than click near the right spot. The
deck pages between them (Next unlocks once a slide's task is done), shows the
current one's explanation and plot, and passes the learner's clicks and drags
to it. The Academy reads its progress through ``academy_snapshot``.

``guide.SlideGuide`` adds the "Your turn" strip above the explanation and the
Show me button in the header.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from karcytics_sdk.plugin.components import PrimaryButton, SecondaryButton
from karcytics_sdk.plugin.rendering import AxesColors, style_axes
from karcytics_sdk.plugin.theme_fallback import Colors, theme_manager
from matplotlib.figure import Figure
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QTextBrowser, QVBoxLayout, QWidget

from ...academy_context import LearningDeckSnapshot
from ...graph._mpl_compat import LockedFigureCanvas
from .compensate import CompensateSlide
from .gate import GateSlide
from .guide import SlideGuide
from .matrix import MatrixSlide
from .one_rule import OneRuleSlide
from .physics import PhysicsSlide
from .ruler import RulerSlide
from .scenes import spectral_dyes, teaching_pair
from .slide import AnswerBox, Slide
from .zero import ZeroSlide

if TYPE_CHECKING:
    from PySide6.QtCore import QUrl

    from ..spectral_viewer import SpectralViewer
    from .scenes import TeachingPair

SLIDES: tuple[type[Slide], ...] = (
    PhysicsSlide,
    ZeroSlide,
    RulerSlide,
    OneRuleSlide,
    CompensateSlide,
    GateSlide,
    MatrixSlide,
)
NEXT_LOCKED_TIP = "Finish this slide's task first: see 👉 Your turn, on the left."
WAITING_HTML = (
    "<h3>Need at least 2 dyes</h3><p>Load a few fluorophores in the Analysis tab first —"
    " spillover only exists between at least two dyes.</p>"
)


class SpectralLearningTab(QWidget):
    """The deck: navigation, the current slide's explanation and plot, and its progress."""

    def __init__(self, viewer: SpectralViewer, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._viewer = viewer
        self.slides: list[Slide] = [slide(self) for slide in SLIDES]
        self._current_step = 0
        self._completed_steps: set[int] = set()
        self._pair: TeachingPair | None = None
        self._pair_dyes: tuple[str, ...] | None = None  # the dyes ``_pair`` was found among
        self._ticker = QTimer(self)
        self._ticker.timeout.connect(self._on_tick)
        self.guide = SlideGuide(self.update_view, self)
        self._setup_ui()
        theme_manager.theme_changed.connect(self._on_theme_changed)

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(16)
        root.addLayout(self._build_nav())
        content = QHBoxLayout()
        content.addLayout(self._build_text_column())
        content.addWidget(self._build_plot(), stretch=1)
        root.addLayout(content, stretch=1)

    def _build_nav(self) -> QHBoxLayout:
        """The step's title, Show me, and Previous / Next."""
        header = QHBoxLayout()
        self._step_label = QLabel("Step 1")
        theme_manager.apply_style(
            self._step_label, "color: {FG_PRIMARY}; font-size: 16px; font-weight: bold;"
        )
        header.addWidget(self._step_label)
        header.addStretch()
        header.addWidget(self.guide.button)
        self._btn_prev = SecondaryButton("← Previous")
        self._btn_prev.clicked.connect(lambda: self._go_to(self._current_step - 1))
        header.addWidget(self._btn_prev)
        self._btn_next = PrimaryButton("Next Step →")
        self._btn_next.clicked.connect(lambda: self._go_to(self._current_step + 1))
        header.addWidget(self._btn_next)
        return header

    def _build_text_column(self) -> QVBoxLayout:
        """The "Your turn" strip, the explanation, the readout and a slide's controls."""
        left = QVBoxLayout()
        self.guide.strip.setMinimumWidth(350)
        self.guide.strip.setMaximumWidth(450)
        left.addWidget(self.guide.strip)
        self._explanation = QTextBrowser()
        self._explanation.setMinimumWidth(350)
        self._explanation.setMaximumWidth(450)
        self._explanation.setOpenLinks(False)
        self._explanation.anchorClicked.connect(self._on_link)
        theme_manager.apply_style(
            self._explanation,
            "background: {BG_DARK}; color: {FG_PRIMARY}; border: 1px solid {BORDER};"
            " border-radius: 6px; padding: 12px; font-size: 14px;",
        )
        left.addWidget(self._explanation, stretch=1)
        # The readout and a slide's answer box or button, framed so Show me can point at them.
        answer_area = QFrame()
        answer_layout = QVBoxLayout(answer_area)
        answer_layout.setContentsMargins(4, 4, 4, 4)
        self._readout = QLabel()
        self._readout.setWordWrap(True)
        theme_manager.apply_style(
            self._readout, "color: {FG_PRIMARY}; font-family: monospace; font-size: 13px;"
        )
        answer_layout.addWidget(self._readout)
        self._controls = QVBoxLayout()  # a slide's answer box or button
        self._controls.setContentsMargins(0, 0, 0, 0)
        answer_layout.addLayout(self._controls)
        left.addWidget(answer_area)
        self.guide.frame_answer_area(answer_area)
        return left

    def _build_plot(self) -> QWidget:
        self._figure = Figure(facecolor=Colors.BG_DARK)
        self._canvas = LockedFigureCanvas(self._figure)
        self._ax = self._figure.add_subplot(111)
        self._canvas.mpl_connect("button_press_event", self._on_press)
        self._canvas.mpl_connect("motion_notify_event", self._on_move)
        self._canvas.mpl_connect("button_release_event", self._on_release)
        frame = QWidget()
        frame_layout = QVBoxLayout(frame)
        frame_layout.setContentsMargins(0, 0, 0, 0)
        frame_layout.addWidget(self._canvas)
        theme_manager.apply_style(frame, "border: 1px solid {BORDER}; border-radius: 6px;")
        return frame

    # ── what the Academy and the viewer use ──

    def academy_snapshot(self) -> LearningDeckSnapshot:
        return LearningDeckSnapshot(
            self._current_step, len(self.slides) - 1, frozenset(self._completed_steps)
        )

    def update_view(self) -> None:
        """Render the current slide: its plot, explanation and controls."""
        last = len(self.slides) - 1
        done = self._current_step in self._completed_steps
        self._btn_prev.setEnabled(self._current_step > 0)
        self._btn_next.setEnabled(done and self._current_step < last)
        self._btn_next.setToolTip("" if done else NEXT_LOCKED_TIP)
        self._clear_controls()
        self._figure.set_facecolor(Colors.BG_DARK)
        self._ax.clear()
        style_axes(self._ax, AxesColors.from_theme(), open_frame=True)
        self._pair = self._find_pair()
        if self._pair is None:
            self._show_waiting()
        else:
            slide = self.slides[self._current_step]
            self._step_label.setText(
                f"Step {self._current_step + 1} of {len(self.slides)}: {slide.title}"
            )
            self._explanation.setHtml(slide.render(self._ax))
            self.guide.draw_help(slide, self._ax)
            self._figure.tight_layout(pad=1.0)
        self.guide.update(self._slide(), self._current_step == last)
        self._canvas.draw()

    def showEvent(self, event: Any) -> None:
        super().showEvent(event)
        self.update_view()

    # ── what the slides use ──

    @property
    def fluors(self) -> dict[str, dict[str, Any]]:
        return self._viewer.active_fluors

    @property
    def pair(self) -> TeachingPair:
        if self._pair is None:
            raise RuntimeError("No teaching pair: fewer than two dyes with spectra are loaded")
        return self._pair

    def is_done(self, slide: Slide) -> bool:
        return self.slides.index(slide) in self._completed_steps

    def complete(self, slide: Slide) -> None:
        """Mark ``slide``'s task done (Next then lets the learner move on)."""
        self._completed_steps.add(self.slides.index(slide))

    def refresh(self) -> None:
        """Render the current slide again: plot, explanation and controls."""
        self.update_view()

    def redraw(self) -> None:
        """Repaint the plot after a slide moved its own artists (a drag, a tick)."""
        self._canvas.draw_idle()

    def ask(self, placeholder: str, on_submit: Callable[[AnswerBox], None]) -> AnswerBox:
        box = AnswerBox(placeholder)
        box.submitted.connect(lambda: on_submit(box))
        self._controls.addWidget(box)
        return box

    def add_button(self, text: str, on_click: Callable[[], None]) -> None:
        button = PrimaryButton(text)
        button.clicked.connect(on_click)
        self._controls.addWidget(button)

    def set_readout(self, text: str) -> None:
        self._readout.setText(text)

    def start_ticks(self, interval_ms: int) -> None:
        """Call the current slide's ``on_tick`` every ``interval_ms`` until ``stop_ticks``."""
        self._ticker.start(interval_ms)

    def stop_ticks(self) -> None:
        self._ticker.stop()

    # ── internals ──

    def _go_to(self, step: int) -> None:
        if not 0 <= step < len(self.slides) or step == self._current_step:
            return
        self._ticker.stop()
        self.guide.reset()
        self.slides[self._current_step].leave()
        self._current_step = step
        self.update_view()

    def _find_pair(self) -> TeachingPair | None:
        """The teaching pair, found again only when the loaded dyes change."""
        dyes = tuple(spectral_dyes(self.fluors))
        if dyes != self._pair_dyes:
            self._pair_dyes = dyes
            self._pair = teaching_pair(self.fluors)
        return self._pair

    def _show_waiting(self) -> None:
        self._step_label.setText("Waiting for Selection...")
        self._explanation.setHtml(WAITING_HTML)
        self._ax.text(
            0.5,
            0.5,
            "Add fluorophores to begin",
            ha="center",
            va="center",
            color=Colors.FG_DISABLED,
            transform=self._ax.transAxes,
            fontsize=12,
        )
        self._ax.set_xlim(0, 1)
        self._ax.set_ylim(0, 1)

    def _clear_controls(self) -> None:
        self.guide.point_at_answer_area(on=False)
        self._readout.setText("")
        while (item := self._controls.takeAt(0)) is not None:
            if (widget := item.widget()) is not None:
                # Later, not now: this may run inside that very widget's click.
                widget.hide()
                widget.deleteLater()

    def _slide(self) -> Slide | None:
        """The current slide, while it is showing (not the waiting message)."""
        return self.slides[self._current_step] if self._pair is not None else None

    def _on_link(self, url: QUrl) -> None:
        if (slide := self._slide()) is not None:
            slide.on_link(url.toString())

    def _on_press(self, event: Any) -> None:
        if event.inaxes is self._ax and (slide := self._slide()) is not None:
            slide.on_press(event.xdata, event.ydata)

    def _on_move(self, event: Any) -> None:
        if event.inaxes is self._ax and (slide := self._slide()) is not None:
            slide.on_drag(event.xdata, event.ydata)

    def _on_release(self, _event: Any) -> None:
        if (slide := self._slide()) is not None:
            slide.on_release()

    def _on_tick(self) -> None:
        if (slide := self._slide()) is not None:
            slide.on_tick()
        else:
            self._ticker.stop()

    def _on_theme_changed(self) -> None:
        if self.isVisible():
            self.update_view()
