"""Renderer strategy for simple subsampled scatter plots."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from karcytics_sdk.plugin.theme_fallback import Colors

from ....analysis.rendering import stable_subsample_mask
from .base import DisplayStrategy


@dataclass
class DotPlotRenderData:
    """Precomputed (possibly subsampled) scatter points, ready to draw."""

    x: np.ndarray
    y: np.ndarray
    s: float
    c: str
    alpha: float


class DotPlotStrategy(DisplayStrategy):
    """Simple subsampled scatter plot renderer."""

    def compute(
        self, x: np.ndarray, y: np.ndarray | None = None, *, xlim=None, ylim=None, **kwargs
    ) -> DotPlotRenderData:
        """Subsample events as needed and bundle draw parameters."""
        if y is None:
            raise ValueError("A dot plot needs a y channel.")
        max_events = kwargs.get("max_events", 100_000)
        n = len(x)

        if max_events is not None and n > max_events:
            # stable_subsample_mask, not Generator.choice — a gated
            # population differing by a handful of events between two
            # otherwise-identical renders must not resample ~50% of the
            # plotted points as a result (see its docstring).
            mask = stable_subsample_mask(n, max_events)
            x, y = x[mask], y[mask]

        return DotPlotRenderData(
            x=x,
            y=y,
            s=kwargs.get("s", kwargs.get("dot_size", 2)),
            c=kwargs.get("c", kwargs.get("dot_color", Colors.ACCENT_PRIMARY)),
            alpha=kwargs.get("alpha", kwargs.get("opacity", 0.25)),
        )

    def draw(self, ax, data: DotPlotRenderData, **kwargs) -> None:
        """Draw the precomputed (possibly subsampled) scatter points."""
        ax.scatter(
            data.x,
            data.y,
            s=data.s,
            c=data.c,
            alpha=data.alpha,
            rasterized=True,
            edgecolors="none",
        )
