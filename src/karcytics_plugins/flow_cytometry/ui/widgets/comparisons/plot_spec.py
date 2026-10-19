"""Declarative per-plot-type contract for the Comparisons tab.

Before this module, "what a plot type needs" was implicitly spread across
four independent places: ``PLOT_REGISTRY`` (renderer/options panel classes),
``PLOTS_MULTI_POPULATION``, ``PLOTS_MULTI_CHANNEL``, ``PLOTS_WITHOUT_CHANNEL_LIST``
(three separate membership sets), and a hand-written ``if/elif`` chain in
``ComparisonsViewer._build_render_kwargs``. Registering a new plot type in
one place without remembering all the others compiled and ran fine — it just
crashed at render time with something like ``KeyError: 'base_x'`` the moment
a user actually generated that plot, because the kwargs-building branch for
it silently didn't exist.

``PlotTypeSpec`` bundles all of that into one required, typed record per
plot type: sample/population/channel constraints AND the function that
builds renderer kwargs from a selection. Since every field is required,
Python itself refuses to construct an incomplete spec — the missing-branch
bug this module replaces cannot compile silently again.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from karcytics_plugins.flow_cytometry.analysis.state import FlowState

    from ....analysis.comparison_data import ComparisonsDataExtractor
    from .options.base import IOptionsPanel
    from .renderers.base import IPlotRenderer


class SampleMode(Enum):
    """How many checked samples a plot type consumes."""

    SINGLE = "single"
    """Exactly one sample is used. The sample checklist is forced into
    single-select (radio) so the UI can't offer a combination the plot
    type doesn't support."""

    MULTI = "multi"
    """Any number of checked samples are used (one series/group each)."""


class PopulationMode(Enum):
    """How populations map onto samples for a plot type."""

    ONE_PER_SAMPLE = "one_per_sample"
    """Exactly one population per sample (radio-style pick within each
    sample's populations) — e.g. Violin, FMO."""

    MULTI = "multi"
    """Any number of populations, using the grouped Shared/Sample-Specific
    selector — e.g. Heatmap, Radar, Histogram Overlay, Pseudocolor Overlay."""


class ChannelMode(Enum):
    """How the shared "Channels" sidebar section behaves for a plot type."""

    NONE = "none"
    """Hidden — the options panel owns its own channel picker(s)."""

    SINGLE = "single"
    """Exactly one channel checked."""

    MULTI = "multi"
    """Any number of channels checked (e.g. Heatmap columns, Radar spokes)."""


KwargsBuilder = Callable[
    ["FlowState", "ComparisonsDataExtractor", dict, list[str], list[tuple], list[str]], dict
]
"""(state, extractor, options_config, sample_ids, pop_pairs, channel_keys) -> renderer kwargs.

Must raise ValueError with a user-facing message on invalid/incomplete
selections; ComparisonsViewer catches ValueError and shows it in the status
bar instead of starting the render worker.
"""


@dataclass(frozen=True)
class PlotTypeSpec:
    """Everything ComparisonsViewer needs to know about one plot type."""

    renderer_cls: type[IPlotRenderer]
    options_panel_cls: type[IOptionsPanel]
    help_title: str
    help_body: str
    sample_mode: SampleMode
    population_mode: PopulationMode
    channel_mode: ChannelMode
    build_kwargs: KwargsBuilder
