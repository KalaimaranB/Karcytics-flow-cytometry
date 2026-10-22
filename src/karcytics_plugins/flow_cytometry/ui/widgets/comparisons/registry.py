"""PLOT_REGISTRY — maps each PlotType id to its PlotTypeSpec (see plot_spec.py).

OCP: adding a new plot type means adding one PlotTypeSpec entry here (plus
the renderer, options panel, and kwargs-builder it references) — zero
changes to ComparisonsViewer. Every field on PlotTypeSpec is required, so a
plot type can't be registered without also declaring its sample/population/
channel constraints and its kwargs builder.
"""

from __future__ import annotations

from . import kwargs_builders as kb
from .options.heatmap_options import HeatmapOptionsPanel
from .options.histogram_overlay_options import HistogramOverlayOptionsPanel
from .options.pseudocolor_overlay_options import PseudocolorOverlayOptionsPanel
from .options.radar_options import RadarOptionsPanel
from .options.violin_options import ViolinOptionsPanel
from .plot_spec import ChannelMode, PlotType, PlotTypeSpec, PopulationMode, SampleMode
from .renderers.heatmap_renderer import HeatmapRenderer
from .renderers.histogram_overlay_renderer import HistogramOverlayRenderer
from .renderers.pseudocolor_overlay_renderer import PseudocolorOverlayRenderer
from .renderers.radar_renderer import RadarRenderer
from .renderers.violin_renderer import ViolinRenderer

# OCP extension point: add a new plot type by adding one entry here.
PLOT_REGISTRY: dict[PlotType, PlotTypeSpec] = {
    PlotType.VIOLIN: PlotTypeSpec(
        label="🎻  Violin Plot",
        renderer_cls=ViolinRenderer,
        options_panel_cls=ViolinOptionsPanel,
        help_title="Violin Plot",
        help_body=(
            "<b>What it shows:</b> The distribution of one channel across multiple samples "
            "side-by-side. Wide violin = many cells at that intensity.<br><br>"
            "<b>When to use:</b> Comparing CD3 or CD19 expression to identify T-cell vs B-cell "
            "enriched samples (thymus vs bone marrow vs spleen)."
        ),
        sample_mode=SampleMode.MULTI,
        population_mode=PopulationMode.ONE_PER_SAMPLE,
        channel_mode=ChannelMode.SINGLE,
        build_kwargs=kb.build_violin_kwargs,
    ),
    PlotType.CHANNEL_HEATMAP: PlotTypeSpec(
        label="🗺️  Channel Heatmap",
        renderer_cls=HeatmapRenderer,
        options_panel_cls=HeatmapOptionsPanel,
        help_title="Channel Heatmap",
        help_body=(
            "<b>What it shows:</b> A colour grid — rows = samples or populations, "
            "columns = channels. Cell colour = median expression level.<br><br>"
            "<b>When to use:</b> One-glance organ identification. Thymus rows light up for "
            "CD3/CD4/CD8; bone marrow rows light up for B220/IgM."
        ),
        sample_mode=SampleMode.MULTI,
        population_mode=PopulationMode.MULTI,
        channel_mode=ChannelMode.MULTI,
        build_kwargs=kb.build_heatmap_kwargs,
    ),
    PlotType.RADAR: PlotTypeSpec(
        label="🕷️  Radar Chart",
        renderer_cls=RadarRenderer,
        options_panel_cls=RadarOptionsPanel,
        help_title="Radar / Spider Chart",
        help_body=(
            "<b>What it shows:</b> Each population as a coloured polygon on a wheel. "
            "Each spoke = a channel. The shape = the immunophenotype fingerprint.<br><br>"
            "<b>When to use:</b> Comparing cell identities visually. Completely different "
            "shapes immediately reveal different organs or cell types."
        ),
        sample_mode=SampleMode.MULTI,
        population_mode=PopulationMode.MULTI,
        channel_mode=ChannelMode.MULTI,
        build_kwargs=kb.build_radar_kwargs,
    ),
    PlotType.HISTOGRAM_OVERLAY: PlotTypeSpec(
        label="📊  Histogram Overlay",
        renderer_cls=HistogramOverlayRenderer,
        options_panel_cls=HistogramOverlayOptionsPanel,
        help_title="Histogram Overlay",
        help_body=(
            "<b>What it shows:</b> Per-population channel distributions overlaid on a single axis "
            "or stacked as ridge panels (waterfall style).<br><br>"
            "<b>When to use:</b> Comparing how different strains, conditions, or populations distribute "
            "along one fluorescence channel. Both Overlay and Ridge modes support any mix of samples "
            "and populations simultaneously."
        ),
        sample_mode=SampleMode.MULTI,
        population_mode=PopulationMode.MULTI,
        channel_mode=ChannelMode.SINGLE,
        build_kwargs=kb.build_histogram_overlay_kwargs,
    ),
    PlotType.PSEUDOCOLOR_OVERLAY: PlotTypeSpec(
        label="🌈  Pseudocolor Overlay",
        renderer_cls=PseudocolorOverlayRenderer,
        options_panel_cls=PseudocolorOverlayOptionsPanel,
        help_title="Pseudocolor Overlay",
        help_body=(
            "<b>What it shows:</b> Multiple gated populations from one sample plotted on the same "
            "2D axis — a density-shaded pseudocolor cloud for context (All Events) with each "
            "selected population overlaid in its own colour.<br><br>"
            "<b>When to use:</b> Seeing where several populations sit relative to each other and "
            "to the whole sample — e.g. confirming CD4+ and CD8+ gates don't overlap, or checking "
            "a rare population's position within the parent cloud."
        ),
        sample_mode=SampleMode.SINGLE,
        population_mode=PopulationMode.MULTI,
        channel_mode=ChannelMode.NONE,
        build_kwargs=kb.build_pseudocolor_overlay_kwargs,
    ),
}
