"""Compensation engine — spillover matrix calculation and application.

Spectral overlap between fluorophores is corrected by computing a
spillover matrix from single-stain controls and applying the inverse
to multi-stain data.

Supports four sources:
1. **Cytometer-embedded** $SPILL / $SPILLOVER from FCS metadata.
2. **Computed** from single-stain controls (median-ratio algorithm).
3. **Estimated** from FMO controls (regression on the missing dye's detector).
4. **Imported** from external CSV/TSV or other analysis software files.

Any of them can then be fine-tuned by hand (``fine_tuned``).

Reference:
    Roederer, M. (2001). Spectral compensation for flow cytometry.
    *Cytometry*, 45:194-205.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from karcytics_sdk.plugin import get_logger

from .constants import MIN_SINGLE_STAINS, SPILLOVER_SIGNIFICANCE_THRESHOLD
from .derived.sync import strip_derived_columns
from .fcs_io import FCSData, get_fluorescence_channels

logger = get_logger(__name__, "flow_cytometry")


# Where a matrix cell's value came from (``CompensationMatrix.origin``).
CELL_ESTIMATED = 0  # the method measured it
CELL_DEFAULT = 1  # the method had no control for it; left at its default
CELL_EDITED = 2  # set by hand

# FMO fit: events used per control, and the Huber tuning constant (95%
# efficiency on clean data).
_FMO_FIT_MAX_EVENTS = 100_000
_HUBER_K = 1.345
_ROBUST_FIT_ITERATIONS = 30
_LARGELY_IGNORED_WEIGHT = 0.5


@dataclass(frozen=True)
class ControlEvents:
    """The events of one control an estimate is fitted on (see ``fit_population``)."""

    events: pd.DataFrame
    file_path: Path | None = None


@dataclass(frozen=True)
class DetectorFit:
    """How the FMO fit for one detector went — what the estimate rests on."""

    channel: str
    events: int  # events the fit used
    down_weighted: float  # share of them the robust fit largely ignored
    r_squared: float  # how much of the detector's signal the other dyes explain


@dataclass
class CompensationMatrix:
    """Container for a computed or imported compensation matrix.

    Attributes:
        matrix:       The N×N spillover matrix (rows = fluorophore,
                      columns = detector): ``matrix[i, j]`` is the share
                      of fluorophore ``i``'s signal seen in detector ``j``.
        channel_names: Ordered channel names corresponding to rows/columns.
        source:       How the matrix was obtained: ``'cytometer'``,
                      ``'computed'``, ``'fmo'``, or ``'imported'``.
        fine_tuned:   Cells were edited by hand since ``source`` produced it.
        origin:       Per cell, where its value came from (``CELL_*``);
                      None when the method produced every cell.
    """

    matrix: np.ndarray
    channel_names: list[str] = field(default_factory=list)
    source: str = "computed"
    fine_tuned: bool = False
    origin: np.ndarray | None = None

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
            "fine_tuned": self.fine_tuned,
            "origin": None if self.origin is None else self.origin.tolist(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> CompensationMatrix:
        """Deserialize from a dictionary."""
        return cls(
            matrix=np.array(data["matrix"]),
            channel_names=data.get("channel_names", []),
            source=data.get("source", "imported"),
            fine_tuned=bool(data.get("fine_tuned", False)),
            origin=None if data.get("origin") is None else np.array(data["origin"], dtype=np.int8),
        )


@dataclass
class SavedMatrix:
    """A matrix kept under a name in the workspace's matrix library."""

    name: str
    matrix: CompensationMatrix
    saved_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def to_dict(self) -> dict:
        return {"name": self.name, "saved_id": self.saved_id, "matrix": self.matrix.to_dict()}

    @classmethod
    def from_dict(cls, data: dict) -> SavedMatrix:
        return cls(
            name=data["name"],
            matrix=CompensationMatrix.from_dict(data["matrix"]),
            saved_id=data.get("saved_id") or uuid.uuid4().hex,
        )


# ── Computation from single-stain controls ───────────────────────────────────


def calculate_spillover_matrix(  # noqa: C901, PLR0912
    single_stains: Sequence[FCSData | ControlEvents],
    unstained: FCSData | ControlEvents | None = None,
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
        first = single_stains[0]
        if not isinstance(first, FCSData):
            raise ValueError("fluorescence_channels is required for bare control events.")
        fluorescence_channels = get_fluorescence_channels(first)

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

    # A dye without a single-stain control keeps its identity row, unmeasured.
    origin = np.full((n, n), CELL_DEFAULT, dtype=np.int8)
    origin[sorted(channels_assigned), :] = CELL_ESTIMATED
    np.fill_diagonal(origin, CELL_ESTIMATED)

    return CompensationMatrix(
        matrix=spillover,
        channel_names=fluorescence_channels,
        source="computed",
        origin=origin,
    )


# ── Estimation from FMO controls ─────────────────────────────────────────────


def calculate_spillover_from_fmo(
    fmo_controls: dict[str, pd.DataFrame],
    fluorescence_channels: list[str],
    fits: list[DetectorFit] | None = None,
) -> CompensationMatrix:
    """Estimate the spillover matrix from fluorescence-minus-one controls.

    An FMO control carries every dye but one, so whatever its missing dye's
    detector records is spill from the others. Regressing that detector on
    the other detectors (raw values, with an intercept for autofluorescence;
    a robust fit, see ``_robust_fit``) gives the weights ``c_k`` that cancel it: ``raw_k − raw_others · c_k ≈ 0``.
    Collecting them as the columns of ``C``, ``I − C`` is the compensation
    matrix up to a per-dye scale, so the spillover matrix is its inverse
    with each row normalised to a diagonal of 1.

    A detector without an FMO control gets no estimate: nothing is taken
    to spill into it, and its column is marked ``CELL_DEFAULT``.

    Args:
        fmo_controls:          Missing dye's channel → that FMO control's
                               uncompensated events.
        fluorescence_channels: The matrix's channels, in order.
        fits:                  If given, receives one ``DetectorFit`` per
                               detector that was fitted.

    Raises:
        ValueError: No usable control, or the estimate can't be inverted.
    """
    n = len(fluorescence_channels)
    weights = np.zeros((n, n), dtype=np.float64)  # weights[j, k]: detector j's share in k
    covered: list[int] = []
    for k, channel in enumerate(fluorescence_channels):
        events = fmo_controls.get(channel)
        if events is None or any(ch not in events.columns for ch in fluorescence_channels):
            continue
        design, target = _fmo_design(events, fluorescence_channels, k)
        solution, event_weights = _robust_fit(design, target)
        weights[[j for j in range(n) if j != k], k] = solution[:-1]
        covered.append(k)
        if fits is not None:
            fits.append(_summarise_fit(channel, design, target, solution, event_weights))
    if not covered:
        raise ValueError("No FMO control has data for every channel of the matrix.")

    try:
        unscaled = np.linalg.inv(np.eye(n) - weights)
    except np.linalg.LinAlgError as exc:
        raise ValueError("The FMO controls don't determine a matrix (singular fit).") from exc
    diagonal = np.diag(unscaled)
    if np.any(diagonal <= 0):
        raise ValueError("The FMO controls don't determine a matrix (unstable fit).")
    # Noise can push a near-zero spill slightly negative, which is unphysical.
    spillover = np.clip(unscaled / diagonal[:, None], 0.0, None)
    np.fill_diagonal(spillover, 1.0)

    # Spill into a detector without an FMO was never measured.
    origin = np.full((n, n), CELL_DEFAULT, dtype=np.int8)
    origin[:, covered] = CELL_ESTIMATED
    np.fill_diagonal(origin, CELL_ESTIMATED)

    logger.info("Estimated spillover matrix (%d×%d) from %d FMO controls.", n, n, len(covered))
    return CompensationMatrix(
        matrix=spillover, channel_names=list(fluorescence_channels), source="fmo", origin=origin
    )


def _fmo_design(
    events: pd.DataFrame, fluorescence_channels: list[str], missing: int
) -> tuple[np.ndarray, np.ndarray]:
    """One FMO control's fit: the other detectors (plus a constant) as the
    design, the missing dye's detector as the target; at most
    ``_FMO_FIT_MAX_EVENTS`` events, taken evenly.
    """
    step = max(1, len(events) // _FMO_FIT_MAX_EVENTS)
    values = events[fluorescence_channels].to_numpy(dtype=np.float64)[::step]
    others = [j for j in range(len(fluorescence_channels)) if j != missing]
    return np.column_stack([values[:, others], np.ones(len(values))]), values[:, missing]


def _robust_fit(design: np.ndarray, target: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Least squares that down-weights outlying events (Huber weights).

    Some events carry signal in the missing dye's detector that the other
    dyes don't explain (dead cells, aggregates); an ordinary fit bends
    towards them and reads it as spill between unrelated dyes. Events that
    are extreme in the *other* detectors still pull on the fit.

    Returns the solution and each event's final weight (1 = fully counted).
    """
    weights = np.ones(len(target))
    solution = np.zeros(design.shape[1])
    for _ in range(_ROBUST_FIT_ITERATIONS):
        weighted = design * weights[:, None]
        previous = solution
        solution, *_ = np.linalg.lstsq(weighted.T @ design, weighted.T @ target, rcond=None)
        residual = target - design @ solution
        # Robust spread of the residuals (median absolute deviation as a sigma).
        scale = 1.4826 * np.median(np.abs(residual - np.median(residual)))
        if scale <= 0 or np.allclose(solution, previous, rtol=1e-6, atol=1e-9):
            break
        weights = np.minimum(1.0, _HUBER_K * scale / np.maximum(np.abs(residual), 1e-12))
    return solution, weights


def _summarise_fit(
    channel: str,
    design: np.ndarray,
    target: np.ndarray,
    solution: np.ndarray,
    weights: np.ndarray,
) -> DetectorFit:
    residual = target - design @ solution
    centred = target - np.average(target, weights=weights)
    spread = float(np.sum(weights * centred**2))
    explained = 1.0 - float(np.sum(weights * residual**2)) / spread if spread > 0 else 1.0
    return DetectorFit(
        channel=channel,
        events=len(target),
        down_weighted=float(np.mean(weights < _LARGELY_IGNORED_WEIGHT)),
        r_squared=explained,
    )


@dataclass(frozen=True)
class FmoFitDetail:
    """One FMO control's fit, event by event — for showing how it works."""

    others: list[str]  # the detectors the fit used, in ``signals`` column order
    signals: np.ndarray  # events × others
    target: np.ndarray  # the missing dye's detector
    weights: np.ndarray  # robust fit: one per other detector
    intercept: float
    plain_weights: np.ndarray  # the same fit without the robust weighting
    event_weights: np.ndarray  # how much each event counted (1 = fully)

    @property
    def largely_ignored(self) -> np.ndarray:
        return self.event_weights < _LARGELY_IGNORED_WEIGHT


def fmo_fit_detail(
    events: pd.DataFrame, fluorescence_channels: list[str], channel: str
) -> FmoFitDetail:
    """Redo the fit ``calculate_spillover_from_fmo`` runs for one control,
    keeping what it normally throws away.
    """
    missing = fluorescence_channels.index(channel)
    design, target = _fmo_design(events, fluorescence_channels, missing)
    solution, event_weights = _robust_fit(design, target)
    plain, *_ = np.linalg.lstsq(design, target, rcond=None)
    return FmoFitDetail(
        others=[ch for ch in fluorescence_channels if ch != channel],
        signals=design[:, :-1],
        target=target,
        weights=solution[:-1],
        intercept=float(solution[-1]),
        plain_weights=plain[:-1],
        event_weights=event_weights,
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
        # Derived columns are computed from the (pre-compensation) inputs, so
        # carrying them over would leave stale values; the caller re-syncs.
        df = strip_derived_columns(data.events).copy()
    else:
        raise ValueError("No event data available for compensation.")

    if comp is None:
        logger.debug("apply_compensation called with None, returning uncompensated events.")
        return df

    return compensate_events(df, comp)


def compensate_events(df: pd.DataFrame, comp: CompensationMatrix) -> pd.DataFrame:
    """Compensate ``df``'s matrix channels in place (raw values in) and return it."""
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
