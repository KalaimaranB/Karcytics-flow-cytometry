"""Auto Gating tab — see ``auto_gating_tab.py`` and ``analysis/autogate``.

Imported only from the workspace builder's deferred Phase 2 step: the engine
pulls in the clustering package (numba), which must stay out of Phase 1.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ....analysis.autogate import DemoEngine
from .auto_gating_tab import AutoGatingTab

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

    from ....analysis.state import FlowState


def create_auto_gating_tab(state: FlowState, parent: QWidget | None = None) -> AutoGatingTab:
    """The tab with its engine: the one place that picks which engine runs.

    Example output (``DemoEngine``) until the analysis exists; swapping the
    engine here changes no widget.
    """
    return AutoGatingTab(state, DemoEngine(), parent=parent)


__all__ = ["AutoGatingTab", "create_auto_gating_tab"]
