"""Radar/Spider chart renderer — one polar subplot per population, one spoke per channel.

Design: instead of cramming all populations onto one polar chart (which creates an
unreadable mega-cluster), each (sample, population) pair gets its own subplot arranged
in a grid.  Shapes become easy to compare side-by-side.
"""

from __future__ import annotations

import math
import textwrap

import numpy as np
from matplotlib.figure import Figure

from ....graph.figure_renderer import IPlotRenderer

_DEFAULT_PALETTE = [
    "#00bcd4",
    "#ef5350",
    "#66bb6a",
    "#ffa726",
    "#ab47bc",
    "#26c6da",
    "#ff7043",
    "#9ccc65",
]


class RadarRenderer(IPlotRenderer):
    """SRP: renders a grid of polar radar subplots, one per (sample, population) pair."""

    def render(self, **kwargs) -> Figure:  # noqa: PLR0915
        # data: {label: [value_per_channel]}
        data: dict[str, list[float]] = kwargs["data"]
        channel_labels: list[str] = kwargs["channel_labels"]
        normalise: bool = kwargs.get("normalise", True)
        fill_alpha: float = kwargs.get("fill_alpha", 0.30)
        line_width: float = kwargs.get("line_width", 2.0)
        bg_color: str = kwargs.get("bg_color", "#0d1117")
        fg_color: str = kwargs.get("fg_color", "#e6edf3")
        border_color: str = kwargs.get("border_color", "#30363d")
        palette: list[str] = kwargs.get("palette", _DEFAULT_PALETTE)

        populations = list(data.keys())
        n_channels = len(channel_labels)

        if not populations or n_channels < 3:  # noqa: PLR2004
            fig = Figure(figsize=(6, 5), facecolor=bg_color)
            ax = fig.add_subplot(111)
            ax.set_facecolor(bg_color)
            ax.text(
                0.5,
                0.5,
                "Select at least 3 channels and one population."
                if not populations
                else "Select at least 3 channels for a radar chart.",
                ha="center",
                va="center",
                color=fg_color,
                transform=ax.transAxes,
                fontsize=12,
            )
            ax.axis("off")
            return fig

        # Build spoke angles
        angles = np.linspace(0, 2 * np.pi, n_channels, endpoint=False).tolist()
        angles_closed = angles + [angles[0]]

        # Normalise: for each channel, scale so max across ALL populations = 1
        matrix = np.array([data[p] for p in populations], dtype=float)  # (n_pops, n_ch)
        if normalise:
            ch_max = np.nanmax(np.abs(matrix), axis=0)
            ch_max[ch_max == 0] = 1.0
            matrix = matrix / ch_max

        # Grid layout: prefer roughly square, max 3 columns
        n_pops = len(populations)
        n_cols = min(3, n_pops)
        n_rows = math.ceil(n_pops / n_cols)

        fig_w = max(6, n_cols * 7.5)
        fig_h = max(5, n_rows * 6.5)
        fig = Figure(figsize=(fig_w, fig_h), facecolor=bg_color)
        fig.suptitle(
            "Immunophenotype Radar" + (" (normalised per channel)" if normalise else ""),
            color=fg_color,
            fontsize=14,
            y=1.0,
        )

        for i, pop_label in enumerate(populations):
            ax = fig.add_subplot(n_rows, n_cols, i + 1, projection="polar")
            ax.set_facecolor(bg_color)
            ax.spines["polar"].set_color(border_color)

            values = matrix[i].tolist()
            values_closed = values + [values[0]]
            colour = palette[i % len(palette)]

            ax.plot(angles_closed, values_closed, color=colour, linewidth=line_width)
            ax.fill(angles_closed, values_closed, color=colour, alpha=fill_alpha)

            # Spoke labels
            ax.set_xticks(angles)
            wrapped_labels = [textwrap.fill(lbl, width=16) for lbl in channel_labels]
            ax.set_xticklabels(wrapped_labels, color=fg_color, fontsize=10)
            ax.tick_params(pad=15)

            # Radial axis
            ax.set_ylim(0, 1.05 if normalise else matrix.max() * 1.1)
            ax.tick_params(axis="y", colors=fg_color, labelsize=8)
            ax.yaxis.set_tick_params(labelcolor=border_color, labelsize=8)
            ax.grid(color=border_color, linewidth=0.5, alpha=0.5)

            # Title = the population label (truncated if long)
            max_title_length = 50
            title = (
                pop_label
                if len(pop_label) <= max_title_length
                else pop_label[: max_title_length - 3] + "…"
            )
            title = textwrap.fill(title, width=35)
            ax.set_title(title, color=colour, fontsize=12, pad=20)

        fig.patch.set_facecolor(bg_color)
        fig.tight_layout(pad=4.0, w_pad=6.0, h_pad=5.0)
        return fig
