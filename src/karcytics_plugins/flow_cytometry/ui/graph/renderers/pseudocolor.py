from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from karcytics_sdk.plugin import get_logger

from ....analysis.constants import PSEUDOCOLOR_MAX_EVENTS
from ....analysis.rendering import compute_pseudocolor_points, stable_subsample_mask
from .base import DisplayStrategy

logger = get_logger(__name__, "flow_cytometry")


@dataclass
class PseudocolorRenderData:
    """Precomputed density-colored scatter points, ready to draw."""

    x_plot: np.ndarray
    y_plot: np.ndarray
    c_plot: np.ndarray
    cmap_name: str
    alpha: float
    point_size: float


class PseudocolorStrategy(DisplayStrategy):
    """Canonical pseudocolor density renderer."""

    def compute(
        self, x: np.ndarray, y: np.ndarray | None = None, *, xlim=None, ylim=None, **kwargs
    ) -> PseudocolorRenderData | None:
        """Compute density-colored scatter points using unified robust math."""
        # Fix import path (rendering is in a sibling of ui, not a child)

        # Subsample for UI performance if extremely large
        max_events = kwargs.get("max_events", PSEUDOCOLOR_MAX_EVENTS)

        if x is None or y is None or xlim is None or ylim is None:
            return None

        # Ensure we use numpy arrays for positional indexing and performance
        x_np = np.asarray(x)
        y_np = np.asarray(y)

        if max_events is not None and len(x_np) > max_events:
            # stable_subsample_mask (not Generator.choice) — see its
            # docstring. A gated population that differs by only a handful
            # of events between two otherwise-identical renders (routine
            # floating-point rounding at a gate boundary) must not resample
            # ~50% of the plotted points as a result.
            mask = stable_subsample_mask(len(x_np), max_events)
            x_sub, y_sub = x_np[mask], y_np[mask]
        else:
            x_sub, y_sub = x_np, y_np

        x_lo, x_hi = xlim
        y_lo, y_hi = ylim

        # Use grid_size if provided, otherwise fall back to quality_multiplier
        grid_size = kwargs.get("grid_size")
        if grid_size:
            # Convert grid_size to quality_multiplier (base is 512)
            quality_multiplier = grid_size / 512.0
        else:
            quality_multiplier = kwargs.get("quality_multiplier", 1.0)

        x_plot, y_plot, c_plot = compute_pseudocolor_points(
            x_sub,
            y_sub,
            (x_lo, x_hi),
            (y_lo, y_hi),
            quality_multiplier=quality_multiplier,
            nbins_scaling=kwargs.get("nbins_scaling"),
            sigma_scaling=kwargs.get("sigma_scaling"),
            density_threshold=kwargs.get("density_threshold"),
            vibrancy_min=kwargs.get("vibrancy_min"),
            vibrancy_range=kwargs.get("vibrancy_range"),
        )

        # Revert to 'o' to maintain the classic thick blue cloud appearance
        # Point size 1.0 for Full, 1.5 for Optimized
        cmap_name: str = kwargs.get("cmap", kwargs.get("colormap", "jet"))
        alpha = kwargs.get("alpha", 0.6)
        is_full = kwargs.get("quality_multiplier", 1.0) >= 2.0  # noqa: PLR2004
        point_size = kwargs.get("s", 1.0 if is_full else 1.5)

        return PseudocolorRenderData(
            x_plot=x_plot,
            y_plot=y_plot,
            c_plot=c_plot,
            cmap_name=cmap_name,
            alpha=alpha,
            point_size=point_size,
        )

    def draw(self, ax, data: PseudocolorRenderData | None, **kwargs) -> None:
        """Draw the precomputed density-colored scatter."""
        if data is None:
            return

        ax.scatter(
            data.x_plot,
            data.y_plot,
            s=data.point_size,
            c=data.c_plot,
            cmap=data.cmap_name,
            vmin=0.0,
            vmax=1.0,
            alpha=data.alpha,
            marker="o",
            rasterized=True,
            edgecolors="none",
            zorder=0,
        )
