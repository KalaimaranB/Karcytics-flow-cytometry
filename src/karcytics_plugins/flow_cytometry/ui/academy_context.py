"""What the Academy's validators may inspect besides the FlowState.

The panel owns one `AcademyContext` and hands it out from `academy_context()`;
the SDK passes it to each validator's `check(state, context)`. The workspace
builder registers each tab's widget here as Phase 2 builds it, so a field is
None until then. Widgets are kept out of `FlowState`, which is saved,
restored and undone and must stay plain data.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

# A tutorial step's metadata key asking the Spectral viewer to spotlight one
# of its sub-tabs on its own (SpectralViewer.get_tutorial_target_rects).
# The only value so far is "learning".
SPECTRAL_TAB_HIGHLIGHT_KEY = "spectral_tab_highlight"

if TYPE_CHECKING:
    from ..analysis.clustering import ClusteringMethod
    from ..analysis.clustering.describe import ClusterSummary
    from ..analysis.gate_coordinator import GateCoordinator
    from ..analysis.statistics import StatType
    from .controllers.derived_editor_controller import DerivedEditorController
    from .graph.graph_manager import GraphManager
    from .ribbons.pipeline_ribbon import PipelineRibbon
    from .widgets.comparisons.plot_spec import PlotType
    from .widgets.comparisons_viewer import ComparisonsViewer
    from .widgets.compensation_view import CompensationView
    from .widgets.flowsom_tree import FlowsomTreeView
    from .widgets.phenograph_graph import PhenographGraphView
    from .widgets.population_analysis_viewer import PopulationAnalysisViewer
    from .widgets.sample_lens.sample_lens_tab import SampleLensTab
    from .widgets.selection.selector_panel import SampleAndPopulationSelector
    from .widgets.spectral_viewer import SpectralViewer
    from .widgets.statistics_explorer import StatisticsExplorer


@dataclass
class AcademyContext:
    """The panel's tab widgets, for Academy validators to query."""

    graph_manager: GraphManager | None = None
    pipeline_ribbon: PipelineRibbon | None = None
    spectral_viewer: SpectralViewer | None = None
    statistics_explorer: StatisticsExplorer | None = None
    comparisons_viewer: ComparisonsViewer | None = None
    compensation_view: CompensationView | None = None
    population_analysis: PopulationAnalysisViewer | None = None
    sample_lens: SampleLensTab | None = None
    derived_editor: DerivedEditorController | None = None
    gate_coordinator: GateCoordinator | None = None  # what Academy corrections act through


# Snapshots: what a widget shows, as plain values, so validators never read its internals.


@dataclass(frozen=True)
class ClusterMapSnapshot:
    """A FlowSOM tree or PhenoGraph cluster graph."""

    run: dict[str, Any]
    method: ClusteringMethod
    color_label: str  # what the map is coloured by
    summaries: tuple[ClusterSummary, ...]  # largest cluster first


@dataclass(frozen=True)
class ClusterResultsSnapshot:
    """The clustering results panel."""

    results: dict[str, Any]
    tab_label: str
    color_label: str | None  # the Interactive Map's colouring; None for a run without clusters
    cluster_rows: dict[Any, tuple[bool, str]]  # Export Populations: id -> (checked, name)
    tree: FlowsomTreeView | None
    graph: PhenographGraphView | None


@dataclass(frozen=True)
class PopulationAnalysisSnapshot:
    """The Population Analysis sidebar's settings, and the run on screen."""

    sample_label: str
    gate_label: str
    channel_checks: dict[str, bool]  # channel key -> checked
    run_name: str
    subsample_percent: int
    hdbscan_enabled: bool
    method_key: str | None  # umap_hdbscan, flowsom, phenograph
    new_run_selected: bool  # History shows [ New Run ]
    is_running: bool
    is_animating: bool
    has_results: bool
    results: ClusterResultsSnapshot | None


@dataclass(frozen=True)
class GraphClusterSnapshot:
    """One PhenoGraph cluster on the cluster graph."""

    cluster: int
    name: str
    phenotype: str
    count: int
    links: tuple[tuple[int, float], ...]  # (other cluster, strength)

    @property
    def stands_apart(self) -> bool:
        return not self.links


@dataclass(frozen=True)
class PopulationPicks:
    """A tab's population selector: what is checked, and whether its picker is open."""

    checked: tuple[tuple[str, str | None, str], ...]  # (sample id, node id, label)
    picker_open: bool

    @classmethod
    def of(cls, selector: SampleAndPopulationSelector) -> PopulationPicks:
        checked = tuple(selector.get_checked_populations())
        return cls(checked, selector.population_selector.isVisible())


@dataclass(frozen=True)
class StatisticsSnapshot:
    populations: PopulationPicks
    checked_stats: frozenset[StatType]
    chart_type_label: str
    channel: str | None  # the ★ channel picker
    has_results: bool


@dataclass(frozen=True)
class ComparisonsSnapshot:
    populations: PopulationPicks
    last_generated: PlotType | None  # set by Generate, not by the plot-type menu
    histogram_layout: str  # ridge, overlay
    checked_channels: tuple[str, ...]


@dataclass(frozen=True)
class LearningDeckSnapshot:
    """The Learning Compensation slide deck."""

    step: int
    last_step: int
    completed: frozenset[int]  # slides whose task is done
