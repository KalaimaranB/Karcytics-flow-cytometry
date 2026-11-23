"""What every way of obtaining a spillover matrix tells the compensation view, and helpers they share."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import NamedTuple

import numpy as np

from ..compensation import (
    CompensationMatrix,
)
from ..experiment import Sample, SampleRole
from ..fcs_io import (
    FCSData,
)
from ..fit_population import (
    fit_events,
    scatter_gates,
)
from ..state import FlowState

SETUP_HINT = " See Method setup."  # appended to a readiness line that needs a choice


# ── What a method tells the view ──────────────────────────────────────


@dataclass
class MethodOptions:
    """The user's choices for one method, made on the Method setup page."""

    sample_id: str | None = None  # the sample to read from; None = the method's default
    gate: str | None = None  # the scatter gate fits are restricted to; None = all events


class Table(NamedTuple):
    """A table for a method's explanation: header row and rows."""

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


def loaded_samples(state: FlowState, *roles: SampleRole) -> list[tuple[Sample, FCSData]]:
    """The samples with one of ``roles`` that have data, each with that data."""
    return [
        (s, s.fcs_data)
        for role in roles
        for s in state.data.experiment.get_samples_by_role(role)
        if s.fcs_data is not None
    ]


def gate_names(samples: list[Sample]) -> list[str]:
    """Every scatter gate found on any of ``samples``, in first-seen order."""
    return list(dict.fromkeys(path for sample in samples for path in scatter_gates(sample)))


def events_used(sample: Sample, gate: str | None) -> str:
    """How many events of ``sample`` the fit uses, as a phrase."""
    fit = fit_events(sample, gate)
    return "no data" if fit is None else fit.describe(gate)


FIT_ON_NOTE = (
    "<br><br><b>Fit on.</b> By default every recorded event is used. Choosing a scatter "
    "gate restricts the calculation to that population (the real cells, without debris "
    "and aggregates), which usually gives a cleaner estimate. The finished matrix is still "
    "applied to every event. Only gates drawn on FSC/SSC are offered: a gate on a "
    "fluorescence axis depends on the very compensation being calculated. A control "
    "without the chosen gate is used whole, and the table says so."
)
