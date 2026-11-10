"""Auto Gating tab — see ``auto_gating_tab.py`` and ``analysis/autogate``.

Imported only from the workspace builder's deferred Phase 2 step: the engine
pulls in the clustering package (numba), which must stay out of Phase 1.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ....analysis.autogate import GatingEngine, ProposalCommitter
from .auto_gating_tab import AutoGatingTab

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

    from ....analysis.state import FlowState
    from ...composition_root import FlowServices


def create_auto_gating_tab(
    state: FlowState, services: FlowServices, parent: QWidget | None = None
) -> AutoGatingTab:
    """The tab with its engine and committer: the one place that picks them."""
    engine = GatingEngine(state, services.axis_manager)
    committer = ProposalCommitter(services.gate_coordinator, services.derived_parameter_service)
    return AutoGatingTab(state, engine, committer, parent=parent)


__all__ = ["AutoGatingTab", "create_auto_gating_tab"]
