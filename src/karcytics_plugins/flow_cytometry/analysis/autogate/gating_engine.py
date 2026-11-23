"""The auto-gating engine: population -> view -> split -> named populations.

Synchronous and fast enough to run on a click (a split looks at no more than
20,000 events; mixtures are fitted on 8,000). Nothing here changes the
experiment: accepting a proposal is ``commit.py``'s job.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

import numpy as np

from .._utils import project_to_display
from ..sample_lens.synthesis import match_scores
from .assembly import (
    exact,
    frame_of,
    plot_of,
    record_of,
    regions_of,
    scale_note,
    with_pending,
)
from .density import find_valley
from .models import (
    DENSITY_VALLEYS,
    MARKER_PAIRS,
    METHODS,
    PCA,
    BarSection,
    GateStory,
    GroupPreview,
    MethodOutcome,
    PlotData,
    Proposal,
    Region,
    SampleOutcome,
    StepRequest,
    method,
)
from .naming import name_regions
from .population import (
    Frame,
    PopulationData,
    load_population,
    plot_rows,
    population_events,
    same_population,
    scatter_pair,
    singlet_pair,
    subsample,
)
from .split import (
    CELLS,
    SINGLETS,
    Split,
    by_mixture,
    by_singlets,
    by_valleys,
    cells_by_density,
)
from .story import story_of
from .views import Axis, View, ViewChoice, choose, loadings_section

if TYPE_CHECKING:
    import pandas as pd

    from ..axis_manager import AxisManager
    from ..gating.gate_node import GateNode
    from ..state import FlowState

CELLS_STEP, SINGLETS_STEP = "cells", "singlets"
KEPT = {CELLS, SINGLETS}
MAX_VIEWS_TRIED = 5  # mixture methods move on from views that hold one population
FLAG_DRIFT = 0.05  # a sample whose own split sits further than this share of an axis needs a look


@dataclass(frozen=True, eq=False)
class _Context:
    """What a proposal was made from, to redo it on another sample."""

    view: View
    split: Split
    frame: Frame
    data: PopulationData


class GatingEngine:
    """Proposes splits of a population and previews them on the rest of the group."""

    def __init__(self, state: FlowState, axis_manager: AxisManager) -> None:
        self._state = state
        self._axis_manager = axis_manager

    # ── Build ─────────────────────────────────────────────────────────

    def propose(self, request: StepRequest) -> Proposal | str:
        """The next split of the population, or why there isn't one.

        With "cells and singlets first" on, convention comes before the method: from All Events
        the cells split on forward scatter, then from that cells gate the singlets
        split, each unless already gated or not found (then the method runs, and
        says why the step was skipped).
        """
        due = self._convention_step(request)
        if due is None:
            return self._propose(request)
        step, conventional = due
        found = self._propose(conventional, step)
        if isinstance(found, Proposal):
            return found
        why = found.split(" Try other")[0].rstrip(".")
        skipped = f"{step.capitalize()} step skipped: {why[:1].lower()}{why[1:]}. "
        result = self._propose(request)
        if isinstance(result, Proposal):
            return replace(result, reason=skipped + result.reason)
        return skipped + result

    def _convention_step(self, request: StepRequest) -> tuple[str, StepRequest] | None:
        """("cells" or "singlets", the request for it), if one is due before ``request``."""
        sample = self._state.data.experiment.samples.get(request.sample_id)
        if not request.cells_first or sample is None or sample.fcs_data is None:
            return None
        root = sample.gate_tree
        if request.node_id is None:
            fsc, ssc = scatter_pair(sample.fcs_data)
            if fsc is None or ssc is None or any(_on_scatter(c) for c in root.children):
                return None  # no scatter, or cells are gated already
            axes = (fsc, ssc)
            step = CELLS_STEP
        else:
            node = root.find_node_by_id(request.node_id)
            pair = singlet_pair(sample.fcs_data)
            if node is None or node not in root.children or not _on_scatter(node) or pair is None:
                return None  # singlets come straight after a cells gate
            if any(_on_channels(c, set(pair)) for c in node.children):
                return None  # singlets are gated already
            axes, step = pair, SINGLETS_STEP
        return step, replace(
            request,
            method_key=DENSITY_VALLEYS.key,
            channels=axes,
            x_channel=axes[0],
            y_channel=axes[1],
            view_rank=0,
        )

    def _propose(self, request: StepRequest, step: str = "") -> Proposal | str:
        info = method(request.method_key)
        axes = (request.x_channel, request.y_channel) if info.user_picks_axes else ("", "")
        channels = tuple(dict.fromkeys(request.channels + tuple(a for a in axes if a)))
        data = load_population(
            self._state,
            self._axis_manager,
            request.sample_id,
            request.node_id,
            channels,
            request.min_events,
        )
        if isinstance(data, str):
            return data
        choice = choose(data, info.key, request.channels, *axes)
        if isinstance(choice, str):
            return choice
        found = self._split(info.key, choice, data, request, step)
        if isinstance(found, str):
            return found
        view, sections, split, rank = found
        split = exact(split, data, view)
        frame = frame_of(view)
        # Named by the view's own markers; PCA axes mix every channel, so by all of them.
        naming = channels if info.key == PCA.key else (view.x.key, view.y.key)
        if all(p.name for p in split.pieces):
            names = [p.name for p in split.pieces]
        else:
            names = name_regions(data, naming, [p.mask for p in split.pieces])
        regions = regions_of(names, split, frame, data, request.min_events)
        if step:  # by convention only the clean population is kept
            regions = [replace(r, is_main=r.is_main and r.name in KEPT) for r in regions]
        if info.key == PCA.key:
            extra = (
                loadings_section(choice.notes, view.x.label),
                loadings_section(choice.notes, view.y.label),
            )
            sections = sections + tuple(s for s in extra if s is not None)
        plot = plot_of(view, frame, data, regions, split)
        reason = self._reason(info.key, rank, view, choice, split, data, regions)
        pending = tuple(a.pending for a in (view.x, view.y) if a.pending is not None)
        provenance = record_of(info.key, data, view, choice.notes, split, request)
        if step:  # how the view was chosen doesn't apply: convention chose it
            reason, provenance["convention"] = _convention_reason(step, split), step
            sections = ()
        reason += scale_note(data, view)
        return Proposal(
            info.key,
            data.sample.sample_id,
            data.parent_id,
            data.parent_name,
            data.parent_total,
            plot,
            sections,
            reason,
            pending,
            provenance,
            _Context(view, split, frame, data),
            rank,
        )

    @staticmethod
    def _split(
        key: str,
        choice: ViewChoice,
        data: PopulationData,
        request: StepRequest,
        step: str = "",
    ) -> tuple[View, tuple[BarSection, ...], Split, int] | str:
        """The split on the requested view, or for the mixtures the first of the next
        MAX_VIEWS_TRIED views (by score) holding at least two populations to gate.
        """
        if key == DENSITY_VALLEYS.key:
            view, sections = choice.ranked(request.view_rank)
            if step == SINGLETS_STEP:
                area, height = (data.events[a.key].to_numpy(np.float64) for a in (view.x, view.y))
                split = by_singlets(view, area, height, request.min_valley)
            elif step == CELLS_STEP:
                split = cells_by_density(view, request.min_valley)
            else:
                split = by_valleys(view, request.min_valley)
            return split if isinstance(split, str) else (view, sections, split, request.view_rank)
        per_event = data.parent_total / max(len(data.events), 1)
        tried = []
        for rank in range(
            request.view_rank, request.view_rank + min(MAX_VIEWS_TRIED, len(choice.views))
        ):
            view, sections = choice.ranked(rank)
            split = by_mixture(view, request.min_valley)
            if not isinstance(split, str):
                big = [p for p in split.pieces if p.mask.sum() * per_event >= request.min_events]
                if len(big) >= 2:  # noqa: PLR2004 - a split needs two populations
                    return view, sections, split, rank
            tried.append(view.name)
        return (
            f"No clear split in the {len(tried)} best views ({', '.join(tried)}): none holds two "
            f"populations of {request.min_events:,}+ events with a valley of {request.min_valley:.2f} "
            "between them. Try other channels, or lower “Clear valley at least”."
        )

    @staticmethod
    def _reason(  # noqa: PLR0913 - everything the sentence names
        key: str,
        rank: int,
        view: View,
        choice: object,
        split: Split,
        data: PopulationData,
        regions: list[Region],
    ) -> str:
        n_views = len(getattr(choice, "views", ()))
        place = f"ranks {rank % max(n_views, 1) + 1}" if rank else "is the clearest"
        if key == MARKER_PAIRS.key:
            lead = f"{view.name} {place} of the {n_views} marker pairs (score {view.score:.2f}). "
        elif key == PCA.key:
            lead = (
                f"{view.name} {place} of the {n_views} planes of {data.parent_name} (score "
                f"{view.score:.2f}). Accepting adds the components as derived parameters, so their "
                "formulas are kept. "
            )
        else:
            lead = ""
        if rank and key != DENSITY_VALLEYS.key:
            lead += "Views ranked above it held one population each, or were skipped. "
        named = ", ".join(f"{r.name} ({r.fraction:.0%})" for r in regions if r.is_main)
        return f"{lead}{split.reason} Named from each group's medians: {named}."

    # ── Apply to group ────────────────────────────────────────────────

    def preview_group(self, proposal: Proposal, request: StepRequest) -> GroupPreview:
        """The proposal's gates on every sample of the group, and how far each sample's own split sits."""
        ctx: _Context = proposal.context
        names = proposal.plot.main_names
        rows = []
        for sid in request.group:
            sample = self._state.data.experiment.samples.get(sid)
            if sample is None:
                continue
            if sample.role.is_control:
                rows.append(
                    SampleOutcome(
                        sample.display_name, {}, 0.0, "Skipped: control sample", False, None
                    )
                )
                continue
            found, node_id = same_population(ctx.data.sample, proposal.parent_id, sample)
            if not found:
                rows.append(
                    SampleOutcome(
                        sample.display_name, {}, 0.0, f"No “{proposal.parent}” here", True, None
                    )
                )
                continue
            events, _ = population_events(sample, node_id)
            if events is None or len(events) < request.min_events:
                rows.append(
                    SampleOutcome(sample.display_name, {}, 0.0, "Too few events", False, None)
                )
                continue
            rows.append(self._on_sample(sample.display_name, subsample(events), proposal, ctx))
        return GroupPreview(names, tuple(rows))

    def _on_sample(
        self, name: str, events: pd.DataFrame, proposal: Proposal, ctx: _Context
    ) -> SampleOutcome:
        frame_df = with_pending(events, ctx.view)
        x = self._values(frame_df, ctx.view.x)
        y = self._values(frame_df, ctx.view.y)
        percents = {}
        for region in proposal.plot.regions:
            if region.is_main and region.gate is not None:
                percents[region.name] = 100.0 * float(np.mean(region.gate.contains(frame_df)))
        drift, ghosts = self._drift(x, y, ctx)
        flagged = drift > FLAG_DRIFT
        status = (
            f"Review: its own split sits {drift:.0%} away"
            if flagged
            else f"Fits (drift {drift:.0%})"
        )
        rows = plot_rows(len(x))
        points = ctx.frame.unit(np.column_stack((x[rows], y[rows])))
        plot = PlotData(
            proposal.plot.x_label,
            proposal.plot.y_label,
            points,
            proposal.plot.regions,
            ghosts,
            proposal.plot.cuts,
        )
        return SampleOutcome(name, percents, drift, status, flagged, plot)

    @staticmethod
    def _values(events: pd.DataFrame, axis: Axis) -> np.ndarray:
        return project_to_display(events[axis.key].to_numpy(dtype=np.float64), axis.scale)

    @staticmethod
    def _drift(x: np.ndarray, y: np.ndarray, ctx: _Context) -> tuple[float, tuple[Region, ...]]:
        frame, split = ctx.frame, ctx.split
        if split.components:
            means = np.array([c.mean for c in split.components])
            refit = by_mixture(
                replace(ctx.view, x=replace(ctx.view.x, values=x), y=replace(ctx.view.y, values=y)),
                0.0,
                means,
            )
            if isinstance(refit, str):
                return 0.0, ()
            shifts = [
                max(
                    abs(n.mean[0] - o.mean[0]) / frame.span("x"),
                    abs(n.mean[1] - o.mean[1]) / frame.span("y"),
                )
                for n, o in zip(refit.components, split.components, strict=True)
            ]
            ghosts = tuple(
                Region("", 0.0, tuple(float(v) for v in frame.unit(p.outline).ravel()))
                for p in refit.pieces
            )
            return float(max(shifts)), ghosts
        drift, ghosts_list = 0.0, []
        for axis, pos in split.cuts:
            valley = find_valley(x if axis == "x" else y)
            if valley is None:
                continue
            drift = max(drift, abs(valley.position - pos) / frame.span(axis))
            u = frame.unit(np.array([[valley.position, valley.position]]))[
                0, 0 if axis == "x" else 1
            ]
            line = (u, 0.0, u, 1.0) if axis == "x" else (0.0, u, 1.0, u)
            ghosts_list.append(Region("", 0.0, tuple(float(v) for v in line)))
        return float(drift), tuple(ghosts_list)

    # ── Compare methods ───────────────────────────────────────────────

    def compare(self, request: StepRequest) -> tuple[MethodOutcome, ...]:
        """Every method's split of the population, beside the user's own gates under it."""
        outcomes: list[MethodOutcome] = []
        best_pair = self.propose(replace(request, method_key=MARKER_PAIRS.key, view_rank=0))
        proposals: dict[str, Proposal | str] = {}
        for info in METHODS:
            req = replace(request, method_key=info.key, view_rank=0)
            if info.key == DENSITY_VALLEYS.key and not (request.x_channel and request.y_channel):
                if isinstance(best_pair, str):
                    proposals[info.key] = best_pair
                    continue
                view = best_pair.context.view
                req = replace(req, x_channel=view.x.key, y_channel=view.y.key)
            proposals[info.key] = best_pair if info.key == MARKER_PAIRS.key else self.propose(req)
        own = self._own_gates(request, proposals)
        outcomes.append(own[0])
        for info in METHODS:
            p = proposals[info.key]
            if isinstance(p, str):
                outcomes.append(MethodOutcome(info.name, info.key, {}, {}, "", None, p))
                continue
            percents = {r.name: 100 * r.fraction for r in p.plot.regions if r.is_main}
            agreement = {
                r.name: max((match_scores(r.mask, m)[0] for m in own[1]), default=0.0)
                for r in p.plot.regions
                if r.is_main and r.mask is not None and own[1]
            }
            outcomes.append(
                MethodOutcome(info.name, info.key, percents, agreement, p.context.view.name, p.plot)
            )
        return tuple(outcomes)

    def _own_gates(
        self, request: StepRequest, proposals: dict[str, Proposal | str]
    ) -> tuple[MethodOutcome, list[np.ndarray]]:
        """The user's gates directly under the population, with their events among the ones the split saw."""
        data = next((p.context.data for p in proposals.values() if isinstance(p, Proposal)), None)
        sample = self._state.data.experiment.samples.get(request.sample_id)
        node = (
            sample.gate_tree.find_node_by_id(request.node_id)
            if sample and request.node_id
            else None
        )
        node = node or (sample.gate_tree if sample else None)
        children = [c for c in node.children if c.gate is not None] if node is not None else []
        if data is None or not children:
            text = "No gates of yours under this population yet." if data is not None else ""
            return MethodOutcome("Your gates", "", {}, {}, "", None, text), []
        masks, percents = [], {}
        for child in children:
            if child.gate is None:
                continue
            try:
                mask = np.asarray(child.gate.contains(data.events), dtype=bool)
            except KeyError:
                continue
            masks.append(mask)
            percents[child.name] = 100.0 * float(mask.mean())
        summary = f"{len(masks)} gate{'s' if len(masks) != 1 else ''} drawn by hand"
        return MethodOutcome("Your gates", "", percents, {}, summary, None), masks

    # ── Why this gate ─────────────────────────────────────────────────

    def story(self, sample_id: str, node_id: str) -> GateStory | None:
        """Why the auto gate ``node_id`` is where it is; None for a gate drawn by hand."""
        sample = self._state.data.experiment.samples.get(sample_id)
        node = sample.gate_tree.find_node_by_id(node_id) if sample else None
        if node is None or node.gate is None or not node.gate.provenance:
            return None
        return story_of(node.name, node.gate.provenance)


def _on_scatter(node: GateNode) -> bool:
    """Is ``node`` gated on scatter channels only (a cells gate)?"""
    gate = node.gate
    if gate is None:
        return False
    params = [p for p in (gate.x_param, getattr(gate, "y_param", None)) if p]
    return bool(params) and all(p.startswith(("FSC", "SSC")) for p in params)


def _convention_reason(step: str, split: Split) -> str:
    lead = {
        CELLS_STEP: "Cells first, by convention: the gate outlines where the cells are, so the "
        "debris corner (low forward and side scatter) is left out. ",
        SINGLETS_STEP: "Singlets next, by convention: doublets (two cells passing together) are "
        "left out. ",
    }[step]
    return f"{lead}{split.reason} Untick “Cells and singlets first” to search the markers instead."


def _on_channels(node: GateNode, channels: set[str]) -> bool:
    """Is ``node`` gated on exactly these channels?"""
    gate = node.gate
    if gate is None:
        return False
    return {p for p in (gate.x_param, getattr(gate, "y_param", None)) if p} == channels
