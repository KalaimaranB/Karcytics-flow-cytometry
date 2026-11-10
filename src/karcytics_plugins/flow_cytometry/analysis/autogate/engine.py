"""The one interface the Auto Gating tab depends on.

The tab is built against this protocol only, so the engine behind it can be
swapped (or faked in a test) without touching any widget.
"""

from __future__ import annotations

from typing import Protocol

from .models import GateStory, GroupPreview, MethodOutcome, Proposal, StepRequest


class AutoGateEngine(Protocol):
    def propose(self, request: StepRequest) -> Proposal | str:
        """The next split of the population, or why there isn't one."""
        ...

    def preview_group(self, proposal: Proposal, request: StepRequest) -> GroupPreview:
        """The proposal's gates on every sample of the group."""
        ...

    def compare(self, request: StepRequest) -> tuple[MethodOutcome, ...]:
        """Every method's split of the population, beside the user's own gates."""
        ...

    def story(self, sample_id: str, node_id: str) -> GateStory | None:
        """Why the auto gate ``node_id`` is where it is; None for a gate drawn by hand."""
        ...
