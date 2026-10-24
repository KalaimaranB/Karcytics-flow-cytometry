"""The workspace's widgets, handed to the controllers once Phase 2 has built them.

WorkspaceBuilder creates them on the panel; `FlowCytometryPanel._finish_phase2`
gathers them here, so a controller takes this instead of the whole panel.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PySide6.QtWidgets import QTabBar

    from .graph.graph_manager import GraphManager
    from .ribbons.gating_ribbon import GatingRibbon
    from .ribbons.pipeline_ribbon import PipelineRibbon
    from .ribbons.workspace_ribbon import WorkspaceRibbon
    from .widgets.comparisons_viewer import ComparisonsViewer
    from .widgets.compensation_view import CompensationView
    from .widgets.gate_hierarchy.widget import GateHierarchy
    from .widgets.groups_panel import GroupsPanel
    from .widgets.node_canvas.canvas_view import NodeCanvas
    from .widgets.population_analysis_viewer import PopulationAnalysisViewer
    from .widgets.properties_panel import PropertiesPanel
    from .widgets.sample_list import SampleList
    from .widgets.statistics_explorer import StatisticsExplorer


@dataclass(frozen=True)
class WorkspaceViews:
    tab_bar: QTabBar
    workspace_ribbon: WorkspaceRibbon
    gating_ribbon: GatingRibbon
    pipeline_ribbon: PipelineRibbon
    groups_panel: GroupsPanel
    sample_list: SampleList
    gate_hierarchy: GateHierarchy
    properties_panel: PropertiesPanel
    graph_manager: GraphManager
    node_canvas: NodeCanvas
    compensation_view: CompensationView
    population_analysis_viewer: PopulationAnalysisViewer
    statistics_explorer: StatisticsExplorer
    comparisons_viewer: ComparisonsViewer

    def refresh_sample_pickers(self) -> None:
        """Every view that lists the experiment's samples."""
        self.groups_panel.refresh()
        self.sample_list.refresh()
        self.pipeline_ribbon.refresh_samples()
        self.population_analysis_viewer.refresh_samples()
        self.statistics_explorer.refresh_samples()
        self.comparisons_viewer.refresh_samples()
