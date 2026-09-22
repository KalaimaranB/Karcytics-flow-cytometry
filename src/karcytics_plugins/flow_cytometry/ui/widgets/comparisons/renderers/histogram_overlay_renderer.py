"""Histogram Overlay renderer — shows multiple population distributions on one channel.

Two layout modes:
  overlay: all histograms on a single shared axis, alpha-blended.
  ridge:   one horizontal row per population, vertically stacked with a shared
           X-axis (waterfall / ridge-line style, matching the reference image).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from matplotlib.figure import Figure
from matplotlib.ticker import FixedFormatter, FixedLocator

from karcytics_plugins.flow_cytometry.analysis.scaling import (
    detect_logicle_top,
    estimate_logicle_params,
)
from karcytics_plugins.flow_cytometry.analysis.transforms import (
    TransformType,
    apply_transform,
    biological_tick_values,
)

from .base import IPlotRenderer

# How many events to sample for KDE computation (speed guard)
_KDE_MAX_EVENTS = 20_000

_X_TRANSFORM_TYPES = {
    "linear": TransformType.LINEAR,
    "log": TransformType.LOG,
    "biex": TransformType.BIEXPONENTIAL,
}


@dataclass
class _Curve:
    """One population's drawable (x, y) curve, plus its label/color."""

    label: str
    color: str
    x: np.ndarray
    y: np.ndarray


class HistogramOverlayRenderer(IPlotRenderer):
    """SRP: renders a histogram overlay comparison for one channel.

    Split into prepare() (heavy numpy/scipy curve computation — gaussian_kde
    for every population, potentially dozens of them) and render() (cheap
    matplotlib drawing of already-computed curves). ComparisonsWorker calls
    prepare() before acquiring MPL_RASTER_LOCK and render() after (see
    worker.py) — holding that process-wide lock around gaussian_kde for many
    populations was previously starving the main gating canvas's paint
    events for the whole duration (see IPlotRenderer.prepare's docstring).

    render() falls back to calling prepare() itself when `curves` isn't
    already in kwargs, so it stays directly callable/testable standalone
    (e.g. unit tests that call render() without going through the worker).
    """

    def prepare(self, **kwargs) -> dict:
        """Heavy step: build one drawable curve per population.

        Pure numpy/scipy — must never touch a Figure/Axes. Each population's
        array is run through the *same* validated transform (linear/log/
        biexponential — analysis.transforms.apply_transform) the main gating
        canvas uses before any binning or density estimation happens, so a
        KDE bandwidth and histogram bin edges are computed in the space
        they're actually displayed in, not in linear space and then merely
        rescaled for display (see module docstring).
        """
        data_per_label: dict[str, np.ndarray] = kwargs["data_per_label"]
        smooth_kde: bool = kwargs.get("smooth_kde", True)
        normalize_to_peak: bool = kwargs.get("normalize_to_peak", True)
        bins: int = int(kwargs.get("bins", 256))
        x_transform: str = kwargs.get("x_transform", "linear")
        palette: list[str] = kwargs.get("palette", _DEFAULT_PALETTE)

        # Filter out empty/non-finite-only/too-small arrays.
        valid: dict[str, np.ndarray] = {}
        for lbl, arr in data_per_label.items():
            if not isinstance(arr, np.ndarray):
                continue
            arr_f = arr[np.isfinite(arr)]
            if len(arr_f) >= 5:  # noqa: PLR2004
                valid[lbl] = arr_f

        out = dict(kwargs)
        if not valid:
            out["curves"] = []
            return out

        labels = list(valid.keys())
        raw_arrays = list(valid.values())
        colors = [palette[i % len(palette)] for i in range(len(labels))]

        transform_type, transform_kwargs = _resolve_transform(x_transform, raw_arrays)
        arrays = [apply_transform(arr, transform_type, **transform_kwargs) for arr in raw_arrays]

        x_min, x_max = _global_range(arrays)
        curves = _compute_curves(
            labels, arrays, colors, x_min, x_max, smooth_kde, normalize_to_peak, bins
        )

        show_neg_decade = transform_type == TransformType.BIEXPONENTIAL and (
            transform_kwargs.get("negative", 0.0) > 0 or any(np.any(arr < 0) for arr in raw_arrays)
        )

        out["curves"] = curves
        out["x_min"] = x_min
        out["x_max"] = x_max
        out["transform_type"] = transform_type
        out["transform_kwargs"] = transform_kwargs
        out["show_neg_decade"] = show_neg_decade
        return out

    def render(self, **kwargs) -> Figure:
        channel_label: str = kwargs.get("channel_label", "Channel")
        layout: str = kwargs.get("layout", "ridge")  # "overlay" | "ridge"
        normalize_to_peak: bool = kwargs.get("normalize_to_peak", True)
        ridge_overlap: float = float(kwargs.get("ridge_overlap", 0.6))
        show_legend: bool = kwargs.get("show_legend", True)
        line_width: float = float(kwargs.get("line_width", 1.5))
        bg_color: str = kwargs.get("bg_color", "#0d1117")
        fg_color: str = kwargs.get("fg_color", "#e6edf3")
        border_color: str = kwargs.get("border_color", "#30363d")

        if "curves" in kwargs:
            prepared = kwargs
        else:
            prepared = self.prepare(**kwargs)

        curves: list[_Curve] = prepared["curves"]
        x_min = float(prepared.get("x_min", 0.0))
        x_max = float(prepared.get("x_max", 1.0))
        transform_type: TransformType = prepared.get("transform_type", TransformType.LINEAR)
        transform_kwargs: dict = prepared.get("transform_kwargs", {})
        show_neg_decade: bool = prepared.get("show_neg_decade", False)

        if not curves:
            return _empty_figure(bg_color, fg_color, border_color)

        if layout == "overlay":
            return _render_overlay(
                curves,
                x_min,
                x_max,
                channel_label,
                normalize_to_peak,
                transform_type,
                transform_kwargs,
                show_neg_decade,
                show_legend,
                line_width,
                bg_color,
                fg_color,
                border_color,
            )
        return _render_ridge(
            curves,
            x_min,
            x_max,
            channel_label,
            ridge_overlap,
            normalize_to_peak,
            transform_type,
            transform_kwargs,
            show_neg_decade,
            line_width,
            bg_color,
            fg_color,
            border_color,
        )


# ── Default colour palette (same as existing comparison renderers) ─────────────

_DEFAULT_PALETTE = [
    "#00bcd4",
    "#ef5350",
    "#66bb6a",
    "#ffa726",
    "#ab47bc",
    "#26c6da",
    "#ff7043",
    "#9ccc65",
    "#29b6f6",
    "#ec407a",
    "#d4e157",
    "#8d6e63",
]


# ── Shared helpers ─────────────────────────────────────────────────────────────


def _compute_kde_curve(
    arr: np.ndarray, x_min: float, x_max: float, n_pts: int = 512
) -> tuple[np.ndarray, np.ndarray] | None:
    """Return (x_grid, y_kde) or None on failure."""
    try:
        from scipy.stats import gaussian_kde

        if len(arr) > _KDE_MAX_EVENTS:
            rng = np.random.default_rng(42)
            arr = rng.choice(arr, _KDE_MAX_EVENTS, replace=False)

        kde = gaussian_kde(arr, bw_method="scott")
        x_grid = np.linspace(x_min, x_max, n_pts)
        return x_grid, kde(x_grid)
    except Exception:
        return None


def _compute_histogram(
    arr: np.ndarray, bins: int, x_min: float, x_max: float
) -> tuple[np.ndarray, np.ndarray]:
    """Return (bin_centers, counts) for a clipped histogram."""
    arr_clipped = arr[(arr >= x_min) & (arr <= x_max)]
    if len(arr_clipped) == 0:
        arr_clipped = arr
    counts, edges = np.histogram(arr_clipped, bins=bins, range=(x_min, x_max))
    centers = 0.5 * (edges[:-1] + edges[1:])
    return centers, counts.astype(float)


def _compute_curves(  # noqa: PLR0913
    labels: list[str],
    arrays: list[np.ndarray],
    colors: list[str],
    x_min: float,
    x_max: float,
    smooth_kde: bool,
    normalize_to_peak: bool,
    bins: int,
) -> list[_Curve]:
    """Build one drawable curve per population — the expensive step."""
    curves = []
    for arr, color, label in zip(arrays, colors, labels, strict=False):
        arr_f = arr[np.isfinite(arr)]

        result = _compute_kde_curve(arr_f, x_min, x_max) if smooth_kde else None
        if result is not None:
            x_vals, y_vals = result
        else:
            x_vals, y_vals = _compute_histogram(arr_f, bins, x_min, x_max)

        if normalize_to_peak and y_vals.max() > 0:
            y_vals = y_vals / y_vals.max()

        curves.append(_Curve(label=label, color=color, x=x_vals, y=y_vals))
    return curves


def _resolve_transform(
    x_transform: str, raw_arrays: list[np.ndarray]
) -> tuple[TransformType, dict]:
    """Map the options panel's x_transform string to a TransformType + params.

    Biexponential T/W/A are estimated from the pooled data across every
    selected population (detect_logicle_top/estimate_logicle_params — the
    same estimators the main gating canvas uses per-channel, in
    analysis/scaling.py) rather than left at fixed defaults, so a channel
    looks the same whether viewed here or on the main canvas.
    """
    transform_type = _X_TRANSFORM_TYPES.get(x_transform, TransformType.LINEAR)
    if transform_type != TransformType.BIEXPONENTIAL:
        return transform_type, {}

    pooled = np.concatenate(raw_arrays) if raw_arrays else np.array([])
    top = detect_logicle_top(pooled)
    width, negative = estimate_logicle_params(pooled, t=top)
    return transform_type, {"top": top, "width": width, "negative": negative}


def _global_range(arrays: list[np.ndarray]) -> tuple[float, float]:
    """Compute a shared x-axis range across all already-transformed arrays."""
    all_vals = np.concatenate(arrays) if arrays else np.array([])
    all_vals = all_vals[np.isfinite(all_vals)]
    if len(all_vals) == 0:
        return 0.0, 1.0

    p1, p99 = np.percentile(all_vals, [0.5, 99.5])
    span = p99 - p1
    if span <= 0:
        span = max(abs(p99), 1.0)
    return p1 - span * 0.02, p99 + span * 0.02


def _apply_bio_ticks(
    ax, transform_type: TransformType, transform_kwargs: dict, show_neg_decade: bool
) -> None:
    """Place biological decade ticks ($10^3$/$10^4$/$10^5$, ...) at their
    correct transformed-space positions on the (already-linear) axis.

    Data feeding this axis was already run through the same transform in
    prepare() — see module docstring — so the axis itself stays linear;
    only tick placement/labels change here, mirroring AxisFormatter on the
    main gating canvas (analysis.transforms.biological_tick_values is
    shared by both) so the same channel/transform reads identically in
    both places. Tick *positions* must be exact (never dithered) even
    though the event data feeding the curves was — same convention as
    CoordinateMapper._biexp_kwargs on the main canvas. `enable_dithering`
    is only ever passed for biexponential — log_transform()/
    linear_transform() don't accept **kwargs at all, unlike
    biexponential_transform(), so it can't be added unconditionally.
    """
    if transform_type == TransformType.LINEAR:
        return
    is_biex = transform_type == TransformType.BIEXPONENTIAL
    raw_ticks, labels = biological_tick_values(is_biex, show_neg_decade)
    tick_kwargs = dict(transform_kwargs)
    if is_biex:
        tick_kwargs["enable_dithering"] = False
    disp_ticks = apply_transform(raw_ticks, transform_type, **tick_kwargs)
    ax.xaxis.set_major_locator(FixedLocator(disp_ticks.tolist()))
    ax.xaxis.set_major_formatter(FixedFormatter(labels))


def _style_spine(ax, fg_color: str, border_color: str) -> None:
    ax.tick_params(colors=fg_color, labelsize=8, length=3)
    for side, spine in ax.spines.items():
        if side in ("top", "right"):
            spine.set_visible(False)
        else:
            spine.set_color(border_color)


def _empty_figure(bg_color: str, fg_color: str, border_color: str) -> Figure:
    fig = Figure(figsize=(8, 5), facecolor=bg_color)
    ax = fig.add_subplot(111)
    ax.set_facecolor(bg_color)
    ax.text(
        0.5,
        0.5,
        "No data to display.\nSelect samples and a channel, then Generate.",
        ha="center",
        va="center",
        color=fg_color,
        fontsize=12,
        transform=ax.transAxes,
    )
    _style_spine(ax, fg_color, border_color)
    return fig


# ── Overlay layout ─────────────────────────────────────────────────────────────


def _render_overlay(  # noqa: PLR0913
    curves: list[_Curve],
    x_min: float,
    x_max: float,
    channel_label: str,
    normalize_to_peak: bool,
    transform_type: TransformType,
    transform_kwargs: dict,
    show_neg_decade: bool,
    show_legend: bool,
    line_width: float,
    bg_color: str,
    fg_color: str,
    border_color: str,
) -> Figure:
    fig = Figure(figsize=(9, 5), facecolor=bg_color)
    ax = fig.add_subplot(111)
    ax.set_facecolor(bg_color)

    for curve in curves:
        ax.fill_between(curve.x, curve.y, alpha=0.45, color=curve.color, linewidth=0)
        ax.plot(
            curve.x,
            curve.y,
            color=curve.color,
            linewidth=line_width,
            alpha=0.9,
            label=curve.label,
        )

    _apply_bio_ticks(ax, transform_type, transform_kwargs, show_neg_decade)
    ax.set_xlabel(channel_label, color=fg_color, fontsize=11)
    y_label = "Normalised Density" if normalize_to_peak else "Density"
    ax.set_ylabel(y_label, color=fg_color, fontsize=10)
    ax.set_xlim(x_min, x_max)
    ax.set_ylim(bottom=0)

    if show_legend and curves:
        leg = ax.legend(
            fontsize=9,
            framealpha=0.15,
            facecolor=bg_color,
            edgecolor=border_color,
            labelcolor=fg_color,
            loc="upper right",
        )
        for text in leg.get_texts():
            text.set_color(fg_color)

    _style_spine(ax, fg_color, border_color)
    ax.set_title(f"Histogram Overlay — {channel_label}", color=fg_color, fontsize=12, pad=10)
    fig.tight_layout(pad=1.5)
    return fig


# ── Ridge (waterfall) layout ───────────────────────────────────────────────────


def _render_ridge(  # noqa: PLR0913, PLR0915
    curves: list[_Curve],
    x_min: float,
    x_max: float,
    channel_label: str,
    ridge_overlap: float,
    normalize_to_peak: bool,
    transform_type: TransformType,
    transform_kwargs: dict,
    show_neg_decade: bool,
    line_width: float,
    bg_color: str,
    fg_color: str,
    border_color: str,
) -> Figure:
    n = len(curves)
    # Height per row; overlap shrinks the effective row height
    row_h = 1.4
    fig_h = max(4.0, n * row_h * (1.0 - ridge_overlap * 0.5) + 1.5)
    fig = Figure(figsize=(8, fig_h), facecolor=bg_color)

    # Build one axes per row using manual positioning so they can overlap.
    # Top/bottom margins are fixed *absolute* sizes (inches), converted to a
    # fraction of this figure's height rather than hardcoded as a fraction
    # directly. fig_h grows with n (more populations = a taller figure), so a
    # margin expressed as a flat fraction (e.g. "8% of the figure") grows
    # right along with it — at n=50 that 8% is several inches of blank
    # canvas. A fixed inch size keeps the blank border visually constant
    # regardless of how many rows are stacked.
    left_margin = 0.08
    right_margin = 0.05
    bottom_margin_in = 0.5
    top_margin_in = 0.45
    bottom_margin = bottom_margin_in / fig_h
    top_margin = top_margin_in / fig_h

    usable_h = 1.0 - bottom_margin - top_margin
    # Standard ridge-plot spacing: panels are `panel_h` tall (figure
    # fraction) and spaced `step` apart, overlapping by (panel_h - step).
    # Solving panel_h + (n-1)*step = usable_h with step = panel_h*(1-overlap)
    # gives a well-defined panel_h in (0, usable_h] for any n >= 1 and any
    # overlap in [0, 1) — unlike the previous formula, no separate cap is
    # needed to keep panels from overflowing the figure.
    if n > 1:
        panel_h = usable_h / (1.0 + (n - 1) * (1.0 - ridge_overlap))
        step = panel_h * (1.0 - ridge_overlap)
    else:
        panel_h = usable_h
        step = 0.0

    axes = []
    for i, curve in enumerate(reversed(curves)):
        # Panels are laid out bottom→top; i=0 is the bottommost visible row.
        bottom = bottom_margin + i * step
        rect = [left_margin, bottom, 1.0 - left_margin - right_margin, panel_h]
        ax = fig.add_axes(rect)  # type: ignore
        ax.set_facecolor(bg_color)
        ax.patch.set_alpha(0.0)  # transparent so lower panels show through

        x_vals, y_vals = curve.x, curve.y

        # Filled area — use a slightly lighter/more opaque fill
        ax.fill_between(
            x_vals,
            y_vals,
            alpha=0.65,
            color=curve.color,
            linewidth=0,
        )
        # Solid top-edge line
        ax.plot(x_vals, y_vals, color=curve.color, linewidth=line_width, alpha=0.95)
        # Flat baseline
        ax.axhline(0, color=curve.color, linewidth=0.8, alpha=0.4)

        # Clip y so the fill from THIS panel doesn't spill into the panel above
        ax.set_ylim(0, y_vals.max() * 1.25 if y_vals.max() > 0 else 1.0)
        ax.set_xlim(x_min, x_max)

        _apply_bio_ticks(ax, transform_type, transform_kwargs, show_neg_decade)

        # Label — right-aligned text inside the panel (like reference image)
        ax.text(
            0.97,
            0.72,
            curve.label,
            transform=ax.transAxes,
            ha="right",
            va="center",
            fontsize=9.5,
            fontweight="bold",
            color=fg_color,
        )

        # Spines and ticks — only bottom panel shows X ticks
        is_bottom = i == 0
        for side, spine in ax.spines.items():
            if side == "bottom":
                spine.set_color(border_color)
                spine.set_linewidth(0.8)
            else:
                spine.set_visible(False)

        if is_bottom:
            ax.tick_params(
                axis="x",
                which="both",
                colors=fg_color,
                labelsize=8,
                length=3,
                bottom=True,
                labelbottom=True,
            )
            ax.set_xlabel(channel_label, color=fg_color, fontsize=11, labelpad=4)
        else:
            ax.tick_params(
                axis="x",
                which="both",
                bottom=True,
                labelbottom=False,
                length=2,
                colors=border_color,
            )

        ax.tick_params(axis="y", left=False, labelleft=False)
        axes.append(ax)

    # Shared title above the topmost panel
    top_ax = axes[-1]
    # Ridge panels have no y-axis ticks/label (standard for this style), so
    # without this note a peak-normalized curve's height is easy to misread
    # as relative abundance/event count rather than relative shape.
    title_suffix = " — peak-normalized" if normalize_to_peak else ""
    top_ax.set_title(
        f"{channel_label}{title_suffix}",
        color=fg_color,
        fontsize=12,
        pad=6,
        loc="left",
    )

    return fig
