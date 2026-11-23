"""Plot widgets with a right-click "Copy Image to Clipboard" menu.

Both pass wheel events up, so a gallery or stats page scrolls while the
pointer is over a plot.
"""

from __future__ import annotations

from collections.abc import Callable

from karcytics_sdk.plugin.components import BioMenu
from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QAction, QPixmap
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from ..graph._mpl_compat import LockedFigureCanvas


def install_copy_menu(widget: QWidget, pixmap: Callable[[], QPixmap]) -> None:
    """Give `widget` a right-click menu that copies `pixmap()` to the clipboard."""

    def show_menu(pos: QPoint) -> None:
        menu = BioMenu(widget)
        action = QAction("Copy Image to Clipboard", menu)
        action.triggered.connect(lambda: QApplication.clipboard().setPixmap(pixmap()))
        menu.addAction(action)
        menu.exec(widget.mapToGlobal(pos))

    widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    widget.customContextMenuRequested.connect(show_menu)


class CopyableCanvas(LockedFigureCanvas):
    """A live matplotlib canvas; copies what is on screen."""

    def __init__(self, figure) -> None:
        super().__init__(figure)
        install_copy_menu(self, self.grab)

    def wheelEvent(self, event) -> None:
        event.ignore()  # let the enclosing scroll area scroll


class CopyablePixmapLabel(QLabel):
    """A plot rendered off-thread to an image, shown at one fixed size.

    Fixed, not expand-to-fill: three expanding variants each broke differently
    (`setScaledContents` distorted the aspect ratio; `KeepAspectRatio` on resize
    left `QGridLayout` rows at wildly different heights). The source is rendered
    larger than `display_size` and downscaled once here, so it stays sharp; the
    clipboard gets the full-resolution source.
    """

    def __init__(self, pixmap: QPixmap, display_size: QSize, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._original_pixmap = pixmap
        self.setFixedSize(display_size)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setPixmap(
            pixmap.scaled(
                display_size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        install_copy_menu(self, lambda: self._original_pixmap)

    def wheelEvent(self, event) -> None:
        event.ignore()  # let the enclosing scroll area scroll
