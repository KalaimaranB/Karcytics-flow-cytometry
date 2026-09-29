"""Compensation engine — spillover matrix calculation and application.

Spectral overlap between fluorophores is corrected by computing a
spillover matrix from single-stain controls and applying the inverse
to multi-stain data.

Supports three sources:
1. **Computed** from single-stain controls (median-ratio algorithm).
2. **Imported** from external CSV/TSV or other analysis software files.
3. **Cytometer-embedded** $SPILL / $SPILLOVER from FCS metadata.

Reference:
    Roederer, M. (2001). Spectral compensation for flow cytometry.
    *Cytometry*, 45:194-205.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from karcytics_sdk.plugin import get_logger

from .constants import MIN_SINGLE_STAINS, SPILLOVER_SIGNIFICANCE_THRESHOLD
from .fcs_io import FCSData, get_fluorescence_channels

logger = get_logger(__name__, "flow_cytometry")


@dataclass
class CompensationMatrix:
    """Container for a computed or imported compensation matrix.

    Attributes:
        matrix:       The N×N spillover matrix (rows = detector,
                      columns = fluorophore).
        channel_names: Ordered channel names corresponding to rows/columns.
        source:       How the matrix was obtained: ``'computed'``,
                      ``'imported'``, or ``'cytometer'``.
    """

    matrix: np.ndarray
    channel_names: list[str] = field(default_factory=list)
    source: str = "computed"

    @property
    def inverse(self) -> np.ndarray:
        """Return the inverse of the spillover matrix for compensation."""
        return np.linalg.inv(self.matrix)

    @property
    def n_channels(self) -> int:
        return len(self.channel_names)

    def to_dict(self) -> dict:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "matrix": self.matrix.tolist(),
            "channel_names": self.channel_names,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict) -> CompensationMatrix:
        """Deserialize from a dictionary."""
        return cls(
            matrix=np.array(data["matrix"]),
            channel_names=data.get("channel_names", []),
            source=data.get("source", "imported"),
        )


# ── Computation from single-stain controls ───────────────────────────────────


def calculate_spillover_matrix(  # noqa: C901, PLR0912
    single_stains: list[FCSData],
    unstained: FCSData | None = None,
    fluorescence_channels: list[str] | None = None,
) -> CompensationMatrix:
    """Compute the spillover matrix from single-stain control samples.

    Algorithm:
        1. Optionally subtract the unstained control's median from all
           channels (autofluorescence background removal).
        2. For each single-stain sample, identify the **primary channel**
           (highest median fluorescence after background subtraction).
        3. For every channel, compute the ratio:
           ``spillover[primary][ch] = median(ch) / median(primary)``.
        4. The spillover matrix diagonal is always 1.0 by definition.

    Args:
        single_stains:        One :class:`FCSData` per fluorophore, each
                              stained with exactly one dye.
        unstained:            Optional unstained control for background
                              subtraction (autofluorescence removal).
        fluorescence_channels: Explicit channel list.  If ``None``,
                              auto-detected from the first sample.

    Returns:
        A populated :class:`CompensationMatrix`.

    Raises:
        ValueError: If fewer than 2 single-stain samples are provided.
    """
    if len(single_stains) < MIN_SINGLE_STAINS:
        raise ValueError("At least 2 single-stain samples are required.")

    if fluorescence_channels is None:
        fluorescence_channels = get_fluorescence_channels(single_stains[0])

    n = len(fluorescence_channels)
    spillover = np.eye(n, dtype=np.float64)

    # Background subtraction: median of unstained control per channel
    bg = np.zeros(n, dtype=np.float64)
    if unstained is not None and unstained.events is not None:
        idxs = [i for i, ch in enumerate(fluorescence_channels) if ch in unstained.events.columns]
        if idxs:
            cols = [fluorescence_channels[i] for i in idxs]
            bg[idxs] = np.median(unstained.events[cols].values, axis=0)

    # Process each single-stain sample
    channels_assigned: set[int] = set()

    for ss in single_stains:
        if ss.events is None:
            logger.warning("Skipping single-stain sample with no events: %s", ss.file_path)
            continue

        # Compute median for each fluorescence channel
        medians = np.zeros(n, dtype=np.float64)
        idxs = [i for i, ch in enumerate(fluorescence_channels) if ch in ss.events.columns]
        if idxs:
            cols = [fluorescence_channels[i] for i in idxs]
            medians[idxs] = np.median(ss.events[cols].values, axis=0) - bg[idxs]

        # The primary channel = the one with the highest median
        primary_idx = int(np.argmax(medians))
        primary_median = medians[primary_idx]
        primary_ch = fluorescence_channels[primary_idx]

        if primary_median <= 0:
            logger.warning(
                "Single-stain sample '%s' has no positive primary channel. Skipping.",
                ss.file_path.name if ss.file_path else "unknown",
            )
            continue

        if primary_idx in channels_assigned:
            logger.warning(
                "Channel '%s' already assigned by another single-stain. Overwriting.",
                primary_ch,
            )

        logger.debug(
            "Identified '%s' as primary channel for %s (median=%.2f). Spillover ratios:",
            primary_ch,
            ss.file_path.name if ss.file_path else "unknown",
            primary_median,
        )

        # Compute spillover ratios
        for j in range(n):
            if j == primary_idx:
                spillover[primary_idx, j] = 1.0
            else:
                ratio = max(0.0, medians[j]) / primary_median
                spillover[primary_idx, j] = ratio
                if ratio > SPILLOVER_SIGNIFICANCE_THRESHOLD:
                    logger.debug("  -> into %s: %.2f%%", fluorescence_channels[j], ratio * 100)

        channels_assigned.add(primary_idx)

    # Warn about unassigned channels
    for i in range(n):
        if i not in channels_assigned:
            logger.warning(
                "No single-stain sample assigned for channel '%s'. Using identity row.",
                fluorescence_channels[i],
            )

    logger.info(
        "Computed spillover matrix (%d×%d) from %d single-stain controls.",
        n,
        n,
        len(single_stains),
    )

    return CompensationMatrix(
        matrix=spillover,
        channel_names=fluorescence_channels,
        source="computed",
    )


# ── Import from FCS metadata ─────────────────────────────────────────────────


def extract_spill_from_fcs(data: FCSData) -> CompensationMatrix | None:
    """Extract a compensation matrix from FCS file metadata.

    Looks for the ``$SPILL`` or ``$SPILLOVER`` keyword in the FCS
    TEXT segment.  The format is:
    ``n, ch1, ch2, ..., chN, s11, s12, ..., sNN``

    Args:
        data: A loaded :class:`FCSData`.

    Returns:
        A :class:`CompensationMatrix` if found, or None.
    """
    spill_str = None
    for key in ("$SPILLOVER", "$SPILL", "SPILLOVER", "SPILL", "spill", "spillover"):
        if key in data.metadata:
            spill_str = data.metadata[key]
            break

    if spill_str is None:
        return None

    try:
        parts = [p.strip() for p in spill_str.split(",")]
        n = int(parts[0])
        channel_names = parts[1 : n + 1]
        values = [float(v) for v in parts[n + 1 :]]

        if len(values) != n * n:
            logger.warning(
                "SPILL keyword malformed: expected %d values, got %d.",
                n * n,
                len(values),
            )
            return None

        matrix = np.array(values, dtype=np.float64).reshape(n, n)

        logger.info("Extracted %d×%d spillover matrix from FCS metadata.", n, n)

        return CompensationMatrix(
            matrix=matrix,
            channel_names=channel_names,
            source="cytometer",
        )
    except (ValueError, IndexError) as exc:
        logger.warning("Failed to parse SPILL keyword: %s", exc)
        return None


# ── Import from CSV/TSV files ─────────────────────────────────────────────────


def import_matrix_from_csv(path: Path) -> CompensationMatrix:
    """Import a spillover matrix from a CSV or tab-delimited file.

    The file should have channel names as both the first row (header)
    and optionally the first column (row labels).  If no row labels
    are present, the header order is used for both axes.

    Args:
        path: Path to the CSV/TSV file.

    Returns:
        A :class:`CompensationMatrix`.

    Raises:
        ValueError: If the file cannot be parsed as a matrix.
    """
    path = Path(path)
    sep = "\t" if path.suffix in (".tsv", ".txt") else ","

    df = pd.read_csv(path, sep=sep, index_col=0 if _has_row_labels(path, sep) else None)
    channel_names = list(df.columns)
    matrix = df.values.astype(np.float64)

    if matrix.shape[0] != matrix.shape[1]:
        raise ValueError(f"Matrix is not square: {matrix.shape[0]}×{matrix.shape[1]}")

    logger.info("Imported %d×%d matrix from %s.", *matrix.shape, path.name)

    return CompensationMatrix(
        matrix=matrix,
        channel_names=channel_names,
        source="imported",
    )


def export_matrix_to_csv(comp: CompensationMatrix, path: Path) -> None:
    """Export a spillover matrix to a CSV file.

    Args:
        comp: The :class:`CompensationMatrix` to export.
        path: Output file path.
    """
    df = pd.DataFrame(
        comp.matrix,
        index=comp.channel_names,
        columns=comp.channel_names,
    )
    df.to_csv(path)
    logger.info("Exported matrix to %s.", path)


# ── Application ──────────────────────────────────────────────────────────────


def apply_compensation(data: FCSData, comp: CompensationMatrix | None) -> pd.DataFrame:
    """Apply compensation to a dataset using the inverse spillover matrix.

    Compensated values replace the original fluorescence columns in the
    returned DataFrame.  Non-fluorescence columns (FSC, SSC, Time) are
    preserved unchanged.

    Args:
        data: The :class:`FCSData` to compensate.
        comp: A :class:`CompensationMatrix` (usually from
              :func:`calculate_spillover_matrix`), or None to return data unchanged.

    Returns:
        A new DataFrame with compensated fluorescence values.
    """
    raw_events = getattr(data, "raw_events", None)
    if raw_events is not None:
        df = raw_events.copy()
    elif data.events is not None:
        df = data.events.copy()
    else:
        raise ValueError("No event data available for compensation.")

    if comp is None:
        logger.debug("apply_compensation called with None, returning uncompensated events.")
        return df

    channels = comp.channel_names

    # Only compensate channels that exist in the data
    present = [ch for ch in channels if ch in df.columns]
    if not present:
        logger.warning("No matching channels found for compensation.")
        return df

    idx = [channels.index(ch) for ch in present]
    # Invert the submatrix for the present channels rather than subsetting the
    # full inverse: inv(M)[idx, idx] != inv(M[idx, idx]) whenever channels are
    # missing, which silently produced wrong compensated values.
    sub_spillover = comp.matrix[np.ix_(idx, idx)]
    sub_matrix = np.linalg.inv(sub_spillover)

    logger.debug(
        "Applying compensation matrix to %d events. Compensating %d/%d channels.",
        len(df),
        len(present),
        len(channels),
    )
    logger.debug("Using mathematical projection: Compensated = Raw @ Matrix_Inverse")

    raw = df[present].values
    compensated = raw @ sub_matrix
    df[present] = compensated

    return df


# ── Helpers ──────────────────────────────────────────────────────────────────


def _has_row_labels(path: Path, sep: str) -> bool:
    """Check if the first column looks like row labels (non-numeric)."""
    try:
        with open(path) as f:
            f.readline().strip().split(sep)
            first_data = f.readline().strip().split(sep)
            if first_data:
                try:
                    float(first_data[0])
                    return False
                except ValueError:
                    return True
    except (OSError, UnicodeDecodeError, IndexError):
        pass
    return False
