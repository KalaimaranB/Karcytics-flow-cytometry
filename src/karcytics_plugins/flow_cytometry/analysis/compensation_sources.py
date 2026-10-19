"""Ways to obtain a spillover matrix.

Each method — read it from an FCS file, compute it from controls, import
it, or estimate it — is one ``MatrixSource``. The compensation view builds
its method selector and its Method setup page from ``MATRIX_SOURCES``, so
adding a method means adding a class here and listing it; the view doesn't
change.

A method is expected to be open about what it does: ``explanation`` says
how it works, ``inputs()`` shows what it will use before it runs, and
``SourceResult.report`` shows what the run rested on.

Whatever a method produces is a starting point: the view always follows it
with fine-tuning by hand.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

import numpy as np
import pandas as pd

from .compensation import (
    CELL_DEFAULT,
    CELL_ESTIMATED,
    CompensationMatrix,
    ControlEvents,
    DetectorFit,
    calculate_spillover_from_fmo,
    calculate_spillover_matrix,
    extract_spill_from_fcs,
    fmo_fit_detail,
    import_matrix_from_csv,
)
from .experiment import Sample, SampleRole
from .fcs_io import (
    FCSData,
    get_channel_marker_label,
    get_fluorescence_channels,
)
from .fit_population import (
    FitEvents,
    fit_events,
    scatter_gates,
)
from .services import experiment_edits
from .state import FlowState

_MIN_SINGLE_STAINS = 2
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

_SAME_MATRIX_TOLERANCE = 5e-5
_SETUP_HINT = " See Method setup."
_ILLUSTRATION_EVENTS = 3000  # points drawn; the fit itself uses far more
_EXAMPLE_KEY = ""
_EXAMPLE_LABEL = "Example data (load FMO controls to see your own)"


# ── What a method tells the view ──────────────────────────────────────


@dataclass
class MethodOptions:
    """The user's choices for one method, made on the Method setup page."""

    sample_id: str | None = None  # the sample to read from; None = the method's default
    gate: str | None = None  # the scatter gate fits are restricted to; None = all events


class Table(NamedTuple):
    headers: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]


@dataclass(frozen=True)
class InputRow:
    """One sample a method will use (or pass over), and why."""

    sample_id: str
    cells: tuple[str, ...]
    # The value the user can set for this sample: (label, value) options and
    # the current one. Empty when the method offers no per-sample choice.
    choices: tuple[tuple[str, str | None], ...] = ()
    choice: str | None = None


@dataclass(frozen=True)
class Inputs:
    """What a method would use if it ran now."""

    headers: tuple[str, ...]  # one per ``InputRow.cells`` entry
    rows: tuple[InputRow, ...]
    choice_header: str = ""  # the column of per-sample choices, shown second


@dataclass(frozen=True)
class FitIllustration:
    """One fit of a method, reduced to a picture: how the reading in one
    detector (``y``) rises with the signal in another (``x``).
    """

    tube: str  # the control the events come from
    missing: str  # the detector on Y — the dye the tube lacks
    other: str  # the detector on X — the dye leaking in
    x: np.ndarray
    y: np.ndarray  # the Y detector with every other dye's share already removed
    ignored: np.ndarray  # events the robust fit largely ignored
    slope: float  # the robust fit
    plain_slope: float  # an ordinary fit through every event
    events: int  # events the fit used (``x``/``y`` are a sample of them)
    example: bool = False  # made-up data, not the user's


class Readiness(NamedTuple):
    """Whether a method can run on the loaded data, and what it found."""

    ready: bool
    text: str  # one short line


@dataclass(frozen=True)
class SourceResult:
    """A matrix a source produced, and how to describe that to the user."""

    matrix: CompensationMatrix
    undo_label: str  # the step's name in Edit → Undo
    summary: str  # one line for the view's status note
    report: Table | None = None  # what the run rested on, for the Method setup page


# Asks the user for a file to open: (dialog title, file filter) -> path, or None if cancelled.
AskPath = Callable[[str, str], str | None]


class MatrixSourceError(Exception):
    """A source couldn't produce a matrix; ``title``/``str()`` explain why."""

    def __init__(self, title: str, message: str) -> None:
        super().__init__(message)
        self.title = title


class MatrixSource(ABC):
    """One way to obtain a spillover matrix."""

    key: str  # the ``CompensationMatrix.source`` its matrices carry
    label: str  # the method's name in the selector
    action: str  # the button that runs it
    tooltip: str
    explanation: str = ""  # how the method works, in plain terms (rich text)
    object_name: str = ""  # the run button's objectName, for tutorial spotlights
    reports: bool = False  # its results carry a ``SourceResult.report``
    by_hand: bool = False  # every value is the user's, so "fine-tuned" says nothing

    @abstractmethod
    def readiness(self, state: FlowState, options: MethodOptions) -> Readiness:
        """Whether ``state`` has what the method needs, and what it found."""

    @abstractmethod
    def obtain(
        self, state: FlowState, ask_path: AskPath | None, options: MethodOptions
    ) -> SourceResult | None:
        """Produce a matrix, or None if the user cancelled.

        May ask the user for a file through ``ask_path``. Must not change
        ``state``. Raises ``MatrixSourceError`` when it can't produce one.
        """

    def inputs(self, state: FlowState, options: MethodOptions) -> Inputs | None:
        """The samples the method would use now; None if it uses none."""

    def set_choice(self, state: FlowState, sample_id: str, value: str | None) -> None:
        """Store the user's pick from an ``InputRow.choices`` column."""

    def sample_choices(self, state: FlowState) -> list[tuple[str, str]] | None:
        """(label, sample id) to offer as ``MethodOptions.sample_id``; None if unused."""

    def gate_choices(self, state: FlowState) -> list[str] | None:
        """Scatter gates to offer as ``MethodOptions.gate``; None if the method doesn't fit."""

    def illustration_choices(self, state: FlowState) -> list[tuple[str, str]] | None:
        """(label, key) of the fits ``illustration()`` can draw; None if it draws none."""

    def illustration(
        self, state: FlowState, options: MethodOptions, key: str
    ) -> FitIllustration | None:
        """The fit behind ``key``, as the method would run it now."""


# ── Shared helpers ────────────────────────────────────────────────────


def _loaded(state: FlowState, *roles: SampleRole) -> list[tuple[Sample, FCSData]]:
    """The samples with one of ``roles`` that have data, each with that data."""
    return [
        (s, s.fcs_data)
        for role in roles
        for s in state.data.experiment.get_samples_by_role(role)
        if s.fcs_data is not None
    ]


def _gates_of(samples: list[Sample]) -> list[str]:
    """Every scatter gate found on any of ``samples``, in first-seen order."""
    return list(dict.fromkeys(path for sample in samples for path in scatter_gates(sample)))


def _events_used(sample: Sample, gate: str | None) -> str:
    fit = fit_events(sample, gate)
    return "no data" if fit is None else fit.describe(gate)


_FIT_ON_NOTE = (
    "<br><br><b>Fit on.</b> By default every recorded event is used. Choosing a scatter "
    "gate restricts the calculation to that population (the real cells, without debris "
    "and aggregates), which usually gives a cleaner estimate. The finished matrix is still "
    "applied to every event. Only gates drawn on FSC/SSC are offered: a gate on a "
    "fluorescence axis depends on the very compensation being calculated. A control "
    "without the chosen gate is used whole, and the table says so."
)


# ── Embedded in the FCS files ─────────────────────────────────────────


class FcsMetadataSource(MatrixSource):
    key = "cytometer"
    label = "Embedded in the FCS files"
    action = "📄 Extract from FCS"
    tooltip = "Read the $SPILL/$SPILLOVER keyword embedded in an FCS file's metadata."
    object_name = "ExtractFCSButton"
    explanation = (
        "<b>How it works.</b> Nothing is calculated. Most cytometers store the spillover "
        "matrix that was set up at acquisition inside each FCS file (the $SPILL or "
        "$SPILLOVER keyword), and this method copies it out exactly as recorded.<br><br>"
        "<b>Which file.</b> By default the first loaded sample that carries a matrix is "
        "used. Files from one run normally carry the same matrix; the table below shows "
        "which samples have one and whether they agree, and you can pick the sample to "
        "read from.<br><br>"
        "<b>Limits.</b> The matrix is only as good as the setup on the instrument that "
        "day. A zero may mean 'no spill' or 'never measured'."
    )

    @staticmethod
    def _embedded(state: FlowState) -> list[tuple[Sample, CompensationMatrix]]:
        """Each loaded sample that carries a matrix, with that matrix."""
        found = []
        for sample in state.data.experiment.samples.values():
            matrix = extract_spill_from_fcs(sample.fcs_data) if sample.fcs_data else None
            if matrix is not None:
                found.append((sample, matrix))
        return found

    def _pick(
        self, state: FlowState, options: MethodOptions
    ) -> tuple[Sample, CompensationMatrix] | None:
        found = self._embedded(state)
        chosen = [pair for pair in found if pair[0].sample_id == options.sample_id]
        return next(iter(chosen or found), None)

    def readiness(self, state: FlowState, options: MethodOptions) -> Readiness:
        picked = self._pick(state, options)
        if picked is None:
            return Readiness(
                False, "None of the loaded FCS files carries a matrix ($SPILL / $SPILLOVER)."
            )
        text = f"The cytometer's own matrix, as recorded in {picked[0].display_name}."
        if any(not _same_values(matrix, picked[1]) for _, matrix in self._embedded(state)):
            text += " Other files carry a different one." + _SETUP_HINT
        return Readiness(True, text)

    def obtain(
        self, state: FlowState, _ask_path: AskPath | None, options: MethodOptions
    ) -> SourceResult | None:
        picked = self._pick(state, options)
        if picked is None:
            raise MatrixSourceError(
                "No Matrix Found",
                "None of the loaded FCS files contain a $SPILL or $SPILLOVER keyword in their "
                "metadata.\n\nYou can compute a matrix from single-stain controls or import one "
                "from CSV instead.",
            )
        sample, matrix = picked
        return SourceResult(
            matrix,
            "Extract Compensation Matrix",
            f"Extracted the {matrix.n_channels}×{matrix.n_channels} matrix embedded "
            f"in {sample.display_name}.",
        )

    def sample_choices(self, state: FlowState) -> list[tuple[str, str]] | None:
        return [(sample.display_name, sample.sample_id) for sample, _ in self._embedded(state)]

    def inputs(self, state: FlowState, options: MethodOptions) -> Inputs | None:
        picked = self._pick(state, options)
        embedded = {sample.sample_id: matrix for sample, matrix in self._embedded(state)}
        rows = []
        for sample in state.data.experiment.samples.values():
            if sample.fcs_data is None:
                continue
            matrix = embedded.get(sample.sample_id)
            if matrix is None or picked is None:
                cells = ("none", "")
            else:
                size = f"{matrix.n_channels}×{matrix.n_channels}"
                if sample is picked[0]:
                    cells = (size, "read from this sample")
                elif _same_values(matrix, picked[1]):
                    cells = (size, "same matrix")
                else:
                    cells = (size, "different matrix")
            rows.append(InputRow(sample.sample_id, (sample.display_name, *cells)))
        return Inputs(("Sample", "Embedded matrix", "Used"), tuple(rows))


def _same_values(a: CompensationMatrix, b: CompensationMatrix) -> bool:
    """Same matrix to the four decimals shown; files round the last digits differently."""
    return (
        a.channel_names == b.channel_names
        and a.matrix.shape == b.matrix.shape
        and np.allclose(a.matrix, b.matrix, rtol=0.0, atol=_SAME_MATRIX_TOLERANCE)
    )


# ── Single-stain controls ─────────────────────────────────────────────


class SingleStainSource(MatrixSource):
    key = "computed"
    label = "Single-stain controls"
    action = "🔬 Calculate Matrix"
    tooltip = (
        "Compute spillover matrix from single-stain controls.\n"
        "Requires samples tagged with role 'Single Stain'."
    )
    explanation = (
        "<b>How it works.</b> A single-stain control carries one dye, so everything it "
        "shows in the other detectors is that dye's spill.<br>"
        "1. Each control's median is taken in every fluorescence channel, on its "
        "uncompensated events (minus the unstained control's median, if one is loaded).<br>"
        "2. The channel with the highest median is taken as that control's dye.<br>"
        "3. Spill into each other detector is its median divided by the dye's own "
        "median.<br><br>"
        "<b>Limits.</b> A dye with no control keeps an empty row (greyed in the matrix). "
        "Medians assume most of the control is positive for its dye; a mostly negative "
        "control underestimates spill." + _FIT_ON_NOTE
    )

    def readiness(self, state: FlowState, _options: MethodOptions) -> Readiness:
        found = len(_loaded(state, SampleRole.SINGLE_STAIN))
        return Readiness(
            found >= _MIN_SINGLE_STAINS,
            f"{found} single-stain control(s) loaded (needs at least {_MIN_SINGLE_STAINS}; "
            "set a sample's role in the Properties panel).",
        )

    def obtain(
        self, state: FlowState, _ask_path: AskPath | None, options: MethodOptions
    ) -> SourceResult | None:
        stains = _loaded(state, SampleRole.SINGLE_STAIN)
        if len(stains) < _MIN_SINGLE_STAINS:
            raise MatrixSourceError(
                "Insufficient Controls",
                f"Found {len(stains)} single-stain controls.\n\n"
                "You need at least 2 single-stain samples to compute a spillover matrix.\n\n"
                "Assign sample roles in the Properties panel by selecting each sample in "
                "the tree.",
            )

        unstained = _loaded(state, SampleRole.UNSTAINED)[:1]
        controls = [_control(sample, fcs, options.gate) for sample, fcs in stains]
        try:
            matrix = calculate_spillover_matrix(
                [control for control in controls if control is not None],
                unstained=_control(*unstained[0], options.gate) if unstained else None,
                fluorescence_channels=get_fluorescence_channels(stains[0][1]),
            )
        except Exception as exc:
            raise MatrixSourceError(
                "Computation Error", f"Failed to compute compensation matrix:\n{exc}"
            ) from exc
        return SourceResult(
            matrix,
            "Compute Compensation Matrix",
            f"Computed a {matrix.n_channels}×{matrix.n_channels} matrix from "
            f"{len(stains)} single-stain controls"
            + (f", on '{options.gate}'." if options.gate else "."),
        )

    def gate_choices(self, state: FlowState) -> list[str] | None:
        controls = _loaded(state, SampleRole.SINGLE_STAIN, SampleRole.UNSTAINED)
        return _gates_of([sample for sample, _ in controls])

    def inputs(self, state: FlowState, options: MethodOptions) -> Inputs | None:
        rows = [
            InputRow(
                sample.sample_id,
                (sample.display_name, used_as, _events_used(sample, options.gate)),
            )
            for used_as, role in (
                ("single stain", SampleRole.SINGLE_STAIN),
                ("unstained (background)", SampleRole.UNSTAINED),
            )
            for sample, _ in _loaded(state, role)
        ]
        return Inputs(("Control", "Used as", "Events used"), tuple(rows))


def _control(sample: Sample, fcs: FCSData, gate: str | None) -> ControlEvents | None:
    fit = fit_events(sample, gate)
    return None if fit is None else ControlEvents(fit.events, fcs.file_path)


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
        "1 means the detector mostly sees other dyes." + _FIT_ON_NOTE
    )

    @staticmethod
    def _placements(state: FlowState) -> tuple[list[str], list[_Placement]]:
        """The matrix channels, and each FMO control with the dye it lacks.

        A tube is placed by the dye recorded on it (set by the user first,
        then found earlier from its data). Any other tube is placed by its
        data, which is recorded on it so this is done once, and failing that
        by its name. Only one tube is used per channel.
        """
        fmos = _loaded(state, SampleRole.FMO_CONTROL)
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
        return Readiness(bool(used), text + _SETUP_HINT)

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
        return _gates_of([sample for sample, _ in _loaded(state, SampleRole.FMO_CONTROL)])

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
                    _events_used(p.sample, options.gate) if p.used else "—",
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


# ── Import from a file ────────────────────────────────────────────────


class CsvImportSource(MatrixSource):
    key = "imported"
    label = "Import from a file"
    action = "📥 Import CSV"
    tooltip = "Import a spillover matrix from a CSV or TSV file."
    explanation = (
        "<b>How it works.</b> Nothing is calculated. The matrix is read from a CSV, TSV "
        "or TXT file exactly as saved, with channel names taken from the header row.<br><br>"
        "<b>Limits.</b> The file must use the same channel names as your samples: "
        "channels that don't match are not compensated."
    )

    def readiness(self, _state: FlowState, _options: MethodOptions) -> Readiness:
        return Readiness(
            True, "A matrix saved as CSV/TSV, e.g. exported from other analysis software."
        )

    def obtain(
        self, _state: FlowState, ask_path: AskPath | None, _options: MethodOptions
    ) -> SourceResult | None:
        path = (
            ask_path("Import Spillover Matrix", "CSV Files (*.csv *.tsv *.txt);;All Files (*)")
            if ask_path
            else None
        )
        if not path:
            return None
        try:
            matrix = import_matrix_from_csv(Path(path))
        except Exception as exc:
            raise MatrixSourceError("Import Error", f"Failed to import matrix:\n{exc}") from exc
        return SourceResult(
            matrix,
            "Import Compensation Matrix",
            f"Imported a {matrix.n_channels}×{matrix.n_channels} matrix from {Path(path).name}.",
        )


# ── Manual entry ──────────────────────────────────────────────────────


class ManualSource(MatrixSource):
    key = "manual"
    label = "Manual entry"
    action = "✍ Start a blank matrix"
    by_hand = True
    tooltip = (
        "Start from a matrix with no spill (every off-diagonal value 0) and type each "
        "value in yourself."
    )
    explanation = (
        "<b>How it works.</b> Nothing is calculated or read. You get a matrix over your "
        "samples' fluorescence channels with 1 on the diagonal and 0 everywhere else, "
        "which compensates nothing, and you type each spill value in on the Matrix page, "
        "watching the before/after preview as you go.<br><br>"
        "<b>Which channels.</b> The fluorescence channels of the sample chosen under "
        "<i>Read from</i> (by default the first loaded sample), listed below. Scatter and "
        "time channels are left out.<br><br>"
        "<b>On the Matrix page.</b> Cells you haven't set yet are shown in grey italic; "
        "the ones you have typed turn green bold, so you can see what is left to do. "
        "The guide under the matrix (the ? button) describes what a correct value looks "
        "like on the plots.<br><br>"
        "<b>Limits.</b> Every value rests on your reading of the plots. Use it when you "
        "have no controls and no embedded matrix, or to enter values from a lab notebook "
        "or a publication."
    )

    @staticmethod
    def _sample(state: FlowState, options: MethodOptions) -> tuple[Sample, FCSData] | None:
        loaded = [
            (s, s.fcs_data)
            for s in state.data.experiment.samples.values()
            if s.fcs_data is not None
        ]
        chosen = [pair for pair in loaded if pair[0].sample_id == options.sample_id]
        return next(iter(chosen or loaded), None)

    def readiness(self, state: FlowState, options: MethodOptions) -> Readiness:
        picked = self._sample(state, options)
        if picked is None:
            return Readiness(False, "Load a sample first: its channels define the matrix.")
        count = len(get_fluorescence_channels(picked[1]))
        return Readiness(
            count > 1,
            f"A blank {count}×{count} matrix over {picked[0].display_name}'s fluorescence "
            "channels, for you to fill in.",
        )

    def obtain(
        self, state: FlowState, _ask_path: AskPath | None, options: MethodOptions
    ) -> SourceResult | None:
        picked = self._sample(state, options)
        channels = get_fluorescence_channels(picked[1]) if picked else []
        if len(channels) < _MIN_MATRIX_CHANNELS:
            raise MatrixSourceError(
                "No Channels",
                "A matrix needs at least two fluorescence channels.\n\n"
                "Load a sample first: its channels define the matrix.",
            )
        size = len(channels)
        # Nothing is set yet: every off-diagonal cell is at its default.
        origin = np.full((size, size), CELL_DEFAULT, dtype=np.int8)
        np.fill_diagonal(origin, CELL_ESTIMATED)
        matrix = CompensationMatrix(np.eye(size), channels, source=self.key, origin=origin)
        return SourceResult(
            matrix,
            "Start Manual Compensation Matrix",
            f"Started a blank {size}×{size} matrix: every spill value is 0 until you type it in.",
        )

    def sample_choices(self, state: FlowState) -> list[tuple[str, str]] | None:
        return [
            (s.display_name, s.sample_id)
            for s in state.data.experiment.samples.values()
            if s.fcs_data is not None
        ]

    def inputs(self, state: FlowState, options: MethodOptions) -> Inputs | None:
        picked = self._sample(state, options)
        if picked is None:
            return Inputs(("Channel", "Marker"), ())
        _sample, fcs = picked
        rows = []
        for channel in get_fluorescence_channels(fcs):
            index = fcs.channels.index(channel)
            marker = fcs.markers[index] if index < len(fcs.markers) else ""
            rows.append(InputRow("", (channel, marker or "—")))
        return Inputs(("Channel", "Marker"), tuple(rows))


# In the selector's order. The first method that is ready is the default, so
# the matrix the cytometer recorded wins whenever the files carry one.
MATRIX_SOURCES: tuple[MatrixSource, ...] = (
    FcsMetadataSource(),
    SingleStainSource(),
    FmoSource(),
    CsvImportSource(),
    ManualSource(),
)
