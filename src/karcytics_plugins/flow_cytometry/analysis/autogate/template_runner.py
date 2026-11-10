"""Running a gating template: where each population you described actually is.

For every step, parent first, the parent population is split on the step's
own markers (one marker against side scatter, two against each other; Cells
and Singlets on scatter, by convention) and the region whose +/lo/− calls
match what was asked for is kept. Its gate gives the next steps their events.
A step whose population isn't there says so, and its children are skipped.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

import numpy as np

from ..clustering.describe import short_marker
from ..fcs_io import get_channel_marker_label
from .assembly import exact, frame_of, plot_of, record_of, regions_of
from .density import find_valley
from .models import TEMPLATE, Proposal, StepRequest
from .naming import calls_of, name_regions
from .population import (
    PopulationData,
    population_events,
    scatter_pair,
    singlet_pair,
    subsample,
)
from .split import CELLS as CELLS_NAME
from .split import SINGLETS as SINGLETS_NAME
from .split import Split, by_mixture, by_singlets, by_valleys, cells_names, whole
from .template import CELLS, SINGLETS, GatingTemplate, TemplateStep
from .views import View, chosen_axes

ASKED_VALLEY = 0.6  # of the usual clear valley: enough when the template says a population is there
ONE_PEAK = 0.1  # below this deepest valley a marker shows one population

if TYPE_CHECKING:
    import pandas as pd

    from ..axis_manager import AxisManager
    from ..experiment import Sample
    from ..fcs_io import FCSData
    from ..state import FlowState
    from .models import BarSection


@dataclass(frozen=True, eq=False)
class StepOutcome:
    step: TemplateStep
    proposal: Proposal | None  # None: not found (``message`` says why)
    message: str = ""


@dataclass(frozen=True, eq=False)
class TemplatePlan:
    template: GatingTemplate
    sample_id: str
    start_id: str | None
    start_name: str
    outcomes: tuple[StepOutcome, ...]

    @property
    def found(self) -> tuple[StepOutcome, ...]:
        return tuple(o for o in self.outcomes if o.proposal is not None)


@dataclass(frozen=True, eq=False)
class _Parent:
    events: pd.DataFrame
    name: str
    node_id: str | None  # in the real tree; None for a population not added yet


class TemplateRunner:
    def __init__(self, state: FlowState, axis_manager: AxisManager) -> None:
        self._state = state
        self._axis_manager = axis_manager

    def run(  # noqa: PLR0913 - the template and the stopping rules
        self,
        template: GatingTemplate,
        sample_id: str,
        start_id: str | None,
        min_events: int = 500,
        min_valley: float = 0.3,
    ) -> TemplatePlan | str:
        sample = self._state.data.experiment.samples.get(sample_id)
        if sample is None or sample.fcs_data is None:
            return "Pick a reference sample with events loaded."
        events, start_name = population_events(sample, start_id)
        if events is None:
            return f"{sample.display_name} has no events loaded."
        if not template.steps:
            return "The template has no populations yet."
        parents: dict[str | None, _Parent] = {None: _Parent(events, start_name, start_id)}
        outcomes = []
        for step in template.ordered():
            parent = parents.get(step.parent_id)
            if parent is None:
                outcomes.append(StepOutcome(step, None, "Skipped: its parent wasn't found."))
                continue
            missing = _axes(sample.fcs_data, step) if step.kind in (CELLS, SINGLETS) else ()
            if isinstance(missing, str):  # a convention step this file can't show: step aside
                parents[step.step_id] = parent
                note = (
                    f"Not drawn: {missing[:1].lower()}{missing[1:]} The populations under it "
                    f"start from {parent.name}."
                )
                outcomes.append(StepOutcome(step, None, note))
                continue
            found = self._step(sample, template, step, parent, (min_events, min_valley))
            if isinstance(found, str):
                outcomes.append(StepOutcome(step, None, found))
                continue
            proposal, kept = found
            parents[step.step_id] = _Parent(kept, step.name, None)
            outcomes.append(StepOutcome(step, proposal))
        return TemplatePlan(template, sample_id, start_id, start_name, tuple(outcomes))

    def _step(
        self,
        sample: Sample,
        template: GatingTemplate,
        step: TemplateStep,
        parent: _Parent,
        rules: tuple[int, float],
    ) -> tuple[Proposal, pd.DataFrame] | str:
        min_events, min_valley = rules
        if len(parent.events) < min_events:
            return f"{parent.name} has {len(parent.events):,} events, fewer than {min_events:,}."
        assert sample.fcs_data is not None  # checked by run
        axes = _axes(sample.fcs_data, step)
        if isinstance(axes, str):
            return axes
        data = self._data(sample, parent, axes)
        view, sections = chosen_axes(data, *axes).ranked(0)
        reason = "No split found."
        valley = min_valley if step.kind in (CELLS, SINGLETS) else ASKED_VALLEY * min_valley
        for split in [*_splits(step, view, data, valley), _already(step, view, data, axes)]:
            if split is None:
                continue
            if isinstance(split, str):
                reason = split
                continue
            split = exact(split, data, view)
            chosen = _chosen(step, split, view, data, axes, min_events)
            if isinstance(chosen, str):
                reason = chosen
                continue
            return self._proposal(
                template=template,
                step=step,
                parent=parent,
                data=data,
                view=view,
                sections=sections,
                split=split,
                chosen=chosen,
                rules=rules,
            )
        return reason

    def _data(self, sample: Sample, parent: _Parent, axes: tuple[str, str]) -> PopulationData:
        fcs = sample.fcs_data
        assert fcs is not None  # checked by run
        return PopulationData(
            sample,
            parent.node_id,
            parent.name,
            subsample(parent.events),
            len(parent.events),
            {ch: self._axis_manager.get_scale(ch, sample.sample_id) for ch in axes},
            {ch: get_channel_marker_label(fcs, ch) for ch in axes},
        )

    def _proposal(  # noqa: PLR0913 - everything a proposal is made of
        self,
        *,
        template: GatingTemplate,
        step: TemplateStep,
        parent: _Parent,
        data: PopulationData,
        view: View,
        sections: tuple[BarSection, ...],
        split: Split,
        chosen: int,
        rules: tuple[int, float],
    ) -> tuple[Proposal, pd.DataFrame] | str:
        min_events, min_valley = rules
        masks = [p.mask for p in split.pieces]
        names = (
            cells_names(view, split)
            if step.kind == CELLS
            else [p.name for p in split.pieces]
            if all(p.name for p in split.pieces)
            else name_regions(data, _called_on(step, view), masks)
        )
        found_as = names[chosen] if len(names) > 1 else f"all of {parent.name}"
        names[chosen] = step.name
        frame = frame_of(view)
        regions = [
            r if r.name == step.name else replace(r, is_main=False)
            for r in regions_of(names, split, frame, data, min_events)
        ]
        kept = next(r for r in regions if r.name == step.name)
        if not kept.is_main:
            return f"{found_as} is there but holds fewer than {min_events:,} events."
        asked = "by convention" if step.kind in (CELLS, SINGLETS) else step.calls_text
        bar = (
            ""
            if step.kind in (CELLS, SINGLETS)
            else f" A valley of {ASKED_VALLEY * min_valley:.2f} is enough here, as the template "
            "says the population is there."
        )
        reason = (
            f"{step.name}: asked for {asked} within {parent.name}. {split.reason}{bar} Kept: "
            f"{found_as} ({kept.fraction:.0%} of {parent.name})."
        )
        request = StepRequest(
            TEMPLATE.key,
            data.sample.sample_id,
            parent.node_id,
            (view.x.key, view.y.key),
            min_events=min_events,
            min_valley=min_valley,
        )
        record = record_of(TEMPLATE.key, data, view, {}, split, request)
        record.update(template=template.name, step=step.name, asked=asked)
        if step.kind in (CELLS, SINGLETS):
            record["convention"] = step.kind
        proposal = Proposal(
            TEMPLATE.key,
            data.sample.sample_id,
            parent.node_id,
            parent.name,
            data.parent_total,
            plot_of(view, frame, data, regions, split),
            sections,
            reason,
            provenance=record,
        )
        gate = split.pieces[chosen].gate
        return proposal, parent.events[np.asarray(gate.contains(parent.events), dtype=bool)]


def resolve(fcs: FCSData, marker: str) -> str | None:
    """The channel measuring ``marker`` (by marker name, label or channel name)."""
    wanted = marker.strip().lower()
    for ch in fcs.channels:
        label = get_channel_marker_label(fcs, ch)
        if wanted in (ch.lower(), label.lower(), short_marker(label).lower()):
            return ch
    return None


def _axes(fcs: FCSData, step: TemplateStep) -> tuple[str, str] | str:
    """The view a step is gated on, or why it can't be drawn on this sample."""
    if step.kind in (CELLS, SINGLETS):
        return _convention_axes(fcs, step.kind)
    channels = [resolve(fcs, c.marker) for c in step.calls]
    missing = [c.marker for c, ch in zip(step.calls, channels, strict=True) if ch is None]
    if missing:
        return f"No channel measures {missing[0]} in this sample."
    if len(channels) == 2:  # noqa: PLR2004 - two markers: one against the other
        return str(channels[0]), str(channels[1])
    fsc, ssc = scatter_pair(fcs)
    other = ssc or fsc
    if other is None:
        return "One marker is drawn against side scatter, and there is none."
    return str(channels[0]), other


def _convention_axes(fcs: FCSData, kind: str) -> tuple[str, str] | str:
    if kind == SINGLETS:
        pair = singlet_pair(fcs)
        return pair or "No forward-scatter height (FSC-H): singlets need area and height."
    fsc, ssc = scatter_pair(fcs)
    if fsc is None or ssc is None:
        return "No forward and side scatter channels for a cells gate."
    return fsc, ssc


def _splits(
    step: TemplateStep, view: View, data: PopulationData, min_valley: float
) -> list[Split | str]:
    if step.kind == CELLS:
        return [by_valleys(view, min_valley, cells=True)]
    if step.kind == SINGLETS:
        area, height = (data.events[a.key].to_numpy(np.float64) for a in (view.x, view.y))
        return [by_singlets(view, area, height, min_valley)]
    if len(step.calls) == 1:
        return [by_valleys(view, min_valley, x_only=True), by_mixture(view, min_valley)]
    return [by_valleys(view, min_valley), by_mixture(view, min_valley)]


def _called_on(step: TemplateStep, view: View) -> tuple[str, ...]:
    """The channels a step's populations are named by: its own markers."""
    return (
        (view.x.key, view.y.key)[: max(len(step.calls), 1)]
        if step.calls
        else (view.x.key, view.y.key)
    )


def _already(
    step: TemplateStep, view: View, data: PopulationData, axes: tuple[str, str]
) -> Split | str | None:
    """When nothing splits: the whole parent, if its one population reads as asked.

    Strictly as asked: a lone population reads "lo" on its own sample's spread
    whatever it is (an unstained tube too), so "lo" never stands in for + or −.
    """
    if step.kind == CELLS:
        return whole(
            view,
            f"No debris valley below the main {view.x.label} peak, so every event is kept as cells.",
        )
    if step.kind == SINGLETS:
        return None  # singlets always cut, by the ratio's spread if there is no valley
    channels = axes[: len(step.calls)]
    got = calls_of(data, channels, [np.ones(len(data.events), dtype=bool)])[0]
    reads = " ".join(
        f"{c.marker}{got.get(ch, '?')}" for ch, c in zip(channels, step.calls, strict=True)
    )
    peaks = [find_valley(data.on_display(ch)) for ch in channels]
    if any(v is not None and v.depth >= ONE_PEAK for v in peaks):
        return (
            f"No {step.calls_text} population in {data.parent_name}: its markers show several "
            "peaks but no clear valley between them. Lower “Clear valley at least” to cut there."
        )
    if any(got.get(ch) != c.level for ch, c in zip(channels, step.calls, strict=True)):
        return (
            f"No {step.calls_text} population in {data.parent_name}: it is one population, "
            f"reading {reads}."
        )
    return whole(
        view,
        f"Nothing splits {data.parent_name} on these markers (no clear valley): it is one "
        f"population, reading {reads} on the whole sample's range, so the gate holds all of it.",
    )


def _chosen(  # noqa: PLR0913 - the step, the split and what to judge it by
    step: TemplateStep,
    split: Split,
    view: View,
    data: PopulationData,
    axes: tuple[str, str],
    min_events: int,
) -> int | str:
    """The piece holding the population asked for (the largest, if several do)."""
    if split.record.get("whole_population"):
        return 0
    if step.kind in (CELLS, SINGLETS):
        wanted = CELLS_NAME if step.kind == CELLS else SINGLETS_NAME
        names = cells_names(view, split) if step.kind == CELLS else [p.name for p in split.pieces]
        return names.index(wanted) if wanted in names else f"No {wanted.lower()} region found."
    masks = [p.mask for p in split.pieces]
    channels = axes[: len(step.calls)]
    calls = calls_of(data, channels, masks)
    per_event = data.parent_total / max(len(data.events), 1)
    matching = [
        i
        for i, got in enumerate(calls)
        if all(got.get(ch) == c.level for ch, c in zip(channels, step.calls, strict=True))
        and masks[i].sum() * per_event >= min_events
    ]
    if not matching:
        found = ", ".join(name_regions(data, channels, masks))
        return f"No {step.calls_text} population found (found: {found})."
    return max(matching, key=lambda i: int(masks[i].sum()))
