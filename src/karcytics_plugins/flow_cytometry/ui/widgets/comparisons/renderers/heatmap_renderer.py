"""Channel heatmap renderer — samples × channels coloured by statistic."""

from __future__ import annotations

import numpy as np
import pandas as pd
from karcytics_sdk.plugin.rendering import AxesColors, style_axes
from matplotlib.figure import Figure

from .base import IPlotRenderer


class HeatmapRenderer(IPlotRenderer):
    """SRP: renders a 2D heatmap of (populations × channels) statistic values."""

    def render(self, **kwargs) -> Figure:  # noqa: PLR0915
        matrix: np.ndarray = kwargs["matrix"]  # shape (n_rows, n_cols)
        row_labels: list[str] = kwargs["row_labels"]
        col_labels: list[str] = kwargs["col_labels"]
        normalise: bool = kwargs.get("normalise", True)
        cmap: str = kwargs.get("cmap", "RdYlBu_r")
        annotate: bool = kwargs.get("annotate", True)
        bg_color: str = kwargs.get("bg_color", "#0d1117")
        fg_color: str = kwargs.get("fg_color", "#e6edf3")
        border_color: str = kwargs.get("border_color", "#30363d")

        n_rows, n_cols = matrix.shape
        fig_w = max(8, n_cols * 1.2 + 3)
        fig_h = max(5, n_rows * 0.8 + 2)
        fig = Figure(figsize=(fig_w, fig_h), facecolor=bg_color)
        ax = fig.add_subplot(111)
        ax.set_facecolor(bg_color)

        if n_rows == 0 or n_cols == 0:
            ax.text(
                0.5,
                0.5,
                "No data to display",
                ha="center",
                va="center",
                color=fg_color,
                transform=ax.transAxes,
                fontsize=13,
            )
            style_axes(ax, AxesColors(fg_color, border_color))
            return fig

        display = matrix.copy()
        if normalise:
            # Normalise each column independently to [0, 1]
            col_min = np.nanmin(display, axis=0)
            col_max = np.nanmax(display, axis=0)
            rng = col_max - col_min
            rng[rng == 0] = 1.0
            display = (display - col_min) / rng

        try:
            import seaborn as sns  # karcytics: allow KS360 - heavy library

            df_heat = pd.DataFrame(display, index=row_labels, columns=col_labels)
            annot_data = matrix if annotate else None  # annotate with raw values
            sns.heatmap(
                df_heat,
                ax=ax,
                cmap=cmap,
                annot=annot_data,
                fmt=".0f" if annotate else "",
                linewidths=0.3,
                linecolor=border_color,
                cbar=True,
                cbar_kws={"shrink": 0.8},
            )
            # Restyle after seaborn overrides
            ax.set_xticklabels(
                col_labels,
                color=fg_color,
                fontsize=9,
                rotation=35,
                ha="right",
                rotation_mode="anchor",
            )
            ax.set_yticklabels(row_labels, color=fg_color, fontsize=9, rotation=0)
            cbar = ax.collections[0].colorbar
            if cbar:
                cbar.ax.tick_params(colors=fg_color, labelsize=8)
                cbar.ax.yaxis.label.set_color(fg_color)
                cbar.outline.set_edgecolor(border_color)  # type: ignore

        except Exception:
            # Fallback: pure matplotlib imshow
            im = ax.imshow(display, cmap=cmap, aspect="auto")
            ax.set_xticks(range(n_cols))
            ax.set_xticklabels(
                col_labels,
                color=fg_color,
                fontsize=9,
                rotation=35,
                ha="right",
                rotation_mode="anchor",
            )
            ax.set_yticks(range(n_rows))
            ax.set_yticklabels(row_labels, color=fg_color, fontsize=9)
            fig.colorbar(im, ax=ax, shrink=0.8)
            if annotate:
                for r in range(n_rows):
                    for c in range(n_cols):
                        val = matrix[r, c]
                        if np.isfinite(val):
                            ax.text(
                                c,
                                r,
                                f"{val:.0f}",
                                ha="center",
                                va="center",
                                color=fg_color,
                                fontsize=7,
                            )

        title = "Channel Expression Heatmap" + (" (normalised per channel)" if normalise else "")
        ax.set_title(title, color=fg_color, fontsize=12, pad=10)
        style_axes(ax, AxesColors(fg_color, border_color))
        fig.tight_layout(pad=1.5)

        # tight_layout often underestimates the bounding box of rotated text before rendering.
        # Enforce a minimum bottom and left margin to ensure labels are not cut off.
        try:
            fig.subplots_adjust(
                bottom=max(fig.subplotpars.bottom, 0.25) if fig.subplotpars else 0.25,
                left=max(fig.subplotpars.left, 0.25) if fig.subplotpars else 0.25,
            )
        except Exception:
            pass

        return fig
