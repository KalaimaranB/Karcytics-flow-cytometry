"""Which samples a gate change spreads to, and the port `GateCoordinator` spreads it through.

The debounced, scheduled spreading itself is `ui/services/gate_propagator.py`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from .experiment import Sample
    from .state import FlowState


class Propagation(Protocol):
    def request_propagation(self, gate_id: str, source_sample_id: str) -> None: ...

    def request_cross_group_propagation(self, gate_id: str, source_sample_id: str) -> None: ...

    def cleanup(self) -> None: ...


def propagation_targets(
    state: FlowState, source_id: str, *, cross_group: bool = False
) -> list[Sample]:
    """The loaded samples a change on `source_id` spreads to.

    Its own groups when `cross_group`; otherwise the active group filter, if the
    source is in it, or every sample.
    """
    experiment = state.data.experiment
    source = experiment.samples.get(source_id)
    if source is None:
        return []

    target_ids: set[str] = set()
    active_group_id = getattr(state.view, "active_group_filter", "__all__")
    if cross_group:
        for group_id in source.group_ids:
            group = experiment.groups.get(group_id)
            if group:
                target_ids.update(group.sample_ids)
    elif active_group_id != "__all__":
        group = experiment.groups.get(active_group_id)
        if group and source_id in group.sample_ids:
            target_ids.update(group.sample_ids)
    else:
        target_ids = set(experiment.samples)
    target_ids.discard(source_id)

    return [
        experiment.samples[sid]
        for sid in target_ids
        if sid in experiment.samples and experiment.samples[sid].fcs_data is not None
    ]
