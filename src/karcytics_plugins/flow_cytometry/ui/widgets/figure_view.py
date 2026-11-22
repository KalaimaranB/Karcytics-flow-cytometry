"""A matplotlib figure drawn off the GUI thread, shown when it lands.

``draw(renderer, kwargs)`` renders it on a background thread (`FigureRenderWorker`)
and swaps the result in. One render runs at a time: requests made meanwhile
collapse into the newest, and a message shown meanwhile wins over the
render still in flight, so the view always ends on what was asked for last.
"""

from __future__ import annotations

from typing import Any

from karcytics_sdk.plugin import get_logger
from karcytics_sdk.plugin.theme_fallback import theme_manager
from matplotlib.figure import Figure
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ..graph.figure_renderer import FigureRenderWorker, IPlotRenderer
from .copyable import CopyableCanvas

logger = get_logger(__name__, "flow_cytometry")


class _Workers:
    """The in-flight worker, outside the widget so teardown can still reach it."""

    current: FigureRenderWorker | None = None

    def stop(self, *_args: Any) -> None:
        if self.current is not None:
            self.current.stop_and_wait()  # Qt aborts if a running QThread dies with its parent


class FigureView(QWidget):
    """Shows the newest figure an `IPlotRenderer` drew for it, or a message.

    ``natural_size``: show each figure at least at its own size (for a view in
    a scroll area, where a big heatmap should scroll rather than squash).
    """

    figure_shown = Signal(object)  # the Figure, now on screen
    render_failed = Signal(str)

    def __init__(self, parent: QWidget | None = None, natural_size: bool = False) -> None:
        super().__init__(parent)
        self._natural_size = natural_size
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._message = QLabel()
        self._message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._message.setWordWrap(True)
        theme_manager.apply_style(self._message, "color: {FG_SECONDARY}; font-size: 11px;")
        self._layout.addWidget(self._message)
        self._canvas: CopyableCanvas | None = None
        self._workers = _Workers()
        self.destroyed.connect(self._workers.stop)
        self._pending: tuple[IPlotRenderer, dict] | None = None
        self._wanted = 0  # bumped by every draw / show_message
        self._running = 0  # which request the in-flight worker draws

    @property
    def figure(self) -> Figure | None:
        """The figure on screen (None while a message shows)."""
        return self._canvas.figure if self._canvas is not None else None

    @property
    def canvas(self) -> CopyableCanvas | None:
        return self._canvas

    def is_rendering(self) -> bool:
        return self._workers.current is not None

    def draw(self, renderer: IPlotRenderer, kwargs: dict) -> None:
        """Render ``renderer(**kwargs)`` in the background and show it."""
        self._wanted += 1
        self._pending = (renderer, kwargs)
        if self._workers.current is None:
            self._start_pending()

    def show_message(self, text: str) -> None:
        """Show ``text`` instead of a figure (a render in flight is dropped when it lands)."""
        self._wanted += 1
        self._pending = None
        self._replace_canvas(None)
        self._message.setText(text)
        self._message.show()

    def _start_pending(self) -> None:
        assert self._pending is not None
        renderer, kwargs = self._pending
        self._pending = None
        self._running = self._wanted
        worker = FigureRenderWorker(renderer, kwargs, self)
        worker.finished_ok.connect(self._on_rendered)
        worker.finished_err.connect(self._on_failed)
        worker.finished.connect(worker.deleteLater)  # QThread.finished: run() has returned
        self._workers.current = worker
        worker.start()

    def _on_rendered(self, figure: Figure) -> None:
        if self._finish() and self._running == self._wanted:
            self._message.hide()
            canvas = CopyableCanvas(figure)
            if self._natural_size:
                dpi = figure.dpi
                canvas.setMinimumSize(
                    int(figure.get_figwidth() * dpi), int(figure.get_figheight() * dpi)
                )
            self._replace_canvas(canvas)
            if self._natural_size:
                # Added at its final size, it may never get a resize event, and
                # an idle draw that came before layout is dropped for good.
                canvas.draw()
            self.figure_shown.emit(figure)

    def _on_failed(self, message: str) -> None:
        if self._finish() and self._running == self._wanted:
            logger.error("A figure could not be drawn: %s", message)
            self.render_failed.emit(message)

    def _finish(self) -> bool:
        """The worker is done; start the next request if one waits. False: superseded."""
        self._workers.current = None
        if self._pending is not None:
            self._start_pending()
            return False
        return True

    def _replace_canvas(self, canvas: CopyableCanvas | None) -> None:
        if self._canvas is not None:
            self._layout.removeWidget(self._canvas)
            self._canvas.deleteLater()
        self._canvas = canvas
        if canvas is not None:
            self._layout.addWidget(canvas)
