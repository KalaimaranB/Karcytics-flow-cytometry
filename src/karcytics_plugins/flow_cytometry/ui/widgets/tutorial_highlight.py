"""Academy spotlight drawn inside a separate window (e.g. a non-modal dialog).

The Academy overlay lives in the main window and can't paint over another
window, so a target inside a dialog would be highlighted on the main window
underneath it instead. A window that hosts tutorial targets owns one of
these and refreshes it from the driver's duck-typed
``get_tutorial_target_rects(step)`` hook, which runs every driver tick.
"""

from __future__ import annotations

from karcytics_sdk.plugin.theme_fallback import theme_manager
from PyQt6.QtCore import QPoint, QRect, Qt, QTimer
from PyQt6.QtWidgets import QFrame, QWidget

# Step metadata key listing objectNames to spotlight inside the window.
IN_WINDOW_TARGETS_KEY = "in_window_targets"

# The driver ticks every 100 ms; once it stops asking (step changed, Academy
# closed) the frames disappear on their own.
_EXPIRE_MS = 400
_PAD = 3


class TutorialHighlight:
    """Accent frames over named descendants of ``host``."""

    def __init__(self, host: QWidget) -> None:
        self._host = host
        self._frames: list[QFrame] = []
        self._expiry = QTimer(host)
        self._expiry.setSingleShot(True)
        self._expiry.timeout.connect(self.clear)

    def rects_for_step(self, step: object) -> list[QRect]:
        """Driver hook body: frame the step's in-window targets.

        Returns the host window's global frame, so the main overlay keeps
        Cyto and the text bubble clear of the window.
        """
        names = (getattr(step, "metadata", None) or {}).get(IN_WINDOW_TARGETS_KEY)
        if not names or not self._host.isVisible():
            self.clear()
            return []
        widgets = [
            w for name in names for w in self._host.findChildren(QWidget, name) if w.isVisible()
        ]
        self._show_on(widgets)
        return [self._host.frameGeometry()]

    @property
    def visible_count(self) -> int:
        return sum(1 for f in self._frames if f.isVisible())

    def clear(self) -> None:
        for frame in self._frames:
            frame.hide()

    def _show_on(self, widgets: list[QWidget]) -> None:
        while len(self._frames) < len(widgets):
            self._frames.append(self._new_frame())
        for frame, widget in zip(self._frames, widgets, strict=False):
            top_left = widget.mapTo(self._host, QPoint(0, 0))
            frame.setGeometry(QRect(top_left, widget.size()).adjusted(-_PAD, -_PAD, _PAD, _PAD))
            frame.show()
            frame.raise_()
        for frame in self._frames[len(widgets) :]:
            frame.hide()
        self._expiry.start(_EXPIRE_MS)

    def _new_frame(self) -> QFrame:
        frame = QFrame(self._host)
        frame.setObjectName("TutorialHighlightFrame")
        frame.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        theme_manager.apply_style(
            frame,
            "QFrame#TutorialHighlightFrame {"
            "  border: 2px solid {ACCENT_PRIMARY};"
            "  border-radius: 6px;"
            "  background: transparent;"
            "}",
        )
        return frame
