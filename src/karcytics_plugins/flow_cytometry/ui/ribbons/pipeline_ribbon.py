"""Pipeline ribbon — tools for the visual node-based gating canvas."""

from karcytics_sdk.plugin.components import BioComboBox, BioHelpButton, repopulate_combo
from karcytics_sdk.plugin.ribbon import ThemedToolbarContainer
from karcytics_sdk.plugin.theme_fallback import Fonts, theme_manager
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from karcytics_plugins.flow_cytometry.analysis.state import FlowState


class PipelineRibbon(ThemedToolbarContainer):
    """Ribbon tab containing tools for the Pipeline canvas."""

    # Emitted when the user selects a new sample to view in the pipeline
    sample_selected = pyqtSignal(str)

    # Emitted when the user requests a logic node
    logic_node_requested = pyqtSignal(str, str)  # sample_id, operator (AND/OR/NOT)

    # Emitted when the user changes layout orientation
    orientation_changed = pyqtSignal(str)

    def __init__(self, state: FlowState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.state = state
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(16)

        # ── Sample Selector ──
        self._lbl1 = QLabel("View Sample:")
        theme_manager.apply_style(
            self._lbl1,
            f"color: {{FG_SECONDARY}}; font-size: {Fonts.SIZE_SMALL}px; background: transparent;",
        )

        self._sample_combo = BioComboBox()
        self._sample_combo.setMinimumWidth(200)
        self._sample_combo.currentIndexChanged.connect(self._on_combo_changed)

        layout.addWidget(self._lbl1)
        layout.addWidget(self._sample_combo)

        # ── Layout Orientation ──
        # Add a separator
        self._sep0 = QLabel("|")
        theme_manager.apply_style(self._sep0, "color: {BORDER}; margin: 0 10px;")
        layout.addWidget(self._sep0)

        self._lbl_orient = QLabel("Layout:")
        theme_manager.apply_style(
            self._lbl_orient,
            f"color: {{FG_SECONDARY}}; font-size: {Fonts.SIZE_SMALL}px; background: transparent;",
        )
        self._orientation_combo = BioComboBox()
        self._orientation_combo.setObjectName("PipelineOrientationCombo")
        self._orientation_combo.setFixedWidth(120)
        self._orientation_combo.addItems(["Vertical", "Horizontal"])
        self._orientation_combo.setCurrentText("Vertical")
        self._orientation_combo.currentTextChanged.connect(self._on_orientation_changed)

        layout.addWidget(self._lbl_orient)
        layout.addWidget(self._orientation_combo)

        # ── Pipeline Help ──
        pipeline_help = BioHelpButton()
        pipeline_help.setHelpText(
            "Welcome to the Pipeline Viewer!\n\n"
            "• Double-click any node's mini-plot to quickly open it in the main Workspace.\n"
            "• Drag and drop from the output port (bottom/right) of a node to the input port (top/left) of another to connect them.\n"
            "• Move nodes around freely to organize your gating strategy.",
            "Pipeline Canvas Instructions",
        )
        layout.addWidget(pipeline_help)

        # ── Logic Nodes ──
        # Add a separator
        self._sep = QLabel("|")
        theme_manager.apply_style(self._sep, "color: {BORDER}; margin: 0 10px;")
        layout.addWidget(self._sep)

        logic_help = BioHelpButton()
        logic_help.setHelpText(
            "Logic gates allow you to combine different gated populations:\n\n"
            "• AND: Keeps only the events present in ALL connected parent populations.\n"
            "• OR: Keeps events present in ANY of the connected parent populations.\n"
            "• NOT: Keeps events from the primary parent, EXCLUDING events from subsequent parents.",
            "Logic Gates",
        )
        layout.addWidget(logic_help)

        logic_tooltips = {
            "AND": "Intersect populations (events must be in all parents)",
            "OR": "Union of populations (events can be in any parent)",
            "NOT": "Exclude populations (events in parent A but not in parent B)",
        }

        self._logic_buttons = []
        for op in ["AND", "OR", "NOT"]:
            btn = QPushButton(f"+ {op}")
            btn.setObjectName(f"Add{op.capitalize()}GateButton")
            btn.setToolTip(logic_tooltips[op])
            # capture op in lambda
            btn.clicked.connect(lambda checked, o=op: self._request_logic_node(o))
            theme_manager.apply_style(
                btn,
                "QPushButton {"
                "    background-color: {BG_LIGHT};"
                "    color: {FG_PRIMARY};"
                "    border: 1px solid {BORDER};"
                "    border-radius: 4px;"
                "    padding: 4px 12px;"
                "}"
                "QPushButton:hover {"
                "    background-color: {ACCENT_PRIMARY};"
                "}",
            )
            layout.addWidget(btn)
            self._logic_buttons.append(btn)

        layout.addStretch()

    def _request_logic_node(self, operator: str) -> None:
        idx = self._sample_combo.currentIndex()
        if idx >= 0:
            sample_id = self._sample_combo.itemData(idx)
            self.logic_node_requested.emit(sample_id, operator)

    def refresh_samples(self) -> None:
        items = [
            (sample.display_name, sample_id)
            for sample_id, sample in self.state.data.experiment.samples.items()
        ]
        repopulate_combo(self._sample_combo, items, restore_data=self.state.view.current_sample_id)

        # Explicitly emit for the currently selected sample to ensure it renders
        self._on_combo_changed(self._sample_combo.currentIndex())

    def _on_combo_changed(self, index: int) -> None:
        if index >= 0:
            sample_id = self._sample_combo.itemData(index)
            self.sample_selected.emit(sample_id)

    def _on_orientation_changed(self, text: str) -> None:
        self.orientation_changed.emit(text.lower())
