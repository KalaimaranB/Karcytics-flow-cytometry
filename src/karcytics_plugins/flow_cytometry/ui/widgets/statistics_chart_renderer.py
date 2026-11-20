"""The Statistics tab's chart: one statistic by population, per sample (headless)."""

from __future__ import annotations

import numpy as np
from karcytics_sdk.plugin.rendering import AxesColors, style_axes
from karcytics_sdk.plugin.theme_fallback import get_contrast_text_color
from matplotlib.colors import LinearSegmentedColormap, to_hex
from matplotlib.figure import Figure

from ..graph.figure_renderer import IPlotRenderer

CHART_TYPES = ("Grouped Bar", "Horizontal Bar", "Heatmap")


class StatisticsChartRenderer(IPlotRenderer):
    """Grouped or horizontal bars (a colour per sample), or a populations × samples heatmap.

    kwargs: ``chart_type`` (one of ``CHART_TYPES``), ``stat_label``,
    ``population_labels``, ``sample_names``, ``values`` and ``estimated``
    (populations × samples, from ``StatisticsTable.values``), ``palette``
    (a colour per sample), and the colours ``background``, ``panel``,
    ``foreground``, ``secondary``, ``border``, ``accent``, ``warning``.
    Estimated values are marked with "*".
    """

    def render(self, **kwargs) -> Figure:
        fig = Figure(facecolor=kwargs["background"])
        ax = fig.add_subplot(111)
        style_axes(ax, AxesColors(kwargs["secondary"], kwargs["border"]), open_frame=True)
        ax.set_facecolor(kwargs["panel"])
        if kwargs["chart_type"] == "Heatmap":
            self._heatmap(fig, ax, kwargs)
        else:
            self._bars(ax, kwargs)
        ax.set_title(
            f"{kwargs['stat_label']} by Population",
            color=kwargs["foreground"],
            fontsize=12,
            pad=12,
        )
        fig.tight_layout(pad=1.5)
        return fig

    @staticmethod
    def _heatmap(fig: Figure, ax, kw: dict) -> None:
        values: np.ndarray = kw["values"]
        estimated: np.ndarray = kw["estimated"]
        cmap = LinearSegmentedColormap.from_list("theme_heatmap", [kw["panel"], kw["accent"]])
        image = ax.imshow(values, aspect="auto", cmap=cmap)
        low, high = (values.min(), values.max()) if values.size else (0.0, 0.0)
        for (i, j), value in np.ndenumerate(values):
            fraction = 0.0 if high <= low else (value - low) / (high - low)
            ax.text(
                j,
                i,
                f"{value:.1f}{'*' if estimated[i, j] else ''}",
                ha="center",
                va="center",
                color=get_contrast_text_color(to_hex(cmap(fraction))),
                fontsize=8,
            )
        ax.set_xticks(np.arange(len(kw["sample_names"])))
        ax.set_xticklabels(
            kw["sample_names"], rotation=30, ha="right", color=kw["foreground"], fontsize=9
        )
        ax.set_yticks(np.arange(len(kw["population_labels"])))
        ax.set_yticklabels(kw["population_labels"], color=kw["foreground"], fontsize=9)
        cbar = fig.colorbar(image, ax=ax)
        cbar.ax.yaxis.set_tick_params(color=kw["secondary"], labelcolor=kw["secondary"])
        cbar.outline.set_edgecolor(kw["border"])  # type: ignore[operator]  # a Spine, typed loosely

    @staticmethod
    def _bars(ax, kw: dict) -> None:
        values: np.ndarray = kw["values"]
        estimated: np.ndarray = kw["estimated"]
        horizontal = kw["chart_type"] == "Horizontal Bar"
        names = kw["sample_names"]
        x = np.arange(len(kw["population_labels"]))
        width = max(0.1, 0.7 / max(len(names), 1))
        for s, name in enumerate(names):
            offset = (s - len(names) / 2 + 0.5) * width
            color = kw["palette"][s % len(kw["palette"])]
            if horizontal:
                ax.barh(x + offset, values[:, s], width, label=name, color=color, alpha=0.85)
                continue
            bars = ax.bar(x + offset, values[:, s], width, label=name, color=color, alpha=0.85)
            for bar, value, is_estimate in zip(bars, values[:, s], estimated[:, s], strict=True):
                ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    bar.get_height() * 1.01,
                    f"{value:.1f}{'*' if is_estimate else ''}",
                    ha="center",
                    va="bottom",
                    color=kw["warning"] if is_estimate else kw["secondary"],
                    fontsize=7,
                )
        labels = dict(color=kw["foreground"], fontsize=9)
        if horizontal:
            ax.set_yticks(x)
            ax.set_yticklabels(kw["population_labels"], **labels)
            ax.set_xlabel(kw["stat_label"], color=kw["secondary"], fontsize=10)
        else:
            ax.set_xticks(x)
            ax.set_xticklabels(kw["population_labels"], rotation=30, ha="right", **labels)
            ax.set_ylabel(kw["stat_label"], color=kw["secondary"], fontsize=10)
        if len(names) > 1:
            ax.legend(
                facecolor=kw["panel"],
                edgecolor=kw["border"],
                labelcolor=kw["foreground"],
                fontsize=9,
            )
