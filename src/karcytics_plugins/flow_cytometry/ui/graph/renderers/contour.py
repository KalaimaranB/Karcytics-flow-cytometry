"""Renderer strategy for 2D Contour plots."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ....analysis.rendering import contour_levels, density_grid, stable_subsample_mask
from .base import DisplayStrategy


@dataclass
class ContourRenderData:
    """Precomputed contour grids (or a sparse-fallback point cloud), ready to draw."""

    sparse: bool
    x_vis: np.ndarray
    y_vis: np.ndarray
    X: np.ndarray | None = None
    Y: np.ndarray | None = None
    smoothed: np.ndarray | None = None
    levels_arr: np.ndarray | list | None = None
    show_filled: bool = False
    color_mode: str = "black"
    colormap: str = "viridis"
    show_dot_underlay: bool = False
    dot_x: np.ndarray | None = None
    dot_y: np.ndarray | None = None


class ContourStrategy(DisplayStrategy):
    """2D Contour plot renderer."""

    def compute(
        self, x: np.ndarray, y: np.ndarray | None = None, *, xlim=None, ylim=None, **kwargs
    ) -> ContourRenderData:
        """Compute smoothed density contour grids."""
        assert y is not None
        assert xlim is not None
        assert ylim is not None
        valid = np.isfinite(x) & np.isfinite(y)
        x_vis, y_vis = x[valid], y[valid]

        if len(x_vis) < 100:  # noqa: PLR2004
            return ContourRenderData(sparse=True, x_vis=x_vis, y_vis=y_vis)

        X, Y, smoothed = density_grid(
            x_vis,
            y_vis,
            xlim,
            ylim,
            bins=kwargs.get("bins", 100),
            sigma=kwargs.get("sigma", kwargs.get("smoothing", 1.5)),
        )
        levels_arr = contour_levels(smoothed, kwargs.get("levels", kwargs.get("num_levels", 10)))

        show_dot_underlay = kwargs.get("show_dot_underlay", False)
        dot_x = dot_y = None
        if show_dot_underlay:
            max_dots = min(len(x_vis), 30_000)
            if len(x_vis) > max_dots:
                # stable_subsample_mask, not Generator.choice — stable
                # under small population-size differences (see its docstring).
                mask = stable_subsample_mask(len(x_vis), max_dots)
                dot_x, dot_y = x_vis[mask], y_vis[mask]
            else:
                dot_x, dot_y = x_vis, y_vis

        return ContourRenderData(
            sparse=False,
            x_vis=x_vis,
            y_vis=y_vis,
            X=X,
            Y=Y,
            smoothed=smoothed,
            levels_arr=levels_arr,
            show_filled=kwargs.get("show_filled", False),
            color_mode=kwargs.get("color_mode", "black"),
            colormap=kwargs.get("colormap", "viridis"),
            show_dot_underlay=show_dot_underlay,
            dot_x=dot_x,
            dot_y=dot_y,
        )

    def draw(self, ax, data: ContourRenderData, **kwargs) -> None:
        """Draw the precomputed contour grids (or sparse-fallback scatter)."""
        if data.sparse:
            ax.scatter(data.x_vis, data.y_vis, s=2, alpha=0.3)
            return

        assert data.smoothed is not None

        # Optional dot underlay first (zorder=0 so contours sit on top)
        if data.show_dot_underlay and data.dot_x is not None:
            ax.scatter(
                data.dot_x,
                data.dot_y,
                s=1,
                c="#888888",
                alpha=0.15,
                zorder=0,
                rasterized=True,
                edgecolors="none",
            )

        # Filled contours
        if data.show_filled:
            ax.contourf(
                data.X,
                data.Y,
                data.smoothed.T,
                levels=data.levels_arr,
                cmap=data.colormap,
                alpha=0.5,
                zorder=1,
            )

        # Contour lines — color mode determines style
        if data.color_mode == "colormap":
            ax.contour(
                data.X,
                data.Y,
                data.smoothed.T,
                levels=data.levels_arr,
                cmap=data.colormap,
                alpha=0.8,
                linewidths=0.8,
                zorder=2,
            )
        elif data.color_mode == "blue":
            ax.contour(
                data.X,
                data.Y,
                data.smoothed.T,
                levels=data.levels_arr,
                colors="#1565C0",
                alpha=0.7,
                linewidths=0.8,
                zorder=2,
            )
        else:  # black (default)
            ax.contour(
                data.X,
                data.Y,
                data.smoothed.T,
                levels=data.levels_arr,
                colors="k",
                alpha=0.5,
                linewidths=0.8,
                zorder=2,
            )
