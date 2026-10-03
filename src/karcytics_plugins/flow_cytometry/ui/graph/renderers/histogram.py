"""Renderer strategy for 1D frequency histograms."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
from karcytics_sdk.plugin.theme_fallback import Colors

from .base import DisplayStrategy

logger = logging.getLogger(__name__)


@dataclass
class HistogramRenderData:
    """Precomputed bin edges, FMO data, KDE curve, and threshold, ready to draw.

    ``ax.hist()`` itself stays in ``draw()`` — it's cheap relative to the KDE
    evaluation below, and reimplementing its binning/patch logic outside
    matplotlib isn't worth the behavioral risk. The genuinely expensive parts
    (validity filtering of large arrays, scipy's O(n*grid) KDE evaluation) are
    what compute() pulls out.
    """

    valid_x: np.ndarray
    fmo_valid_x: np.ndarray
    bin_edges: np.ndarray
    bins: int
    density_mode: bool
    p_val: float | None
    x_grid: np.ndarray | None
    kde_vals: np.ndarray | None
    # Events inside a highlighted gate (a subset of ``valid_x``), drawn over
    # the population on the same bins. None = no gate to highlight.
    highlight_x: np.ndarray | None = None


# The whole population, when it is only the backdrop to a highlighted gate.
_BACKDROP_COLOR = "#888888"


class HistogramStrategy(DisplayStrategy):
    """1D Histogram renderer with optional KDE overlay."""

    def compute(  # noqa: PLR0915
        self, x: np.ndarray, y: np.ndarray | None = None, *, xlim=None, ylim=None, **kwargs
    ) -> HistogramRenderData | None:
        """Compute bin edges, FMO threshold, and KDE curve for the histogram."""
        valid_x = x[np.isfinite(x)]
        if len(valid_x) == 0:
            return None

        density_mode = kwargs.get("y_axis_mode", "count") == "frequency"

        # Bin count — auto uses Sturges' rule, otherwise use provided value
        auto_bins = kwargs.get("auto_bins", False)
        if auto_bins:
            bins = int(np.ceil(np.log2(len(valid_x)) + 1))
            bins = max(32, min(bins, 512))
        else:
            bins = kwargs.get("bins", 256)

        fmo_data_x = kwargs.get("fmo_data_x")
        if fmo_data_x is not None:
            fmo_valid_x = fmo_data_x[np.isfinite(fmo_data_x)]
        else:
            fmo_valid_x = np.array([])

        # Calculate common bin edges so bars align perfectly
        if len(fmo_valid_x) > 0:
            min_val = min(valid_x.min(), fmo_valid_x.min())
            max_val = max(valid_x.max(), fmo_valid_x.max())
        else:
            min_val = valid_x.min()
            max_val = valid_x.max()

        if min_val == max_val:
            min_val -= 0.5
            max_val += 0.5

        bin_edges = np.linspace(min_val, max_val, bins + 1)

        p_val = None
        if (
            kwargs.get("show_fmo_threshold", True)
            and fmo_data_x is not None
            and len(fmo_valid_x) > 0
        ):
            perc = kwargs.get("fmo_threshold_percentile", 99.0)
            logger.debug(
                "[HIST-COMPUTE] np.percentile FMO threshold: n=%d perc=%s",
                len(fmo_valid_x),
                perc,
            )
            p_val = np.percentile(fmo_valid_x, perc)

        # Optional KDE smoothing overlay — the expensive part (O(n * grid))
        x_grid = None
        kde_vals = None
        smooth_kde = kwargs.get("smooth_kde", False)
        if smooth_kde and len(valid_x) > 10:  # noqa: PLR2004
            try:
                from scipy.stats import gaussian_kde

                logger.debug("[HIST-COMPUTE] gaussian_kde: n=%d", len(valid_x))
                kde = gaussian_kde(valid_x, bw_method="scott")
                x_grid = np.linspace(valid_x.min(), valid_x.max(), 512)
                kde_vals = kde(x_grid)
                logger.debug("[HIST-COMPUTE] gaussian_kde done")
                if not density_mode:
                    # Scale KDE to match raw count histogram
                    bin_width = (bin_edges[-1] - bin_edges[0]) / bins
                    kde_vals = kde_vals * len(valid_x) * bin_width
            except Exception:
                x_grid = None
                kde_vals = None  # KDE silently skipped on failure

        highlight_x = kwargs.get("highlight_x")
        if highlight_x is not None:
            highlight_x = highlight_x[np.isfinite(highlight_x)]

        return HistogramRenderData(
            highlight_x=highlight_x,
            valid_x=valid_x,
            fmo_valid_x=fmo_valid_x,
            bin_edges=bin_edges,
            bins=bins,
            density_mode=density_mode,
            p_val=p_val,
            x_grid=x_grid,
            kde_vals=kde_vals,
        )

    def draw(self, ax, data: HistogramRenderData | None, **kwargs) -> None:  # noqa: PLR0915
        """Draw the histogram, optional FMO overlay, threshold, and KDE curve."""
        if data is None:
            return

        color = kwargs.get("color", kwargs.get("bar_color", Colors.ACCENT_PRIMARY))
        filled = kwargs.get("filled", True)
        histtype = "stepfilled" if filled else "step"

        # Render FMO Overlay (drawn underneath main histogram)
        if len(data.fmo_valid_x) > 0:
            fmo_color = kwargs.get("fmo_color", "#888888")
            logger.debug(
                "[HIST-DRAW] ax.hist FMO: n=%d bins=%d dtype=%s",
                len(data.fmo_valid_x),
                data.bins,
                data.fmo_valid_x.dtype,
            )
            ax.hist(
                data.fmo_valid_x,
                bins=data.bin_edges,
                color=fmo_color,
                alpha=0.5,
                histtype="stepfilled",
                density=data.density_mode,
                zorder=0,  # Ensure it stays in the background
            )
            logger.debug("[HIST-DRAW] ax.hist FMO done")
            # Ensure the main histogram renders on top
            kwargs["zorder"] = 1

        logger.debug(
            "[HIST-DRAW] ax.hist main: n=%d bins=%d dtype=%s",
            len(data.valid_x),
            data.bins,
            data.valid_x.dtype,
        )
        ax.hist(
            data.valid_x,
            bins=data.bin_edges,
            color=color if data.highlight_x is None else _BACKDROP_COLOR,
            alpha=kwargs.get("alpha", 0.7),
            histtype=histtype,
            density=data.density_mode,
            zorder=kwargs.get("zorder", 1),
        )
        logger.debug("[HIST-DRAW] ax.hist main done")

        if data.highlight_x is not None and len(data.highlight_x) > 0:
            self._draw_highlight(ax, data, color)

        # Draw the threshold line for FMO AFTER both histograms
        if data.p_val is not None:
            perc = kwargs.get("fmo_threshold_percentile", 99.0)
            t_color = kwargs.get("fmo_threshold_color", "#ff4444")
            ax.axvline(x=data.p_val, color=t_color, linestyle="--", linewidth=1.5, zorder=3)

            # Format the text (e.g. 99th, 95.5th, 90th)
            perc_str = f"{perc:g}"
            suffix = (
                "th"
                if perc_str.endswith("11") or perc_str.endswith("12") or perc_str.endswith("13")
                else {"1": "st", "2": "nd", "3": "rd"}.get(perc_str[-1], "th")
            )

            ax.text(
                data.p_val,
                ax.get_ylim()[1] * 0.95,
                f" {perc_str}{suffix} %tile (Gate Threshold)",
                color=t_color,
                fontsize=8,
                va="top",
                ha="left",
                zorder=3,
            )

        # Optional KDE smoothing overlay
        if data.x_grid is not None and data.kde_vals is not None:
            ax.plot(data.x_grid, data.kde_vals, color=color, linewidth=1.5, alpha=0.9)

        y_label = "Frequency (%)" if data.density_mode else "Count"
        ax.set_ylabel(y_label, fontsize=9)
        logger.debug("[HIST-DRAW] draw complete")

    @staticmethod
    def _draw_highlight(ax, data: HistogramRenderData, color: str) -> None:
        """Draw the gated subset over the population, on the population's scale."""
        assert data.highlight_x is not None
        weights = None
        if data.density_mode:
            # Normalising the subset on its own would give it the same area as
            # the whole population; weight it as a share of the population.
            bin_width = (data.bin_edges[-1] - data.bin_edges[0]) / data.bins
            weights = np.full(len(data.highlight_x), 1.0 / (len(data.valid_x) * bin_width))
        ax.hist(
            data.highlight_x,
            bins=data.bin_edges,
            weights=weights,
            color=color,
            alpha=0.85,
            histtype="stepfilled",
            zorder=2,
        )
