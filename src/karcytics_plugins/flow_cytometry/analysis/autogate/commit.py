"""Accepting a proposal: its populations become ordinary gates in the tree.

Gates go in through the gate coordinator, exactly like gates drawn by hand,
so they are undoable, propagate to the group and appear everywhere. Combined
axes (principal components) are created first as derived parameters, reusing
one that already has the same formula.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from ..derived.models import DerivedParameterDraft
from ..services.derived_parameter_service import DerivedParameterError
from ..transforms import TransformType

if TYPE_CHECKING:
    from ..gate_coordinator import GateCoordinator
    from ..services.derived_parameter_service import DerivedParameterService
    from .models import PendingAxis, Proposal
    from .template_runner import TemplatePlan


class ProposalCommitter:
    def __init__(self, coordinator: GateCoordinator, derived: DerivedParameterService) -> None:
        self._coordinator = coordinator
        self._derived = derived

    def accept(self, proposal: Proposal) -> list[str]:
        """Add the proposal's main populations under its parent; returns the new nodes' ids."""
        param_ids = {axis.key: self._axis_parameter(axis) for axis in proposal.pending_axes}
        added = []
        for region in proposal.gated:
            gate = region.gate
            assert gate is not None  # gated regions have one
            gate.x_param = param_ids.get(gate.x_param, gate.x_param)
            if gate.y_param is not None:
                gate.y_param = param_ids.get(gate.y_param, gate.y_param)
            gate.provenance = {
                **proposal.provenance,
                "population": region.name,
                "share": round(region.fraction, 4),
            }
            node_id = self._coordinator.add_gate(
                gate, proposal.sample_id, name=region.name, parent_node_id=proposal.parent_id
            )
            if node_id is not None:
                added.append(node_id)
        return added

    def accept_plan(self, plan: TemplatePlan) -> dict[str, str]:
        """Add every population a template run found, parents first.

        Each goes under the gate just made for its parent step, or, where that
        step wasn't drawn (no forward-scatter height for Singlets, say), under
        the nearest one that was. Returns step id → new node id.
        """
        steps = {s.step_id: s for s in plan.template.steps}
        created: dict[str, str] = {}
        for outcome in plan.found:
            assert outcome.proposal is not None  # found
            parent_step, parent_id = outcome.step.parent_id, plan.start_id
            while parent_step is not None:
                if parent_step in created:
                    parent_id = created[parent_step]
                    break
                parent_step = steps[parent_step].parent_id
            added = self.accept(replace(outcome.proposal, parent_id=parent_id))
            if added:
                created[outcome.step.step_id] = added[0]
        return created

    def _axis_parameter(self, axis: PendingAxis) -> str:
        """The derived parameter for ``axis``: one with the same formula, or a new one."""
        formula = self._derived.canonicalize(axis.formula)
        for existing in self._derived.definitions:
            if existing.formula == formula:
                return existing.param_id
        name, n = axis.name, 1
        while True:
            try:
                self._derived.validate_name(name)
                break
            except DerivedParameterError:
                n += 1
                name = f"{axis.name} ({n})"
        draft = DerivedParameterDraft(
            name, axis.formula, TransformType.LINEAR.value, positive_denominators=False
        )
        return self._derived.create(draft).param_id
