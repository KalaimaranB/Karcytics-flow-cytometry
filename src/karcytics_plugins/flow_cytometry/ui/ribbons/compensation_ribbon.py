"""Compensation ribbon — empty; the Compensation tab's tools live in its view.

Kept so the ribbon stack stays index-aligned with the tab bar (see
``ui/widgets/compensation_view.py`` for the actual tools).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from karcytics_sdk.plugin.ribbon import ThemedToolbarContainer
from PyQt6.QtWidgets import QHBoxLayout

if TYPE_CHECKING:
    from ...analysis.state import FlowState


class CompensationRibbon(ThemedToolbarContainer):
    """Placeholder ribbon for the Compensation tab (hidden while it is active)."""

    def __init__(self, state: FlowState, parent=None) -> None:
        super().__init__(parent)
        self._state = state
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.addStretch()
