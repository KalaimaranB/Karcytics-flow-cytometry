"""A spillover matrix estimated from FMO controls: which dye each tube lacks, and the fits."""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..compensation import (
    CompensationMatrix,
    DetectorFit,
    calculate_spillover_from_fmo,
    fmo_fit_detail,
)
from ..experiment import Sample, SampleRole
from ..fcs_io import (
    FCSData,
    get_channel_marker_label,
    get_fluorescence_channels,
)
from ..fit_population import (
    FitEvents,
    fit_events,
)
from ..services import experiment_edits
from ..state import FlowState
from .base import (
    FIT_ON_NOTE,
    SETUP_HINT,
    AskPath,
    FitIllustration,
    InputRow,
    Inputs,
    MatrixSource,
    MatrixSourceError,
    MethodOptions,
    Readiness,
    SourceResult,
    Table,
    events_used,
    gate_names,
    loaded_samples,
)

_MIN_MATRIX_CHANNELS = 2
# Placing an FMO by its signal. A tube's level in each channel is taken
# relative to the other FMOs' median there (about 1 where it carries the
# dye). The dye it lacks is the channel where that is lowest, provided it is
# dimmer than the others at all, and stands clear of the tube's next-lowest
# channel, so a tube that is merely dim overall is not placed.
_DIMMER_THAN_OTHER_FMOS = 0.8
_CLEAR_OF_NEXT_CHANNEL = 0.7
_MIN_OTHER_FMOS = 2
_SIGNAL_SAMPLE_EVENTS = 20_000

_ILLUSTRATION_EVENTS = 3000  # points drawn; the fit itself uses far more
_EXAMPLE_KEY = ""
_EXAMPLE_LABEL = "Example data (load FMO controls to see your own)"


# ── FMO controls ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class _Placement:
    """An FMO control and the channel of the dye it lacks, if that is known."""

    sample: Sample
    fcs: FCSData
    channel: str | None
    reason: str  # how the channel was found, or why the tube isn't used
    used: bool


_FMO_INPUT_HEADERS = ("FMO tube", "Lacks", "How we know", "Events used")
_SET_BY_YOU = "set by you"
_FROM_DATA = "from its data (dim in this channel)"
_FROM_NAME = "guessed from its name (its data didn't settle it) — please check"
_UNKNOWN = "not used — couldn't tell which dye it lacks"
_DETECT_AGAIN = "Detect again"


class _Seating:
    """FMO tubes placed on channels so far; only the first tube on a channel is used."""

    def __init__(self, fmos: list[tuple[Sample, FCSData]]) -> None:
        self._fmos = fmos
        self.placements: dict[int, _Placement] = {}
        self._taken: dict[str, str] = {}  # channel → the tube that covers it

    def place(self, index: int, channel: str, reason: str) -> bool:
        """Place tube ``index`` on ``channel``; False when another tube already covers it."""
        sample, fcs = self._fmos[index]
        used = channel not in self._taken
        if used:
            self._taken[channel] = sample.display_name
        else:
            reason = f"not used — {self._taken[channel]} already covers it"
        self.placements[index] = _Placement(sample, fcs, channel, reason, used)
        return used


class FmoSource(MatrixSource):
    key = "fmo"
    label = "FMO controls"
    action = "🧮 Estimate from FMOs"
    reports = True
    tooltip = (
        "Estimate the spillover matrix from fluorescence-minus-one controls.\n"
        "Each FMO lacks one dye, so its signal in that dye's detector is spill from the "
        "others.\nRequires samples tagged with role 'FMO Control'."
    )
    explanation = (
        "<b>How it works.</b> An FMO control is stained with every dye but one, so "
        "whatever its missing dye's detector records has leaked in from the other dyes.<br>"
        "1. <b>Which dye each tube lacks</b> is read from its data: the one channel where it "
        "is dimmer than the other FMO tubes, with no other channel coming close. That is "
        "worked out once and kept, and "
        "shown in the table below, where you can change it. Only when the data doesn't "
        "settle it (fewer than three FMO tubes, say) is the tube's name used as a guess.<br>"
        "2. <b>One fit per tube:</b> the missing dye's detector is written as a weighted "
        "sum of the other detectors, plus a constant for autofluorescence, across the "
        "tube's uncompensated events (at most 100,000).<br>"
        "3. <b>Robust weighting:</b> the fit is repeated, each time giving less weight to "
        "events far from the fitted line (dead cells, aggregates), until it settles.<br>"
        "4. <b>Solving the matrix:</b> the weights of all tubes together are inverted into "
        "the spillover matrix, each row scaled to 1 on the diagonal. Slightly negative "
        "values are set to 0.<br><br>"
        "<b>Limits.</b> A detector with no FMO tube gets no estimate (greyed in the "
        "matrix, left at 0). Dyes that are always bright on the same cells can't be told "
        "apart. This is Karcytics' own method, not a published standard: after a run, "
        "check the fit report below and each pair on the preview, then fine-tune.<br><br>"
        "<b>Reading the fit report.</b> <i>Set aside as outliers</i> is the share of events "
        "the robust weighting largely ignored; a high share means a messy tube. "
        "<i>Explained by the other dyes (R²)</i> is how much of that detector's signal the "
        "fit attributes to spill: near 0 means little spills into it (not a bad fit), near "
        "1 means the detector mostly sees other dyes." + FIT_ON_NOTE
    )

    @staticmethod
    def _placements(state: FlowState) -> tuple[list[str], list[_Placement]]:
        """The matrix channels, and each FMO control with the dye it lacks.

        A tube is placed by the dye recorded on it (set by the user first,
        then found earlier from its data). Any other tube is placed by its
        data, which is recorded on it so this is done once, and failing that
        by its name. Only one tube is used per channel.
        """
        fmos = loaded_samples(state, SampleRole.FMO_CONTROL)
        if not fmos:
            return [], []
        channels = get_fluorescence_channels(fmos[0][1])
        seating = _Seating(fmos)
        place, placements = seating.place, seating.placements

        recorded = [index for index, (sample, _) in enumerate(fmos) if sample.fmo_minus]
        open_ = [index for index in range(len(fmos)) if index not in recorded]
        for index in sorted(recorded, key=lambda i: fmos[i][0].fmo_minus_detected):
            sample, fcs = fmos[index]
            channel = fmo_missing_channel(sample, fcs, channels)
            if channel is None:  # recorded as something this panel doesn't have
                open_.append(index)
            else:
                place(index, channel, _FROM_DATA if sample.fmo_minus_detected else _SET_BY_YOU)

        dimmest = _dimmest_by_tube([fcs for _, fcs in fmos], open_, channels)
        # The clearest cases claim their channel first.
        for index in sorted(dimmest, key=lambda i: dimmest[i][1]):
            channel = channels[dimmest[index][0]]
            if place(index, channel, _FROM_DATA):
                experiment_edits.record_detected_fmo_minus(state, fmos[index][0].sample_id, channel)

        for index in open_:
            if index in placements:
                continue
            sample, fcs = fmos[index]
            named = _named_channel(sample.display_name, fcs, channels)
            if named is None:
                placements[index] = _Placement(sample, fcs, None, _UNKNOWN, used=False)
            else:
                place(index, named, _FROM_NAME)
        return channels, [placements[index] for index in sorted(placements)]

    def readiness(self, state: FlowState, _options: MethodOptions) -> Readiness:
        channels, placements = self._placements(state)
        if not placements:
            return Readiness(
                False,
                "No FMO controls loaded (set a sample's role to FMO Control in the "
                "Properties panel).",
            )
        used = [p for p in placements if p.used]
        text = f"{len(used)} FMO control(s) cover {len(used)} of {len(channels)} channels."
        if len(used) < len(placements):
            text += f" {len(placements) - len(used)} not used."
        return Readiness(bool(used), text + SETUP_HINT)

    def obtain(
        self, state: FlowState, _ask_path: AskPath | None, options: MethodOptions
    ) -> SourceResult | None:
        channels, placements = self._placements(state)
        used = {p.channel: p for p in placements if p.used and p.channel is not None}
        fitted = {
            channel: fit
            for channel, p in used.items()
            if (fit := fit_events(p.sample, options.gate)) is not None
        }
        if not fitted:
            raise MatrixSourceError(
                "No Usable FMO Controls",
                "No loaded FMO control could be matched to the dye it lacks.\n\n"
                "Open Method setup and set each tube's Missing dye.",
            )
        fits: list[DetectorFit] = []
        try:
            matrix = calculate_spillover_from_fmo(
                {channel: fit.events for channel, fit in fitted.items()}, channels, fits
            )
        except Exception as exc:
            raise MatrixSourceError(
                "Estimation Error", f"Failed to estimate a matrix from the FMO controls:\n{exc}"
            ) from exc

        summary = (
            f"Estimated a {matrix.n_channels}×{matrix.n_channels} matrix from "
            f"{len(fits)} FMO control(s)"
            + (f", fitted on '{options.gate}'." if options.gate else ".")
        )
        uncovered = [ch for ch in channels if ch not in {fit.channel for fit in fits}]
        if uncovered:
            summary += (
                f" Spill into {', '.join(uncovered)} is not estimated (no FMO): those cells "
                "are greyed out and left at 0."
            )
        tubes = {channel: p.sample.display_name for channel, p in used.items()}
        return SourceResult(
            matrix,
            "Estimate Compensation Matrix",
            summary,
            _fmo_report(matrix, fits, tubes, fitted, options.gate),
        )

    def gate_choices(self, state: FlowState) -> list[str] | None:
        return gate_names([sample for sample, _ in loaded_samples(state, SampleRole.FMO_CONTROL)])

    def inputs(self, state: FlowState, options: MethodOptions) -> Inputs | None:
        channels, placements = self._placements(state)
        if not placements:
            return Inputs(_FMO_INPUT_HEADERS, ())
        fcs = placements[0].fcs
        choices: tuple[tuple[str, str | None], ...] = (
            (_DETECT_AGAIN, None),
            *((get_channel_marker_label(fcs, channel), channel) for channel in channels),
        )
        rows = [
            InputRow(
                p.sample.sample_id,
                (
                    p.sample.display_name,
                    p.channel or "unknown",
                    p.reason,
                    events_used(p.sample, options.gate) if p.used else "—",
                ),
                choices,
                # What will be used, however it was found.
                p.channel,
            )
            for p in placements
        ]
        covered = {p.channel for p in placements if p.used}
        rows += [
            InputRow("", ("(no FMO control)", channel, "not estimated — left at 0", "—"))
            for channel in channels
            if channel not in covered
        ]
        return Inputs(_FMO_INPUT_HEADERS, tuple(rows), choice_header="Missing dye")

    def set_choice(self, state: FlowState, sample_id: str, value: str | None) -> None:
        experiment_edits.set_fmo_minus(state, sample_id, value)

    def illustration_choices(self, state: FlowState) -> list[tuple[str, str]] | None:
        _channels, placements = self._placements(state)
        tubes = [
            (f"{p.sample.display_name} (no {p.channel})", p.channel)
            for p in placements
            if p.used and p.channel is not None
        ]
        return tubes or [(_EXAMPLE_LABEL, _EXAMPLE_KEY)]

    def illustration(
        self, state: FlowState, options: MethodOptions, key: str
    ) -> FitIllustration | None:
        if key == _EXAMPLE_KEY:
            return _example_illustration()
        channels, placements = self._placements(state)
        placement = next((p for p in placements if p.used and p.channel == key), None)
        fit = fit_events(placement.sample, options.gate) if placement else None
        if placement is None or fit is None or any(c not in fit.events.columns for c in channels):
            return None
        detail = fmo_fit_detail(fit.events, channels, key)
        # Show the dye that leaks in the most: largest weight × how much it varies.
        leak = int(np.argmax(np.abs(detail.weights) * detail.signals.std(axis=0)))
        rest = np.delete(np.arange(len(detail.others)), leak)
        shown = slice(None, None, max(1, len(detail.target) // _ILLUSTRATION_EVENTS))
        return FitIllustration(
            tube=placement.sample.display_name,
            missing=key,
            other=detail.others[leak],
            x=detail.signals[shown, leak],
            y=(detail.target - detail.signals[:, rest] @ detail.weights[rest] - detail.intercept)[
                shown
            ],
            ignored=detail.largely_ignored[shown],
            slope=float(detail.weights[leak]),
            plain_slope=float(detail.plain_weights[leak]),
            events=len(detail.target),
        )


def _example_illustration() -> FitIllustration:
    """A made-up tube lacking PE, where FITC leaks 12% into the PE detector
    and a few events are bright there for no good reason.
    """
    rng = np.random.default_rng(0)
    events = _ILLUSTRATION_EVENTS
    dim_share, junk_share = 0.5, 0.05
    fitc = np.where(rng.random(events) < dim_share, 400.0, 6000.0)
    fitc = fitc * rng.lognormal(0, 0.5, events)
    pe = 0.12 * fitc + rng.normal(0, 60, events)
    junk = rng.random(events) < junk_share
    pe[junk] += rng.uniform(400, 2500, int(junk.sum()))
    frame = pd.DataFrame({"FITC-A": fitc, "PE-A": pe})
    detail = fmo_fit_detail(frame, ["FITC-A", "PE-A"], "PE-A")
    return FitIllustration(
        tube="Example tube",
        missing="PE-A",
        other="FITC-A",
        x=fitc,
        y=pe - detail.intercept,
        ignored=detail.largely_ignored,
        slope=float(detail.weights[0]),
        plain_slope=float(detail.plain_weights[0]),
        events=events,
        example=True,
    )


def _fmo_report(
    matrix: CompensationMatrix,
    fits: list[DetectorFit],
    tubes: dict[str, str],
    fitted: dict[str, FitEvents],
    gate: str | None,
) -> Table:
    """Per detector: the tube, the events, and how well the fit explained them."""
    channels = matrix.channel_names
    rows = []
    for fit in fits:
        detector = channels.index(fit.channel)
        spill_in = matrix.matrix[:, detector].copy()
        spill_in[detector] = 0.0
        strongest = int(np.argmax(spill_in))
        rows.append(
            (
                fit.channel,
                tubes[fit.channel],
                _events_fitted(fit.events, fitted[fit.channel], gate),
                f"{fit.down_weighted:.1%}",
                f"{fit.r_squared:.2f}",
                f"{channels[strongest]} ({spill_in[strongest]:.3f})"
                if spill_in[strongest] > 0
                else "none found",
            )
        )
    return Table(
        (
            "Detector",
            "FMO tube",
            "Events fitted",
            "Set aside as outliers",
            "Explained by the other dyes (R²)",
            "Largest spill into it",
        ),
        tuple(rows),
    )


def _events_fitted(used: int, available: FitEvents, gate: str | None) -> str:
    text = available.describe(gate)
    if used < len(available.events):
        text = f"{used:,}, sampled evenly from {text}"
    return text


def _normalise(name: str) -> str:
    """A dye/marker name reduced to what people keep when retyping it:
    'APC-Cy7-A', 'APC Cy7' and 'APCCy7' all become 'apccy7'.
    """
    name = re.sub(r"-[ahw]$", "", name.casefold().strip())  # area/height/width suffix
    return re.sub(r"[^0-9a-z]", "", name)


def fmo_missing_channel(sample: Sample, fcs: FCSData, channels: list[str]) -> str | None:
    """The channel of the dye recorded on an FMO control (``fmo_minus``, which
    a template may hold as a marker name), or None if nothing usable is.
    """
    if not sample.fmo_minus:
        return None
    return _matching_channel({_normalise(sample.fmo_minus)}, fcs, channels)


def _named_channel(name: str, fcs: FCSData, channels: list[str]) -> str | None:
    """The channel whose dye or marker a tube's name mentions, if exactly one."""
    # Runs of whole words, so "CD4" doesn't match inside "CD45" but
    # "Pacific Blue" still matches as one name.
    words = re.split(r"[\s_]+", name)
    candidates = {
        _normalise(" ".join(words[i:j]))
        for i in range(len(words))
        for j in range(i + 1, len(words) + 1)
    }
    return _matching_channel(candidates, fcs, channels)


def _matching_channel(candidates: set[str], fcs: FCSData, channels: list[str]) -> str | None:
    names: dict[str, set[str]] = {}
    for channel in channels:
        index = fcs.channels.index(channel) if channel in fcs.channels else -1
        marker = fcs.markers[index] if 0 <= index < len(fcs.markers) else ""
        names[channel] = {_normalise(n) for n in (channel, marker) if n} - {""}
    # The longest name wins: "APC Cy7" names APC-Cy7, not APC.
    hits = {
        ch: max(map(len, known & candidates)) for ch, known in names.items() if known & candidates
    }
    best = [ch for ch, length in hits.items() if length == max(hits.values())]
    return best[0] if len(best) == 1 else None


def placed_fmo_channel(state: FlowState, sample_id: str) -> str | None:
    """The dye the FMO method takes ``sample_id`` to lack, however it was found."""
    _channels, placements = FmoSource._placements(state)
    return next((p.channel for p in placements if p.sample.sample_id == sample_id), None)


def _signal_levels(controls: list[FCSData], channels: list[str]) -> np.ndarray | None:
    """Each control's bright end (95th percentile) in each channel, or None
    if a control lacks one of the channels.
    """
    levels = []
    for fcs in controls:
        events = fcs.raw_events if fcs.raw_events is not None else fcs.events
        if events is None or any(ch not in events.columns for ch in channels):
            return None
        step = max(1, len(events) // _SIGNAL_SAMPLE_EVENTS)
        levels.append(np.percentile(events[channels].to_numpy()[::step], 95, axis=0))
    return np.maximum(np.array(levels, dtype=np.float64), 1.0)


def _dimmest_by_tube(
    controls: list[FCSData], tubes: list[int], channels: list[str]
) -> dict[int, tuple[int, float]]:
    """For each of ``tubes`` whose data singles out one channel: (channel index, how clearly)."""
    levels = _signal_levels(controls, channels) if tubes else None
    if levels is None:
        return {}
    return {i: found for i in tubes if (found := _dimmest_channel(levels, i)) is not None}


def _dimmest_channel(levels: np.ndarray, control: int) -> tuple[int, float] | None:
    """The one channel where ``control`` is dimmer than the other FMOs — the
    dye it lacks — and how far it stands out (its relative level there over
    that of its next-lowest channel; smaller is clearer). None if no single
    channel stands out.
    """
    others = np.delete(levels, control, axis=0)
    if len(others) < _MIN_OTHER_FMOS or levels.shape[1] < _MIN_MATRIX_CHANNELS:
        return None
    relative = levels[control] / np.median(others, axis=0)
    lowest, next_lowest = np.argsort(relative)[:2]
    standout = float(relative[lowest] / relative[next_lowest])
    if relative[lowest] >= _DIMMER_THAN_OTHER_FMOS or standout >= _CLEAR_OF_NEXT_CHANNEL:
        return None
    return int(lowest), standout
