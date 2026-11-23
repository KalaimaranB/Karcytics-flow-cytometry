"""The spillover matrix the cytometer recorded in the FCS files ($SPILL / $SPILLOVER)."""

from __future__ import annotations

from ..compensation import (
    CompensationMatrix,
    extract_spill_from_fcs,
    same_matrix,
)
from ..experiment import Sample
from ..state import FlowState
from .base import (
    SETUP_HINT,
    AskPath,
    InputRow,
    Inputs,
    MatrixSource,
    MatrixSourceError,
    MethodOptions,
    Readiness,
    SourceResult,
)

# ── Embedded in the FCS files ─────────────────────────────────────────


class FcsMetadataSource(MatrixSource):
    """The matrix the cytometer recorded in an FCS file's $SPILL keyword."""

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
        """Ready when a loaded file carries a matrix; warns when the files' matrices differ."""
        picked = self._pick(state, options)
        if picked is None:
            return Readiness(
                False, "None of the loaded FCS files carries a matrix ($SPILL / $SPILLOVER)."
            )
        text = f"The cytometer's own matrix, as recorded in {picked[0].display_name}."
        if any(not same_matrix(matrix, picked[1]) for _, matrix in self._embedded(state)):
            text += " Other files carry a different one." + SETUP_HINT
        return Readiness(True, text)

    def obtain(
        self, state: FlowState, _ask_path: AskPath | None, options: MethodOptions
    ) -> SourceResult | None:
        """The picked file's embedded matrix."""
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
        """The samples whose files carry a matrix."""
        return [(sample.display_name, sample.sample_id) for sample, _ in self._embedded(state)]

    def inputs(self, state: FlowState, options: MethodOptions) -> Inputs | None:
        """Every loaded sample, and whether its file carries a matrix."""
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
                elif same_matrix(matrix, picked[1]):
                    cells = (size, "same matrix")
                else:
                    cells = (size, "different matrix")
            rows.append(InputRow(sample.sample_id, (sample.display_name, *cells)))
        return Inputs(("Sample", "Embedded matrix", "Used"), tuple(rows))
