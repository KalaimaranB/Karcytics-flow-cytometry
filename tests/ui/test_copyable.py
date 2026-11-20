"""The plot widgets' right-click "Copy Image to Clipboard" menu."""

from __future__ import annotations

import pytest
from karcytics_sdk.plugin.components import BioMenu
from PySide6.QtCore import QPoint, QSize
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

from karcytics_plugins.flow_cytometry.ui.widgets.copyable import CopyablePixmapLabel


@pytest.mark.ui
def test_copy_puts_the_full_resolution_source_on_the_clipboard(qtbot, monkeypatch):
    """The tile shows a downscaled image; pasting elsewhere must keep full quality."""

    def choose_first_action(menu, *_args):
        menu.actions()[0].trigger()

    monkeypatch.setattr(BioMenu, "exec", choose_first_action)
    source = QPixmap(934, 746)
    source.fill()
    label = CopyablePixmapLabel(source, QSize(467, 373))
    qtbot.addWidget(label)

    label.customContextMenuRequested.emit(QPoint(10, 10))

    copied = QApplication.clipboard().pixmap()
    assert (copied.width(), copied.height()) == (934, 746)
