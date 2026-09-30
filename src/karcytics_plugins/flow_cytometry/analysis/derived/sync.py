"""Keep a sample's derived-parameter columns in step with its definitions.

Derived columns are never persisted and never written to ``raw_events``;
they're recomputed from the current event table on demand. ``sync_fcs_data``
is idempotent and cheap when nothing changed, so it's safe to call from
every place that loads, compensates, or reads events.

Two things can make a column stale:

* the definition changed (formula or invalid-value policy) — tracked by a
  per-column signature;
* the event table itself was replaced (compensation, reload, ...) — tracked
  by a weak reference to the frame this module last produced. Any frame we
  didn't produce is treated as fresh base data and fully recomputed, even
  if it happens to carry copies of old derived columns.

Updates always swap in a *new* DataFrame instead of mutating in place, so
concurrent readers never see a half-written column and every GateNode mask
cache (keyed on frame identity) misses naturally.
"""

from __future__ import annotations

import weakref
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
from karcytics_sdk.plugin import get_logger

from .models import DerivedParameter, is_derived_key

if TYPE_CHECKING:
    from ..experiment import Experiment, Sample
    from ..fcs_io import FCSData

logger = get_logger(__name__, "flow_cytometry")


@dataclass
class SyncResult:
    """Outcome of syncing one sample.

    Attributes:
        changed: True if the event table was replaced.
        missing: param_id -> input channels this sample lacks (column is
                 all-NaN for those).
        errors:  param_id -> error message for definitions that failed to
                 evaluate (column is all-NaN).
    """

    changed: bool = False
    missing: dict[str, list[str]] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)


def strip_derived_columns(events: pd.DataFrame) -> pd.DataFrame:
    """Return ``events`` without any derived columns (same object if none)."""
    derived = [c for c in events.columns if is_derived_key(c)]
    return events.drop(columns=derived) if derived else events


def _frame_is_ours(fcs_data: FCSData) -> bool:
    ref = fcs_data.derived_frame_ref
    return ref is not None and ref() is fcs_data.events


def sync_fcs_data(fcs_data: FCSData, definitions: Sequence[DerivedParameter]) -> SyncResult:
    """Bring ``fcs_data``'s derived columns, channels and labels up to date."""
    result = SyncResult()
    events = fcs_data.events
    if events is None:
        return result

    wanted = {d.param_id: d for d in definitions}
    ours = _frame_is_ours(fcs_data)
    signatures = fcs_data.derived_signatures if ours else {}

    existing = [c for c in events.columns if is_derived_key(c)]
    keep = [
        c for c in existing if ours and c in wanted and signatures.get(c) == wanted[c].signature
    ]
    to_compute = [d for d in definitions if d.param_id not in keep]
    to_drop = [c for c in existing if c not in keep]

    _sync_channel_list(fcs_data, definitions)

    wanted_order = [d.param_id for d in definitions]
    if not to_compute and not to_drop and existing == wanted_order:
        # Nothing to do — the common path for workspaces with no derived
        # parameters, and for repeated ensure() calls.
        _record(fcs_data, events, definitions)
        _collect_missing(events, definitions, result)
        return result

    base = events.drop(columns=to_drop) if to_drop else events
    new_cols: dict[str, np.ndarray] = {}
    for defn in to_compute:
        new_cols[defn.param_id] = _compute(defn, base, result)
    _collect_missing(base, definitions, result)

    real_cols = [c for c in base.columns if not is_derived_key(c)]
    parts = [base[real_cols + keep]] if keep else [base[real_cols]]
    if new_cols:
        parts.append(pd.DataFrame(new_cols, index=base.index))
    merged = pd.concat(parts, axis=1) if len(parts) > 1 else parts[0].copy()
    merged = merged[real_cols + wanted_order]

    fcs_data.events = merged
    _record(fcs_data, merged, definitions)
    result.changed = True
    return result


def sync_sample(experiment: Experiment, sample: Sample) -> SyncResult:
    """Sync one sample against the experiment's definitions.

    Returns immediately — touching nothing — for the common case of an
    experiment with no derived parameters and a sample with no leftover
    derived columns, so workspaces that never use the feature are unaffected.
    """
    fcs_data = sample.fcs_data
    if fcs_data is None:
        return SyncResult()
    definitions = list(getattr(experiment, "derived_parameters", ()))
    if not definitions:
        columns = getattr(fcs_data.events, "columns", ())
        if not any(is_derived_key(c) for c in columns):
            return SyncResult()
    return sync_fcs_data(fcs_data, definitions)


def sync_experiment(experiment: Experiment) -> dict[str, SyncResult]:
    """Sync every loaded sample in ``experiment``.

    Call after anything that replaces event tables for many samples at once
    (compensation, workspace reload, undo restore).
    """
    return {sid: sync_sample(experiment, s) for sid, s in experiment.samples.items()}


def _compute(defn: DerivedParameter, base: pd.DataFrame, result: SyncResult) -> np.ndarray:
    try:
        expr = defn.expression
        if expr.missing_channels(base.columns):
            return np.full(len(base), np.nan)
        return expr.evaluate(base, positive_denominators=defn.positive_denominators)
    except Exception as exc:  # a bad definition must never break sample loading
        logger.warning(f"Derived parameter '{defn.name}' failed to evaluate: {exc}")
        result.errors[defn.param_id] = str(exc)
        return np.full(len(base), np.nan)


def _collect_missing(
    events: pd.DataFrame, definitions: Sequence[DerivedParameter], result: SyncResult
) -> None:
    for defn in definitions:
        try:
            missing = defn.expression.missing_channels(events.columns)
        except Exception:  # invalid formula is already reported via errors
            continue
        if missing:
            result.missing[defn.param_id] = missing


def _sync_channel_list(fcs_data: FCSData, definitions: Sequence[DerivedParameter]) -> None:
    # Derived keys always sit after the real channels, so the positional
    # channels<->markers pairing for real detectors is never disturbed.
    real = [c for c in fcs_data.channels if not is_derived_key(c)]
    fcs_data.channels = real + [d.param_id for d in definitions]
    fcs_data.derived_labels = {d.param_id: d.label for d in definitions}


def _record(
    fcs_data: FCSData, frame: pd.DataFrame, definitions: Sequence[DerivedParameter]
) -> None:
    fcs_data.derived_signatures = {d.param_id: d.signature for d in definitions}
    fcs_data.derived_frame_ref = weakref.ref(frame)
