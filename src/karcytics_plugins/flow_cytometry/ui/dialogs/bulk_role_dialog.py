from karcytics_sdk.plugin import get_logger
from karcytics_sdk.plugin.components import PrimaryButton, SecondaryButton
from karcytics_sdk.plugin.dialogs import show_warning
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from karcytics_plugins.flow_cytometry.analysis.experiment import SampleRole
from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.ui.widgets.styled_combo import FlowComboBox

logger = get_logger(__name__, "flow_cytometry")


class BulkRoleDialog(QDialog):
    """Dialog for assigning a role to multiple samples simultaneously."""

    def __init__(self, state: FlowState, parent=None):
        super().__init__(parent)
        self._state = state

        self.setWindowTitle("Bulk Assign Roles")
        self.setMinimumSize(400, 500)

        self._setup_ui()
        self._populate_samples()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Header
        header = QLabel("Select samples and choose a role to assign to all of them:")
        header.setWordWrap(True)
        layout.addWidget(header)

        # Sample List (Multi-select)
        self.sample_list = QListWidget()
        self.sample_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.sample_list.setToolTip("Use Ctrl+Click or Shift+Click to select multiple samples")
        layout.addWidget(self.sample_list, stretch=1)

        # Role selection
        role_layout = QHBoxLayout()
        role_layout.addWidget(QLabel("Target Role:"))
        self.role_combo = FlowComboBox()

        # Populate roles
        self.role_combo.addItem("Unstained", userData=SampleRole.UNSTAINED)
        self.role_combo.addItem("Single Stain", userData=SampleRole.SINGLE_STAIN)
        self.role_combo.addItem("FMO Control", userData=SampleRole.FMO_CONTROL)
        self.role_combo.addItem("Isotype Control", userData=SampleRole.ISOTYPE_CONTROL)
        self.role_combo.addItem("Full Panel", userData=SampleRole.FULL_PANEL)
        self.role_combo.addItem("Other", userData=SampleRole.OTHER)

        role_layout.addWidget(self.role_combo, stretch=1)
        layout.addLayout(role_layout)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.btn_cancel = SecondaryButton("Cancel")
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_cancel)

        self.btn_assign = PrimaryButton("Assign Role")
        self.btn_assign.clicked.connect(self._on_assign)
        btn_layout.addWidget(self.btn_assign)

        layout.addLayout(btn_layout)

    def _populate_samples(self):
        exp = self._state.data.experiment
        for sid, sample in exp.samples.items():
            item = QListWidgetItem(f"{sample.display_name} (Current: {sample.role.value})")
            item.setData(Qt.ItemDataRole.UserRole, sid)
            self.sample_list.addItem(item)

    def _on_assign(self):
        selected_items = self.sample_list.selectedItems()
        if not selected_items:
            show_warning(
                self,
                "No Selection",
                "Please select at least one sample to assign a role.",
            )
            return

        target_role = self.role_combo.currentData()
        exp = self._state.data.experiment

        assigned_count = 0
        for item in selected_items:
            sid = item.data(Qt.ItemDataRole.UserRole)
            sample = exp.samples.get(sid)
            if sample:
                sample.role = target_role
                assigned_count += 1

        logger.info(f"Bulk assigned role {target_role.value} to {assigned_count} samples.")
        self.accept()
