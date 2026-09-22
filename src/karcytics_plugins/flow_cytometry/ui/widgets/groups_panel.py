"""Groups panel — displays sample groups with roles and colors.

Shows all defined groups in the workspace.  Clicking a group filters
the sample tree below to show only that group's samples.

Displays group list: Name, Size (count), Role (compensation,
control, test), and a color indicator.
"""

from __future__ import annotations

from karcytics_sdk.plugin import get_logger
from karcytics_sdk.plugin.theme_fallback import Colors, Fonts
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from karcytics_plugins.flow_cytometry.analysis.state import FlowState

logger = get_logger(__name__, "flow_cytometry")


class GroupListWidget(QListWidget):
    """Custom QListWidget to support dropping samples."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.on_drop = None

    def dropEvent(self, event):
        if self.on_drop:
            self.on_drop(event)
        else:
            super().dropEvent(event)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat("application/x-qabstractitemmodeldatalist"):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat("application/x-qabstractitemmodeldatalist"):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)


class GroupsPanel(QWidget):
    """Left-sidebar panel showing sample groups.

    Signals:
        group_selected(group_id): Emitted when a group is clicked.
    """

    group_selected = pyqtSignal(str)

    def __init__(self, state: FlowState, parent=None) -> None:
        super().__init__(parent)
        self._state = state
        self.setObjectName("GroupsPanel")
        self.setFixedHeight(160)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 4)
        layout.setSpacing(4)

        self._header = QLabel("Groups")
        layout.addWidget(self._header)

        self._list = GroupListWidget()
        self._list.currentRowChanged.connect(self._on_row_changed)
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._on_context_menu)
        self._list.on_drop = self._on_drop_event
        layout.addWidget(self._list, stretch=1)

        self._apply_theme_styles()

        # Add "All Samples" as default
        self._populate_default()

    def _apply_theme_styles(self) -> None:
        """Dynamically refresh colors based on the current theme."""
        if hasattr(self, "_header"):
            self._header.setStyleSheet(
                f"color: {Colors.FG_SECONDARY}; font-size: {Fonts.SIZE_SMALL}px;"
                f" font-weight: 700; text-transform: uppercase;"
                f" letter-spacing: 1px; background: transparent;"
            )
        if hasattr(self, "_list"):
            self._list.setStyleSheet(
                f"QListWidget {{ background: {Colors.BG_DARKEST};"
                f" border: none; outline: none; }}"
                f"QListWidget::item {{ padding: 6px 8px;"
                f" border-bottom: 1px solid {Colors.BORDER};"
                f" color: {Colors.FG_PRIMARY}; }}"
                f"QListWidget::item:selected {{ background: {Colors.BG_MEDIUM};"
                f" color: {Colors.ACCENT_PRIMARY}; }}"
                f"QListWidget::item:hover {{ background: {Colors.BG_DARK}; }}"
            )

    def _populate_default(self) -> None:
        """Add the default 'All Samples' entry."""
        self._list.clear()
        item = QListWidgetItem("📂  All Samples")
        item.setData(Qt.ItemDataRole.UserRole, "__all__")
        self._list.addItem(item)
        self._list.setCurrentRow(0)

    def _on_row_changed(self, row: int) -> None:
        if row < 0:
            return
        item = self._list.item(row)
        if item:
            group_id = item.data(Qt.ItemDataRole.UserRole)
            self.group_selected.emit(group_id or "__all__")

    def refresh(self) -> None:
        """Rebuild the group list from the current state."""
        current_item = self._list.currentItem()
        active_group_id = current_item.data(Qt.ItemDataRole.UserRole) if current_item else "__all__"

        self._list.clear()

        # Always include "All Samples"
        all_item = QListWidgetItem("📂  All Samples")
        all_item.setData(Qt.ItemDataRole.UserRole, "__all__")
        self._list.addItem(all_item)

        target_row = 0
        for i, group in enumerate(self._state.data.experiment.groups.values()):
            role_icon = {
                "compensation": "🔬",
                "control": "🎛",
                "test": "🧪",
                "all_samples": "📂",
                "custom": "📁",
            }.get(group.role.value, "📁")

            text = f"{role_icon}  {group.name}  ({group.size})"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, group.group_id)
            self._list.addItem(item)

            if group.group_id == active_group_id:
                target_row = i + 1

        self._list.blockSignals(True)
        self._list.setCurrentRow(target_row)
        self._list.blockSignals(False)

    def _on_drop_event(self, event):
        """Handle samples dropped from the SampleList."""
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        item = self._list.itemAt(pos)
        if not item:
            event.ignore()
            return

        group_id = item.data(Qt.ItemDataRole.UserRole)
        if not group_id or group_id == "__all__":
            event.ignore()
            return

        if event.mimeData().hasFormat("application/x-qabstractitemmodeldatalist"):
            # Extract sample_ids from tree widget items
            # The mime data encodes tree widget items. We just need the source widget
            source = event.source()
            from PyQt6.QtWidgets import QTreeWidget

            if isinstance(source, QTreeWidget):
                group = self._state.data.experiment.groups.get(group_id)
                if not group:
                    return

                changed = False
                for s_item in source.selectedItems():
                    sample_id = s_item.data(0, Qt.ItemDataRole.UserRole)
                    if sample_id and sample_id not in group.sample_ids:
                        group.sample_ids.append(sample_id)
                        sample = self._state.data.experiment.samples.get(sample_id)
                        if sample and group_id not in sample.group_ids:
                            sample.group_ids.append(group_id)
                        changed = True

                if changed:
                    event.acceptProposedAction()
                    self.refresh()
                    # Reselect the group to show updated items
                    for i in range(self._list.count()):
                        if self._list.item(i).data(Qt.ItemDataRole.UserRole) == group_id:
                            self._list.setCurrentRow(i)
                            break
                    from karcytics_sdk.plugin import CentralEventBus

                    from karcytics_plugins.flow_cytometry.analysis import events

                    CentralEventBus.publish(events.SAMPLE_UPDATED, {"source": "GroupsPanel"})
            else:
                event.ignore()

    def _on_context_menu(self, pos):
        """Show context menu for a group."""
        item = self._list.itemAt(pos)
        if not item:
            return

        group_id = item.data(Qt.ItemDataRole.UserRole)
        if not group_id or group_id == "__all__":
            return

        from karcytics_sdk.plugin.dialogs import ask_yes_no
        from PyQt6.QtWidgets import QInputDialog, QMenu

        menu = QMenu(self)

        rename_action = menu.addAction("Rename Group")
        delete_action = menu.addAction("Delete Group")

        action = menu.exec(self._list.mapToGlobal(pos))

        if action == rename_action:
            group = self._state.data.experiment.groups.get(group_id)
            if group:
                name, ok = QInputDialog.getText(
                    self, "Rename Group", "Enter new name:", text=group.name
                )
                if ok and name.strip():
                    group.name = name.strip()
                    self.refresh()
                    from karcytics_sdk.plugin import CentralEventBus

                    from karcytics_plugins.flow_cytometry.analysis import events

                    CentralEventBus.publish(events.SAMPLE_UPDATED, {"source": "GroupsPanel"})

        elif action == delete_action:
            confirmed = ask_yes_no(
                self,
                "Delete Group",
                "Are you sure you want to delete this group?",
            )
            if confirmed:
                group = self._state.data.experiment.groups.get(group_id)
                if group:
                    # Remove from all samples
                    for sample_id in group.sample_ids:
                        sample = self._state.data.experiment.samples.get(sample_id)
                        if sample and group_id in sample.group_ids:
                            sample.group_ids.remove(group_id)
                    # Remove from experiment
                    del self._state.data.experiment.groups[group_id]
                    self.refresh()
                    from karcytics_sdk.plugin import CentralEventBus

                    from karcytics_plugins.flow_cytometry.analysis import events

                    CentralEventBus.publish(events.SAMPLE_UPDATED, {"source": "GroupsPanel"})
