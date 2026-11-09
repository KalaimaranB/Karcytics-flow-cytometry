"""The one interface the Auto Gating tab depends on.

The tab is built against this protocol only, so the engine behind it can be
swapped without touching any widget: ``DemoEngine`` (example output, while
the analysis is being built) now, the real engine later.
"""

from __future__ import annotations

from typing import Protocol

from .models import GateStory, GroupPreview, MethodOutcome, Proposal, StepRequest


class AutoGateEngine(Protocol):
    is_demo: bool  # True: everything returned is example output

    def propose(self, request: StepRequest) -> Proposal:
        """The next split of ``request.population``."""
        ...

    def preview_group(self, request: StepRequest, adaptive: bool) -> GroupPreview:
        """The proposed gates on every sample of the group (fixed, or moved to fit each)."""
        ...

    def compare(self, request: StepRequest) -> tuple[MethodOutcome, ...]:
        """Every method's strategy from ``request.population``, beside the user's own gates."""
        ...

    def story(self, gate: str, parent: str, request: StepRequest) -> GateStory:
        """Why the auto gate ``gate`` (a population of ``parent``) is where it is."""
        ...
