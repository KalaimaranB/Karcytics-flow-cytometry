"""GateHierarchy — top-level gate hierarchy panel (icicle chart redesign).

Preserves the complete public API of the original gate_hierarchy.py so that
main_panel.py and all other callers need no changes except wiring the new
propagation_mode_changed signal.

New public additions:
    Signal: propagation_mode_changed(bool)
"""

from __future__ import annotations

from karcytics_sdk.plugin import CentralEventBus
from karcytics_sdk.plugin.theme_fallback import Fonts, theme_manager
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from karcytics_plugins.flow_cytometry.analysis import events
from karcytics_plugins.flow_cytometry.analysis.state import FlowState

from .all_samples_popup import AllSamplesPopup
from .node_tree_engine import NodeTreeEngine
from .propagation_toggle import PropagationToggle
from .sample_view import SampleViewWidget


class GateHierarchy(QWidget):
    """Icicle-chart gate hierarchy panel for the lower-left sidebar.

    Backward-compatible public API:
        Signals:
            gate_double_clicked(node_id)
            selection_changed(node_id)
            gate_rename_requested(sample_id, node_id, new_name)
            gate_delete_requested(sample_id, node_id)
            copy_gates_requested(sample_id)

        New signal:
            propagation_mode_changed(bool)

    Methods:
            set_active_sample(sample_id)
            refresh()
            update_gate_stats(sample_id, node_id)
            update_all_sample_stats(sample_id)
    """

    # ── Signals (backward-compatible) ────────────────────────────────
    gate_double_clicked = pyqtSignal(str)
    selection_changed = pyqtSignal(str)
    gate_rename_requested = pyqtSignal(str, str, str)
    gate_delete_requested = pyqtSignal(str, str)
    copy_gates_requested = pyqtSignal(str)

    # New
    propagation_mode_changed = pyqtSignal(bool)
    propagate_requested = pyqtSignal(str, str)  # sample_id, node_id

    def __init__(self, state: FlowState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("GatingHierarchyView")
        self._state = state
        self._active_sample_id: str | None = None
        self._engine = NodeTreeEngine()

        self._setup_ui()
        self._setup_events()

    # ── UI construction ───────────────────────────────────────────────

    def _setup_ui(self) -> None:  # noqa: PLR0915
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Header strip ──────────────────────────────────────────────
        self._header_widget = QWidget()
        self._header_widget.setFixedHeight(72)
        theme_manager.apply_style(
            self._header_widget, "background: {BG_DARK}; border-bottom: 1px solid {BORDER};"
        )
        header_layout = QVBoxLayout(self._header_widget)
        header_layout.setContentsMargins(8, 6, 8, 6)
        header_layout.setSpacing(4)

        # Section label
        self._section_label = QLabel("GATING HIERARCHY")
        theme_manager.apply_style(
            self._section_label,
            "color: {FG_DISABLED}; font-size: 9px; font-weight: 700;"
            " letter-spacing: 1px; background: transparent;",
        )
        header_layout.addWidget(self._section_label)

        # Toggle + All Samples button row
        controls_row = QHBoxLayout()
        controls_row.setSpacing(6)

        self._toggle = PropagationToggle()
        self._toggle.propagation_mode_changed.connect(self._on_propagation_toggled)
        controls_row.addWidget(self._toggle, stretch=1)

        self._btn_all_samples = QPushButton("⊞")
        self._btn_all_samples.setObjectName("AllSamplesOverviewButton")
        self._btn_all_samples.setToolTip("All Samples Overview")
        self._btn_all_samples.setFixedSize(28, 22)
        self._btn_all_samples.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_all_samples.clicked.connect(self._on_all_samples_clicked)
        theme_manager.apply_style(
            self._btn_all_samples,
            """
                QPushButton {
                    background: {BG_MEDIUM};
                    color: {ACCENT_PRIMARY};
                    border: 1px solid {BORDER};
                    border-radius: 4px;
                    font-size: 13px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background: {BORDER};
                    color: {FG_PRIMARY};
                }
            """,
        )
        controls_row.addWidget(self._btn_all_samples)

        header_layout.addLayout(controls_row)
        layout.addWidget(self._header_widget)

        # ── Icicle scroll area ─────────────────────────────────────────
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        theme_manager.apply_style(
            self._scroll,
            "QScrollArea { background: {BG_DARKEST}; border: none; }"
            "QScrollBar:vertical { background: {BG_DARK}; width: 4px; }"
            "QScrollBar::handle:vertical { background: {BORDER}; border-radius: 2px; }",
        )

        self._sample_view = SampleViewWidget(self._state)
        self._sample_view.setObjectName("GatingHierarchySampleView")
        self._sample_view.node_clicked.connect(self._on_node_clicked)
        self._sample_view.node_double_clicked.connect(self._on_node_double_clicked)
        self._sample_view.rename_requested.connect(self._on_rename_requested)
        self._sample_view.delete_requested.connect(self._on_delete_requested)
        self._sample_view.propagate_requested.connect(self._on_propagate_requested)

        self._scroll.setWidget(self._sample_view)
        self._scroll.setObjectName("GatingHierarchyScrollArea")
        layout.addWidget(self._scroll, stretch=1)

        # ── Overlay Controls ──
        overlay_layout = QHBoxLayout(self._scroll)
        overlay_layout.setAlignment(Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight)
        overlay_layout.setContentsMargins(0, 0, 16, 16)
        overlay_layout.setSpacing(8)

        self.btn_zoom_in = QPushButton("Zoom In (+)")
        self.btn_zoom_in.clicked.connect(self._sample_view.zoom_in)
        self._style_zoom_btn(self.btn_zoom_in)

        self.btn_zoom_out = QPushButton("Zoom Out (-)")
        self.btn_zoom_out.clicked.connect(self._sample_view.zoom_out)
        self._style_zoom_btn(self.btn_zoom_out)

        self.btn_fit = QPushButton("Fit View (F)")
        self.btn_fit.clicked.connect(self._sample_view.fit_view)
        self._style_zoom_btn(self.btn_fit)

        overlay_layout.addWidget(self.btn_zoom_out)
        overlay_layout.addWidget(self.btn_zoom_in)
        overlay_layout.addWidget(self.btn_fit)

        # ── Empty state ───────────────────────────────────────────────
        self._empty_label = QLabel(
            "No gates applied.\n\n"
            "Select a sample and use\n"
            "a gate drawing tool on\n"
            "the canvas to begin."
        )
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setWordWrap(True)
        theme_manager.apply_style(
            self._empty_label,
            f"color: {{FG_DISABLED}}; font-size: {Fonts.SIZE_SMALL}px;"
            " padding: 24px; background: {BG_DARKEST};",
        )
        layout.addWidget(self._empty_label, stretch=1)
        self._empty_label.hide()

    def _style_zoom_btn(self, btn: QPushButton) -> None:
        theme_manager.apply_style(
            btn,
            "QPushButton {"
            "  background: {BG_MEDIUM};"
            "  color: {FG_PRIMARY};"
            "  border: 1px solid {BORDER};"
            "  border-radius: 4px;"
            "  padding: 6px 12px;"
            "}"
            "QPushButton:hover {"
            "  background: {BORDER};"
            "  border: 1px solid {ACCENT_PRIMARY};"
            "}",
        )

    def _setup_events(self) -> None:
        CentralEventBus.subscribe(events.GATE_CREATED, self._on_gate_change)
        CentralEventBus.subscribe(events.GATES_CREATED, self._on_gate_change)
        CentralEventBus.subscribe(events.GATE_RENAMED, self._on_gate_renamed)
        CentralEventBus.subscribe(events.GATE_DELETED, self._on_gate_change)
        CentralEventBus.subscribe(events.GATE_SELECTED, self._on_gate_selected)
        CentralEventBus.subscribe(events.SAMPLE_SELECTED, self._on_gate_selected)
        self.destroyed.connect(self._cleanup)

    def _cleanup(self) -> None:
        """Unsubscribe from CentralEventBus when the widget is destroyed.

        Without this, a gate event firing after this widget is torn down
        (e.g. the panel was closed/rebuilt) still invokes the bound
        _on_gate_change/_on_gate_selected callbacks — which then touch
        self._scroll and friends after their underlying Qt C++ objects are
        already deleted, raising "wrapped C/C++ object ... has been deleted".
        """
        try:
            CentralEventBus.unsubscribe(events.GATE_CREATED, self._on_gate_change)
            CentralEventBus.unsubscribe(events.GATES_CREATED, self._on_gate_change)
            CentralEventBus.unsubscribe(events.GATE_RENAMED, self._on_gate_renamed)
            CentralEventBus.unsubscribe(events.GATE_DELETED, self._on_gate_change)
            CentralEventBus.unsubscribe(events.GATE_SELECTED, self._on_gate_selected)
            CentralEventBus.unsubscribe(events.SAMPLE_SELECTED, self._on_gate_selected)
        except Exception:
            pass

    # ── Public API (backward-compatible) ─────────────────────────────

    def set_active_sample(self, sample_id: str | None) -> None:
        """Update the active sample and refresh the icicle."""
        self._active_sample_id = sample_id
        self.refresh()

    def refresh(self) -> None:
        """Full rebuild of the icicle from current state."""
        sid = self._active_sample_id or self._state.view.current_sample_id
        if not sid:
            self._section_label.setText("GATING HIERARCHY")
            self._show_empty(True)
            return

        sample = self._state.data.experiment.samples.get(sid)
        if sample is None:
            self._section_label.setText("GATING HIERARCHY")
            self._show_empty(True)
            return

        self._section_label.setText(f"GATING HIERARCHY — {sample.display_name.upper()}")

        total_events = 0
        if sample.fcs_data is not None:
            total_events = sample.fcs_data.num_events

        rects = self._engine.compute(sample.gate_tree, total_events)
        has_gates = len(rects) > 1

        if not has_gates:
            self._show_empty(True)
            return

        self._show_empty(False)
        self._sample_view.set_rects(rects)

        gate_id = self._state.view.current_gate_id
        if not gate_id:
            gate_id = sample.gate_tree.node_id
        self._sample_view.set_selected(gate_id)

    def update_gate_stats(self, sample_id: str, node_id: str = "") -> None:
        """Incremental stats update — refreshes the whole icicle for simplicity."""
        sid = self._active_sample_id or self._state.view.current_sample_id
        if sample_id == sid:
            self.refresh()

    def update_all_sample_stats(self, sample_id: str) -> None:
        sid = self._active_sample_id or self._state.view.current_sample_id
        if sample_id == sid:
            self.refresh()

    # ── Compatibility shim: _gate_item_map ───────────────────────────
    # main_panel.py accesses _gate_item_map to sync tree selection.
    # We provide a no-op dict so no AttributeError is raised.

    @property
    def _gate_item_map(self) -> dict:
        return {}

    # ── Internal event handlers ───────────────────────────────────────

    def _on_gate_change(self, _data: dict) -> None:
        try:
            self.refresh()
        except RuntimeError:
            # A child (e.g. _scroll) was already deleted by Qt before
            # `destroyed` fired for `self` and unsubscribed us — see
            # _cleanup()'s docstring. Unsubscribe now so it doesn't recur.
            self._cleanup()

    def _on_gate_renamed(self, data: dict) -> None:
        """Update just the renamed node's label — a rename changes no tree
        structure, so it doesn't need a full icicle relayout (see refresh()).
        """
        sid = self._active_sample_id or self._state.view.current_sample_id
        if data.get("sample_id") != sid:
            return
        node_id = data.get("node_id")
        new_name = data.get("new_name")
        if not node_id or new_name is None:
            return
        try:
            self._sample_view.rename_node(node_id, new_name)
        except RuntimeError:
            self._cleanup()

    def _on_gate_selected(self, _data: dict) -> None:
        try:
            sid = self._active_sample_id or self._state.view.current_sample_id
            if not sid:
                return
            sample = self._state.data.experiment.samples.get(sid)
            if not sample:
                return
            gate_id = self._state.view.current_gate_id
            if not gate_id:
                gate_id = sample.gate_tree.node_id
            self._sample_view.set_selected(gate_id)
        except RuntimeError:
            self._cleanup()

    def _on_propagation_toggled(self, enabled: bool) -> None:
        self.propagation_mode_changed.emit(enabled)

    def _on_all_samples_clicked(self) -> None:
        sid = self._active_sample_id or self._state.view.current_sample_id
        if not sid:
            return
        # The popup no longer auto-dismisses on an outside click (so it can
        # stay open while the rest of the app is used) — re-clicking the
        # trigger while one is already open must close it explicitly instead
        # of leaving an orphaned instance behind.
        existing = getattr(self, "_popup", None)
        if existing is not None:
            existing.hide()
            existing.deleteLater()
        self._popup = AllSamplesPopup(self)
        self._popup.sample_selected.connect(self._on_popup_sample_selected)
        self._popup.show_near(self._btn_all_samples, self._state, sid)

    def _on_popup_sample_selected(self, sample_id: str) -> None:
        self._popup.hide()
        self.set_active_sample(sample_id)

    def _on_node_clicked(self, node_id: str) -> None:
        self._sample_view.set_selected(node_id)
        self.selection_changed.emit(node_id)

    def _on_node_double_clicked(self, node_id: str) -> None:
        self.gate_double_clicked.emit(node_id)

    def _on_rename_requested(self, node_id: str) -> None:
        sid = self._active_sample_id or self._state.view.current_sample_id
        if not sid:
            return
        sample = self._state.data.experiment.samples.get(sid)
        if not sample:
            return
        node = sample.gate_tree.find_node_by_id(node_id)
        current_name = node.name if node else ""

        from PyQt6.QtWidgets import QInputDialog, QLineEdit

        new_name, ok = QInputDialog.getText(
            self,
            "Rename Population",
            "Enter new name:",
            QLineEdit.EchoMode.Normal,
            current_name,
        )
        if ok and new_name:
            self.gate_rename_requested.emit(sid, node_id, new_name)

    def _on_delete_requested(self, node_id: str) -> None:
        sid = self._active_sample_id or self._state.view.current_sample_id
        if sid:
            self.gate_delete_requested.emit(sid, node_id)

    def _on_propagate_requested(self, node_id: str) -> None:
        sid = self._active_sample_id or self._state.view.current_sample_id
        if sid:
            self.propagate_requested.emit(sid, node_id)

    # ── Helpers ───────────────────────────────────────────────────────

    def _show_empty(self, empty: bool) -> None:
        self._scroll.setVisible(not empty)
        self._empty_label.setVisible(empty)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # Re-layout on resize so proportions stay correct
        self.refresh()
