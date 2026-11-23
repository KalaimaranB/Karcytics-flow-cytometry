"""A spillover matrix imported from a CSV file."""

from __future__ import annotations

from pathlib import Path

from ..compensation import (
    import_matrix_from_csv,
)
from ..state import FlowState
from .base import (
    AskPath,
    MatrixSource,
    MatrixSourceError,
    MethodOptions,
    Readiness,
    SourceResult,
)

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
