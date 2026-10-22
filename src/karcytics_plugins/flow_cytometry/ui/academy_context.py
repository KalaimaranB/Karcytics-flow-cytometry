"""What the Academy's validators may inspect besides the FlowState.

The panel owns one `AcademyContext` and hands it out from `academy_context()`;
the SDK passes it to each validator's `check(state, context)`. The workspace
builder registers each tab's widget here as Phase 2 builds it, so a field is
None until then. Widgets are kept out of `FlowState`, which is saved,
restored and undone and must stay plain data.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .controllers.derived_editor_controller import DerivedEditorController
    from .graph.graph_manager import GraphManager
    from .ribbons.pipeline_ribbon import PipelineRibbon
    from .widgets.comparisons_viewer import ComparisonsViewer
    from .widgets.compensation_view import CompensationView
    from .widgets.population_analysis_viewer import PopulationAnalysisViewer
    from .widgets.sample_lens.sample_lens_tab import SampleLensTab
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
