"""The Population Statistics tab's 100% stacked expression-profile chart (headless)."""

from __future__ import annotations

import matplotlib as mpl
import numpy as np
from karcytics_sdk.plugin.rendering import AxesColors, style_axes
from matplotlib.figure import Figure

from ..graph.figure_renderer import IPlotRenderer


class ExpressionProfileRenderer(IPlotRenderer):
    """One stacked bar per cluster: each marker's share of the cluster's expression.

    kwargs: ``profiles`` (clusters × markers, rows summing to 100, from
    ``result_tables.stacked_profiles``), ``cluster_labels``, ``marker_labels``,
    and the colours ``background``, ``panel``, ``foreground``, ``secondary``,
    ``border``.
    """

    def render(self, **kwargs) -> Figure:
        profiles: np.ndarray = kwargs["profiles"]
        foreground: str = kwargs["foreground"]
        fig = Figure(facecolor=kwargs["background"], figsize=(6, 4))
        ax = fig.add_subplot(111)
        style_axes(ax, AxesColors(kwargs["secondary"], kwargs["border"], kwargs["background"]))
        ax.tick_params(labelsize=8)

        x = np.arange(len(profiles))
        bottoms = np.zeros(len(profiles))
        palette = mpl.colormaps["tab20"]
        for j, marker in enumerate(kwargs["marker_labels"]):
            ax.bar(
                x, profiles[:, j], width=0.7, bottom=bottoms, label=marker, color=palette(j % 20)
            )
            bottoms += profiles[:, j]

        ax.set_xticks(x)
        ax.set_xticklabels([str(label) for label in kwargs["cluster_labels"]])
        ax.set_xlabel("Cluster ID", color=foreground, fontsize=9)
        ax.set_ylabel("Relative Expression (%)", color=foreground, fontsize=9)
        ax.set_title("100% Stacked Expression Profiles", color=foreground, fontsize=10)
        ax.legend(
            bbox_to_anchor=(1.02, 1),
            loc="upper left",
            fontsize=8,
            facecolor=kwargs["panel"],
            edgecolor=kwargs["border"],
            labelcolor=foreground,
        )
        fig.subplots_adjust(right=0.75, bottom=0.15)
        fig.tight_layout()
        return fig
