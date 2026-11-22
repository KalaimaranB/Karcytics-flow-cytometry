"""A gating plot's right-click menu: copy it as an image, or save it as PNG, PDF or SVG."""

from __future__ import annotations

import io
from collections.abc import Callable, Sequence
from datetime import datetime
from functools import partial
from typing import Any

from karcytics_sdk.plugin import get_logger
from karcytics_sdk.plugin.components import BioMenu
from karcytics_sdk.plugin.dialogs import get_save_path
from karcytics_sdk.plugin.rendering.lock import MPL_RASTER_LOCK
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QWidget

logger = get_logger(__name__, "flow_cytometry")

FORMATS = {"png": 150, "pdf": 300, "svg": 150}  # file format -> dpi
_CLIPBOARD_DPI = 96


def install_plot_menu(
    canvas: QWidget, figure: Any, extra: Sequence[tuple[str, Callable[[], None]]] = ()
) -> None:
    """Right-click on ``canvas`` offers Copy to Clipboard and Download (``figure``).

    ``extra`` (text, callback) entries follow; it is read each time the menu
    opens, so its owner can add to it later.
    """

    def show_menu(pos: QPoint) -> None:
        menu = BioMenu(canvas)
        menu.addAction("📋  Copy to Clipboard (PNG)", lambda: copy_plot(figure))
        menu.addSeparator()
        download = menu.addMenu("💾  Download")
        for fmt in FORMATS:
            download.addAction(fmt.upper(), partial(save_plot, canvas, figure, fmt))
        if extra:
            menu.addSeparator()
            for text, callback in extra:
                menu.addAction(text, callback)
        menu.exec(canvas.mapToGlobal(pos))

    canvas.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    canvas.customContextMenuRequested.connect(show_menu)


def copy_plot(figure: Any) -> None:
    """Put the plot on the clipboard as a PNG image."""
    buffer = io.BytesIO()
    try:
        with MPL_RASTER_LOCK:  # savefig rasterizes through the shared Agg backend
            figure.savefig(buffer, format="png", dpi=_CLIPBOARD_DPI, bbox_inches="tight")
    except Exception:  # noqa: BLE001 - a failed copy is logged, never a crash
        logger.exception("Copying the plot failed")
        return
    image = QImage()
    image.loadFromData(buffer.getvalue())
    QApplication.clipboard().setImage(image)


def save_plot(parent: QWidget, figure: Any, fmt: str, dpi: int | None = None) -> str | None:
    """Ask where, then save the plot as ``fmt``; the path saved to, or None.

    ``dpi`` overrides the format's usual resolution (``FORMATS``).
    """
    default = f"flow_plot_{datetime.now():%Y%m%d_%H%M%S}.{fmt}"
    path = get_save_path(parent, f"Save plot as {fmt.upper()}", default, f"{fmt.upper()} (*.{fmt})")
    if not path:
        return None
    try:
        with MPL_RASTER_LOCK:
            figure.savefig(path, format=fmt, dpi=dpi or FORMATS[fmt], bbox_inches="tight")
    except Exception:  # noqa: BLE001 - a failed save is logged, never a crash
        logger.exception("Saving the plot to %s failed", path)
        return None
    return path
