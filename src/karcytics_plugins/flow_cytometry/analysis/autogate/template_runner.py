"""Running a gating template: where each population you described actually is.

For every step, parent first, the parent population is split on the step's
own markers (one marker against side scatter, two against each other; Cells
and Singlets on scatter, by convention) and the region whose +/lo/− calls
match what was asked for is kept. Its gate gives the next steps their events.
A step whose population isn't there says so, and its children are skipped.

Where the experiment has a control for a step's markers (an FMO lacking it, or
an unstained tube), the control is put through the same gates and its 99.5th
percentile is tried first as where positive starts.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

import numpy as np

from ..clustering.describe import short_marker
from ..fcs_io import get_channel_marker_label
from .assembly import exact, frame_of, plot_of, record_of, regions_of, scale_note
from .controls import ControlLine, control_for, control_line
from .density import find_valley, peak_beyond
from .models import TEMPLATE, Proposal, StepRequest
from .naming import calls_of, name_regions
from .population import (
    PopulationData,
    population_events,
    same_population,
    scatter_pair,
    search_scales,
    singlet_pair,
    subsample,
)
from .split import CELLS as CELLS_NAME
from .split import SINGLETS as SINGLETS_NAME
from .split import (
    Split,
    by_density,
    by_lines,
    by_mixture,
    by_singlets,
    by_valleys,
    cells_by_density,
    whole,
)
from .template import CELLS, MARKERS, SINGLETS, GatingTemplate, TemplateStep
from .views import View, chosen_axes

ASKED_VALLEY = 0.6  # of the usual clear valley: enough when the template says a population is there
ONE_PEAK = 0.1  # below this deepest valley a marker shows one population

if TYPE_CHECKING:
    import pandas as pd

    from ..axis_manager import AxisManager
    from ..experiment import Sample
    from ..fcs_io import FCSData
    from ..gating.base import Gate
    from ..state import FlowState
    from .models import BarSection


@dataclass(frozen=True, eq=False)
class StepOutcome:
    """What one template step found, or why it found nothing."""

    step: TemplateStep
    proposal: Proposal | None  # None: not found (``message`` says why)
    message: str = ""


@dataclass(frozen=True, eq=False)
class TemplatePlan:
    """A template run on one sample: each step's outcome."""

    template: GatingTemplate
    sample_id: str
    start_id: str | None
    start_name: str
    outcomes: tuple[StepOutcome, ...]

    @property
    def found(self) -> tuple[StepOutcome, ...]:
        """The steps that found their population."""
        return tuple(o for o in self.outcomes if o.proposal is not None)


@dataclass(frozen=True, eq=False)
class _Parent:
    events: pd.DataFrame
    name: str
    node_id: str | None  # in the real tree; None for a population not added yet
    start_id: str | None  # the population the template starts from
    gates: tuple[Gate, ...] = ()  # the template's gates from there to here


class TemplateRunner:
    """Runs a gating template step by step on one sample."""

    def __init__(self, state: FlowState, axis_manager: AxisManager) -> None:
        self._state = state
        self._axis_manager = axis_manager

    def run(
        self,
        template: GatingTemplate,
        sample_id: str,
        start_id: str | None,
        min_events: int = 500,
        min_valley: float = 0.3,
    ) -> TemplatePlan | str:
        """Find each step's population, parents first; a reason if nothing can start."""
        sample = self._state.data.experiment.samples.get(sample_id)
        if sample is None or sample.fcs_data is None:
            return "Pick a reference sample with events loaded."
        events, start_name = population_events(sample, start_id)
        if events is None:
            return f"{sample.display_name} has no events loaded."
        if not template.steps:
            return "The template has no populations yet."
        parents: dict[str | None, _Parent] = {None: _Parent(events, start_name, start_id, start_id)}
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
            proposal, gate = found
            kept = parent.events[np.asarray(gate.contains(parent.events), dtype=bool)]
            parents[step.step_id] = _Parent(kept, step.name, None, start_id, (*parent.gates, gate))
            outcomes.append(StepOutcome(step, proposal))
        return TemplatePlan(template, sample_id, start_id, start_name, tuple(outcomes))

    def _step(
        self,
        sample: Sample,
        template: GatingTemplate,
        step: TemplateStep,
        parent: _Parent,
        rules: tuple[int, float],
    ) -> tuple[Proposal, Gate] | str:
        min_events, min_valley = rules
        if len(parent.events) < min_events:
            return f"{parent.name} has {len(parent.events):,} events, fewer than {min_events:,}."
        assert sample.fcs_data is not None  # checked by run
        axes = _axes(sample.fcs_data, step)
        if isinstance(axes, str):
            return axes
        data = self._data(sample, parent, axes)
        view, sections = chosen_axes(data, *axes).ranked(0)
        reason, ruled_out = "No split found.", ""
        valley = min_valley if step.kind in (CELLS, SINGLETS) else ASKED_VALLEY * min_valley
        lines, note = self._lines(sample, step, parent, data)
        cut = (
            len(lines) == len(step.calls) and not note and all(c.level != "lo" for c in step.calls)
        )
        candidates = [
            *([_by_controls(view, lines)] if cut else []),
            *_splits(step, view, data, valley),
            _already(step, view, data, axes),
        ]
        for split in candidates:
            if split is None:
                continue
            if isinstance(split, str):
                reason = split
                continue
            split = exact(split, data, view)
            matching = _chosen(step, split, data, axes, min_events)
            if isinstance(matching, str):
                reason = matching
                continue
            wrong = {i: _wrong_side(step, data, split.pieces[i].mask, lines) for i in matching}
            matching = [i for i in matching if not wrong[i]]
            if not matching:  # the controls say it isn't what was asked for
                ruled_out = f"A region reads {step.calls_text}, but {next(iter(wrong.values()))}"
                continue
            split, chosen = _joined(split, matching, data, view)
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
                note=note,
            )
        return f"{ruled_out or reason} {note}".strip()

    def _lines(
        self, sample: Sample, step: TemplateStep, parent: _Parent, data: PopulationData
    ) -> tuple[dict[str, ControlLine], str]:
        """Control lines (channel → line) for the markers the step calls, from the same
        population in control tubes, through the same gates; and, if they can't be cut
        at, why not. Lines that aren't cut at still rule out regions on their wrong side.
        """
        if step.kind != MARKERS:
            return {}, ""
        others = [s for s in self._state.data.experiment.samples.values() if s is not sample]
        lines, notes = {}, []
        for ch, call in zip(data.labels, step.calls, strict=False):
            control = control_for(others, ch, data.labels[ch])
            if control is None:
                continue
            events = _through(control[0], sample, parent)
            line = control_line(*control, events, ch, data.labels[ch], data.scales[ch])
            if line is None:
                notes.append(
                    f"The {control[1]} control {control[0].display_name} has too few events "
                    f"in {parent.name} to place a line, so it isn't used."
                )
                continue
            lines[ch] = line
            side = "above" if call.level == "+" else "below"
            if call.level != "lo" and not peak_beyond(
                data.on_display(ch), line.position, above=side == "above"
            ):
                notes.append(
                    f"The {line.kind} control {line.control} puts {line.marker}+ at "
                    f"{line.position:.2f}, but {parent.name} has no clear population {side} "
                    "it (only the tail of the other side), so it isn't cut at."
                )
        return lines, " ".join(notes)

    def _data(self, sample: Sample, parent: _Parent, axes: tuple[str, str]) -> PopulationData:
        fcs = sample.fcs_data
        assert fcs is not None  # checked by run
        events = subsample(parent.events)
        scales, rescaled = search_scales(events, axes, self._axis_manager, sample.sample_id)
        return PopulationData(
            sample,
            parent.node_id,
            parent.name,
            events,
            len(parent.events),
            scales,
            {ch: get_channel_marker_label(fcs, ch) for ch in axes},
            rescaled=rescaled,
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
        note: str = "",
    ) -> tuple[Proposal, Gate] | str:
        min_events, min_valley = rules
        masks = [p.mask for p in split.pieces]
        if all(p.name for p in split.pieces):
            names = [p.name for p in split.pieces]
        elif "control_lines" in split.record:
            names = _line_names(split, data, _called_on(step, view), masks)
        else:
            names = name_regions(data, _called_on(step, view), masks)
        found_as = (
            f"all of {parent.name}"
            if split.record.get("whole_population")
            else names[chosen]
            if len(names) > 1
            else _reading(step, data, view, masks[0])
        )
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
            if step.kind in (CELLS, SINGLETS) or "control_lines" in split.record
            else f" A valley of {ASKED_VALLEY * min_valley:.2f} is enough here, as the template "
            "says the population is there."
        )
        reason = (
            f"{step.name}: asked for {asked} within {parent.name}. {split.reason}{bar} Kept: "
            f"{found_as} ({kept.fraction:.0%} of {parent.name}).{scale_note(data, view)}"
            + (f" {note}" if note else "")
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
        return proposal, split.pieces[chosen].gate


def _through(control: Sample, reference: Sample, parent: _Parent) -> pd.DataFrame | None:
    """``control``'s events in ``parent``'s population: the start population matched by
    name, then the template's gates so far. None if the control has no such population.
    """
    found, node_id = same_population(reference, parent.start_id, control)
    if not found:
        return None
    events, _name = population_events(control, node_id)
    try:
        for gate in parent.gates:
            if events is None:
                return None
            events = events[np.asarray(gate.contains(events), dtype=bool)]
    except KeyError:  # the control lacks a channel a gate is on
        return None
    return events


def _by_controls(view: View, lines: dict[str, ControlLine]) -> Split:
    """The view cut where the controls say positive starts."""
    return by_lines(
        view,
        {("x" if ch == view.x.key else "y"): line.position for ch, line in lines.items()},
        f"On {view.name}: " + "; ".join(line.text for line in lines.values()) + ".",
        {"control_lines": {line.marker: line.record() for line in lines.values()}},
    )


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
        return [cells_by_density(view, min_valley)]
    if step.kind == SINGLETS:
        area, height = (data.events[a.key].to_numpy(np.float64) for a in (view.x, view.y))
        return [by_singlets(view, area, height, min_valley)]
    # Density regions first (gates shaped like the populations), then straight cuts at
    # the valleys, then a mixture: the first whose region reads as asked is kept.
    one = len(step.calls) == 1
    return [
        by_density(view, min_valley),
        by_valleys(view, min_valley, x_only=one),
        by_mixture(view, min_valley),
    ]


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


def _joined(
    split: Split, matching: list[int], data: PopulationData, view: View
) -> tuple[Split, int]:
    """``split`` with the matching pieces as one (density regions that read alike are one
    population, e.g. low- and high-side-scatter live cells); the index of that piece.
    """
    if len(matching) == 1 or split.join is None:
        return split, max(matching, key=lambda i: int(split.pieces[i].mask.sum()))
    piece = split.join([split.pieces[i] for i in matching])
    if piece is None:
        return split, matching[0]
    rest = [p for i, p in enumerate(split.pieces) if i not in matching]
    joined = exact(replace(split, pieces=[piece, *rest]), data, view)
    return joined, 0


def _reading(step: TemplateStep, data: PopulationData, view: View, mask: np.ndarray) -> str:
    """How a lone region reads on the step's markers, e.g. "PI−"."""
    if step.kind != MARKERS:
        return step.name
    channels = (view.x.key, view.y.key)[: len(step.calls)]
    got = calls_of(data, channels, [mask])[0]
    return " ".join(
        f"{c.marker}{got.get(ch, '?')}" for ch, c in zip(channels, step.calls, strict=True)
    )


def _chosen(
    step: TemplateStep,
    split: Split,
    data: PopulationData,
    axes: tuple[str, str],
    min_events: int,
) -> list[int] | str:
    """The pieces holding the population asked for (several regions may read as asked)."""
    if split.record.get("whole_population"):
        return [0]
    if step.kind in (CELLS, SINGLETS):
        wanted = CELLS_NAME if step.kind == CELLS else SINGLETS_NAME
        names = [p.name for p in split.pieces]
        return [names.index(wanted)] if wanted in names else f"No {wanted.lower()} region found."
    masks = [p.mask for p in split.pieces]
    channels = axes[: len(step.calls)]
    calls = (
        _against_lines(split, data, channels, masks)
        if "control_lines" in split.record
        else calls_of(data, channels, masks)
    )
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
    return matching


def _wrong_side(
    step: TemplateStep, data: PopulationData, mask: np.ndarray, lines: dict[str, ControlLine]
) -> str:
    """Why a region lies on the wrong side of a control line for what was asked; "" if not."""
    for ch, call in zip(data.labels, step.calls, strict=False):
        line = lines.get(ch)
        if line is None or call.level == "lo":
            continue
        above = float(np.median(data.on_display(ch)[mask])) > line.position
        if above != (call.level == "+"):
            side = "below" if call.level == "+" else "above"
            return (
                f"most of it lies {side} {line.position:.2f}, where the {line.kind} control "
                f"{line.control} puts {line.marker}+, so it isn't taken."
            )
    return ""


def _against_lines(
    split: Split, data: PopulationData, channels: tuple[str, ...], masks: list[np.ndarray]
) -> list[dict[str, str]]:
    """Each piece's calls by which side of the control lines it lies: + above, − below."""
    on = dict(zip(("x", "y"), channels, strict=False))  # the step's markers, x first
    at = {on[axis]: position for axis, position in split.cuts}
    return [
        {ch: ("+" if np.median(data.on_display(ch)[mask]) > at[ch] else "−") for ch in channels}
        if mask.any()
        else {}
        for mask in masks
    ]


def _line_names(
    split: Split, data: PopulationData, channels: tuple[str, ...], masks: list[np.ndarray]
) -> list[str]:
    """Pieces named by the control lines, e.g. "CD4+ CD8−"."""
    return [
        " ".join(f"{short_marker(data.labels[ch])}{calls.get(ch, '?')}" for ch in channels)
        for calls in _against_lines(split, data, channels, masks)
    ]
