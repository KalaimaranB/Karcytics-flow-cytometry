"""Ways to obtain a spillover matrix.

Each method — read it from an FCS file, compute it from controls, import
it, or estimate it — is one ``MatrixSource``. The compensation view builds
its method selector from ``MATRIX_SOURCES``, so adding a method means
adding a class here and listing it; the view doesn't change.

Whatever a method produces is a starting point: the view always follows it
with fine-tuning by hand.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PyQt6.QtWidgets import QFileDialog, QWidget

from karcytics_plugins.flow_cytometry.analysis.compensation import (
    CompensationMatrix,
    calculate_spillover_from_fmo,
    calculate_spillover_matrix,
    extract_spill_from_fcs,
    import_matrix_from_csv,
)
from karcytics_plugins.flow_cytometry.analysis.experiment import Sample, SampleRole
from karcytics_plugins.flow_cytometry.analysis.fcs_io import FCSData, get_fluorescence_channels
from karcytics_plugins.flow_cytometry.analysis.state import FlowState

_MIN_SINGLE_STAINS = 2
# Placing an FMO by its signal: it must be this much dimmer than the other
# FMOs' median in the channel of the dye it lacks.
_MISSING_DYE_RATIO = 0.5
_MIN_OTHER_FMOS = 2
_SIGNAL_SAMPLE_EVENTS = 20_000


@dataclass(frozen=True)
class SourceResult:
    """A matrix a source produced, and how to describe that to the user."""

    matrix: CompensationMatrix
    undo_label: str  # the step's name in Edit → Undo
    summary: str  # one line for the view's status note


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
    object_name: str = ""  # the run button's objectName, for tutorial spotlights
    advanced: bool = False  # listed under "Advanced algorithms"

    @abstractmethod
    def readiness(self, state: FlowState) -> tuple[bool, str]:
        """Whether ``state`` has what the method needs, and one line saying so."""

    @abstractmethod
    def obtain(self, state: FlowState, parent: QWidget) -> SourceResult | None:
        """Produce a matrix, or None if the user cancelled.

        May prompt the user (``parent`` owns any dialog). Must not change
        ``state``. Raises ``MatrixSourceError`` when it can't produce one.
        """


def _loaded(state: FlowState, role: SampleRole) -> list[tuple[Sample, FCSData]]:
    """The samples with ``role`` that have data, each with that data."""
    samples = state.data.experiment.get_samples_by_role(role)
    return [(s, s.fcs_data) for s in samples if s.fcs_data is not None]


class SingleStainSource(MatrixSource):
    key = "computed"
    label = "Single-stain controls"
    action = "🔬 Calculate Matrix"
    tooltip = (
        "Compute spillover matrix from single-stain controls.\n"
        "Requires samples tagged with role 'Single Stain'."
    )

    def readiness(self, state: FlowState) -> tuple[bool, str]:
        found = len(_loaded(state, SampleRole.SINGLE_STAIN))
        return (
            found >= _MIN_SINGLE_STAINS,
            f"{found} single-stain control(s) loaded (needs at least {_MIN_SINGLE_STAINS}; "
            "set a sample's role in the Properties panel).",
        )

    def obtain(self, state: FlowState, parent: QWidget) -> SourceResult | None:
        single_stains = [fcs for _, fcs in _loaded(state, SampleRole.SINGLE_STAIN)]
        if len(single_stains) < _MIN_SINGLE_STAINS:
            raise MatrixSourceError(
                "Insufficient Controls",
                f"Found {len(single_stains)} single-stain controls.\n\n"
                "You need at least 2 single-stain samples to compute a spillover matrix.\n\n"
                "Assign sample roles in the Properties panel by selecting each sample in "
                "the tree.",
            )

        unstained_samples = state.data.experiment.get_samples_by_role(SampleRole.UNSTAINED)
        unstained = unstained_samples[0].fcs_data if unstained_samples else None
        try:
            matrix = calculate_spillover_matrix(single_stains, unstained=unstained or None)
        except Exception as exc:
            raise MatrixSourceError(
                "Computation Error", f"Failed to compute compensation matrix:\n{exc}"
            ) from exc
        return SourceResult(
            matrix,
            "Compute Compensation Matrix",
            f"Computed a {matrix.n_channels}×{matrix.n_channels} matrix from "
            f"{len(single_stains)} single-stain controls.",
        )


class FcsMetadataSource(MatrixSource):
    key = "cytometer"
    label = "Embedded in the FCS files"
    action = "📄 Extract from FCS"
    tooltip = "Read the $SPILL/$SPILLOVER keyword embedded in an FCS file's metadata."
    object_name = "ExtractFCSButton"

    @staticmethod
    def _embedded(state: FlowState) -> tuple[Sample, CompensationMatrix] | None:
        """The first loaded sample that carries a matrix, and that matrix."""
        for sample in state.data.experiment.samples.values():
            if sample.fcs_data is None:
                continue
            matrix = extract_spill_from_fcs(sample.fcs_data)
            if matrix is not None:
                return sample, matrix
        return None

    def readiness(self, state: FlowState) -> tuple[bool, str]:
        found = self._embedded(state)
        if found is None:
            return False, "None of the loaded FCS files carries a matrix ($SPILL / $SPILLOVER)."
        return True, f"The cytometer's own matrix, recorded in {found[0].display_name}."

    def obtain(self, state: FlowState, parent: QWidget) -> SourceResult | None:
        found = self._embedded(state)
        if found is not None:
            sample, matrix = found
            return SourceResult(
                matrix,
                "Extract Compensation Matrix",
                f"Extracted the {matrix.n_channels}×{matrix.n_channels} matrix embedded "
                f"in {sample.display_name}.",
            )
        raise MatrixSourceError(
            "No Matrix Found",
            "None of the loaded FCS files contain a $SPILL or $SPILLOVER keyword in their "
            "metadata.\n\nYou can compute a matrix from single-stain controls or import one "
            "from CSV instead.",
        )


class FmoSource(MatrixSource):
    key = "fmo"
    label = "FMO controls"
    action = "🧮 Estimate from FMOs"
    tooltip = (
        "Estimate the spillover matrix from fluorescence-minus-one controls.\n"
        "Each FMO lacks one dye, so its signal in that dye's detector is spill from the "
        "others.\nRequires samples tagged with role 'FMO Control'."
    )

    @staticmethod
    def _controls(state: FlowState) -> tuple[list[str], dict[str, _Fmo], list[str]]:
        """Matrix channels, missing channel → its FMO, and the names of the
        FMOs that couldn't be placed.

        A tube is placed by the dye set on it, else by its name; one whose
        name doesn't say is placed by its signal, among the channels no other
        tube claimed. Only one tube is used per channel.
        """
        # Tubes with the dye set by hand claim their channel first.
        fmos = sorted(
            _loaded(state, SampleRole.FMO_CONTROL), key=lambda pair: pair[0].fmo_minus is None
        )
        if not fmos:
            return [], {}, []
        channels = get_fluorescence_channels(fmos[0][1])
        placed: dict[str, _Fmo] = {}
        unnamed: list[int] = []
        unplaced: list[str] = []
        for index, (sample, fcs) in enumerate(fmos):
            channel = fmo_missing_channel(sample, fcs, channels)
            if channel is None:
                unnamed.append(index)
            elif channel in placed:
                unplaced.append(sample.display_name)
            else:
                placed[channel] = _Fmo(sample.display_name, fcs, "name")

        levels = _signal_levels([fcs for _, fcs in fmos], channels) if unnamed else None
        for index in unnamed:
            sample, fcs = fmos[index]
            free = [c for c, ch in enumerate(channels) if ch not in placed]
            channel_index = None if levels is None else _dimmest_channel(levels, index, free)
            if channel_index is None:
                unplaced.append(sample.display_name)
            else:
                placed[channels[channel_index]] = _Fmo(sample.display_name, fcs, "signal")
        return channels, placed, unplaced

    def readiness(self, state: FlowState) -> tuple[bool, str]:
        channels, placed, unplaced = self._controls(state)
        if not placed and not unplaced:
            return False, (
                "No FMO controls loaded (set a sample's role to FMO Control, and its "
                "Missing dye, in the Properties panel)."
            )
        text = f"FMO controls cover {len(placed)} of {len(channels)} fluorescence channels"
        text += f": {_pairings(placed)}." if placed else "."
        if unplaced:
            text += (
                f" Not used: {', '.join(unplaced)} (its missing dye is unclear, or another "
                "tube covers it). Set each tube's Missing dye in the Properties panel."
            )
        return bool(placed), text

    def obtain(self, state: FlowState, parent: QWidget) -> SourceResult | None:
        channels, placed, unplaced = self._controls(state)
        if not placed:
            raise MatrixSourceError(
                "No Usable FMO Controls",
                "No loaded FMO control could be matched to the dye it lacks.\n\n"
                "Select each FMO sample and set its Missing dye in the Properties panel.",
            )
        try:
            matrix = calculate_spillover_from_fmo(
                {channel: fmo.data for channel, fmo in placed.items()}, channels
            )
        except Exception as exc:
            raise MatrixSourceError(
                "Estimation Error", f"Failed to estimate a matrix from the FMO controls:\n{exc}"
            ) from exc

        summary = (
            f"Estimated a {matrix.n_channels}×{matrix.n_channels} matrix from "
            f"{len(placed)} FMO control(s) ({_pairings(placed)})."
        )
        uncovered = [ch for ch in channels if ch not in placed]
        if uncovered:
            summary += f" No FMO for {', '.join(uncovered)}: spill into those is left at 0."
        if unplaced:
            summary += f" Skipped {', '.join(unplaced)}."
        return SourceResult(matrix, "Estimate Compensation Matrix", summary)


@dataclass(frozen=True)
class _Fmo:
    """An FMO control placed on the channel of the dye it lacks."""

    name: str
    data: FCSData
    placed_by: str  # "name" | "signal"


def _pairings(placed: dict[str, _Fmo]) -> str:
    """'tube → missing channel' for each control, flagging the ones guessed from signal."""
    return ", ".join(
        f"{fmo.name} → {channel}" + (" (from its signal)" if fmo.placed_by == "signal" else "")
        for channel, fmo in placed.items()
    )


def _normalise(name: str) -> str:
    """A dye/marker name reduced to what people keep when retyping it:
    'APC-Cy7-A', 'APC Cy7' and 'APCCy7' all become 'apccy7'.
    """
    name = re.sub(r"-[ahw]$", "", name.casefold().strip())  # area/height/width suffix
    return re.sub(r"[^0-9a-z]", "", name)


def fmo_missing_channel(sample: Sample, fcs: FCSData, channels: list[str]) -> str | None:
    """The channel of the dye an FMO control lacks, read from its labels.

    From ``fmo_minus`` when the user or the experiment template set it,
    else from the marker or channel named in the sample's name.
    """
    names: dict[str, set[str]] = {}
    for channel in channels:
        index = fcs.channels.index(channel) if channel in fcs.channels else -1
        marker = fcs.markers[index] if 0 <= index < len(fcs.markers) else ""
        names[channel] = {_normalise(n) for n in (channel, marker) if n} - {""}

    if sample.fmo_minus:
        candidates = {_normalise(sample.fmo_minus)}
    else:
        # Runs of whole words, so "CD4" doesn't match inside "CD45" but
        # "Pacific Blue" still matches as one name.
        words = re.split(r"[\s_]+", sample.display_name)
        candidates = {
            _normalise(" ".join(words[i:j]))
            for i in range(len(words))
            for j in range(i + 1, len(words) + 1)
        }
    # The longest name wins: "APC Cy7" names APC-Cy7, not APC.
    hits = {
        ch: max(map(len, known & candidates)) for ch, known in names.items() if known & candidates
    }
    best = [ch for ch, length in hits.items() if length == max(hits.values())]
    return best[0] if len(best) == 1 else None


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


def _dimmest_channel(levels: np.ndarray, control: int, free: list[int]) -> int | None:
    """The channel (among ``free``) where ``control`` is clearly dimmer than
    the other FMOs — the dye it lacks. None if nothing stands out.
    """
    others = np.delete(levels, control, axis=0)
    if len(others) < _MIN_OTHER_FMOS or not free:
        return None
    ratios = levels[control, free] / np.median(others[:, free], axis=0)
    dimmest = int(np.argmin(ratios))
    return free[dimmest] if ratios[dimmest] < _MISSING_DYE_RATIO else None


class CsvImportSource(MatrixSource):
    key = "imported"
    label = "Import from a file"
    action = "📥 Import CSV"
    tooltip = "Import a spillover matrix from a CSV or TSV file."

    def readiness(self, state: FlowState) -> tuple[bool, str]:
        return True, "A matrix saved as CSV/TSV, e.g. exported from other analysis software."

    def obtain(self, state: FlowState, parent: QWidget) -> SourceResult | None:
        path, _ = QFileDialog.getOpenFileName(
            parent,
            "Import Spillover Matrix",
            "",
            "CSV Files (*.csv *.tsv *.txt);;All Files (*)",
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


# In the selector's order. The first method that is ready is the default, so
# the matrix the cytometer recorded wins whenever the files carry one.
MATRIX_SOURCES: tuple[MatrixSource, ...] = (
    FcsMetadataSource(),
    SingleStainSource(),
    FmoSource(),
    CsvImportSource(),
)
