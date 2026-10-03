"""Ways to obtain a spillover matrix.

Each way — read it from an FCS file, compute it from controls, import it,
or (later) estimate it — is one ``MatrixSource``. The compensation view
builds its "get a matrix" buttons from ``MATRIX_SOURCES``, so adding a
method means adding a class here and listing it; the view doesn't change.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtWidgets import QFileDialog, QWidget

from karcytics_plugins.flow_cytometry.analysis.compensation import (
    CompensationMatrix,
    calculate_spillover_matrix,
    extract_spill_from_fcs,
    import_matrix_from_csv,
)
from karcytics_plugins.flow_cytometry.analysis.experiment import SampleRole
from karcytics_plugins.flow_cytometry.analysis.state import FlowState

_MIN_SINGLE_STAINS = 2


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

    label: str
    tooltip: str
    object_name: str = ""  # widget objectName, for tutorial spotlights
    primary: bool = False  # drawn as the emphasised button

    @abstractmethod
    def obtain(self, state: FlowState, parent: QWidget) -> SourceResult | None:
        """Produce a matrix, or None if the user cancelled.

        May prompt the user (``parent`` owns any dialog). Must not change
        ``state``. Raises ``MatrixSourceError`` when it can't produce one.
        """


class SingleStainSource(MatrixSource):
    label = "🔬 Calculate Matrix"
    tooltip = (
        "Compute spillover matrix from single-stain controls.\n"
        "Requires samples tagged with role 'Single Stain'."
    )
    primary = True

    def obtain(self, state: FlowState, parent: QWidget) -> SourceResult | None:
        exp = state.data.experiment
        single_stains = [
            s.fcs_data
            for s in exp.get_samples_by_role(SampleRole.SINGLE_STAIN)
            if s.fcs_data is not None
        ]
        if len(single_stains) < _MIN_SINGLE_STAINS:
            raise MatrixSourceError(
                "Insufficient Controls",
                f"Found {len(single_stains)} single-stain controls.\n\n"
                "You need at least 2 single-stain samples to compute a spillover matrix.\n\n"
                "Assign sample roles in the Properties panel by selecting each sample in "
                "the tree.",
            )

        unstained_samples = exp.get_samples_by_role(SampleRole.UNSTAINED)
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
    label = "📄 Extract from FCS"
    tooltip = "Read the $SPILL/$SPILLOVER keyword embedded in an FCS file's metadata."
    object_name = "ExtractFCSButton"

    def obtain(self, state: FlowState, parent: QWidget) -> SourceResult | None:
        for sample in state.data.experiment.samples.values():
            if sample.fcs_data is None:
                continue
            matrix = extract_spill_from_fcs(sample.fcs_data)
            if matrix is not None:
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


class CsvImportSource(MatrixSource):
    label = "📥 Import CSV"
    tooltip = "Import a spillover matrix from a CSV or TSV file."

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


MATRIX_SOURCES: tuple[MatrixSource, ...] = (
    SingleStainSource(),
    FcsMetadataSource(),
    CsvImportSource(),
)
