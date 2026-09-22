"""Axis transformations for flow cytometry data visualization.

Provides linear, logarithmic, and biexponential (logicle) transforms
using ``flowkit``'s validated C-extension implementations.

The Logicle transform uses the Parks et al. (2006) algorithm via
``flowutils``, not a simplified approximation.

Reference:
    Parks, D.R., Roederer, M., Moore, W.A. (2006). A new "Logicle"
    display method avoids deceptive effects of logarithmic scaling for
    low signals and compensated data. *Cytometry Part A*, 69A:541-551.
"""

from __future__ import annotations

import threading
from enum import Enum
from typing import Any

import numpy as np
from karcytics_sdk.plugin import get_logger

logger = get_logger(__name__, "flow_cytometry")


class TransformType(Enum):
    """Available axis transformation types."""

    LINEAR = "linear"
    LOG = "log"
    BIEXPONENTIAL = "biexponential"


def biological_tick_values(
    is_biex: bool, show_negative_decade: bool = False
) -> tuple[np.ndarray, list[str]]:
    """Standard flow cytometry decade tick positions (10^3..10^5) and labels.

    Returns raw (untransformed) tick values — callers must run them through
    the same ``apply_transform`` call used for the plotted data to get
    display-space positions. Shared by every view that displays log/
    biexponential-transformed data (the main gating canvas's AxisFormatter,
    the Comparisons Histogram Overlay renderer, ...) so decade labels read
    identically across the whole app.
    """
    pos_decades = [10**3, 10**4, 10**5]
    pos_labels = ["$10^3$", "$10^4$", "$10^5$"]
    if is_biex:
        if show_negative_decade:
            raw = np.array([-(10**3), 0] + pos_decades, dtype=float)
            lbl = [r"$-10^3$", "0"] + pos_labels
        else:
            raw = np.array([0] + pos_decades, dtype=float)
            lbl = ["0"] + pos_labels
    else:
        raw = np.array(pos_decades, dtype=float)
        lbl = pos_labels
    return raw, lbl


def compute_bio_tick_positions(
    transform_type: TransformType, transform_kwargs: dict, show_negative_decade: bool = False
) -> tuple[np.ndarray, list[str]]:
    """Bio-decade tick positions already run through apply_transform, i.e. in
    display space — ready to hand straight to a matplotlib FixedLocator on
    an axis whose data was transformed with the same type/kwargs.

    Ticks are never dithered (`enable_dithering=False`) even when the
    underlying event data was, so decade lines land exactly — same
    convention as CoordinateMapper._biexp_kwargs on the main canvas.
    Returns an empty result for LINEAR (no decade ticks needed there).
    """
    if transform_type == TransformType.LINEAR:
        return np.array([]), []
    is_biex = transform_type == TransformType.BIEXPONENTIAL
    raw_ticks, labels = biological_tick_values(is_biex, show_negative_decade)
    tick_kwargs = dict(transform_kwargs)
    if is_biex:
        tick_kwargs["enable_dithering"] = False
    disp_ticks = apply_transform(raw_ticks, transform_type, **tick_kwargs)
    return disp_ticks, labels


# ── Cache for FlowKit transform instances ────────────────────────────────────

_thread_local = threading.local()
_flowkit_logicle_warning_issued = False

# ── bokeh frozen-app template detection fix ───────────────────────────────────
# bokeh.core.templates.get_env() is @lru_cache'd and checks sys.frozen /
# sys._MEIPASS *globally* to decide where its own Jinja2 templates live,
# wrongly assuming that if the *process* is frozen, bokeh itself must be
# bundled at the standard PyInstaller location. It never is here: Karcytics core
# is frozen, while bokeh (a transitive dependency, pulled in by flowkit) lives
# in this plugin's own separate, non-frozen .venv.
#
# An earlier version of this fix "solved" that by temporarily deleting
# sys._MEIPASS around the first `import flowkit`. That crashed production:
# PyInstaller's own frozen import machinery (pyimod02_importers.py) reads
# sys._MEIPASS on EVERY import, on every thread, for the entire life of the
# frozen process — deleting it, even briefly and even from a background
# thread, can (and did) collide with a completely unrelated import happening
# concurrently on the main thread and crash the whole plugin load.
#
# This version never touches sys.frozen/sys._MEIPASS at all. It replaces
# bokeh's cached get_env() directly with the same logic bokeh's own
# "not frozen" branch already uses.
_bokeh_env_patch_lock = threading.Lock()
_bokeh_env_patched = False


def patch_bokeh_template_env() -> None:
    """Make bokeh look for its own Jinja2 templates next to itself, always.

    Idempotent and safe to call multiple times / from multiple threads. Cheap
    (only imports ``bokeh.core.templates``, not the full ``bokeh.plotting`` /
    ``flowkit`` chain) — call this synchronously and early (see
    ``get_panel_class()``) so there is no window where an unpatched
    ``get_env()`` could ever run.
    """
    global _bokeh_env_patched
    with _bokeh_env_patch_lock:
        if _bokeh_env_patched:
            return

        try:
            import os
            from functools import lru_cache

            import bokeh.core.templates as bokeh_templates
            from jinja2 import Environment, FileSystemLoader

            templates_path = os.path.join(os.path.dirname(bokeh_templates.__file__), "_templates")

            @lru_cache(None)
            def _correct_get_env() -> Environment:
                return Environment(
                    loader=FileSystemLoader(templates_path),
                    trim_blocks=True,
                    lstrip_blocks=True,
                )

            bokeh_templates.get_env = _correct_get_env
        except Exception as exc:
            logger.debug("Could not patch bokeh's template env (non-fatal): %s", exc)
        else:
            _bokeh_env_patched = True


def _report_flowkit_failure(e: Exception) -> None:
    """Report a FlowKit LogicleTransform failure loudly and fatally.

    There is no acceptable approximate substitute for the real Logicle
    transform — a silently-swapped formula (e.g. arcsinh) produces a
    plausible-looking but numerically wrong plot, which is worse than an
    outright failure because it goes undetected. FlowKit failing to import
    or apply indicates a real environment problem (e.g. a dependency
    resolving from the wrong location) that must be fixed, not papered over.
    """
    global _flowkit_logicle_warning_issued
    if not _flowkit_logicle_warning_issued:
        logger.error("FlowKit LogicleTransform unavailable: %s", e)
        _flowkit_logicle_warning_issued = True
    else:
        logger.debug("FlowKit LogicleTransform unavailable (repeated): %s", e)

    from karcytics_sdk.plugin.runtime_services import diagnostics

    diagnostics.report_error(
        "The biexponential (Logicle) transform is unavailable — FlowKit failed to "
        "load or apply. Plots using this transform cannot be rendered correctly.",
        exception=e,
        fatal=True,
    )


def _get_logicle_transform(
    fk: Any, top: float, width: float, positive: float, negative: float
) -> Any:
    if not hasattr(_thread_local, "logicle_cache"):
        _thread_local.logicle_cache = {}
    key = (top, width, positive, negative)
    if key not in _thread_local.logicle_cache:
        _thread_local.logicle_cache[key] = fk.transforms.LogicleTransform(
            top, width, positive, negative
        )
    return _thread_local.logicle_cache[key]


def linear_transform(
    data: np.ndarray,
    **_kwargs,
) -> np.ndarray:
    """Linear (identity) transform — returns raw values unchanged.

    Matplotlib auto-ranges the axes based on the actual data extent,
    which is what scientists expect for scatter parameters like
    FSC-A and SSC-A.

    Args:
        data: Raw channel values.

    Returns:
        The same values (as float64 for consistency).
    """
    return data.astype(np.float64)


def log_transform(
    data: np.ndarray,
    decades: float = 4.5,
    min_value: float = 1.0,
) -> np.ndarray:
    """Logarithmic (base-10) scaling.

    Values below ``min_value`` are clamped to ``min_value`` to avoid
    log(0) or log(negative).

    Args:
        data:      Raw channel values.
        decades:   Number of decades to display.
        min_value: Floor value before taking the log.

    Returns:
        Log-scaled values.
    """
    clamped = np.maximum(data, min_value)
    return np.log10(clamped) / decades


def biexponential_transform(  # noqa: PLR0913
    data: np.ndarray,
    *,
    enable_dithering: bool = True,
    top: float = 262144.0,
    width: float = 1.0,
    positive: float = 4.5,
    negative: float = 0.0,
) -> np.ndarray:
    """Biexponential (logicle) transform for compensated data.

    Uses ``flowkit.transforms.LogicleTransform`` which wraps the
    validated C implementation from ``flowutils``.  This is the **real**
    Parks 2006 algorithm, not an approximation.

    There is no fallback: an approximation formula uses the ``width``
    parameter differently and produces a plausible-looking but numerically
    wrong plot. If FlowKit is unavailable, this raises (after reporting a
    fatal diagnostic) rather than silently degrading.

    Args:
        data:             Raw channel values.
        enable_dithering: If True, apply +/-0.5 uniform jitter to prevent barcode artifacts.
        top:              Maximum expected data value (T parameter).
        width:            Linearization width (W parameter, decades).
        positive:         Number of positive decades (M parameter).
        negative:         Additional negative decades (A parameter).

    Returns:
        Transformed values in display units.
    """
    # Apply continuous +/-0.5 uniform dithering to prevent integer banding
    # (barcode artifacts) which dramatically skew density calculations near 0
    data_jitter = np.asarray(data, dtype=np.float64).copy()
    if enable_dithering:
        data_jitter += np.random.uniform(-0.5, 0.5, size=data_jitter.shape)

    # ── FlowKit LogicleTransform (real Parks 2006 algorithm) ──────────
    # NOTE: flowkit.transforms is a namespace package — it cannot be imported
    # with 'from flowkit.transforms import LogicleTransform'. Access via fk.transforms.
    try:
        patch_bokeh_template_env()
        import flowkit as fk

        transform_obj = _get_logicle_transform(fk, top, width, positive, negative)
        # np.ascontiguousarray ensures a C-contiguous, owned float64 buffer —
        # the FlowKit C extension (flowutils) requires this; a non-contiguous
        # view from ravel() can cause a SIGBUS on ARM macOS.
        flat_data = np.ascontiguousarray(data_jitter.ravel(), dtype=np.float64)
        transformed = transform_obj.apply(flat_data)
        return transformed.reshape(data_jitter.shape)
    except Exception as e:
        _report_flowkit_failure(e)
        raise


def apply_transform(
    data: np.ndarray,
    transform_type: TransformType,
    **_kwargs,
) -> np.ndarray:
    """Apply a named transform to data.

    Args:
        data:           Raw channel values.
        transform_type: Which transform to apply.
        **_kwargs:       Additional arguments passed to the transform.

    Returns:
        Transformed values.
    """
    # Use .value to avoid module-aliasing identity bugs with Enums sent across IPC
    val = transform_type.value if isinstance(transform_type, Enum) else str(transform_type)

    if val == TransformType.LINEAR.value:
        return linear_transform(data, **_kwargs)
    if val == TransformType.LOG.value:
        return log_transform(data, **_kwargs)
    if val == TransformType.BIEXPONENTIAL.value:
        return biexponential_transform(data, **_kwargs)
    raise ValueError(f"Unknown transform: {transform_type}")


def invert_linear_transform(
    data: np.ndarray,
    **_kwargs,
) -> np.ndarray:
    """Inverse of linear (identity) transform."""
    return data.astype(np.float64)


def invert_log_transform(
    data: np.ndarray,
    decades: float = 4.5,
    _min_value: float = 1.0,
    **_kwargs,
) -> np.ndarray:
    """Inverse of logarithmic scaling.

    Args:
        data:      Transformed channel values.
        decades:   Number of decades displayed.
        min_value: Floor value that was originally used.

    Returns:
        Raw channel values.
    """
    return 10.0 ** (data * decades)


def invert_biexponential_transform(
    data: np.ndarray,
    *,
    top: float = 262144.0,
    width: float = 1.0,
    positive: float = 4.5,
    negative: float = 0.0,
    **_kwargs,
) -> np.ndarray:
    """Inverse of biexponential (logicle) transform.

    Args:
        data:     Transformed channel values in display units.
        top:      Maximum expected data value (T parameter).
        width:    Linearization width (W parameter, decades).
        positive: Number of positive decades (M parameter).
        negative: Additional negative decades (A parameter).

    Returns:
        Raw channel values.
    """
    # ── FlowKit inverse (real Parks 2006 algorithm) ───────────────────
    # NOTE: flowkit.transforms is a namespace package — access via fk.transforms.
    try:
        patch_bokeh_template_env()
        import flowkit as fk

        transform_obj = _get_logicle_transform(fk, top, width, positive, negative)
        flat_data = np.asarray(data, dtype=np.float64).ravel()
        raw = transform_obj.inverse(flat_data)
        return raw.reshape(data.shape)
    except Exception as e:
        _report_flowkit_failure(e)
        raise


def invert_transform(
    data: np.ndarray,
    transform_type: TransformType,
    **_kwargs,
) -> np.ndarray:
    """Apply the inverse of a named transform to mapped data.

    Args:
        data:           Transformed display values.
        transform_type: Which transform was applied.
        **_kwargs:       Additional arguments passed to the transform.

    Returns:
        Raw data values.
    """
    # Use .value to avoid module-aliasing identity bugs with Enums sent across IPC
    val = transform_type.value if isinstance(transform_type, Enum) else str(transform_type)

    if val == TransformType.LINEAR.value:
        return invert_linear_transform(data, **_kwargs)
    if val == TransformType.LOG.value:
        return invert_log_transform(data, **_kwargs)
    if val == TransformType.BIEXPONENTIAL.value:
        return invert_biexponential_transform(data, **_kwargs)
    raise ValueError(f"Unknown transform: {transform_type}")
