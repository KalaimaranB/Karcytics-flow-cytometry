"""Spectral Ribbon - Access spectral viewing and compensation tools."""

from __future__ import annotations

from typing import TYPE_CHECKING

from karcytics_sdk.plugin.ribbon import ThemedToolbarContainer
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout

if TYPE_CHECKING:
    from ...analysis.state import FlowState


class SpectralRibbon(ThemedToolbarContainer):
    """Toolbar ribbon for spectral intelligence tools."""

    open_spectral_viewer_requested = pyqtSignal()

    def __init__(self, state: FlowState, parent=None) -> None:
        super().__init__(parent)
        self._state = state
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(6)

        layout.addStretch()
