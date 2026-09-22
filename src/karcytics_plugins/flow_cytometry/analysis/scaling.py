"""Axis scaling and range calculation utilities.

Provides data structures for persisting per-axis scale settings (e.g.,
Min/Max, Logicle T, W, M, A parameters) and utilities for calculating
robust auto-ranges that ignore extreme outliers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from karcytics_sdk.plugin import get_logger

from .constants import (
    BIEXP_SNAP_LO,
    LINEAR_SNAP_LO,
    LOGICLE_A_NEG_THRESHOLD,
    LOGICLE_NEG_COUNT_MIN,
    LOGICLE_NEG_FRACTION_MIN,
    LOGICLE_T_DEFAULT,
    OUTLIER_PERCENTILE_MAX,
    PHYSICAL_SIGNAL_MAX,
)
from .transforms import TransformType, apply_transform

logger = get_logger(__name__, "flow_cytometry")


@dataclass
class AxisScale:
    """Settings for how to scale and display a single axis."""

    transform_type: TransformType = TransformType.LINEAR

    # Range limits (None means auto-scale)
    min_val: float | None = None
    max_val: float | None = None

    # Biexponential (Logicle) parameters
    # Matches standard Transform dialog defaults and naming
    logicle_t: float = 262144.0  # Top data value (determines max scale)
    logicle_w: float = 1.0  # Width Basis (linear range around 0)
    logicle_m: float = 4.5  # Positive decades
    logicle_a: float = 0.0  # Extra negative decades

    # Outlier bounds (percentile to ignore at each end)
    outlier_percentile: float = 0.1  # Default to 0.1% (p0.1 and p99.9)

    def __post_init__(self):
        """Validate scale parameters after initialization."""
        # Validate transform type
        valid_transforms = {t.value for t in TransformType}
        if self.transform_type.value not in valid_transforms:
            raise ValueError(
                f"Invalid transform_type: {self.transform_type}. Must be one of: {valid_transforms}"
            )

        # Validate range
        if self.min_val is not None and self.max_val is not None and self.min_val >= self.max_val:
            raise ValueError(f"min_val ({self.min_val}) must be less than max_val ({self.max_val})")

        # Validate Logicle parameters
        if self.transform_type == TransformType.BIEXPONENTIAL:
            if self.logicle_t <= 0:
                raise ValueError(f"logicle_t must be positive, got {self.logicle_t}")
            if self.logicle_w < 0:
                raise ValueError(f"logicle_w must be non-negative, got {self.logicle_w}")
            if self.logicle_m <= 0:
                raise ValueError(f"logicle_m must be positive, got {self.logicle_m}")
            if self.logicle_a < 0:
                raise ValueError(f"logicle_a must be non-negative, got {self.logicle_a}")

        # Validate outlier percentile
        if not 0 <= self.outlier_percentile <= OUTLIER_PERCENTILE_MAX:
            raise ValueError(
                f"outlier_percentile must be between 0 and 50, got {self.outlier_percentile}"
            )

    def copy(self) -> AxisScale:
        return AxisScale(
            transform_type=self.transform_type,
            min_val=self.min_val,
            max_val=self.max_val,
            logicle_t=self.logicle_t,
            logicle_w=self.logicle_w,
            logicle_m=self.logicle_m,
            logicle_a=self.logicle_a,
            outlier_percentile=self.outlier_percentile,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "transform_type": self.transform_type.value,
            "min_val": self.min_val,
            "max_val": self.max_val,
            "logicle_t": self.logicle_t,
            "logicle_w": self.logicle_w,
            "logicle_m": self.logicle_m,
            "logicle_a": self.logicle_a,
            "outlier_percentile": self.outlier_percentile,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AxisScale:
        """Create an AxisScale instance from a dictionary."""
        return cls(
            transform_type=TransformType(str(data.get("transform_type", "linear"))),
            min_val=data.get("min_val"),
            max_val=data.get("max_val"),
            logicle_t=data.get("logicle_t", 262144.0),
            logicle_w=data.get("logicle_w", 1.0),
            logicle_m=data.get("logicle_m", 4.5),
            logicle_a=data.get("logicle_a", 0.0),
            outlier_percentile=data.get("outlier_percentile", 0.1),
        )


def get_transform_kwargs(scale: AxisScale) -> dict:
    """Map an AxisScale's Logicle fields to apply_transform()'s kwargs.

    Shared by the main gating canvas's compute stage (ui/graph/canvas/
    data_layer.py) and any other caller that needs to run raw channel data
    through the exact same transform a given AxisScale describes.
    """
    if scale.transform_type == TransformType.BIEXPONENTIAL:
        return {
            "top": scale.logicle_t,
            "width": scale.logicle_w,
            "positive": scale.logicle_m,
            "negative": scale.logicle_a,
        }
    return {}


def compute_axis_limits(
    raw_data: np.ndarray, scale: AxisScale, kwargs: dict
) -> tuple[float, float] | None:
    """Display-space (post-transform) axis limits: the scale's manual
    min/max if set, else an auto-computed range — both run through
    apply_transform() so the result matches whatever's plotted.
    """
    if scale.min_val is not None and scale.max_val is not None:
        lim = apply_transform(
            np.array([scale.min_val, scale.max_val]), scale.transform_type, **kwargs
        )
        return (lim[0], lim[1])
    valid_raw = raw_data[np.isfinite(raw_data)]
    if len(valid_raw) > 0:
        raw_min, raw_max = calculate_auto_range(valid_raw, scale.transform_type)
        lim = apply_transform(np.array([raw_min, raw_max]), scale.transform_type, **kwargs)
        return (lim[0], lim[1])
    return None


def _auto_range_linear(p_min: float, p_max: float) -> tuple[float, float]:
    floor = min(0.0, p_min)
    span = p_max - floor
    if span <= 0:
        span = 1.0
    ceiling = p_max + span * 0.05
    if LINEAR_SNAP_LO < p_max < LOGICLE_T_DEFAULT:
        ceiling = LOGICLE_T_DEFAULT
    return (floor, ceiling)


def _auto_range_log(
    valid_data: np.ndarray, p_max: float, outlier_percentile: float
) -> tuple[float, float]:
    pos_data = valid_data[valid_data > 0]
    if len(pos_data) == 0:
        return (0.1, 10.0)
    p_min_pos = np.percentile(pos_data, outlier_percentile)
    return (float(p_min_pos * 0.5), float(p_max * 2.0))


def _auto_range_biexponential(p_min: float, p_max: float) -> tuple[float, float]:
    display_min = p_min - max(abs(p_min) * 0.1, 100.0) if p_min < 0 else min(-100.0, p_min - 100.0)

    span = max(p_max - display_min, 1.0)
    display_max = p_max + span * 0.05

    if BIEXP_SNAP_LO < display_max < LOGICLE_T_DEFAULT:
        display_max = LOGICLE_T_DEFAULT

    return (display_min, display_max)


def calculate_auto_range(  # noqa: PLR0911
    data: np.ndarray, transform_type: TransformType, outlier_percentile: float = 0.1
) -> tuple[float, float]:
    """Calculate a robust display range ignoring extreme outliers."""
    if len(data) == 0:
        return (0.0, 1.0)

    valid = np.isfinite(data)
    valid_data = data[valid]

    if len(valid_data) == 0:
        return (0.0, 1.0)

    # Secondary guard: discard physically impossible values (|x| > PHYSICAL_SIGNAL_MAX)
    physical_mask = np.abs(valid_data) <= PHYSICAL_SIGNAL_MAX
    if not np.all(physical_mask):
        valid_data = valid_data[physical_mask]
        if len(valid_data) == 0:
            return (0.0, 1.0)

    p_min = float(np.percentile(valid_data, outlier_percentile))
    p_max = float(np.percentile(valid_data, 100.0 - outlier_percentile))

    if transform_type == TransformType.LINEAR:
        return _auto_range_linear(p_min, p_max)
    if transform_type == TransformType.LOG:
        return _auto_range_log(valid_data, p_max, outlier_percentile)
    if transform_type == TransformType.BIEXPONENTIAL:
        return _auto_range_biexponential(p_min, p_max)

    return (p_min, p_max)


def _filter_physical(data: np.ndarray) -> np.ndarray:
    """Return finite, physically-plausible values only.

    Factored out of calculate_auto_range's existing guard so every
    percentile-based estimator in this module uses the same rule:
    discard non-finite values and |x| > 1e9 artefacts from truncated
    FCS files. No real cytometer channel legitimately exceeds ±1 GFU.
    """
    valid = data[np.isfinite(data)]
    if len(valid) == 0:
        return valid
    physical_mask = np.abs(valid) <= PHYSICAL_SIGNAL_MAX
    return valid[physical_mask]


def detect_logicle_top(data) -> float:
    """Return the Logicle T (Top) parameter for this channel's data."""
    if len(data) == 0:
        return 262144.0

    valid = _filter_physical(np.asarray(data))
    if len(valid) == 0:
        return 262144.0

    p99 = float(np.percentile(valid, 99.9))

    if p99 <= 262144.0 * 1.5:
        return 262144.0
    if p99 <= 1_048_576.0 * 1.5:
        return 1_048_576.0
    return float(2 ** int(np.ceil(np.log2(p99))))


def estimate_logicle_params(
    data: np.ndarray,
    t: float = 262144.0,
    m: float = 4.5,
) -> tuple[float, float]:
    """Estimate Logicle W and A parameters from data.

    W is calculated using the FlowJo/flowCore method:
        W = (M - log10(T / |r|)) / 2
    where r is the 5th percentile of the negative tail.
    """
    valid = _filter_physical(np.asarray(data))
    if len(valid) == 0:
        return 1.0, 0.0

    neg_data = valid[valid < 0]

    if (
        len(neg_data) < LOGICLE_NEG_COUNT_MIN
        or len(neg_data) / len(valid) < LOGICLE_NEG_FRACTION_MIN
    ):
        w = 0.5
    else:
        # FlowCore reference implementation uses the raw 5th percentile of negative events
        # without pre-trimming, ensuring the exact FlowJo mathematical behavior.
        r = float(np.percentile(neg_data, 5))

        if r >= 0:
            w = 0.5
        else:
            try:
                w = (m - np.log10(t / abs(r))) / 2.0
                # Original clamp ceiling: m/2.0
                # This allows uncompensated tails to properly scale.
                w = max(0.1, min(w, m / 2.0))
            except Exception:
                w = 0.5

    min_val = float(np.percentile(valid, 0.1))
    try:
        if min_val < LOGICLE_A_NEG_THRESHOLD:
            # Positive log10 of the magnitude, minus the decades already in the linear region
            a = np.log10(abs(min_val)) - w
            # Cap A at 1.0 to provide enough negative log space to compress the tail
            # into a tight cluster without shifting the entire plot's zero point too far right.
            a = max(0.0, min(a, 1.0))
        else:
            a = 0.0
    except Exception:
        a = 0.0

    return float(w), float(a)
