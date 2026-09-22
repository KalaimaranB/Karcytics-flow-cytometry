"""Pseudocolor multi-population overlay renderer — one sample, many populations
plotted on a single 2D axis.

Generalizes the previous BackgatingRenderer (grey parent / single coloured
child, never registered in PLOT_REGISTRY) into an arbitrary-length stack of
population layers, with the base/context layer optionally density-shaded
(pseudocolor) instead of a flat grey scatter — reusing the same density math
(`compute_pseudocolor_points`) the single-sample gating canvas already uses
via `PseudocolorStrategy` (ui/graph/renderers/pseudocolor.py).

Plot chrome (white background, dark text/gridlines) intentionally does not
follow the app's dark/light theme — it matches the main gating canvas's own
`_PLOT_BG`/`_MPL_STYLE` (ui/graph/flow_canvas.py), which is white
unconditionally because the jet colormap's low-density floor renders as a
dark, near-invisible blue against a dark background. Overlay populations use
`JET_SAFE_OVERLAY_PALETTE` instead of the app's themed chart palette, since
jet's own hue range (blue→cyan→green→yellow→red) would make a themed blue/
green/red highlight blend into the density cloud instead of standing out
from it.
"""

from __future__ import annotations

import numpy as np
from matplotlib.figure import Figure
from matplotlib.ticker import FixedFormatter, FixedLocator

from karcytics_plugins.flow_cytometry.analysis.rendering import stable_subsample_mask
from karcytics_plugins.flow_cytometry.analysis.transforms import (
    TransformType,
    compute_bio_tick_positions,
)

from .base import IPlotRenderer

# Cap points actually drawn per layer — the underlying event arrays can be
# gate-sized (hundreds of thousands); rasterized scatter still needs a visual cap.
_MAX_BASE_EVENTS = 20_000
_MAX_LAYER_EVENTS = 8_000

# Overlay colour palette, deliberately outside jet's own hue range (blue,
# cyan, green, yellow, orange, red) so a highlighted population never blends
# into the density cloud it's drawn over. Used both as the production
# palette (kwargs_builders.build_pseudocolor_overlay_kwargs sets it
# explicitly) and as the fallback for standalone/direct-render callers, e.g.
# unit tests, that omit the "palette" kwarg entirely.
JET_SAFE_OVERLAY_PALETTE = [
    "#000000",  # black
    "#e91e8c",  # magenta
    "#7209b7",  # purple
    "#6f4518",  # brown
    "#495057",  # slate grey
]

# Chrome matching the main gating canvas's own white plot background
# (ui/graph/flow_canvas.py's _PLOT_BG/_MPL_STYLE). Public — kwargs_builders.
# build_pseudocolor_overlay_kwargs sets these explicitly on every production
# render; also used here as this renderer's own fallback when a caller (e.g.
# a unit test) calls render() directly without them.
DEFAULT_BG = "#FFFFFF"
DEFAULT_FG = "#333333"
DEFAULT_BORDER = "#d0d7de"


_UNSET = object()


class PseudocolorOverlayRenderer(IPlotRenderer):
    """SRP: renders a base population (optionally density-shaded) plus N
    coloured population overlays on one 2D scatter axis.

    Pure drawing only — no heavy numpy/scipy density computation. That work
    (`compute_pseudocolor_points`, which can take seconds over a real gated
    population) is expected to happen in the kwargs builder *before*
    ComparisonsWorker acquires MPL_RASTER_LOCK to call this method, since that lock
    exists to serialize matplotlib's C-level drawing calls, not to guard
    plain data prep — see kwargs_builders.build_pseudocolor_overlay_kwargs.
    Pass ``base_density`` as that pre-computed ``(x_plot, y_plot, c_plot)``
    triple (or ``None`` to force the flat fallback). If the kwarg is omitted
    entirely, this method computes it itself — kept only so the renderer
    stays usable/testable standalone, e.g. in unit tests.
    """

    def render(self, **kwargs) -> Figure:  # noqa: PLR0913
        base_x: np.ndarray = kwargs["base_x"]
        base_y: np.ndarray = kwargs["base_y"]
        base_label: str = kwargs.get("base_label", "All Events")
        layers: list[dict] = kwargs.get("layers", [])
        palette: list[str] = kwargs.get("palette", JET_SAFE_OVERLAY_PALETTE)
        default_opacity: float = kwargs.get("layer_opacity", 0.7)
        sample_label: str = kwargs.get("sample_label", "")
        show_density_base: bool = kwargs.get("show_density_base", True)
        bg_color: str = kwargs.get("bg_color", DEFAULT_BG)
        colormap: str = kwargs.get("colormap", "Greys")
        base_point_size: float = kwargs.get("base_point_size", 1.0)
        base_opacity: float = kwargs.get("base_opacity", 0.55)
        xlim: tuple[float, float] | None = kwargs.get("xlim")
        ylim: tuple[float, float] | None = kwargs.get("ylim")
        x_scale = kwargs.get("x_scale")
        y_scale = kwargs.get("y_scale")
        x_transform_kwargs: dict = kwargs.get("x_transform_kwargs", {})
        y_transform_kwargs: dict = kwargs.get("y_transform_kwargs", {})

        base_density = kwargs.get("base_density", _UNSET)
        if base_density is _UNSET:
            base_density = self._compute_base_density(base_x, base_y, show_density_base)

        fig = Figure(figsize=(7, 6), facecolor=bg_color)
        ax = fig.add_subplot(111)
        ax.set_facecolor(bg_color)

        if xlim is not None:
            ax.set_xlim(*xlim)
        elif len(base_x):
            ax.set_xlim(float(np.nanmin(base_x)), float(np.nanmax(base_x)))
        if ylim is not None:
            ax.set_ylim(*ylim)
        elif len(base_y):
            ax.set_ylim(float(np.nanmin(base_y)), float(np.nanmax(base_y)))

        self._apply_axis_scale(ax.xaxis, x_scale, x_transform_kwargs, base_x)
        self._apply_axis_scale(ax.yaxis, y_scale, y_transform_kwargs, base_y)

        self._draw_base_layer(
            ax, base_x, base_y, base_density, base_label, colormap, base_point_size, base_opacity
        )

        self._draw_overlay_layers(ax, layers, palette, default_opacity)
        self._apply_final_styling(fig, ax, kwargs, sample_label)
        return fig

    def _draw_overlay_layers(self, ax, layers, palette, default_opacity):
        for i, layer in enumerate(layers):
            lx, ly = layer["x"], layer["y"]
            if len(lx) == 0:
                continue
            if len(lx) > _MAX_LAYER_EVENTS:
                mask = stable_subsample_mask(len(lx), _MAX_LAYER_EVENTS)
                lx, ly = lx[mask], ly[mask]
            color = layer.get("color") or palette[i % len(palette)]
            ax.scatter(
                lx,
                ly,
                s=3,
                alpha=layer.get("opacity", default_opacity),
                color=color,
                rasterized=True,
                zorder=1,
                label=f"{layer['label']} ({len(layer['x']):,} events)",
            )

    def _apply_final_styling(self, fig, ax, kwargs, sample_label) -> None:
        bg_color = kwargs.get("bg_color", DEFAULT_BG)
        fg_color = kwargs.get("fg_color", DEFAULT_FG)
        border_color = kwargs.get("border_color", DEFAULT_BORDER)
        ax.set_xlabel(kwargs.get("x_label", "X"), color=fg_color, fontsize=11)
        ax.set_ylabel(kwargs.get("y_label", "Y"), color=fg_color, fontsize=11)
        title = f"Pseudocolor Overlay: {sample_label}" if sample_label else "Pseudocolor Overlay"
        ax.set_title(title, color=fg_color, fontsize=12, pad=10)
        if ax.get_legend_handles_labels()[1]:
            ax.legend(
                fontsize=8,
                facecolor=bg_color,
                edgecolor=border_color,
                labelcolor=fg_color,
                loc="best",
            )
        _style_axes(ax, fg_color, border_color)
        fig.tight_layout(pad=1.5)

    @staticmethod
    def _compute_base_density(base_x: np.ndarray, base_y: np.ndarray, show_density_base: bool):
        """Fallback for standalone/test use only — production callers should
        pass a pre-computed ``base_density`` kwarg (see class docstring).
        """
        from karcytics_plugins.flow_cytometry.analysis.constants import PSEUDOCOLOR_MAX_EVENTS
        from karcytics_plugins.flow_cytometry.analysis.rendering import (
            compute_pseudocolor_base_density,
        )

        return compute_pseudocolor_base_density(
            base_x, base_y, PSEUDOCOLOR_MAX_EVENTS, enabled=show_density_base
        )

    def _apply_axis_scale(self, axis, scale, transform_kwargs, base_data) -> None:
        if scale is not None and scale.transform_type != TransformType.LINEAR:
            show_neg = scale.transform_type == TransformType.BIEXPONENTIAL and (
                transform_kwargs.get("negative", 0.0) > 0 or bool(np.any(base_data < 0))
            )
            ticks, labels = compute_bio_tick_positions(
                scale.transform_type, transform_kwargs, show_neg
            )
            if len(ticks):
                axis.set_major_locator(FixedLocator(ticks.tolist()))
                axis.set_major_formatter(FixedFormatter(labels))

    def _draw_base_layer(  # noqa: PLR0913
        self,
        ax,
        base_x,
        base_y,
        base_density,
        base_label,
        colormap,
        base_point_size,
        base_opacity,
    ) -> None:
        if base_density is not None:
            x_plot, y_plot, c_plot = base_density
            ax.scatter(
                x_plot,
                y_plot,
                s=base_point_size,
                c=c_plot,
                cmap=colormap,
                vmin=0.0,
                vmax=1.0,
                alpha=base_opacity,
                marker="o",
                rasterized=True,
                edgecolors="none",
                zorder=0,
                label=f"{base_label} ({len(base_x):,} events)",
            )
        elif len(base_x) and len(base_y):
            bx, by = base_x, base_y
            if len(bx) > _MAX_BASE_EVENTS:
                mask = stable_subsample_mask(len(bx), _MAX_BASE_EVENTS)
                bx, by = bx[mask], by[mask]
            ax.scatter(
                bx,
                by,
                s=1.5,
                alpha=0.12,
                color="#8b949e",
                rasterized=True,
                zorder=0,
                label=f"{base_label} ({len(base_x):,} events)",
            )


def _style_axes(ax, fg_color: str, border_color: str) -> None:
    ax.tick_params(colors=fg_color, labelsize=9)
    for spine in ax.spines.values():
        spine.set_color(border_color)
    ax.set_axisbelow(True)
    ax.xaxis.grid(True, color=border_color, linewidth=0.4, alpha=0.5)
    ax.yaxis.grid(True, color=border_color, linewidth=0.4, alpha=0.5)
