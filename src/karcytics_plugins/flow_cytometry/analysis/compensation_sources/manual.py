"""A spillover matrix typed in by hand, starting from the identity."""

from __future__ import annotations

import numpy as np

from ..compensation import (
    CELL_DEFAULT,
    CELL_ESTIMATED,
    CompensationMatrix,
)
from ..experiment import Sample
from ..fcs_io import (
    FCSData,
    get_fluorescence_channels,
)
from ..state import FlowState
from .base import (
    AskPath,
    InputRow,
    Inputs,
    MatrixSource,
    MatrixSourceError,
    MethodOptions,
    Readiness,
    SourceResult,
)

_MIN_MATRIX_CHANNELS = 2


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
