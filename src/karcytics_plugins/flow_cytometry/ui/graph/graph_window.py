"""Graph window: one interactive plot of one population (a sample or a gated subset).

A toolbar with the gating path and navigation, the axis/display controls,
the plot (``FlowCanvas``, where gates are drawn and edited) and a line about
the selected gate. The window owns the plot's axis scales: it fits them to
the data, remembers them per channel (``AxisManager``) and applies the
canvas's zoom and auto-range requests. ``GraphManager`` tabs and tiles these.
"""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, Any

from karcytics_sdk.plugin import CentralEventBus, get_logger
from karcytics_sdk.plugin.theme_fallback import theme_manager
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from karcytics_plugins.flow_cytometry.analysis import events
from karcytics_plugins.flow_cytometry.analysis.experiment import SampleRole
from karcytics_plugins.flow_cytometry.analysis.fcs_io import get_channel_marker_label
from karcytics_plugins.flow_cytometry.analysis.gate_coordinator import GateCoordinator
from karcytics_plugins.flow_cytometry.analysis.gating import Gate, GateNode
from karcytics_plugins.flow_cytometry.analysis.plot_view import (
    ROOT_KEY,
    fitted_scales,
    opening_view,
)
from karcytics_plugins.flow_cytometry.analysis.population_matching import name_path
from karcytics_plugins.flow_cytometry.analysis.population_service import (
    PopulationService,
    population_events,
)
from karcytics_plugins.flow_cytometry.analysis.scaling import AxisScale, calculate_auto_range
from karcytics_plugins.flow_cytometry.analysis.services import experiment_edits
from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.analysis.transforms import TransformType

from ..services.bus_subscriptions import subscribe_while_alive
from .canvas.modes import GateDrawingMode
from .components.axis_control_panel import AxisControlPanel
from .components.graph_toolbar import GraphToolbar
from .flow_canvas import FlowCanvas
from .render_settings_dialog import RenderSettingsDialog
from .render_window import RenderWindow
from .transform_dialog import TransformDialog

if TYPE_CHECKING:
    from karcytics_plugins.flow_cytometry.analysis.experiment import Sample

logger = get_logger(__name__, "flow_cytometry")

_TOOL_MODE_MAP = {
    "select": GateDrawingMode.NONE,
    "rectangle": GateDrawingMode.RECTANGLE,
    "polygon": GateDrawingMode.POLYGON,
    "ellipse": GateDrawingMode.ELLIPSE,
    "quadrant": GateDrawingMode.QUADRANT,
    "range": GateDrawingMode.RANGE,
}
_AXIS_DEBOUNCE_MS = 100  # scrolling through an axis combo renders once, at the end
_SIZE_POLL_MS, _SIZE_POLL_LIMIT = 250, 20  # wait up to 5 s for a lazy layout to give a size
_NO_SAMPLE_CHANNELS = ["FSC-A", "SSC-A", "FSC-H", "SSC-H"]


class GraphWindow(QWidget):
    """One population's plot, its axis controls and gate drawing."""

    gate_drawn = Signal(object, str, object)  # Gate, sample_id, parent_node_id
    gate_selection_changed = Signal(object)  # gate_id or None
    axis_changed = Signal()
    axis_scale_sync_requested = Signal(str, object)  # channel_name, AxisScale
    navigation_requested = Signal(str)  # "next_sample", "prev_sample", "parent_gate"
    tool_change_requested = Signal(str)  # a key of _TOOL_MODE_MAP
    derived_editor_requested = Signal(object, str)  # this GraphWindow, "x" | "y"

    def __init__(  # noqa: PLR0913
        self,
        state: FlowState,
        sample_id: str,
        node_id: str | None = None,
        axis_manager: Any | None = None,
        population_service: PopulationService | None = None,
        controller: GateCoordinator | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        if controller is None:
            raise ValueError("GateCoordinator must be injected")
        self._state = state
        self._axis_manager = axis_manager
        self._population_service = population_service
        self._sample_id = sample_id
        self._node_id = node_id
        self._controller = controller
        self._x_scale = AxisScale(TransformType.LINEAR)
        self._y_scale = AxisScale(TransformType.LINEAR)
        self._render_windows: list[RenderWindow] = []  # modeless: kept from garbage collection

        self._axis_debounce = QTimer(self)
        self._axis_debounce.setSingleShot(True)
        self._axis_debounce.setInterval(_AXIS_DEBOUNCE_MS)
        self._axis_debounce.timeout.connect(self._do_axis_render)

        self._setup_ui()
        subscribe_while_alive(
            self,
            {
                events.GATE_RENAMED: self._on_gate_renamed,
                events.SAMPLE_UPDATED: lambda _data: self._populate_fmo_combo(),
                events.DERIVED_PARAMS_CHANGED: self._on_derived_params_changed,
            },
        )

        # Some layouts (a QTabWidget on macOS) size their pages lazily: render
        # once this window has a size, polling briefly until it does.
        self._size_attempts = 0
        self._size_watcher = QTimer(self)
        self._size_watcher.timeout.connect(self._check_size_and_render)
        self._size_watcher.start(_SIZE_POLL_MS)

    # ── Public ────────────────────────────────────────────────────────

    @property
    def sample_id(self) -> str:
        return self._sample_id

    @property
    def node_id(self) -> str | None:
        return self._node_id

    @property
    def axis_panel(self) -> AxisControlPanel:
        return self._axis_panel

    @property
    def canvas(self) -> FlowCanvas:
        return self._canvas

    def set_drawing_mode(self, tool_name: str) -> None:
        """Pick the gate tool by name (a key of ``_TOOL_MODE_MAP``)."""
        self._canvas.set_drawing_mode(_TOOL_MODE_MAP.get(tool_name, GateDrawingMode.NONE))

    def refresh_gates(self, gates: list[Gate], gate_nodes: list[GateNode]) -> None:
        """Redraw the gate overlays (``gate_nodes`` label them with their stats)."""
        self._canvas.set_gates(gates, gate_nodes)

    def select_axis_param(self, axis: str, param: str) -> None:
        """Put ``param`` on ``axis`` ("x" or "y") and re-render.

        Refreshes the channel list first, so a derived parameter created a
        moment ago is selectable even before DERIVED_PARAMS_CHANGED arrives.
        """
        self._refresh_axis_channels(None)
        self._axis_panel.block_combos(True)
        if axis == "y":
            self._axis_panel.set_current_y(param)
        else:
            self._axis_panel.set_current_x(param)
        self._axis_panel.block_combos(False)
        self._on_axis_changed()

    def reload_from_state(self) -> None:
        """Re-read everything this graph shows from the state, by id.

        After undo/redo every Sample/GateNode object is new: the gate
        overlays (which hold Gate objects), the FMO choices, the channel list
        (a derived parameter may have come or gone), the scales and the
        plotted population all have to be looked up again. Also abandons a
        half-finished gate drag, which would otherwise commit onto a gate
        that no longer exists.
        """
        self._canvas.cancel_drawing()
        gates, nodes = self._controller.get_gates_for_display(self._sample_id, self._node_id)
        self.refresh_gates(gates, nodes)
        self._populate_fmo_combo()
        self._refresh_axis_channels(None)
        self.refresh_breadcrumb()
        self._on_axis_changed()

    def update_gate_info(self, gate: Gate | None, stats: dict) -> None:
        """Show the selected gate's counts under the plot (None: hide the line)."""
        if gate is None:
            self._gate_info.setVisible(False)
            return
        self._gate_info.setText(
            f"  ⊳ {stats.get('name', 'Population')}  │  "
            f"{int(stats.get('count', 0)):,} events  │  "
            f"{stats.get('pct_parent', 0.0):.1f}% of parent  │  "
            f"{stats.get('pct_total', 0.0):.1f}% of total"
        )
        self._gate_info.setVisible(True)

    def apply_axis_scale(self, channel_name: str, scale: AxisScale) -> None:
        """Use ``scale`` for ``channel_name`` if this plot shows it (another graph changed it)."""
        changed = False
        if self._axis_panel.get_current_x() == channel_name:
            self._x_scale = scale.copy()
            changed = True
        if self._axis_panel.get_current_y() == channel_name:
            self._y_scale = scale.copy()
            changed = True
        if changed:
            self._canvas.set_scales(self._x_scale, self._y_scale)

    def refresh_breadcrumb(self) -> None:
        """Show the gating path to this population in the toolbar."""
        sample = self._shown_sample()
        if sample is None:
            self._toolbar.set_breadcrumb_text("⊘ No sample selected")
            return
        node = sample.gate_tree.find_node_by_id(self._node_id) if self._node_id else None
        parts = [f"🧪 {sample.display_name}"]
        parts += [f"⊳ {name}" for name in (name_path(node) if node is not None else [])]
        self._toolbar.set_breadcrumb_text("  ›  ".join(parts))

    # ── Building ──────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        self._toolbar = GraphToolbar(self)
        self._toolbar.navigation_requested.connect(self.navigation_requested.emit)
        self._toolbar.set_parent_button_visible(self._node_id is not None)
        layout.addWidget(self._toolbar)

        self._axis_panel = AxisControlPanel(self)
        self._axis_panel.axis_changed.connect(self._on_axis_changed)
        self._axis_panel.display_mode_changed.connect(self._on_mode_changed)
        self._axis_panel.fmo_overlay_changed.connect(self._on_fmo_changed)
        self._axis_panel.transforms_requested.connect(self._open_transform_dialog)
        self._axis_panel.settings_requested.connect(self._open_render_settings_dialog)
        self._axis_panel.new_derived_requested.connect(
            lambda axis: self.derived_editor_requested.emit(self, axis)
        )
        layout.addWidget(self._axis_panel)

        self._canvas = FlowCanvas(self._state, self._controller, self)
        self._canvas.setMinimumSize(150, 150)
        layout.addWidget(self._canvas, stretch=1)
        # The global plot type, set without a redraw: the axes and scales come later.
        self._axis_panel.blockSignals(True)
        self._axis_panel.set_display_mode(self._state.view.active_plot_type)
        self._axis_panel.blockSignals(False)
        if mode := self._axis_panel.get_current_display_mode():
            self._canvas.set_display_mode(mode, redraw=False)
        self._canvas.gate_created.connect(
            lambda gate: self.gate_drawn.emit(gate, self._sample_id, self._node_id)
        )
        self._canvas.gate_selected.connect(self.gate_selection_changed.emit)
        self._canvas.drawing_cancelled.connect(lambda: self.tool_change_requested.emit("select"))
        self._canvas.scale_edit_requested.connect(self._on_scales_edited)
        self._canvas.auto_range_requested.connect(self._auto_range)
        self._canvas.add_plot_action("🔍  Render Full Quality", self._open_render_window)

        self._gate_info = QLabel()
        self._gate_info.setVisible(False)
        theme_manager.apply_style(
            self._gate_info,
            "color: {FG_SECONDARY}; font-size: 10px; background: {BG_DARK};"
            " padding: 3px 8px; border-radius: 3px;",
        )
        layout.addWidget(self._gate_info)

        self._populate_axis_combos()
        self._on_axis_changed()

    def _shown_sample(self) -> Sample | None:
        return self._state.data.experiment.samples.get(self._sample_id)

    def _channel_choices(self, sample: Sample) -> list[tuple[str, str]]:
        fcs = sample.fcs_data
        assert fcs is not None
        return [(get_channel_marker_label(fcs, ch), ch) for ch in fcs.channels]

    def _populate_axis_combos(self) -> None:
        """Fill the axis lists and pick the axes this population opens on (``opening_view``)."""
        sample = self._shown_sample()
        self._axis_panel.block_combos(True)
        if sample is None or sample.fcs_data is None:
            self._axis_panel.set_channels(
                [(c, c) for c in _NO_SAMPLE_CHANNELS], derived_entry=False
            )
            self._axis_panel.set_current_x("FSC-A")
            self._axis_panel.set_current_y("SSC-A")
        else:
            self._axis_panel.set_channels(self._channel_choices(sample))
            self._populate_fmo_combo()
            view = self._state.view
            opening = opening_view(sample, self._node_id, view.active_x_param, view.active_y_param)
            if self._axis_manager is not None:
                if opening.x_scale is not None:
                    self._axis_manager.set_scale(
                        opening.x_param, opening.x_scale, sample_id=self._sample_id
                    )
                if opening.y_scale is not None:
                    self._axis_manager.set_scale(
                        opening.y_param, opening.y_scale, sample_id=self._sample_id
                    )
            if opening.plot_type is not None:
                view.active_plot_type = opening.plot_type
                self._axis_panel.set_display_mode(opening.plot_type)
            self._axis_panel.set_current_x(opening.x_param)
            self._axis_panel.set_current_y(opening.y_param)
        self._axis_panel.block_combos(False)

    def _populate_fmo_combo(self) -> None:
        """List the experiment's FMO controls as overlays, keeping the current choice."""
        current = self._axis_panel.get_current_fmo()
        self._axis_panel.clear_fmo_combo()
        for sample_id, sample in self._state.data.experiment.samples.items():
            if sample.role == SampleRole.FMO_CONTROL:
                self._axis_panel.add_fmo_option(sample.display_name, sample_id)
        if current:
            self._axis_panel.set_current_fmo(current)

    def _refresh_axis_channels(self, changed_param: str | None) -> None:
        """Re-list the channels (a derived parameter came, went or changed) and re-render if needed."""
        sample = self._shown_sample()
        if sample is None or sample.fcs_data is None:
            return
        channels = sample.fcs_data.channels
        x_ch, y_ch = self._axis_panel.get_current_x(), self._axis_panel.get_current_y()

        def still_there(current: str, preferred: str) -> str:
            for choice in (current, preferred):
                if choice in channels:
                    return choice
            return channels[0] if channels else current

        new_x, new_y = still_there(x_ch, "FSC-A"), still_there(y_ch, "SSC-A")
        self._axis_panel.block_combos(True)
        self._axis_panel.set_channels(self._channel_choices(sample))
        self._axis_panel.set_current_x(new_x)
        self._axis_panel.set_current_y(new_y)
        self._axis_panel.block_combos(False)
        if (new_x, new_y) != (x_ch, y_ch) or changed_param in (x_ch, y_ch):
            self._on_axis_changed()

    # ── Rendering ─────────────────────────────────────────────────────

    def _check_size_and_render(self) -> None:
        self._size_attempts += 1
        if self.width() > 0 and self.height() > 0:
            self._size_watcher.stop()
            self._render_initial()
        elif self._size_attempts > _SIZE_POLL_LIMIT:
            logger.warning("GraphWindow: no size after %d attempts", self._size_attempts)
            self._size_watcher.stop()

    def _render_initial(self) -> None:
        """Fit the scales to this population and draw it."""
        sample = self._shown_sample()
        if sample is None or sample.fcs_data is None:
            return
        assert self._population_service is not None
        gated = self._population_service.get_gated_events(self._sample_id, self._node_id)
        if gated is None:
            logger.warning("GraphWindow: no events for %s / %s", self._sample_id, self._node_id)
            return
        if len(gated) == 0:
            self._canvas.set_data(gated)
            return
        x_ch, y_ch = self._axis_panel.get_current_x(), self._axis_panel.get_current_y()
        fitted = fitted_scales(
            self._state.data.experiment,
            sample,
            self._node_id,
            (x_ch, y_ch),
            (self._x_scale, self._y_scale),
        )
        if fitted is None:
            return
        # Kept per channel too, so the group preview draws with the same scales.
        self._x_scale, self._y_scale = fitted
        if self._axis_manager is not None:
            self._axis_manager.set_scale(x_ch, self._x_scale.copy(), sample_id=self._sample_id)
            self._axis_manager.set_scale(y_ch, self._y_scale.copy(), sample_id=self._sample_id)

        fcs = sample.fcs_data
        self._canvas.begin_update()
        self._canvas.set_sample_id(self._sample_id)
        self._canvas.set_axes(
            x_ch, y_ch, get_channel_marker_label(fcs, x_ch), get_channel_marker_label(fcs, y_ch)
        )
        self._canvas.set_scales(self._x_scale.copy(), self._y_scale.copy())
        self._canvas.end_update()  # one redraw with the right axes and scales
        self._canvas.set_data(gated)
        self._notify_axis_change()

    def _on_axis_changed(self) -> None:
        """An axis changed: take its scale now, render once the choice settles."""
        x_ch, y_ch = self._axis_panel.get_current_x(), self._axis_panel.get_current_y()
        self._state.view.active_x_param = x_ch
        self._state.view.active_y_param = y_ch
        if self._axis_manager is not None:
            self._x_scale = self._axis_manager.get_scale(x_ch, self._sample_id).copy()
            self._y_scale = self._axis_manager.get_scale(y_ch, self._sample_id).copy()
        if (sample := self._shown_sample()) is not None:
            sample.last_viewed_axes[self._node_id or ROOT_KEY] = {"x_param": x_ch, "y_param": y_ch}
        self._axis_panel.set_spinner_visible(True)
        self._axis_debounce.start()

    def _do_axis_render(self) -> None:
        self._render_initial()
        self._axis_panel.set_spinner_visible(False)
        self.axis_changed.emit()
        CentralEventBus.publish(
            events.AXIS_PARAMS_CHANGED,
            {
                "sample_id": self._sample_id,
                "x_param": self._axis_panel.get_current_x(),
                "y_param": self._axis_panel.get_current_y(),
            },
        )

    def _notify_axis_change(self) -> None:
        """Tell the rest of the workspace (group preview, sidebar) the scales changed."""
        CentralEventBus.publish(
            events.AXIS_RANGE_CHANGED,
            {
                "sample_id": self._sample_id,
                "x_param": self._axis_panel.get_current_x(),
                "y_param": self._axis_panel.get_current_y(),
                "x_scale": self._x_scale,
                "y_scale": self._y_scale,
            },
        )

    def _on_scales_edited(self, x_scale: AxisScale, y_scale: AxisScale) -> None:
        """The canvas asked for new ranges (a wheel zoom)."""
        self._x_scale, self._y_scale = x_scale.copy(), y_scale.copy()
        self._canvas.set_scales(self._x_scale.copy(), self._y_scale.copy())
        self._notify_axis_change()

    def _auto_range(self) -> None:
        """Fit both ranges to the data (the F key)."""
        x_range, y_range = self._calculate_auto_range("x"), self._calculate_auto_range("y")
        x_scale, y_scale = self._x_scale.copy(), self._y_scale.copy()
        x_scale.min_val, x_scale.max_val = x_range
        y_scale.min_val, y_scale.max_val = y_range
        self._on_scales_edited(x_scale, y_scale)

    def _calculate_auto_range(
        self, axis: str, outlier_p: float | None = None
    ) -> tuple[float, float]:
        """A robust min/max for ``axis`` ("x" or "y") over the whole sample.

        ``outlier_p``: the percentile clipped at each end (None: the axis scale's own).
        """
        events_df = population_events(self._state.data.experiment, self._shown_sample())
        column = (
            self._axis_panel.get_current_x() if axis == "x" else self._axis_panel.get_current_y()
        )
        if events_df is None or not column or column not in events_df:
            return (0.0, 1.0)
        scale = self._x_scale if axis == "x" else self._y_scale
        pct = outlier_p if outlier_p is not None else scale.outlier_percentile
        return calculate_auto_range(
            events_df[column].values, scale.transform_type, outlier_percentile=pct
        )

    # ── Controls ──────────────────────────────────────────────────────

    def _on_gate_renamed(self, data: dict) -> None:
        if data.get("sample_id") == self._sample_id:  # maybe an ancestor: the path shows it
            self.refresh_breadcrumb()

    def _on_derived_params_changed(self, data: dict) -> None:
        self._refresh_axis_channels(data.get("param_id"))

    def _on_mode_changed(self, mode) -> None:
        if mode:
            self._canvas.set_display_mode(mode)
            self._state.view.active_plot_type = mode.value  # thumbnails follow it
            CentralEventBus.publish(events.DISPLAY_MODE_CHANGED, {"mode": mode.value})

    def _on_fmo_changed(self, sample_id: str) -> None:
        self._canvas.set_fmo_overlay(sample_id)
        self._state.view.active_fmo_sample_id = sample_id or None
        CentralEventBus.publish(
            events.FMO_CHANGED, {"fmo_sample_id": self._state.view.active_fmo_sample_id}
        )
        if sample_id:
            self.tool_change_requested.emit("range")  # an FMO is almost always for a range gate

    def _open_render_settings_dialog(self) -> None:
        dialog = RenderSettingsDialog(self._state, self)
        dialog.settings_applied.connect(self._on_render_settings_applied)
        dialog.show()

    def _on_render_settings_applied(self, new_config) -> None:
        self._state.view.render_config = new_config
        experiment_edits.announce_unsaved_change()
        self._canvas.redraw()

    def _open_render_window(self) -> None:
        """This plot with every event at full resolution, in its own window."""
        self._render_windows = [w for w in self._render_windows if w.isVisible()]
        window = RenderWindow(
            state=self._state,
            sample_id=self._sample_id,
            node_id=self._node_id,
            axes=(self._axis_panel.get_current_x(), self._axis_panel.get_current_y()),
            scales=(self._x_scale.copy(), self._y_scale.copy()),
            display_mode=self._axis_panel.get_current_display_mode(),
            gates=list(self._canvas.active_gates),
            gate_nodes=list(self._canvas.gate_nodes),
            parent=self.window(),
        )
        window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        window.show()
        self._render_windows.append(window)

    def _open_transform_dialog(self) -> None:
        """The Transform & Scaling dialog for both axes."""
        dialog = TransformDialog(
            x_name=self._axis_panel.get_current_x_text(),
            y_name=self._axis_panel.get_current_y_text(),
            x_scale=self._x_scale,
            y_scale=self._y_scale,
            auto_range_x_callback=partial(self._calculate_auto_range, "x"),
            auto_range_y_callback=partial(self._calculate_auto_range, "y"),
            parent=self,
        )
        dialog.scale_changed.connect(self._on_scale_set)
        dialog.show()

    def _on_scale_set(self, axis: str, scale: AxisScale) -> None:
        """The transform dialog changed one axis's scale: keep it, share it, redraw."""
        channel = (
            self._axis_panel.get_current_x() if axis == "x" else self._axis_panel.get_current_y()
        )
        old = self._x_scale if axis == "x" else self._y_scale
        if axis == "x":
            self._x_scale = scale.copy()
        else:
            self._y_scale = scale.copy()
        if self._axis_manager is not None:
            self._axis_manager.set_scale(channel, scale.copy(), sample_id=self._sample_id)
        self.axis_scale_sync_requested.emit(channel, scale.copy())
        self._notify_axis_change()
        if old.transform_type != scale.transform_type:
            self._canvas.refresh_transform()
            CentralEventBus.publish(
                events.TRANSFORM_CHANGED,
                {
                    "sample_id": self._sample_id,
                    "axis": axis,
                    "channel": channel,
                    "old_type": old.transform_type,
                    "new_type": scale.transform_type,
                },
            )
        experiment_edits.announce_unsaved_change()
        self._render_initial()
