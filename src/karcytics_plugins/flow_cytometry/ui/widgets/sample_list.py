"""Sample list widget — lists loaded samples without gating hierarchy."""

from __future__ import annotations

from karcytics_sdk.plugin import CentralEventBus
from karcytics_sdk.plugin.theme_fallback import Colors, Fonts
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QHeaderView,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from karcytics_plugins.flow_cytometry.analysis import events
from karcytics_plugins.flow_cytometry.analysis.experiment import Sample
from karcytics_plugins.flow_cytometry.analysis.state import FlowState

# Icons and Colors from the original SampleTree
_ROLE_BADGES = {
    "tube": "○",
    "fmo": "◉",
    "compensation": "◧",
    "blank": "◌",
}


def _get_role_color(role: str) -> str:
    colors = {
        "tube": Colors.FG_PRIMARY,
        "fmo": Colors.ACCENT_PRIMARY,
        "compensation": "#FFB74D",
        "blank": Colors.FG_DISABLED,
    }
    return colors.get(role, "#B0BEC5")


class SampleList(QWidget):
    """List of loaded samples with basic stats.

    Signals:
        sample_double_clicked(sample_id): Emitted on double click.
        selection_changed(sample_id): Emitted on selection change.
    """

    sample_double_clicked = pyqtSignal(str)
    selection_changed = pyqtSignal(str)
    population_open_requested = pyqtSignal(str, str)

    def __init__(self, state: FlowState, parent=None) -> None:
        super().__init__(parent)
        self._state = state
        self._active_group_filter: str = "__all__"
        self.setObjectName("SampleList")
        self._setup_ui()
        self._setup_events()

    def _setup_events(self) -> None:
        """Subscribe to relevant state events."""
        CentralEventBus.subscribe(events.SAMPLE_LOADED, self._on_sample_loaded)
        self.destroyed.connect(self._cleanup)

    def _cleanup(self) -> None:
        """Unsubscribe from events when the widget is destroyed."""
        try:
            CentralEventBus.unsubscribe(events.SAMPLE_LOADED, self._on_sample_loaded)
        except Exception:
            pass

    def _on_sample_loaded(self, data: dict) -> None:
        """Handle incoming sample loaded events."""
        try:
            self.refresh()
        except RuntimeError:
            # Fallback if destroyed signal didn't unregister in time
            CentralEventBus.unsubscribe(events.SAMPLE_LOADED, self._on_sample_loaded)

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Tree widget using QTreeWidget for multi-column support
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Sample", "Events"])
        self._tree.setColumnCount(2)
        self._tree.setIndentation(0)
        self._tree.setRootIsDecorated(False)
        self._tree.setDragEnabled(True)
        self._tree.setDragDropMode(QTreeWidget.DragDropMode.DragOnly)

        header_view = self._tree.header()
        if header_view:
            header_view.setStretchLastSection(False)
            header_view.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            header_view.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
            header_view.resizeSection(1, 75)

        self._tree.itemDoubleClicked.connect(self._on_double_click)
        self._tree.currentItemChanged.connect(self._on_selection_changed)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_context_menu)
        self._tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        layout.addWidget(self._tree, stretch=1)

        # Empty state placeholder
        self._empty_label = QLabel(
            "No samples loaded.\n\nUse the Workspace tab to:\n• Add Samples (FCS files)\n• Add Groups"
        )
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setWordWrap(True)
        layout.addWidget(self._empty_label, stretch=1)
        self._empty_label.hide()

        self._apply_theme_styles()

    def _apply_theme_styles(self) -> None:
        """Dynamically refresh all UI colors based on the current theme."""
        if hasattr(self, "_tree"):
            self._tree.setStyleSheet(
                f"QTreeWidget {{ background: {Colors.BG_DARKEST};"
                f" border: none; outline: none;"
                f" color: {Colors.FG_PRIMARY};"
                f" font-size: {Fonts.SIZE_SMALL}px; }}"
                f"QTreeWidget::item {{ padding: 6px 4px;"
                f" border-bottom: 1px solid {Colors.BG_DARK}; }}"
                f"QTreeWidget::item:selected {{ background: {Colors.BG_MEDIUM};"
                f" color: {Colors.ACCENT_PRIMARY}; border-left: 3px solid {Colors.ACCENT_PRIMARY}; }}"
                f"QTreeWidget::item:hover {{ background: {Colors.BG_DARK}; }}"
                f"QHeaderView::section {{ background: {Colors.BG_DARK};"
                f" color: {Colors.FG_SECONDARY}; border: none;"
                f" border-bottom: 1px solid {Colors.BORDER};"
                f" padding: 4px 6px; font-size: 10px; font-weight: 600; }}"
            )
        if hasattr(self, "_empty_label"):
            self._empty_label.setStyleSheet(
                f"color: {Colors.FG_DISABLED}; font-size: {Fonts.SIZE_SMALL}px;"
                f" padding: 24px; background: {Colors.BG_DARKEST};"
            )

        self._update_empty_state()

    def filter_by_group(self, group_id: str) -> None:
        """Filter the list by group."""
        self._active_group_filter = group_id
        if not hasattr(self._state.view, "active_group_filter"):
            self._state.view.active_group_filter = "__all__"
        self._state.view.active_group_filter = group_id
        self.refresh()

    def refresh(self) -> None:
        """Rebuild the list from the current state."""
        # Save current selection
        current_item = self._tree.currentItem()
        selected_id = None
        if current_item and current_item.isSelected():
            selected_id = current_item.data(0, Qt.ItemDataRole.UserRole)

        self._tree.blockSignals(True)
        self._tree.clear()
        samples = self._get_filtered_samples()

        for sample in samples:
            item = self._create_sample_item(sample)
            self._tree.addTopLevelItem(item)

        self._update_empty_state()

        # Restore selection without emitting signals
        if selected_id:
            for i in range(self._tree.topLevelItemCount()):
                tl_item = self._tree.topLevelItem(i)
                if tl_item and tl_item.data(0, Qt.ItemDataRole.UserRole) == selected_id:
                    self._tree.setCurrentItem(tl_item)
                    tl_item.setSelected(True)
                    break
        else:
            self._tree.clearSelection()
            self._tree.setCurrentItem(None)

        self._tree.blockSignals(False)

    def update_all_sample_stats(self, *args, **kwargs) -> None:
        """Compatibility signature to absorb signal events harmlessly or update event counts."""
        self.refresh()

    def update_gate_stats(self, sample_id: str, gate_id: str = "") -> None:
        pass  # We don't track gates here

    def _get_filtered_samples(self) -> list[Sample]:
        experiment = self._state.data.experiment
        if self._active_group_filter == "__all__":
            return list(experiment.samples.values())

        group = experiment.groups.get(self._active_group_filter)
        if not group:
            return list(experiment.samples.values())

        return [experiment.samples[sid] for sid in group.sample_ids if sid in experiment.samples]

    def _create_sample_item(self, sample: Sample) -> QTreeWidgetItem:
        badge = _ROLE_BADGES.get(sample.role, "○")  # type: ignore
        name = f"{badge} {sample.display_name}"

        if sample.fcs_data and sample.fcs_data.is_compensated:
            name += " [Comp]"

        if sample.markers:
            name += f"  [{', '.join(sample.markers)}]"

        item = QTreeWidgetItem(
            [
                name,
                f"{sample.event_count:,}" if sample.has_data else "—",
            ]
        )
        item.setData(0, Qt.ItemDataRole.UserRole, sample.sample_id)
        item.setToolTip(0, name)

        color = _get_role_color(sample.role)  # type: ignore
        item.setForeground(0, QColor(color))

        font = item.font(0)
        font.setBold(True)
        item.setFont(0, font)

        return item

    def select_sample(self, sample_id: str | None) -> None:
        """Select a sample in the list by ID."""
        if not sample_id:
            self._tree.clearSelection()
            self._tree.setCurrentItem(None)
            return

        for i in range(self._tree.topLevelItemCount()):
            tl_item = self._tree.topLevelItem(i)
            if tl_item and tl_item.data(0, Qt.ItemDataRole.UserRole) == sample_id:
                self._tree.setCurrentItem(tl_item)
                tl_item.setSelected(True)
                break

    def _update_empty_state(self) -> None:
        is_empty = self._tree.topLevelItemCount() == 0
        self._tree.setVisible(not is_empty)
        self._empty_label.setVisible(is_empty)

    def _on_double_click(self, item: QTreeWidgetItem, column: int) -> None:
        if item is None:
            return
        sample_id = item.data(0, Qt.ItemDataRole.UserRole)
        if sample_id:
            self.sample_double_clicked.emit(sample_id)

    def _on_selection_changed(self, current: QTreeWidgetItem, previous: QTreeWidgetItem) -> None:
        if current is None:
            return
        if not current.isSelected():
            return
        sample_id = current.data(0, Qt.ItemDataRole.UserRole)
        if sample_id:
            self.selection_changed.emit(sample_id)

    def _on_context_menu(self, pos) -> None:
        """Show context menu for samples."""
        items = self._tree.selectedItems()
        if not items:
            return

        from karcytics_sdk.plugin.components import BioMenu

        menu = BioMenu(self)

        experiment = self._state.data.experiment

        # Add to Group submenu
        if experiment.groups:
            add_menu = menu.addMenu("Add to Group")
            if add_menu:
                for group in experiment.groups.values():
                    action = add_menu.addAction(group.name)
                    if action:
                        action.setData(group.group_id)

                add_menu.triggered.connect(
                    lambda action: self._add_samples_to_group(items, action.data())
                )

        # Remove from Group option (if currently filtering by a group)
        if self._active_group_filter != "__all__":
            group = experiment.groups.get(self._active_group_filter)  # type: ignore
            if group:
                menu.addSeparator()
                remove_action = menu.addAction(f"Remove from '{group.name}'")
                if remove_action:
                    remove_action.triggered.connect(
                        lambda: self._remove_samples_from_group(items, group.group_id)
                    )

        # View Population (if exactly one sample is selected)
        if len(items) == 1:
            sample_id = items[0].data(0, Qt.ItemDataRole.UserRole)
            sample = experiment.samples.get(sample_id)

            if not menu.isEmpty():
                menu.addSeparator()
            rename_action = menu.addAction("Rename Sample")
            if rename_action is not None:
                rename_action.triggered.connect(
                    lambda checked=False, i=items[0]: self._rename_sample(i)
                )

            if sample and sample.gate_tree:
                menu.addSeparator()

                def add_populations(node, prefix="", is_last=True, is_root=True):
                    # Action for current node
                    if is_root:
                        display_name = node.name
                    else:
                        marker = "┗━ " if is_last else "┣━ "
                        display_name = prefix + marker + node.name

                    action = menu.addAction(display_name)
                    # Use default arguments to capture loop variables safely
                    action.triggered.connect(
                        lambda checked=False, s_id=sample_id, n_id=node.node_id: (
                            self.population_open_requested.emit(s_id, n_id)
                        )
                    )

                    # Recursively add children
                    if node.children:
                        child_prefix = prefix + ("   " if is_last else "┃  ")
                        for i, child in enumerate(node.children):
                            add_populations(child, child_prefix, i == len(node.children) - 1, False)

                add_populations(sample.gate_tree)

        # Delete Sample option
        if not menu.isEmpty():
            menu.addSeparator()
        delete_action = menu.addAction(
            "Delete Sample" if len(items) == 1 else f"Delete {len(items)} Samples"
        )
        if delete_action is not None:
            delete_action.triggered.connect(
                lambda checked=False, it=items: self._delete_samples(it)
            )

        if not menu.isEmpty():
            menu.exec(self._tree.mapToGlobal(pos))

    def _rename_sample(self, item: QTreeWidgetItem) -> None:
        """Rename the selected sample."""
        sample_id = item.data(0, Qt.ItemDataRole.UserRole)
        sample = self._state.data.experiment.samples.get(sample_id)
        if not sample:
            return

        from PyQt6.QtWidgets import QInputDialog

        new_name, ok = QInputDialog.getText(
            self, "Rename Sample", "New name:", text=sample.display_name
        )
        if ok and new_name and new_name.strip() != sample.display_name:
            sample.display_name = new_name.strip()
            CentralEventBus.publish(events.SAMPLE_UPDATED, {"source": "SampleList"})
            self.refresh()

    def _delete_samples(self, items: list[QTreeWidgetItem]) -> None:
        """Remove the selected samples from the workspace."""
        from karcytics_sdk.plugin.dialogs import ask_yes_no

        count = len(items)
        msg = f"Are you sure you want to remove the selected sample{'s' if count > 1 else ''} from the workspace?\n\nThis will not delete any files from your disk."
        confirmed = ask_yes_no(self, "Remove Sample", msg)

        if confirmed:
            changed = False
            for item in items:
                sample_id = item.data(0, Qt.ItemDataRole.UserRole)
                if sample_id and sample_id in self._state.data.experiment.samples:
                    self._state.data.experiment.remove_sample(sample_id)
                    changed = True

            if changed:
                CentralEventBus.publish(events.EXPERIMENT_DATA_CHANGED, {"source": "SampleList"})
                self.refresh()

    def _add_samples_to_group(self, items, group_id: str) -> None:
        """Add selected samples to a specific group."""
        group = self._state.data.experiment.groups.get(group_id)
        if not group:
            return

        changed = False
        for item in items:
            sample_id = item.data(0, Qt.ItemDataRole.UserRole)
            if sample_id and sample_id not in group.sample_ids:
                group.sample_ids.append(sample_id)
                sample = self._state.data.experiment.samples.get(sample_id)
                if sample and group_id not in sample.group_ids:
                    sample.group_ids.append(group_id)
                changed = True

        if changed:
            CentralEventBus.publish(events.SAMPLE_UPDATED, {"source": "SampleList"})

    def _remove_samples_from_group(self, items, group_id: str) -> None:
        """Remove selected samples from the current group."""
        group = self._state.data.experiment.groups.get(group_id)
        if not group:
            return

        changed = False
        for item in items:
            sample_id = item.data(0, Qt.ItemDataRole.UserRole)
            if sample_id and sample_id in group.sample_ids:
                group.sample_ids.remove(sample_id)
                sample = self._state.data.experiment.samples.get(sample_id)
                if sample and group_id in sample.group_ids:
                    sample.group_ids.remove(group_id)
                changed = True

        if changed:
            CentralEventBus.publish(events.SAMPLE_UPDATED, {"source": "SampleList"})
            self.refresh()

    def cleanup(self) -> None:
        """Clear tree state."""
        self._tree.clear()
