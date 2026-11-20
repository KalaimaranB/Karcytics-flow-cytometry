"""The results of one clustering run (UMAP + HDBSCAN, FlowSOM or PhenoGraph), as tabs.

The method's own view comes first (FlowSOM's tree, PhenoGraph's graph), then
the Plot Gallery and, for a clustered run, the Interactive Map and Population
Statistics. Re-cutting the run rebuilds every tab after the first.
"""

from __future__ import annotations

from typing import Any

from karcytics_sdk.plugin.theme_fallback import theme_manager
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from ...analysis.clustering import FLOWSOM, PHENOGRAPH, method_of
from ...analysis.flowsom_analysis import recut_run
from ...analysis.phenograph_analysis import apply_clusters
from ..academy_context import ClusterResultsSnapshot
from .cluster_map_tab import ClusterMapTab
from .cluster_plot_gallery import ClusterPlotGallery
from .cluster_statistics_tab import ClusterStatisticsTab
from .flowsom_tree import FlowsomTreeView
from .phenograph_graph import PhenographGraphView

_TABS_QSS = """
QTabWidget { background: transparent; }
QTabWidget::pane { border: 1px solid {BORDER}; border-radius: 4px; background: {BG_DARK}; }
QTabBar::tab { background: {BG_MEDIUM}; color: {FG_SECONDARY}; padding: 8px 16px;
    border: 1px solid {BORDER}; border-bottom: none; border-top-left-radius: 4px;
    border-top-right-radius: 4px; margin-right: 2px; }
QTabBar::tab:selected { background: {BG_DARK}; color: {FG_PRIMARY}; font-weight: bold;
    border-bottom: 1px solid {BG_DARK}; }
QTabBar::tab:hover:!selected { background: {BG_LIGHT}; }
"""

STATISTICS_TAB = "Population Statistics"


class ClusterResultsPanel(QWidget):
    """A clustering run's views, one tab each."""

    results_modified = Signal()
    recluster_requested = Signal(float)  # PhenoGraph: re-cluster at this resolution

    def __init__(
        self,
        results: dict[str, Any],
        state: Any | None = None,
        gate_coordinator: Any | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.run = results
        self._state = state
        self._gate_coordinator = gate_coordinator
        self._method = method_of(results)
        self._map: ClusterMapTab | None = None
        self._statistics: ClusterStatisticsTab | None = None

        self._tabs = QTabWidget()
        self._tabs.setObjectName("ClusterResultsTabs")
        # Its own name for the tab-header row: a "click this tab" step
        # spotlights the tabs, not the whole widget (as MainTabBar does).
        if (tab_bar := self._tabs.tabBar()) is not None:
            tab_bar.setObjectName("ClusterResultsTabBar")
        theme_manager.apply_style(self._tabs, _TABS_QSS)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._tabs)

        self._tree_view: FlowsomTreeView | None = None
        self._graph_view: PhenographGraphView | None = None
        if self._method is FLOWSOM:
            self._tree_view = FlowsomTreeView(results)
            self._tree_view.k_changed.connect(self._on_k_changed)
            self._tabs.addTab(self._tree_view, "FlowSOM Tree")
        elif self._method is PHENOGRAPH:
            self._graph_view = PhenographGraphView(results)
            self._graph_view.resolution_changed.connect(self._on_resolution_changed)
            self._tabs.addTab(self._graph_view, "Cluster Graph")
        self._build_result_tabs()

    def academy_snapshot(self) -> ClusterResultsSnapshot:
        return ClusterResultsSnapshot(
            results=self.run,
            tab_label=self._tabs.tabText(self._tabs.currentIndex()),
            color_label=self._map.color_label if self._map is not None else None,
            cluster_rows=self._statistics.cluster_rows() if self._statistics is not None else {},
            tree=self._tree_view,
            graph=self._graph_view,
        )

    def _build_result_tabs(self) -> None:
        self._tabs.addTab(ClusterPlotGallery(self.run, self._method, self._state), "Plot Gallery")
        self._map = self._statistics = None
        if "clusters" not in self.run:
            return
        self._map = ClusterMapTab(self.run, self._method)
        self._map.population_drawn.connect(self._on_population_drawn)
        self._tabs.addTab(self._map, "Interactive Map")
        self._tabs.addTab(self._new_statistics_tab(), STATISTICS_TAB)

    def _new_statistics_tab(self) -> ClusterStatisticsTab:
        self._statistics = ClusterStatisticsTab(
            self.run, self._method, self._state, self._gate_coordinator
        )
        self._statistics.results_modified.connect(self.results_modified)
        return self._statistics

    def _on_population_drawn(self) -> None:
        """A drawn population changes the tables: rebuild the statistics tab in place."""
        old = self._statistics
        index = self._tabs.indexOf(old) if old is not None else -1
        if old is None or index < 0:
            return
        current = self._tabs.currentIndex()
        self._tabs.removeTab(index)
        old.deleteLater()
        self._tabs.insertTab(index, self._new_statistics_tab(), STATISTICS_TAB)
        self._tabs.setCurrentIndex(current)
        self.results_modified.emit()

    def _on_k_changed(self, k: int) -> None:
        """Re-cut a FlowSOM run into ``k`` metaclusters and rebuild what shows them."""
        if k == self.run.get("k"):
            return
        recut_run(self.run, k)
        self._rebuild_after_recut()

    def _on_resolution_changed(self, resolution: float) -> None:
        """Ask for a PhenoGraph re-cluster (seconds, in the background); see apply_recluster."""
        if resolution == self.run.get("resolution") or self._graph_view is None:
            return
        self._graph_view.set_busy("Re-clustering…")
        self.recluster_requested.emit(resolution)

    def apply_recluster(self, arrays: dict[str, Any]) -> None:
        """Show a finished PhenoGraph re-cluster (or say why it failed)."""
        if self._graph_view is None:
            return
        self._graph_view.set_busy("")
        if "error" in arrays:
            self._graph_view.show_error(str(arrays["error"]))
            return
        apply_clusters(self.run, arrays)
        self._rebuild_after_recut()

    def _rebuild_after_recut(self) -> None:
        """Rebuild what shows the clusters after a re-cut, keeping the method's own view."""
        current = self._tabs.currentIndex()
        while self._tabs.count() > 1:  # keep the tree or graph (tab 0)
            widget = self._tabs.widget(1)
            self._tabs.removeTab(1)
            if widget is not None:
                widget.deleteLater()
        self._build_result_tabs()
        for view in (self._tree_view, self._graph_view):
            if view is not None:
                view.refresh()
        self._tabs.setCurrentIndex(current)
        self.results_modified.emit()
