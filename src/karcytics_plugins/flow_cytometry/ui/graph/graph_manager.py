"""Graph manager — tabbed container for multiple GraphWindow instances.

Handles opening, closing, and switching between graph windows in the
center canvas area of the workspace.  Allows having multiple graph windows
to have multiple graph windows open simultaneously.

Also exposes the active graph's signals for gating integration:
when a tool is selected in the gating ribbon, the GraphManager
forwards the drawing mode to the currently active graph's canvas.
"""

from __future__ import annotations

from typing import Any

from karcytics_sdk.plugin import CentralEventBus, get_logger
from karcytics_sdk.plugin.theme_fallback import Colors, Fonts
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QLabel,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from karcytics_plugins.flow_cytometry.analysis import events
from karcytics_plugins.flow_cytometry.analysis.gating import Gate, GateNode
from karcytics_plugins.flow_cytometry.analysis.protocols import (
    IGateCoordinator,
    IPopulationService,
)
from karcytics_plugins.flow_cytometry.analysis.state import FlowState

from .graph_window import GraphWindow

logger = get_logger(__name__, "flow_cytometry")


class GraphManager(QWidget):
    """Tabbed container managing multiple :class:`GraphWindow` instances.

    The center canvas area of the workspace.  Shows a welcome screen
    when no graphs are open, and a tabbed interface when one or more
    graphs are active.

    Signals:
        gate_drawn(Gate, sample_id, parent_node_id):
            Forwarded from the active GraphWindow when a gate is created.
        gate_selection_changed(gate_id):
            Forwarded when a gate overlay is clicked on the canvas.
    """

    gate_drawn = pyqtSignal(object, str, object)  # Gate, sample_id, parent_node_id
    gate_selection_changed = pyqtSignal(object)  # gate_id or None
    active_graph_changed = pyqtSignal(str, object)  # sample_id, node_id (or "", None)
    tool_change_requested = pyqtSignal(str)

    def __init__(
        self,
        state: FlowState,
        axis_manager: Any,
        population_service: IPopulationService,
        controller: IGateCoordinator | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._state = state
        self._axis_manager = axis_manager
        self._population_service = population_service
        if controller is None:
            raise ValueError("IGateCoordinator must be injected")
        self._controller = controller
        self._graphs: dict[str, GraphWindow] = {}  # key: "sample_id:gate_id"
        self._current_tool = "select"
        self._setup_ui()
        self._setup_events()

    def _setup_events(self) -> None:
        """Subscribe to relevant state events."""
        CentralEventBus.subscribe(events.GATE_RENAMED, self._on_bus_event)
        self.destroyed.connect(self._cleanup_events)

    def _cleanup_events(self) -> None:
        """Unsubscribe from CentralEventBus when this widget is destroyed."""
        try:
            CentralEventBus.unsubscribe(events.GATE_RENAMED, self._on_bus_event)
        except Exception:
            pass

    def _on_bus_event(self, data: dict) -> None:
        """Handle incoming bus events."""
        # Refresh all tab labels for the given sample
        sample_id = data.get("sample_id")
        if sample_id:
            for i in range(self._tabs.count()):
                graph = self._tabs.widget(i)
                if isinstance(graph, GraphWindow) and graph.sample_id == sample_id:
                    self._update_tab_label(i)

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Tab widget for multiple graphs
        self._tabs = QTabWidget()
        self._tabs.setTabsClosable(True)
        self._tabs.setMovable(True)
        self._tabs.setDocumentMode(True)
        self._tabs.tabCloseRequested.connect(self._close_tab)
        self._tabs.currentChanged.connect(self._on_tab_changed)

        self._tabs.setStyleSheet(
            f"QTabWidget {{ background-color: {Colors.BG_DARKEST}; border: none; }}"
            f"QTabWidget::pane {{ border: none; background-color: {Colors.BG_DARKEST}; }}"
            f"QTabWidget::tab-bar {{ left: 0px; alignment: left; }}"
            f"QTabBar {{ background-color: {Colors.BG_DARKEST}; border: none; }}"
            f"QTabBar::tab {{"
            f"  background-color: {Colors.BG_DARK};"
            f"  color: {Colors.FG_SECONDARY};"
            f"  padding: 6px 32px 6px 12px;"
            f"  border: none;"
            f"  border-bottom: 2px solid transparent;"
            f"  font-size: {Fonts.SIZE_SMALL}px;"
            f"  margin-right: 2px;"
            f"  min-width: 120px;"
            f"}}"
            f"QTabBar::tab:selected {{"
            f"  color: {Colors.FG_PRIMARY};"
            f"  border-bottom: 2px solid {Colors.ACCENT_PRIMARY};"
            f"  background-color: {Colors.BG_DARKEST};"
            f"}}"
            f"QTabBar::tab:hover {{"
            f"  color: {Colors.FG_PRIMARY};"
            f"  background-color: {Colors.BG_MEDIUM};"
            f"}}"
            f"QTabBar::close-button {{"
            f"  background-color: {Colors.BG_MEDIUM};"
            f"  border: 1px solid {Colors.BORDER};"
            f"  border-radius: 3px;"
            f"  margin: 2px 4px;"
            f"  padding: 2px;"
            f"  subcontrol-position: right center;"
            f"}}"
            f"QTabBar::close-button:hover {{"
            f"  background-color: {Colors.ACCENT_PRIMARY};"
            f"  border: 1px solid {Colors.ACCENT_PRIMARY};"
            f"}}"
        )

        # Welcome/empty screen
        self._welcome = QWidget()
        welcome_layout = QVBoxLayout(self._welcome)
        welcome_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._welcome_title = QLabel("🧪 Flow Cytometry Workspace")
        self._welcome_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        welcome_layout.addWidget(self._welcome_title)

        self._welcome_subtitle = QLabel("Double-click a sample in the tree to open a graph.")
        self._welcome_subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._welcome_subtitle.setWordWrap(True)
        welcome_layout.addWidget(self._welcome_subtitle)

        # Keyboard shortcut hints
        self._welcome_hints = QLabel("Quick actions:\n  Workspace tab → Add Samples")
        self._welcome_hints.setAlignment(Qt.AlignmentFlag.AlignCenter)
        welcome_layout.addWidget(self._welcome_hints)

        layout.addWidget(self._welcome)
        layout.addWidget(self._tabs)

        self._apply_theme_styles()
        self._update_visibility()

    def _apply_theme_styles(self) -> None:
        """Dynamically refresh colors based on the current theme."""
        self.setStyleSheet(f"background: {Colors.BG_DARKEST};")
        if hasattr(self, "_tabs"):
            self._tabs.setStyleSheet(
                f"QTabWidget {{ background-color: {Colors.BG_DARKEST}; border: none; }}"
                f"QTabWidget::pane {{ border: none; background-color: {Colors.BG_DARKEST}; }}"
                f"QTabWidget::tab-bar {{ left: 0px; alignment: left; }}"
                f"QTabBar {{ background-color: {Colors.BG_DARKEST}; border: none; }}"
                f"QTabBar::tab {{"
                f"  background-color: {Colors.BG_DARK};"
                f"  color: {Colors.FG_SECONDARY};"
                f"  padding: 6px 32px 6px 12px;"
                f"  border: none;"
                f"  border-bottom: 2px solid transparent;"
                f"  font-size: {Fonts.SIZE_SMALL}px;"
                f"  margin-right: 2px;"
                f"  min-width: 120px;"
                f"}}"
                f"QTabBar::tab:selected {{"
                f"  color: {Colors.FG_PRIMARY};"
                f"  border-bottom: 2px solid {Colors.ACCENT_PRIMARY};"
                f"  background-color: {Colors.BG_DARKEST};"
                f"}}"
                f"QTabBar::tab:hover {{"
                f"  color: {Colors.FG_PRIMARY};"
                f"  background-color: {Colors.BG_MEDIUM};"
                f"}}"
                f"QTabBar::close-button {{"
                f"  background-color: {Colors.BG_MEDIUM};"
                f"  border: 1px solid {Colors.BORDER};"
                f"  border-radius: 3px;"
                f"  margin: 2px 4px;"
                f"  padding: 2px;"
                f"  subcontrol-position: right center;"
                f"}}"
                f"QTabBar::close-button:hover {{"
                f"  background-color: {Colors.ACCENT_PRIMARY};"
                f"  border: 1px solid {Colors.ACCENT_PRIMARY};"
                f"}}"
            )
        if hasattr(self, "_welcome"):
            self._welcome.setStyleSheet(f"background: {Colors.BG_DARKEST};")
        if hasattr(self, "_welcome_title"):
            self._welcome_title.setStyleSheet(
                f"color: {Colors.FG_PRIMARY}; font-size: 20px;"
                f" font-weight: 700; background: transparent;"
            )
        if hasattr(self, "_welcome_subtitle"):
            self._welcome_subtitle.setStyleSheet(
                f"color: {Colors.FG_DISABLED}; font-size: {Fonts.SIZE_NORMAL}px;"
                f" background: transparent; margin-top: 8px;"
            )
        if hasattr(self, "_welcome_hints"):
            self._welcome_hints.setStyleSheet(
                f"color: {Colors.FG_DISABLED}; font-size: {Fonts.SIZE_SMALL}px;"
                f" background: transparent; margin-top: 16px;"
            )
        for graph in getattr(self, "_graphs", {}).values():
            if hasattr(graph, "_apply_theme_styles"):
                graph._apply_theme_styles()

    # ── Public API ────────────────────────────────────────────────────

    def open_graph_for_sample(self, sample_id: str, node_id: str | None = None) -> None:
        """Open (or focus) a graph window for a sample/gate.

        If a graph for this sample+gate already exists, it is brought
        to focus.  Otherwise, a new tab is created.

        Args:
            sample_id: The sample to graph.
            node_id:   The population/node within the sample (None for ungated).
        """
        key = f"{sample_id}:{node_id or 'root'}"

        if key in self._graphs:
            # Focus existing tab
            graph = self._graphs[key]
            idx = self._tabs.indexOf(graph)
            if idx >= 0:
                self._tabs.setCurrentIndex(idx)
                # Ensure it's up to date
                self._update_tab_label(idx)
                graph._update_breadcrumb()
            return

        # Create new graph window
        sample = self._state.data.experiment.samples.get(sample_id)
        if sample is None:
            logger.warning("Cannot open graph — sample %s not found", sample_id)
            return

        if node_id is not None:
            if not sample.gate_tree.find_node_by_id(node_id):
                logger.warning(
                    f"Cannot open graph — node {node_id} not found in sample {sample_id}"
                )
                return

        graph = GraphWindow(
            state=self._state,
            sample_id=sample_id,
            node_id=node_id,
            axis_manager=self._axis_manager,
            population_service=self._population_service,
            controller=self._controller,
        )
        self._graphs[key] = graph

        # Apply current tool
        graph.set_drawing_mode(self._current_tool)

        # Render existing gates
        if self._controller:
            gates, nodes = self._controller.get_gates_for_display(sample_id, node_id)
            graph.refresh_gates(gates, nodes)

        # Wire signals
        graph.gate_drawn.connect(self._on_gate_drawn)
        graph.gate_selection_changed.connect(self._on_gate_selection)
        graph.axis_scale_sync_requested.connect(self._on_axis_scale_sync)
        graph.navigation_requested.connect(self.navigate_active_graph)
        graph.tool_change_requested.connect(self.tool_change_requested.emit)

        idx = self._tabs.addTab(graph, "")
        self._update_tab_label(idx)
        self._tabs.setCurrentIndex(idx)

        # Explicitly ensure visibility and layout
        graph.show()
        graph.updateGeometry()
        self._tabs.updateGeometry()
        self._tabs.show()

        self._update_visibility()
        logger.info(
            f"Opened graph for {sample.display_name} (population={node_id}), tab_count={self._tabs.count()}"
        )

    def _update_tab_label(self, index: int) -> None:
        """Regenerate the tab title for a specific index."""
        graph = self._tabs.widget(index)
        if not isinstance(graph, GraphWindow):
            return

        sample = self._state.data.experiment.samples.get(graph.sample_id)
        if not sample:
            return

        tab_label = sample.display_name
        if graph.node_id:
            node = sample.gate_tree.find_node_by_id(graph.node_id)
            if node:
                tab_label = f"{sample.display_name} › {node.name}"

        self._tabs.setTabText(index, tab_label)

    def set_drawing_mode(self, tool_name: str) -> None:
        """Set the drawing mode on all open graph windows.

        Args:
            tool_name: The tool name from GatingRibbon.
        """
        self._current_tool = tool_name
        for graph in self._graphs.values():
            graph.set_drawing_mode(tool_name)

    def set_selected_gate(self, gate_id: str | None) -> None:
        """Highlight a specific gate on the active graph.

        Args:
            gate_id: The gate ID to select, or None to deselect.
        """
        graph = self.get_active_graph()
        if graph:
            graph.canvas.select_gate(gate_id)

    def refresh_gates_on_sample(
        self,
        sample_id: str,
        gates: list[Gate],
        gate_nodes: list[GateNode],
    ) -> None:
        """Refresh gate overlays on all open graphs for a sample.

        Args:
            sample_id:  The sample whose gates changed.
            gates:      Updated gate list.
            gate_nodes: Updated gate node list.
        """
        for _key, graph in self._graphs.items():
            if graph.sample_id == sample_id:
                graph.refresh_gates(gates, gate_nodes)

    def get_active_graph(self) -> GraphWindow | None:
        """Return the currently active GraphWindow, or None."""
        widget = self._tabs.currentWidget()
        return widget if isinstance(widget, GraphWindow) else None

    def _close_tab(self, index: int) -> None:
        """Close a graph tab and clean up."""
        widget = self._tabs.widget(index)
        if isinstance(widget, GraphWindow):
            key = f"{widget.sample_id}:{widget.node_id or 'root'}"
            self._graphs.pop(key, None)

        self._tabs.removeTab(index)
        if widget:
            widget.deleteLater()

        self._update_visibility()

    def close_graphs_for_nodes(self, deleted_nodes_by_sample: dict[str, set[str]]) -> None:
        """Close tabs that are viewing any of the specified nodes."""
        for i in range(self._tabs.count() - 1, -1, -1):
            widget = self._tabs.widget(i)
            if isinstance(widget, GraphWindow):
                deleted_nodes = deleted_nodes_by_sample.get(widget.sample_id, set())
                if widget.node_id in deleted_nodes:
                    self._close_tab(i)

    def _get_parallel_node(
        self, source_sample_id: str, source_node_id: str | None, target_sample_id: str
    ) -> str | None:
        """Find the equivalent gate node ID in another sample by name path."""
        source_sample = self._state.data.experiment.samples.get(source_sample_id)
        target_sample = self._state.data.experiment.samples.get(target_sample_id)
        if not source_sample or not target_sample or not source_node_id:
            return None

        curr_node = source_sample.gate_tree.find_node_by_id(source_node_id)
        if not curr_node:
            return None

        path = []
        c = curr_node
        while c and not c.is_root:
            path.append(c.name)
            c = c.parents[0] if c.parents else None  # type: ignore
        path.reverse()

        t_node = target_sample.gate_tree
        for p_name in path:
            matched = False
            for child in t_node.children:
                if child.name == p_name:
                    t_node = child
                    matched = True
                    break
            if not matched:
                break

        if t_node and not t_node.is_root:
            return t_node.node_id
        return None

    def navigate_active_graph(self, action: str) -> None:  # noqa: PLR0911
        """Handle Next/Prev/Parent navigation from a graph toolbar."""
        idx = self._tabs.currentIndex()
        if idx < 0:
            return

        widget = self._tabs.widget(idx)
        from .graph_window import GraphWindow

        if not isinstance(widget, GraphWindow):
            return
        graph: GraphWindow = widget
        current_sample_id = graph.sample_id
        current_node_id = graph.node_id

        sample = self._state.data.experiment.samples.get(current_sample_id)
        if not sample:
            return

        if action == "parent_gate":
            if not current_node_id:
                return
            node = sample.gate_tree.find_node_by_id(current_node_id)
            if node and node.parents and not node.parents[0].is_root:
                self.open_graph_for_sample(current_sample_id, node.parents[0].node_id)
            else:
                self.open_graph_for_sample(current_sample_id, None)
            return

        # For next/prev, iterate over samples
        samples = list(self._state.data.experiment.samples.values())
        if not samples:
            return

        base_idx = next((i for i, s in enumerate(samples) if s.sample_id == current_sample_id), -1)
        if base_idx < 0:
            return

        if action == "next_sample":
            target_idx = (base_idx + 1) % len(samples)
        elif action == "prev_sample":
            target_idx = (base_idx - 1) % len(samples)
        else:
            return

        target_sample = samples[target_idx]
        target_node_id = self._get_parallel_node(
            current_sample_id,
            current_node_id,
            target_sample.sample_id,  # type: ignore
        )
        self.open_graph_for_sample(target_sample.sample_id, target_node_id)

    def open_graph_with_context(self, sample_id: str) -> None:
        """Open a graph for a sample, preserving the gating context of the current active graph."""
        graph = self.get_active_graph()
        if not graph or not graph.node_id:
            self.open_graph_for_sample(sample_id)
            return

        target_node_id = self._get_parallel_node(graph.sample_id, graph.node_id, sample_id)
        self.open_graph_for_sample(sample_id, target_node_id)

    def _on_tab_changed(self, index: int) -> None:
        """Apply the current drawing mode when switching tabs and notify app."""
        graph = self.get_active_graph()
        if graph:
            graph.set_drawing_mode(self._current_tool)
            self.active_graph_changed.emit(graph.sample_id, graph.node_id)
        else:
            self.active_graph_changed.emit("", None)

    def _on_gate_drawn(self, gate: Gate, sample_id: str, parent_node_id) -> None:
        """Forward gate_drawn from the active graph."""
        self.gate_drawn.emit(gate, sample_id, parent_node_id)

    def _on_gate_selection(self, gate_id) -> None:
        """Forward gate selection from the active graph."""
        self.gate_selection_changed.emit(gate_id)

    def _on_axis_scale_sync(self, channel_name: str, scale) -> None:
        """Propagate AxisScale to all other graphs in the same group."""
        sender = self.sender()

        sender_group_ids = []
        if sender and hasattr(sender, "sample_id"):
            sample_id = sender.sample_id
            sender_sample = self._state.data.experiment.samples.get(sample_id)
            if sender_sample:
                sender_group_ids = sender_sample.group_ids

        for graph in self._graphs.values():
            if graph is sender:
                continue

            # Only propagate to graphs showing samples in the same group
            graph_sample = self._state.data.experiment.samples.get(graph.sample_id)
            if graph_sample and any(g in sender_group_ids for g in graph_sample.group_ids):
                graph.apply_axis_scale(channel_name, scale)

    def refresh(self) -> None:
        """Refresh all open graph windows."""
        for graph in self._graphs.values():
            graph._update_breadcrumb()

    def cleanup(self) -> None:
        """Explicitly release all graph resources."""
        logger.info("Cleaning up GraphManager...")
        # Close all tabs properly
        while self._tabs.count() > 0:
            self._close_tab(0)
        self._graphs.clear()

    def _update_visibility(self) -> None:
        """Toggle between welcome screen and tabs."""
        has_graphs = self._tabs.count() > 0
        self._tabs.setVisible(has_graphs)
        self._welcome.setVisible(not has_graphs)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        logger.info(
            f"GraphManager resized: {self.width()}x{self.height()}, tabs_visible={self._tabs.isVisible()}, welcome_visible={self._welcome.isVisible()}"
        )
