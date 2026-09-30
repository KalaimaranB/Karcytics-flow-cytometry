"""Properties panel — context-sensitive detail view for selected items.

Shows different content depending on what's selected:
- **Sample**: file metadata, keywords, channel list, marker assignments
- **Gate**: gate type, parameters, event count, %parent, %total,
  plus computed statistics (Mean, MFI, CV)
- **No selection**: general workspace info

This is the right-side panel of the workspace.  It refreshes in
real-time when gate statistics are updated by the ``GateController``
or ``GatePropagator``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from karcytics_sdk.plugin import CentralEventBus, get_logger
from karcytics_sdk.plugin.theme_fallback import Colors, Fonts, theme_manager
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFormLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from karcytics_plugins.flow_cytometry.analysis import events
from karcytics_plugins.flow_cytometry.analysis.experiment import Sample
from karcytics_plugins.flow_cytometry.analysis.fcs_io import derived_labels_of
from karcytics_plugins.flow_cytometry.analysis.gate_coordinator import GateCoordinator
from karcytics_plugins.flow_cytometry.analysis.gating.gate_node import GateNode
from karcytics_plugins.flow_cytometry.analysis.state import FlowState

from .group_preview import GroupPreviewPanel
from .styled_combo import FlowComboBox

logger = get_logger(__name__, "flow_cytometry")


class PropertiesPanel(QWidget):
    """Right-sidebar panel showing properties of the selected item.

    Dynamically updates when the user clicks on a sample or gate
    in the sample tree, and refreshes live when gate statistics
    are recomputed.
    """

    roleChanged = pyqtSignal()

    def __init__(
        self,
        state: FlowState,
        axis_manager: Any,
        population_service: Any,
        coordinator: GateCoordinator,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._state = state
        self._axis_manager = axis_manager
        self._population_service = population_service
        self._coordinator = coordinator
        self._current_sample_id: str | None = None
        self._current_node_id: str | None = None
        self._is_alive = True  # must be set before _setup_ui() calls _clear_content()
        self.setObjectName("PropertiesPanel")
        self._setup_ui()
        self._setup_events()

    def _setup_events(self) -> None:
        # Store as bound references so we can unsubscribe later (see cleanup())
        def _on_axis_changed(_):
            if self._is_alive:
                self.refresh()

        def _on_stats(data: dict):
            if self._is_alive:
                self.refresh_gate_stats(data.get("sample_id"), data.get("node_id"))  # type: ignore

        self._on_axis_params_changed = _on_axis_changed
        self._on_stats_computed_cb = _on_stats
        CentralEventBus.subscribe(events.AXIS_PARAMS_CHANGED, self._on_axis_params_changed)
        CentralEventBus.subscribe(events.STATS_COMPUTED, self._on_stats_computed_cb)

    def cleanup(self) -> None:
        """Unsubscribe from CentralEventBus to prevent zombie callbacks after deletion.

        Must be called before the widget is destroyed (typically from
        ``FlowCytometryPanel.cleanup()``).
        """
        self._is_alive = False
        try:
            CentralEventBus.unsubscribe(events.AXIS_PARAMS_CHANGED, self._on_axis_params_changed)
            CentralEventBus.unsubscribe(events.STATS_COMPUTED, self._on_stats_computed_cb)
        except Exception:
            pass

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        self._header = QLabel("Properties")
        self._header.setFixedHeight(32)
        theme_manager.apply_style(
            self._header,
            f"color: {{FG_SECONDARY}}; font-size: {Fonts.SIZE_SMALL}px;"
            " font-weight: 700; text-transform: uppercase;"
            " letter-spacing: 1px; background: {BG_DARK};"
            " padding: 6px 12px;"
            " border-bottom: 1px solid {BORDER};",
        )
        layout.addWidget(self._header)

        # Splitter to allow user to resize the two panels
        self._splitter = QSplitter(Qt.Orientation.Vertical)
        self._splitter.setHandleWidth(2)
        theme_manager.apply_style(self._splitter, "QSplitter::handle { background: {BORDER}; }")

        # Scrollable content (Top)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        theme_manager.apply_style(self._scroll, "background: {BG_DARKEST};")

        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setSpacing(8)
        self._content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._scroll.setWidget(self._content)
        self._splitter.addWidget(self._scroll)

        # Group Preview section (Bottom)
        self._group_preview = GroupPreviewPanel(
            self._state, None, self._axis_manager, self._population_service
        )
        self._splitter.addWidget(self._group_preview)

        # Set initial sizes (1/3 properties, 2/3 preview as requested)
        self._splitter.setSizes([300, 600])

        layout.addWidget(self._splitter)

        # Initial state
        self._show_empty()

    def _apply_theme_styles(self) -> None:
        """Re-render the currently-displayed sample/group properties (their
        content is Colors-derived) on theme change. The panel's own static
        chrome (header/splitter/scroll) self-themes via `theme_manager` and
        doesn't need re-invocation here.
        """
        if hasattr(self, "_current_sample_id") and (
            self._current_sample_id or self._current_node_id
        ):
            self.refresh()

    def show_sample_properties(self, sample_id: str, gate_id: str | None) -> None:
        """Update the panel to show properties of the selected item.

        Args:
            sample_id: The selected sample's ID.
            gate_id:   The selected gate's ID (None if sample root).
        """
        self._current_sample_id = sample_id
        self._current_node_id = gate_id

        # Update preview context
        self._group_preview.update_context(sample_id, gate_id)

        sample = self._state.data.experiment.samples.get(sample_id)
        if sample is None:
            self._show_empty()
            return

        if gate_id:
            self._show_gate_properties(sample, gate_id)
        else:
            self._show_sample_details(sample)

    def refresh(self) -> None:
        """Refresh the panel (e.g., after state restore)."""
        if not self._is_alive:
            return
        if self._current_sample_id and self._current_node_id:
            self.show_sample_properties(self._current_sample_id, self._current_node_id)
        elif self._current_sample_id:
            self.show_sample_properties(self._current_sample_id, None)
        else:
            self._show_empty()

    def refresh_gate_stats(self, sample_id: str, node_id: str) -> None:
        """Live-refresh if the currently displayed gate was updated.

        Called by the ``GateController`` when stats change.

        Args:
            sample_id: The sample whose gate was updated.
            node_id:   The gate that was updated.
        """
        if self._current_sample_id == sample_id and self._current_node_id == node_id:
            self.show_sample_properties(sample_id, node_id)

    # ── Private display methods ───────────────────────────────────────

    def _cleanup(self) -> None:
        """Unsubscribe from global events to prevent callbacks on a deleted widget."""
        if not self._is_alive:
            return
        self._is_alive = False
        try:
            CentralEventBus.unsubscribe(events.AXIS_PARAMS_CHANGED, self._on_axis_params_changed)
            cb = getattr(self, "_on_stats_computed_cb", None)
            if cb:
                CentralEventBus.unsubscribe(events.STATS_COMPUTED, cb)
        except Exception:
            pass

    def closeEvent(self, event) -> None:
        """Ensure event-bus subscriptions are torn down before Qt deletes children."""
        self._cleanup()
        super().closeEvent(event)

    def _clear_content(self) -> None:
        """Remove all widgets from the content area."""
        # Guard against callbacks firing after the C++ layout has been deleted
        if not self._is_alive:
            return
        if not hasattr(self, "_content_layout") or self._content_layout is None:
            return

        self._content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        while self._content_layout.count():
            child = self._content_layout.takeAt(0)
            if child:
                w = child.widget()
                if w:
                    w.deleteLater()

    def _show_empty(self) -> None:
        """Show empty/default state."""
        self._clear_content()
        self._header.setText("Properties")
        self._current_sample_id = None
        self._current_node_id = None

        if hasattr(self, "_group_preview"):
            self._group_preview.update_context(None, None)

        self._content_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        lbl = QLabel("Select a sample or gate\nfrom the tree to view\nits properties.")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(
            f"color: {Colors.FG_DISABLED}; font-size: {Fonts.SIZE_SMALL}px;"
            f" background: transparent; padding: 24px;"
        )
        self._content_layout.addWidget(lbl)

    def _show_sample_details(self, sample: Sample) -> None:  # noqa: PLR0915
        """Display sample metadata and channel info."""
        self._clear_content()
        self._header.setText(f"📄 {sample.display_name}")

        form = QFormLayout()
        form.setSpacing(10)
        form.setContentsMargins(0, 0, 0, 0)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        label_style = (
            f"color: {Colors.FG_SECONDARY}; font-size: {Fonts.SIZE_SMALL}px;"
            f" background: transparent;"
        )
        value_style = (
            f"color: {Colors.FG_PRIMARY}; font-size: {Fonts.SIZE_SMALL}px; background: transparent;"
        )

        from karcytics_sdk.plugin.components import BioHelpButton
        from PyQt6.QtWidgets import QHBoxLayout

        def _create_label(label_text: str, help_text: str | None = None) -> QWidget:
            w = QWidget()
            lay = QHBoxLayout(w)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(4)
            lbl = QLabel(label_text)
            lbl.setStyleSheet(label_style)
            lay.addWidget(lbl)

            if help_text:
                help_btn = BioHelpButton()
                help_btn.setHelpText(help_text, title=label_text.replace(":", ""))
                lay.addWidget(help_btn)

            lay.addStretch()
            return w

        def _add_row(label_text: str, value_text: str, help_text: str | None = None) -> None:
            val = QLabel(value_text)
            val.setStyleSheet(value_style)
            val.setWordWrap(True)
            val.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            form.addRow(_create_label(label_text, help_text), val)

        from PyQt6.QtWidgets import QComboBox

        from ...analysis.experiment import SampleRole

        # Plain QComboBox only styles the closed box itself — its popup
        # QAbstractItemView is a separate top-level widget that Qt renders
        # with the default (non-dark) palette unless given its own explicit
        # QSS. That left the popup's current-selection row unreadable (dark
        # text on a dark background) even though the closed box looked
        # fine. FlowComboBox already styles QAbstractItemView (base, hover,
        # and selected item colors) for every other dropdown in this
        # module, so reuse it here instead of a one-off, popup-less
        # stylesheet.
        role_combo = FlowComboBox()
        role_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        role_combo.setMinimumWidth(180)

        for role in SampleRole:
            role_combo.addItem(role.value.replace("_", " ").title(), role)

        # Set current role
        for i in range(role_combo.count()):
            if role_combo.itemData(i) == sample.role:
                role_combo.setCurrentIndex(i)
                break

        def _on_role_changed(idx: int):
            new_role = role_combo.itemData(idx)
            sample.role = new_role
            CentralEventBus.publish(
                events.SAMPLE_UPDATED,
                {"sample_id": sample.sample_id, "stats": None, "tree": None},
            )
            self.roleChanged.emit()

        role_combo.currentIndexChanged.connect(_on_role_changed)

        role_help_text = (
            "<b>Unstained</b><br>"
            "<i>What:</i> Cells with no fluorescent dyes.<br>"
            "<i>Karcytics:</i> Used as the universal negative baseline for Compensation and Autofluorescence Extraction.<br><br>"
            "<b>Single Stain</b><br>"
            "<i>What:</i> Cells stained with exactly ONE color.<br>"
            "<i>Karcytics:</i> Required by the Compensation Ribbon to mathematically calculate spectral spillover.<br><br>"
            "<b>FMO Control</b><br>"
            "<i>What:</i> Cells stained with all colors EXCEPT one.<br>"
            "<i>Karcytics:</i> Used as a control to objectively set manual gate boundaries between positive and negative populations.<br><br>"
            "<b>Isotype Control</b><br>"
            "<i>What:</i> Stained with non-specific antibodies.<br>"
            "<i>Karcytics:</i> Used to subtract background noise when calculating Statistics (e.g. MFI).<br><br>"
            "<b>Full Panel</b><br>"
            "<i>What:</i> Experimental samples with all colors.<br>"
            "<i>Karcytics:</i> The primary targets for Dimensionality Reduction and Clustering engines.<br><br>"
            "<b>Other</b><br>"
            "<i>What:</i> Viability or biological controls.<br>"
            "<i>Karcytics:</i> Ignored by automated engines."
        )

        form.addRow(_create_label("Role:", role_help_text), role_combo)

        _add_row("Events:", f"{sample.event_count:,}" if sample.has_data else "Not loaded")

        if sample.fcs_data:
            _add_row("File:", sample.fcs_data.file_path.name)

        if sample.markers:
            _add_row("Markers:", ", ".join(sample.markers))
        if sample.fmo_minus:
            _add_row("FMO Minus:", sample.fmo_minus)
        if sample.is_compensated:
            _add_row("Compensated:", "✅ Yes")

        # Gate count
        gate_count = self._count_gates(sample.gate_tree)
        if gate_count > 0:
            _add_row("Gates:", f"{gate_count} population{'s' if gate_count > 1 else ''}")

        # Channel list — show all, word wrap handles overflow
        if sample.fcs_data and sample.fcs_data.channels:
            _add_row("Channels:", ", ".join(sample.fcs_data.channels))

        form_widget = QWidget()
        form_widget.setLayout(form)
        self._content_layout.addWidget(form_widget)
        self._content_layout.addStretch()

    @staticmethod
    def _parent_pct_label(node: GateNode, gate: object | None) -> str:
        """Named, not a bare "% Parent": a node's *statistical* parent
        (whatever this percentage is actually computed against) isn't
        always obvious from the canvas alone — e.g. a UMAP cluster's edge
        is drawn from the "UMAP Reduction" container either way. Only for
        an ordinary gated node (exactly one real parent) — a logic node's
        combined "% Parent" isn't a single meaningful ratio the way its
        per-parent breakdown is, so it keeps the generic label.
        """
        if node.parents and gate is not None:
            return f"% of {node.parents[0].name}:"
        return "% Parent:"

    @staticmethod
    def _add_estimation_rows(
        add_row: Callable[..., None], statistics: dict, count: float, pct_total: float
    ) -> None:
        """Surface a node's UMAP-subsample correction, if any — never
        replacing the raw Event Count/% Total rows above, only adding to
        them, so a scientist sees both side by side. See
        `DagEvaluator._propagate_estimation` for what `is_scale_valid`
        means and why an OR/NOT-combined node can't get a corrected number.
        """
        if not statistics.get("is_estimated"):
            return
        if statistics.get("is_scale_valid"):
            scale = statistics.get("scale_factor", 1.0)
            est_count = statistics.get("estimated_count", count)
            est_pct_total = statistics.get("estimated_pct_total", pct_total)
            add_row("Estimated Count:", f"{int(est_count):,} (×{scale:.2f})", highlight=True)
            add_row("Estimated % Total:", f"{est_pct_total:.2f}%", highlight=True)
            add_row(
                "⚠ Estimate:",
                "Scaled up from a UMAP subsample — statistically valid, not an exact count.",
            )
        else:
            add_row(
                "⚠ Estimate:",
                "Combines a UMAP-subsampled population via OR/NOT — count can't be "
                "safely corrected and may undercount the true population.",
            )

    @staticmethod
    def _param_label(sample: Sample, param: str) -> str:
        return derived_labels_of(sample.fcs_data).get(param, param)

    def _derived_formula_rows(self, gate) -> list[tuple[str, str]]:
        """Formula of each derived axis, noting if it changed since drawing."""
        current = {d.param_id: d for d in self._state.data.experiment.derived_parameters}
        recorded = getattr(gate, "derived_formulas", {}) or {}
        rows: list[tuple[str, str]] = []
        for param in dict.fromkeys(p for p in (gate.x_param, gate.y_param) if p):
            defn = current.get(param)
            drawn_on = recorded.get(param)
            if defn is None:
                if drawn_on:
                    rows.append(("ƒ Formula:", f"{drawn_on} (definition deleted)"))
                continue
            text = defn.formula
            if drawn_on and drawn_on != defn.formula:
                text += f"\n⚠ Drawn on: {drawn_on}"
            rows.append((f"ƒ {defn.name}:", text))
        return rows

    def _show_gate_properties(self, sample: Sample, node_id: str) -> None:  # noqa: PLR0915
        """Display gate-specific properties with detailed statistics."""
        self._clear_content()

        node = sample.gate_tree.find_node_by_id(node_id)
        # A logic node (AND/OR/NOT) has no `gate` of its own but still has
        # real statistics worth showing here — most importantly whether it's
        # a scaled UMAP estimate, since that's exactly where "safely
        # correctable" vs. "not" (see DagEvaluator._propagate_estimation)
        # matters most to a scientist reading this panel.
        if node is None or (node.gate is None and not node.is_logic_node):
            self._show_empty()
            return

        gate = node.gate
        self._header.setText(f"⊳ {node.name}")

        form = QFormLayout()
        form.setSpacing(6)
        form.setContentsMargins(0, 0, 0, 0)

        label_style = (
            f"color: {Colors.FG_SECONDARY}; font-size: {Fonts.SIZE_SMALL}px;"
            f" background: transparent;"
        )
        value_style = (
            f"color: {Colors.FG_PRIMARY}; font-size: {Fonts.SIZE_SMALL}px; background: transparent;"
        )
        stat_value_style = (
            f"color: {Colors.ACCENT_PRIMARY}; font-size: {Fonts.SIZE_SMALL}px;"
            f" background: transparent; font-weight: 600;"
        )

        def _add_row(label_text: str, value_text: str, highlight: bool = False) -> None:
            lbl = QLabel(label_text)
            lbl.setStyleSheet(label_style)
            val = QLabel(value_text)
            val.setStyleSheet(stat_value_style if highlight else value_style)
            val.setWordWrap(True)
            val.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            form.addRow(lbl, val)

        name_lbl = QLabel("Name:")
        name_lbl.setStyleSheet(label_style)

        name_edit = QLineEdit(node.name)
        name_edit.setStyleSheet(
            f"background: {Colors.BG_DARK}; color: {Colors.FG_PRIMARY}; border: 1px solid {Colors.BORDER}; padding: 4px;"
        )
        name_edit.editingFinished.connect(lambda: self._on_name_changed(name_edit.text()))
        form.addRow(name_lbl, name_edit)

        # Gate identity
        if gate is not None:
            _add_row("Type:", type(gate).__name__)
            _add_row("X Param:", self._param_label(sample, gate.x_param))
            if gate.y_param:
                _add_row("Y Param:", self._param_label(sample, gate.y_param))
            for label, text in self._derived_formula_rows(gate):
                _add_row(label, text)
            _add_row("Adaptive:", "🧠 Yes" if gate.adaptive else "No")
        else:
            _add_row("Type:", f"{node.logic_operator} Logic")

        # Population statistics — highlighted
        if node.statistics:
            count = node.statistics.get("count", 0)
            pct_parent = node.statistics.get("pct_parent", 0.0)
            pct_total = node.statistics.get("pct_total", 0.0)

            _add_row("Event Count:", f"{int(count):,}", highlight=True)
            _add_row(self._parent_pct_label(node, gate), f"{pct_parent:.2f}%", highlight=True)
            _add_row("% Total:", f"{pct_total:.2f}%", highlight=True)

            self._add_estimation_rows(_add_row, node.statistics, count, pct_total)

        # Child gate count
        child_count = len(node.children)
        if child_count > 0:
            _add_row("Sub-gates:", f"{child_count}")

        # Final Assemblage
        form_widget = QWidget()
        form_widget.setLayout(form)
        self._content_layout.addWidget(form_widget)

        self._content_layout.addStretch()

    def set_active_gate(self, node_id: str | None) -> None:
        """Update the panel to show properties for a specific population."""
        self.show_sample_properties(self._current_sample_id, node_id)  # type: ignore

    def _on_name_changed(self, new_name: str) -> None:
        if self._current_sample_id and self._current_node_id:
            sample = self._state.data.experiment.samples.get(self._current_sample_id)
            if sample:
                node = sample.gate_tree.find_node_by_id(self._current_node_id)
                if node and node.name == new_name:
                    return

            self._coordinator.rename_population(
                self._current_sample_id, self._current_node_id, new_name
            )

    def _count_gates(self, node) -> int:
        """Count total gates in a tree (excluding root)."""
        count = 0
        for child in node.children:
            if child.gate is not None:
                count += 1
            count += self._count_gates(child)
        return count
