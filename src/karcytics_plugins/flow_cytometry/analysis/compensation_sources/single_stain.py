"""A spillover matrix computed from single-stain controls (and an unstained one)."""

from __future__ import annotations

from ..compensation import (
    ControlEvents,
    calculate_spillover_matrix,
)
from ..experiment import Sample, SampleRole
from ..fcs_io import (
    FCSData,
    get_fluorescence_channels,
)
from ..fit_population import (
    fit_events,
)
from ..state import FlowState
from .base import (
    FIT_ON_NOTE,
    AskPath,
    InputRow,
    Inputs,
    MatrixSource,
    MatrixSourceError,
    MethodOptions,
    Readiness,
    SourceResult,
    events_used,
    gate_names,
    loaded_samples,
)

_MIN_SINGLE_STAINS = 2


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
        "control underestimates spill." + FIT_ON_NOTE
    )

    def readiness(self, state: FlowState, _options: MethodOptions) -> Readiness:
        found = len(loaded_samples(state, SampleRole.SINGLE_STAIN))
        return Readiness(
            found >= _MIN_SINGLE_STAINS,
            f"{found} single-stain control(s) loaded (needs at least {_MIN_SINGLE_STAINS}; "
            "set a sample's role in the Properties panel).",
        )

    def obtain(
        self, state: FlowState, _ask_path: AskPath | None, options: MethodOptions
    ) -> SourceResult | None:
        stains = loaded_samples(state, SampleRole.SINGLE_STAIN)
        if len(stains) < _MIN_SINGLE_STAINS:
            raise MatrixSourceError(
                "Insufficient Controls",
                f"Found {len(stains)} single-stain controls.\n\n"
                "You need at least 2 single-stain samples to compute a spillover matrix.\n\n"
                "Assign sample roles in the Properties panel by selecting each sample in "
                "the tree.",
            )

        unstained = loaded_samples(state, SampleRole.UNSTAINED)[:1]
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
        controls = loaded_samples(state, SampleRole.SINGLE_STAIN, SampleRole.UNSTAINED)
        return gate_names([sample for sample, _ in controls])

    def inputs(self, state: FlowState, options: MethodOptions) -> Inputs | None:
        rows = [
            InputRow(
                sample.sample_id,
                (sample.display_name, used_as, events_used(sample, options.gate)),
            )
            for used_as, role in (
                ("single stain", SampleRole.SINGLE_STAIN),
                ("unstained (background)", SampleRole.UNSTAINED),
            )
            for sample, _ in loaded_samples(state, role)
        ]
        return Inputs(("Control", "Used as", "Events used"), tuple(rows))


def _control(sample: Sample, fcs: FCSData, gate: str | None) -> ControlEvents | None:
    fit = fit_events(sample, gate)
    return None if fit is None else ControlEvents(fit.events, fcs.file_path)
