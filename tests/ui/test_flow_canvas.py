"""Unit tests for FlowCanvas rendering engine.

Tests the core canvas functionality including:
- Initialization and attribute setup
- Rendering pipeline
- Gate drawing state machine
- Artist management
- Event handling state
"""

from unittest.mock import Mock, patch

import numpy as np
import pandas as pd
import pytest

from karcytics_plugins.flow_cytometry.analysis.gating import (
    EllipseGate,
    PolygonGate,
    QuadrantGate,
    RectangleGate,
)
from karcytics_plugins.flow_cytometry.analysis.scaling import AxisScale
from karcytics_plugins.flow_cytometry.analysis.transforms import TransformType
from karcytics_plugins.flow_cytometry.ui.graph.flow_canvas import (
    DisplayMode,
    FlowCanvas,
    GateDrawingMode,
)


class _FakeWorker:
    """Stand-in for AnalysisWorker: records signal connections, lets the test fire them manually."""

    def __init__(self):
        self._finished_cbs = []
        self._error_cbs = []
        self.finished = Mock()
        self.finished.connect = self._finished_cbs.append
        self.error = Mock()
        self.error.connect = self._error_cbs.append

    def emit_finished(self, results):
        for cb in list(self._finished_cbs):
            cb(results)

    def emit_error(self, message):
        for cb in list(self._error_cbs):
            cb(message)


def _synchronous_scheduler():
    """A fake ITaskScheduler that runs the analyzer synchronously.

    submit() calls analyzer.run(state) right away but defers the
    finished/error signal emission via QTimer.singleShot(0, ...), so the
    caller's .connect() calls (made immediately after submit() returns) are
    already registered before the callback fires. Avoids depending on the
    real QThreadPool, which under a full test-suite run can be contended by
    unrelated tests' background tasks.
    """
    from PyQt6.QtCore import QTimer

    scheduler = Mock()
    workers = []

    def _submit(analyzer, state=None):
        worker = _FakeWorker()
        workers.append(worker)

        def _run_and_emit():
            try:
                results = analyzer.run(state)
            except Exception as exc:
                worker.emit_error(str(exc))
            else:
                worker.emit_finished(results)

        QTimer.singleShot(0, _run_and_emit)
        return worker

    scheduler.submit.side_effect = _submit
    return scheduler, workers


class TestFlowCanvasInitialization:
    """Test FlowCanvas initialization and attribute setup."""

    @pytest.mark.ui
    def test_canvas_initializes_without_error(self):
        """Canvas should initialize without errors."""
        # Mock PyQt parent
        parent = None
        canvas = FlowCanvas(parent=parent)
        assert canvas is not None

    @pytest.mark.ui
    def test_all_required_attributes_initialized(self):
        """All required attributes should be initialized in __init__."""
        parent = None
        canvas = FlowCanvas(parent=parent)

        # Data state
        assert hasattr(canvas, "_current_data")
        assert hasattr(canvas, "_x_param")
        assert hasattr(canvas, "_y_param")
        assert hasattr(canvas, "_x_scale")
        assert hasattr(canvas, "_y_scale")
        assert hasattr(canvas, "_display_mode")

        # Service instances
        assert hasattr(canvas, "_coordinate_mapper")
        assert hasattr(canvas, "_gate_factory")
        assert hasattr(canvas, "_gate_overlay_renderer")

        # Rendering caches
        assert hasattr(canvas, "_canvas_bitmap_cache")
        assert hasattr(canvas, "_gate_overlay_artists")
        assert hasattr(canvas, "_gate_artists")  # This was missing!

        # Gate drawing state
        assert hasattr(canvas, "_drawing_mode")
        assert hasattr(canvas, "_fsm")

        # Gate state
        assert hasattr(canvas, "_gate_patches")
        assert hasattr(canvas, "_active_gates")
        assert hasattr(canvas, "_gate_nodes")
        assert hasattr(canvas, "_selected_gate_id")

        # Editing state — drag-handle editing lives in GateEditor + the FSM's
        # EDITING state, not standalone canvas fields (see TestFlowCanvasEditState).
        assert hasattr(canvas, "_gate_editor")

    @pytest.mark.ui
    def test_gate_artists_is_list(self):
        """_gate_artists should be a list, not None."""
        parent = None
        canvas = FlowCanvas(parent=parent)
        assert isinstance(canvas._gate_artists, list)
        assert len(canvas._gate_artists) == 0

    @pytest.mark.ui
    def test_gate_overlay_artists_is_dict(self):
        """_gate_overlay_artists should be a dict."""
        parent = None
        canvas = FlowCanvas(parent=parent)
        assert isinstance(canvas._gate_overlay_artists, dict)
        assert len(canvas._gate_overlay_artists) == 0

    @pytest.mark.ui
    def test_initial_drawing_mode_is_none(self):
        """Initial drawing mode should be NONE."""
        parent = None
        canvas = FlowCanvas(parent=parent)
        assert canvas._drawing_mode == GateDrawingMode.NONE
        from karcytics_plugins.flow_cytometry.ui.graph.gate_drawing_fsm import DrawingState

        assert canvas._fsm.state == DrawingState.IDLE

    @pytest.mark.ui
    def test_initial_display_mode_is_pseudocolor(self):
        """Initial display mode should be PSEUDOCOLOR."""
        parent = None
        canvas = FlowCanvas(parent=parent)
        assert canvas._display_mode == DisplayMode.PSEUDOCOLOR


class TestFlowCanvasRenderingPipeline:
    """Test rendering pipeline doesn't crash."""

    @pytest.mark.ui
    def test_render_data_layer_empty_data(self):
        """_render_data_layer should handle empty data gracefully."""
        parent = None
        canvas = FlowCanvas(parent=parent)

        # Should not raise an error even with no data
        canvas._render_data_layer()

    @pytest.mark.ui
    def test_render_gate_layer_empty_gates(self):
        """_render_gate_layer should handle empty gate list gracefully."""
        parent = None
        canvas = FlowCanvas(parent=parent)

        # Should not raise an error
        canvas._render_gate_layer()

        # Should have cleared artist lists
        assert len(canvas._gate_artists) == 0
        assert len(canvas._gate_patches) == 0

    @pytest.mark.ui
    def test_redraw_calls_both_layers(self, qtbot):
        """redraw() should asynchronously render the data layer, then the gate layer."""
        parent = None
        canvas = FlowCanvas(parent=parent)
        canvas.isVisible = Mock(return_value=True)
        canvas.width = Mock(return_value=100)
        canvas.height = Mock(return_value=100)
        canvas._task_scheduler, _workers = _synchronous_scheduler()
        canvas._gate_renderer.render = Mock()

        canvas.redraw()

        # The gate layer only redraws once the data layer's compute+rasterize
        # actually completes and data_layer_finished fires.
        qtbot.waitUntil(lambda: canvas._gate_renderer.render.called, timeout=2000)

    @pytest.mark.ui
    def test_gate_artists_clear_in_render_data(self, qtbot):
        """_render_data_layer should clear gate artists once the async render completes."""
        parent = None
        canvas = FlowCanvas(parent=parent)
        canvas._task_scheduler, _workers = _synchronous_scheduler()

        # Add a mock artist
        mock_artist = Mock()
        canvas._gate_artists.append(mock_artist)

        # Call render - should clear once the async render completes
        canvas._render_data_layer()

        qtbot.waitUntil(lambda: len(canvas._gate_artists) == 0, timeout=2000)

    @pytest.mark.ui
    def test_gate_artists_clear_in_render_gate(self):
        """_render_gate_layer should clear and rebuild gate artists."""
        parent = None
        canvas = FlowCanvas(parent=parent)

        # Add a mock artist
        mock_artist = Mock()
        mock_artist.remove = Mock()
        canvas._gate_artists.append(mock_artist)

        # Call render - should clear
        canvas._render_gate_layer()

        assert len(canvas._gate_artists) == 0


class TestFlowCanvasGateDrawingStateMachine:
    """Test gate drawing mode transitions."""

    @pytest.mark.ui
    def test_set_drawing_mode(self):
        """Should be able to set drawing mode."""
        parent = None
        canvas = FlowCanvas(parent=parent)

        canvas.set_drawing_mode(GateDrawingMode.RECTANGLE)
        assert canvas._drawing_mode == GateDrawingMode.RECTANGLE

    @pytest.mark.ui
    def test_clear_drawing_state(self):
        """Should be able to clear drawing state."""
        parent = None
        canvas = FlowCanvas(parent=parent)

        # Set up some state
        canvas._drawing_mode = GateDrawingMode.POLYGON
        from karcytics_plugins.flow_cytometry.ui.graph.gate_drawing_fsm import DrawingState

        canvas._fsm.state = DrawingState.DRAWING
        canvas._fsm._polygon_vertices = [(100, 100), (200, 200)]

        # Clear state
        canvas._fsm.cancel()

        # Should reset state to IDLE
        assert canvas._fsm.state == DrawingState.IDLE
        assert len(canvas._fsm._polygon_vertices) == 0

    @pytest.mark.ui
    def test_set_drawing_mode_grabs_focus_for_active_tools(self):
        """Selecting a drawing tool must grab keyboard focus immediately.

        Quadrant finalizes on mouse *press* (no drag), so its only
        cancelable phase is the crosshair preview *before* any click —
        Escape can only cancel it if the canvas already has focus at that
        point, since a plain mouse hover never transfers focus on its own.
        """
        parent = None
        canvas = FlowCanvas(parent=parent)
        canvas.setFocus = Mock()

        canvas.set_drawing_mode(GateDrawingMode.QUADRANT)
        canvas.setFocus.assert_called_once()

    @pytest.mark.ui
    def test_set_drawing_mode_none_does_not_grab_focus(self):
        """Switching back to the select tool shouldn't steal focus."""
        parent = None
        canvas = FlowCanvas(parent=parent)
        canvas.setFocus = Mock()

        canvas.set_drawing_mode(GateDrawingMode.NONE)
        canvas.setFocus.assert_not_called()

    @pytest.mark.ui
    def test_multiple_mode_transitions(self):
        """Should handle multiple mode transitions."""
        parent = None
        canvas = FlowCanvas(parent=parent)

        modes = [
            GateDrawingMode.RECTANGLE,
            GateDrawingMode.POLYGON,
            GateDrawingMode.ELLIPSE,
            GateDrawingMode.QUADRANT,
            GateDrawingMode.RANGE,
            GateDrawingMode.NONE,
        ]

        for mode in modes:
            canvas.set_drawing_mode(mode)
            assert canvas._drawing_mode == mode


class TestFlowCanvasEditState:
    """Test post-construction gate editing: handle/body hit-testing and the
    press -> drag -> release -> commit lifecycle.
    """

    @staticmethod
    def _select_rectangle_gate(canvas):
        """Create + select a RectangleGate on `canvas`, matching how the FSM
        expects selection to already be resolved (node_id in
        `_selected_gate_id`, matching GateNode in `_gate_nodes`).
        """
        from karcytics_plugins.flow_cytometry.analysis.gating import GateNode

        gate = RectangleGate("FSC-A", "SSC-A", x_min=0, x_max=100, y_min=0, y_max=100)
        node = GateNode(gate=gate, name="Gate 1")
        canvas._active_gates = [gate]
        canvas._gate_nodes = [node]
        canvas._selected_gate_id = node.node_id
        canvas.set_axes("FSC-A", "SSC-A")
        canvas._ax.set_xlim(-50, 150)
        canvas._ax.set_ylim(-50, 150)
        canvas.set_gates([gate], [node])
        return gate, node

    @pytest.mark.ui
    def test_try_hit_edit_handle_finds_corner(self):
        """Clicking exactly on a corner handle of the selected gate should hit it."""
        canvas = FlowCanvas(parent=None)
        gate, _node = self._select_rectangle_gate(canvas)

        hit = canvas._try_hit_edit_handle(0, 100)  # the "nw" corner in data space
        assert hit is not None
        hit_gate, handle_key = hit
        assert hit_gate is gate
        assert handle_key == "nw"

    @pytest.mark.ui
    def test_try_hit_edit_handle_misses_far_away(self):
        """A click far from any handle should not hit anything."""
        canvas = FlowCanvas(parent=None)
        self._select_rectangle_gate(canvas)

        assert canvas._try_hit_edit_handle(-40, 140) is None

    @pytest.mark.ui
    def test_try_hit_edit_handle_none_when_nothing_selected(self):
        """No selected gate means no handles are hit-testable at all."""
        canvas = FlowCanvas(parent=None)
        gate = RectangleGate("FSC-A", "SSC-A", x_min=0, x_max=100, y_min=0, y_max=100)
        from karcytics_plugins.flow_cytometry.analysis.gating import GateNode

        node = GateNode(gate=gate, name="Gate 1")
        canvas._active_gates = [gate]
        canvas._gate_nodes = [node]
        canvas._selected_gate_id = None  # nothing selected
        canvas.set_axes("FSC-A", "SSC-A")
        canvas.set_gates([gate], [node])

        assert canvas._try_hit_edit_handle(0, 100) is None

    @pytest.mark.ui
    def test_try_hit_selected_gate_body(self):
        """A click inside the selected gate's shape (not on a handle) hits the body."""
        canvas = FlowCanvas(parent=None)
        gate, _node = self._select_rectangle_gate(canvas)

        assert canvas._try_hit_selected_gate_body(50, 50) is gate  # center, well inside
        assert canvas._try_hit_selected_gate_body(-40, 140) is None  # outside

    @pytest.mark.ui
    def test_drag_handle_end_to_end_commits_once(self):
        """Press on a handle, drag, release: exactly one modify_gate() call,
        with the final geometry — no calls during motion.
        """
        from karcytics_plugins.flow_cytometry.ui.graph.gate_drawing_fsm import DrawingState

        canvas = FlowCanvas(parent=None)
        gate, node = self._select_rectangle_gate(canvas)
        canvas._sample_id = "sample-1"
        canvas._controller = Mock()
        canvas._controller.modify_gate = Mock(return_value=True)

        canvas._fsm.handle_press(0, 100, "none")
        assert canvas._fsm.state == DrawingState.EDITING
        canvas._controller.modify_gate.assert_not_called()

        canvas._fsm.handle_motion(20, 100, "none")  # drag "nw" handle inward
        canvas._controller.modify_gate.assert_not_called()  # no commit mid-drag
        assert gate.x_min == 20  # live preview did mutate the real gate in place

        canvas._fsm.handle_release(20, 100, "none")
        assert canvas._fsm.state == DrawingState.IDLE
        canvas._controller.modify_gate.assert_called_once_with(gate.gate_id, "sample-1", x_min=20)

    @pytest.mark.ui
    def test_drag_with_no_change_does_not_commit(self):
        """A press+release with no actual movement should not call modify_gate()."""
        canvas = FlowCanvas(parent=None)
        gate, node = self._select_rectangle_gate(canvas)
        canvas._sample_id = "sample-1"
        canvas._controller = Mock()

        canvas._fsm.handle_press(0, 100, "none")
        canvas._fsm.handle_release(0, 100, "none")

        canvas._controller.modify_gate.assert_not_called()

    @pytest.mark.ui
    def test_cancel_mid_edit_restores_original_geometry(self):
        """Escape during a drag must restore the gate rather than leaving it
        mutated with no corresponding commit.
        """
        canvas = FlowCanvas(parent=None)
        gate, node = self._select_rectangle_gate(canvas)
        canvas._sample_id = "sample-1"
        canvas._controller = Mock()
        canvas._controller.get_gates_for_display = Mock(return_value=([gate], [node]))

        canvas._fsm.handle_press(0, 100, "none")
        canvas._fsm.handle_motion(20, 100, "none")
        assert gate.x_min == 20

        canvas._fsm.cancel()

        assert gate.x_min == 0  # restored
        canvas._controller.modify_gate.assert_not_called()

    @pytest.mark.ui
    def test_rejected_edit_restores_and_refreshes(self):
        """If modify_gate() rejects the edit (validation failure), the
        canvas must resync — restore the gate and refresh overlays — since
        the live-drag preview already mutated it with no GATE_MODIFIED
        event to trigger that on its own.
        """
        canvas = FlowCanvas(parent=None)
        gate, node = self._select_rectangle_gate(canvas)
        canvas._sample_id = "sample-1"
        canvas._controller = Mock()
        canvas._controller.modify_gate = Mock(return_value=False)
        canvas.refresh_gates = Mock()

        canvas._fsm.handle_press(0, 100, "none")
        canvas._fsm.handle_motion(20, 100, "none")
        canvas._fsm.handle_release(20, 100, "none")

        canvas._controller.modify_gate.assert_called_once()
        assert gate.x_min == 0  # restored after rejection
        canvas.refresh_gates.assert_called_once()

    @pytest.mark.ui
    def test_ellipse_drag_handle_end_to_end(self):
        """Same drag lifecycle as rectangle, generalized to EllipseGate —
        confirms the FSM/hit-test/commit path is truly generic across gate
        types rather than rectangle-specific.
        """
        from karcytics_plugins.flow_cytometry.analysis.gating import GateNode
        from karcytics_plugins.flow_cytometry.ui.graph.gate_drawing_fsm import DrawingState

        canvas = FlowCanvas(parent=None)
        gate = EllipseGate("FSC-A", "SSC-A", center=(50, 50), width=20, height=10)
        node = GateNode(gate=gate, name="Ellipse 1")
        canvas._active_gates = [gate]
        canvas._gate_nodes = [node]
        canvas._selected_gate_id = node.node_id
        canvas.set_axes("FSC-A", "SSC-A")
        canvas._ax.set_xlim(-50, 150)
        canvas._ax.set_ylim(-50, 150)
        canvas.set_gates([gate], [node])

        canvas._sample_id = "sample-1"
        canvas._controller = Mock()
        canvas._controller.modify_gate = Mock(return_value=True)

        hit = canvas._try_hit_edit_handle(70, 50)  # the "e" handle
        assert hit is not None
        assert hit[1] == "e"

        canvas._fsm.handle_press(70, 50, "none")
        assert canvas._fsm.state == DrawingState.EDITING

        canvas._fsm.handle_motion(90, 50, "none")
        assert gate.width == 40  # |90 - center_x(50)|
        canvas._controller.modify_gate.assert_not_called()

        canvas._fsm.handle_release(90, 50, "none")
        assert canvas._fsm.state == DrawingState.IDLE
        canvas._controller.modify_gate.assert_called_once_with(gate.gate_id, "sample-1", width=40)

    @pytest.mark.ui
    def test_polygon_vertex_drag_end_to_end(self):
        """Per-vertex handle drag, plus body-move (translate all vertices)."""
        from karcytics_plugins.flow_cytometry.analysis.gating import GateNode
        from karcytics_plugins.flow_cytometry.ui.graph.gate_drawing_fsm import DrawingState

        canvas = FlowCanvas(parent=None)
        gate = PolygonGate("FSC-A", "SSC-A", vertices=[(0, 0), (100, 0), (50, 100)])
        node = GateNode(gate=gate, name="Polygon 1")
        canvas._active_gates = [gate]
        canvas._gate_nodes = [node]
        canvas._selected_gate_id = node.node_id
        canvas.set_axes("FSC-A", "SSC-A")
        canvas._ax.set_xlim(-50, 150)
        canvas._ax.set_ylim(-50, 150)
        canvas.set_gates([gate], [node])

        canvas._sample_id = "sample-1"
        canvas._controller = Mock()
        canvas._controller.modify_gate = Mock(return_value=True)

        hit = canvas._try_hit_edit_handle(100, 0)  # vertex v1
        assert hit is not None
        assert hit[1] == "v1"

        canvas._fsm.handle_press(100, 0, "none")
        assert canvas._fsm.state == DrawingState.EDITING

        canvas._fsm.handle_motion(120, 10, "none")
        assert gate.vertices[1] == (120.0, 10.0)
        canvas._controller.modify_gate.assert_not_called()

        canvas._fsm.handle_release(120, 10, "none")
        canvas._controller.modify_gate.assert_called_once_with(
            gate.gate_id, "sample-1", vertices=[(0, 0), (120.0, 10.0), (50, 100)]
        )

    @pytest.mark.ui
    def test_polygon_body_move_end_to_end(self):
        from karcytics_plugins.flow_cytometry.analysis.gating import GateNode
        from karcytics_plugins.flow_cytometry.ui.graph.gate_drawing_fsm import DrawingState

        canvas = FlowCanvas(parent=None)
        gate = PolygonGate("FSC-A", "SSC-A", vertices=[(0, 0), (100, 0), (50, 100)])
        node = GateNode(gate=gate, name="Polygon 1")
        canvas._active_gates = [gate]
        canvas._gate_nodes = [node]
        canvas._selected_gate_id = node.node_id
        canvas.set_axes("FSC-A", "SSC-A")
        canvas._ax.set_xlim(-50, 150)
        canvas._ax.set_ylim(-50, 150)
        canvas.set_gates([gate], [node])

        canvas._sample_id = "sample-1"
        canvas._controller = Mock()
        canvas._controller.modify_gate = Mock(return_value=True)

        # Click well inside the triangle, away from any vertex handle.
        assert canvas._try_hit_edit_handle(50, 30) is None
        body_gate = canvas._try_hit_selected_gate_body(50, 30)
        assert body_gate is gate

        canvas._fsm.handle_press(50, 30, "none")
        assert canvas._fsm.state == DrawingState.EDITING

        canvas._fsm.handle_motion(60, 40, "none")  # +10, +10
        assert gate.vertices == [(10.0, 10.0), (110.0, 10.0), (60.0, 110.0)]

        canvas._fsm.handle_release(60, 40, "none")
        canvas._controller.modify_gate.assert_called_once_with(
            gate.gate_id, "sample-1", vertices=[(10.0, 10.0), (110.0, 10.0), (60.0, 110.0)]
        )

    @pytest.mark.ui
    def test_quadrant_center_drag_end_to_end(self):
        """Quadrant editing drags the shared parent's x_mid/y_mid via
        whichever QuadrantSubGate is selected. Deliberately selects a
        *non-representative* subgate (GateLayerRenderer dedups the 4
        subgates to one rendered crosshair, keyed by whichever iterates
        first) to exercise _find_overlay_key_for_gate's parent-identity
        resolution rather than a same-id lookup happening to work by luck.
        """
        from karcytics_plugins.flow_cytometry.analysis.gating import GateNode
        from karcytics_plugins.flow_cytometry.ui.graph.gate_drawing_fsm import DrawingState

        canvas = FlowCanvas(parent=None)
        root = GateNode(name="All Events")
        quadrant = QuadrantGate("FSC-A", "SSC-A", x_mid=50, y_mid=50)
        sub_nodes = quadrant.create_nodes(root)
        root.children.extend(sub_nodes)
        subgates = [n.gate for n in sub_nodes]  # Q1, Q2, Q3, Q4 order

        canvas._active_gates = subgates  # Q1 renders as the representative
        canvas._gate_nodes = sub_nodes
        canvas._selected_gate_id = sub_nodes[1].node_id  # select Q2, not Q1
        canvas.set_axes("FSC-A", "SSC-A")
        canvas._ax.set_xlim(-50, 150)
        canvas._ax.set_ylim(-50, 150)
        canvas.set_gates(subgates, sub_nodes)

        # The single rendered crosshair is keyed by Q1's gate_id, not Q2's —
        # confirms the dedup quirk this test targets is actually present.
        assert subgates[0].gate_id in canvas._gate_overlay_artists
        assert subgates[1].gate_id not in canvas._gate_overlay_artists

        canvas._sample_id = "sample-1"
        canvas._controller = Mock()
        canvas._controller.modify_gate = Mock(return_value=True)

        hit = canvas._try_hit_edit_handle(50, 50)
        assert hit is not None
        hit_gate, handle_key = hit
        assert hit_gate is subgates[1]  # resolved via the selected Q2 subgate
        assert handle_key == "center"

        canvas._fsm.handle_press(50, 50, "none")
        assert canvas._fsm.state == DrawingState.EDITING

        # Must not raise (this is where a ghosted/ill-removed old crosshair
        # would previously surface) and must move the shared parent.
        canvas._fsm.handle_motion(80, 20, "none")
        assert quadrant.x_mid == 80
        assert quadrant.y_mid == 20
        canvas._controller.modify_gate.assert_not_called()

        canvas._fsm.handle_release(80, 20, "none")
        canvas._controller.modify_gate.assert_called_once_with(
            subgates[1].gate_id, "sample-1", x_mid=80, y_mid=20
        )

    @pytest.mark.ui
    def test_alt_click_cycles_through_overlapping_gates(self):
        """A plain click always hits the top-most gate; holding Alt cycles
        to the next one underneath so a fully-occluded gate can be reached
        without moving or deleting anything.
        """
        from karcytics_plugins.flow_cytometry.analysis.gating import GateNode

        canvas = FlowCanvas(parent=None)
        # Two fully overlapping rectangles — same bounds — so every click
        # point hits both, with gate_b drawn on top (later in the list).
        gate_a = RectangleGate("FSC-A", "SSC-A", x_min=0, x_max=100, y_min=0, y_max=100)
        gate_b = RectangleGate("FSC-A", "SSC-A", x_min=0, x_max=100, y_min=0, y_max=100)
        node_a = GateNode(gate=gate_a, name="Gate A")
        node_b = GateNode(gate=gate_b, name="Gate B")
        canvas._active_gates = [gate_a, gate_b]
        canvas._gate_nodes = [node_a, node_b]
        canvas.set_axes("FSC-A", "SSC-A")
        canvas._ax.set_xlim(-50, 150)
        canvas._ax.set_ylim(-50, 150)
        canvas.set_gates([gate_a, gate_b], [node_a, node_b])

        canvas._controller = None  # exercise the local-fallback selection path

        # Plain click: top-most (gate_b, drawn last) wins.
        canvas._fsm.handle_press(50, 50, "none", alt_cycle=False)
        assert canvas._selected_gate_id == node_b.node_id

        # Alt+click from here cycles to the next one under the cursor: gate_a.
        canvas._fsm.handle_press(50, 50, "none", alt_cycle=True)
        assert canvas._selected_gate_id == node_a.node_id

        # Alt+click again wraps back around to gate_b.
        canvas._fsm.handle_press(50, 50, "none", alt_cycle=True)
        assert canvas._selected_gate_id == node_b.node_id

    @pytest.mark.ui
    def test_alt_click_skips_handle_and_body_hit_testing(self):
        """Alt+click always goes straight to cycle-select — it must not be
        interpreted as grabbing a handle/body of the already-selected gate.
        """
        canvas = FlowCanvas(parent=None)
        gate, node = self._select_rectangle_gate(canvas)
        canvas._sample_id = "sample-1"
        canvas._controller = Mock()

        from karcytics_plugins.flow_cytometry.ui.graph.gate_drawing_fsm import DrawingState

        # (0, 100) is exactly the "nw" handle of the selected gate — a plain
        # click there would start an EDITING drag (see
        # test_drag_handle_end_to_end_commits_once); Alt+click must not.
        canvas._fsm.handle_press(0, 100, "none", alt_cycle=True)

        assert canvas._fsm.state != DrawingState.EDITING


class TestFlowCanvasDataManagement:
    """Test data loading and parameter management."""

    @pytest.mark.ui
    def test_set_data_with_dataframe(self):
        """set_data should accept pandas DataFrame."""
        parent = None
        canvas = FlowCanvas(parent=parent)

        # Create sample data
        data = pd.DataFrame(
            {
                "FSC-A": np.random.normal(100000, 20000, 1000),
                "SSC-A": np.random.normal(5000, 1000, 1000),
                "FITC-A": np.random.exponential(50, 1000),
            }
        )

        # Mock the redraw method to avoid matplotlib issues
        with patch.object(canvas, "redraw"):
            canvas.set_data(data)
            assert canvas._current_data is data


class TestFlowCanvasAxesManagement:
    """Test axis parameter management."""

    @pytest.mark.ui
    def test_set_axes_changes_parameters(self):
        """set_axes should update axis parameters."""
        parent = None
        canvas = FlowCanvas(parent=parent)

        with patch.object(canvas, "redraw"):
            canvas.set_axes("FITC-A", "PE-A", "FITC-A", "PE-A")
            assert canvas._x_param == "FITC-A"
            assert canvas._y_param == "PE-A"


class TestFlowCanvasScaleManagement:
    """Test axis scaling and transformation."""

    @pytest.mark.ui
    def test_set_scales_updates_coordinate_mapper(self):
        """set_scales should update the coordinate mapper."""
        parent = None
        canvas = FlowCanvas(parent=parent)

        x_scale = AxisScale(TransformType.BIEXPONENTIAL)
        y_scale = AxisScale(TransformType.LOG)

        with patch.object(canvas, "redraw"):
            canvas.set_scales(x_scale, y_scale)
            assert canvas._coordinate_mapper.x_scale is x_scale
            assert canvas._coordinate_mapper.y_scale is y_scale


class TestFlowCanvasDisplayManagement:
    """Test display mode management."""

    @pytest.mark.ui
    def test_set_display_mode_changes_mode(self):
        """set_display_mode should update display mode."""
        parent = None
        canvas = FlowCanvas(parent=parent)

        canvas.set_display_mode(DisplayMode.CONTOUR)
        assert canvas._display_mode == DisplayMode.CONTOUR


class TestFlowCanvasEventHandling:
    """Test mouse and keyboard event handling."""

    @pytest.mark.ui
    def test_mouse_press_event_handling(self):
        """Mouse press events should be handled."""
        parent = None
        canvas = FlowCanvas(parent=parent)

        # Mock matplotlib event
        event = Mock()
        event.button = 1  # Left click
        event.xdata = 100
        event.ydata = 200
        event.inaxes = canvas._ax
        event.dblclick = False
        canvas._drawing_mode = GateDrawingMode.RECTANGLE

        # This should not crash
        canvas._on_press(event)
        assert canvas._fsm._drag_start == (100, 200)

    @pytest.mark.ui
    def test_mouse_release_event_handling(self):
        """Mouse release events should be handled."""
        parent = None
        canvas = FlowCanvas(parent=parent)

        # Set up drag start
        canvas._fsm._drag_start = (50, 50)
        from karcytics_plugins.flow_cytometry.ui.graph.gate_drawing_fsm import DrawingState

        canvas._fsm.state = DrawingState.DRAWING

        # Mock matplotlib event. While DRAWING, handle_release finalizes the
        # gate at the release point even if it lands outside the axes, so it
        # reads pixel coords (event.x/event.y) and transforms them itself —
        # these need to be real numbers, not default Mock attributes.
        event = Mock()
        event.button = 1
        event.xdata = 150
        event.ydata = 250
        event.x, event.y = canvas._ax.transData.transform((150, 250))
        event.inaxes = canvas._ax

        canvas._on_release(event)
        # Should clear drag start in FSM
        assert canvas._fsm._drag_start is None

    @pytest.mark.ui
    def test_drawing_mode_changes(self):
        """Drawing mode should change correctly."""
        parent = None
        canvas = FlowCanvas(parent=parent)

        assert canvas._drawing_mode == GateDrawingMode.NONE

        # Test setting drawing mode (this would normally be done by UI)
        canvas._drawing_mode = GateDrawingMode.RECTANGLE
        assert canvas._drawing_mode == GateDrawingMode.RECTANGLE


class TestFlowCanvasRendering:
    """Test rendering pipeline and visual updates."""

    @pytest.mark.ui
    def test_render_gate_layer_calls_redraw(self):
        """_gate_renderer.render should be called."""
        parent = None
        canvas = FlowCanvas(parent=parent)

        # Mock the redraw method
        with patch.object(canvas._gate_renderer, "render") as mock_redraw:
            canvas._render_gate_layer()
            mock_redraw.assert_called_once()

    @pytest.mark.ui
    def test_coordinate_transformation_accuracy(self):
        """Coordinate transformations should be accurate."""
        parent = None
        canvas = FlowCanvas(parent=parent)

        # Test with linear scales
        test_points = np.array([0, 1000, 10000, 100000])

        # Transform should be identity for linear scale
        transformed = canvas._coordinate_mapper.transform_x(test_points)
        np.testing.assert_array_almost_equal(transformed, test_points)

    @pytest.mark.ui
    def test_axis_ticks_with_transforms(self):
        """Axis ticks should be generated correctly with transforms."""
        parent = None
        canvas = FlowCanvas(parent=parent)

        # Set biexponential scale
        biexp_scale = AxisScale(TransformType.BIEXPONENTIAL)
        canvas.set_scales(biexp_scale, biexp_scale)

        # This should not crash
        canvas._setup_axis_ticks()
        # The actual tick setup is hard to test without real matplotlib
