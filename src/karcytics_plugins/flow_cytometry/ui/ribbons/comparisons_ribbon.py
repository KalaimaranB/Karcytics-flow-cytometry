"""Comparisons ribbon — empty placeholder (controls live inside ComparisonsViewer)."""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QWidget


class ComparisonsRibbon(QWidget):
    """Placeholder ribbon for the Comparisons tab.

    All controls are in the ComparisonsViewer left sidebar, so this ribbon
    intentionally shows nothing — it just satisfies the ribbon stack index alignment.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.setFixedHeight(0)
