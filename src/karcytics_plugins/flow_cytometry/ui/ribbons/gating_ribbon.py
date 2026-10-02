"""Gating ribbon — gate drawing tools and gate management.

Actions: Select pointer, Rectangle, Polygon, Ellipse, Quad,
Range/Bisector, Delete Gate, FMO Auto-Gate, Copy Gates to group,
Adaptive Gate toggle.
"""

from __future__ import annotations

from karcytics_sdk.plugin.components import SecondaryButton
from karcytics_sdk.plugin.ribbon import ThemedToolbarContainer
from karcytics_sdk.plugin.theme_fallback import Fonts, theme_manager
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QWidget

from karcytics_plugins.flow_cytometry.analysis.state import FlowState


class GatingRibbon(ThemedToolbarContainer):
    """Toolbar ribbon for gating tools and actions.

    Signals:
        tool_selected(str):            Gate tool name or ``"select"``.
        delete_gate_requested:         Emitted when Delete Gate is clicked.
        fmo_autogate_requested:        Emitted when FMO Auto-Gate is clicked.
        copy_gates_requested:          Emitted when Copy Gates is clicked.
        derived_params_requested:      Emitted when ƒ Derived is clicked.
        adaptive_toggled(bool):        Emitted when Adaptive is toggled.
    """

    tool_selected = pyqtSignal(str)  # gate type name
    delete_gate_requested = pyqtSignal()
    fmo_autogate_requested = pyqtSignal()
    copy_gates_requested = pyqtSignal()
    derived_params_requested = pyqtSignal()
    adaptive_toggled = pyqtSignal(bool)

    def __init__(self, state: FlowState, parent=None) -> None:
        super().__init__(parent)
        self._state = state
        self._active_tool = "select"
        self._setup_ui()

    @property
    def active_tool(self) -> str:
        return self._active_tool

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(6)

        # Drawing tools section
        tools_label = QLabel("Tools:")
        theme_manager.apply_style(
            tools_label,
            f"color: {{FG_SECONDARY}}; font-size: {Fonts.SIZE_SMALL}px;"
            f" font-weight: 600; background: transparent;",
        )
        layout.addWidget(tools_label)

        # Select tool (default pointer mode)
        tool_defs = [
            ("🖱 Select", "select", "Select and edit existing gates"),
            ("⬚ Rect", "rectangle", "Click and drag to draw a rectangular gate"),
            (
                "⬡ Polygon",
                "polygon",
                "Click to add vertices. Double-click or press Enter to close.",
            ),
            ("⬭ Ellipse", "ellipse", "Click and drag to draw an elliptical gate"),
            ("✛ Quad", "quadrant", "Click to place quadrant crosshairs"),
            ("⊢ Range", "range", "Click and drag horizontally to draw a 1D range gate"),
        ]

        self._tool_buttons: list[SecondaryButton] = []
        for label, tool_id, tooltip in tool_defs:
            btn = SecondaryButton(label)
            btn.setCheckable(True)
            btn.setObjectName(f"Tool_{tool_id}")
            btn.setToolTip(tooltip)
            btn.clicked.connect(lambda checked, t=tool_id: self._on_tool(t))
            layout.addWidget(btn)
            self._tool_buttons.append(btn)

        # Set Select as initially checked
        self._tool_buttons[0].setChecked(True)

        self._tools_label = tools_label

        # Separator
        self._sep1 = QWidget()
        self._sep1.setFixedWidth(1)
        self._sep1.setFixedHeight(32)
        theme_manager.apply_style(self._sep1, "background: {BORDER};")
        layout.addWidget(self._sep1)

        # Delete gate
        btn_delete = SecondaryButton("🗑 Delete")
        btn_delete.setToolTip("Delete the currently selected gate")
        btn_delete.clicked.connect(self.delete_gate_requested)
        layout.addWidget(btn_delete)

        # Separator
        self._sep2 = QWidget()
        self._sep2.setFixedWidth(1)
        self._sep2.setFixedHeight(32)
        theme_manager.apply_style(self._sep2, "background: {BORDER};")
        layout.addWidget(self._sep2)

        # Smart features
        btn_copy = SecondaryButton("📋 Copy Gates")
        btn_copy.setObjectName("CopyGatesButton")
        btn_copy.setToolTip("Copy gates from this sample to all samples in the group")
        btn_copy.clicked.connect(self.copy_gates_requested)
        layout.addWidget(btn_copy)

        btn_derived = SecondaryButton("ƒ Derived")
        btn_derived.setObjectName("DerivedParamsButton")
        btn_derived.setToolTip(
            "Create per-cell formulas such as a ratio of two channels, "
            "usable as a plot axis, a gate parameter and in statistics"
        )
        btn_derived.clicked.connect(self.derived_params_requested)
        layout.addWidget(btn_derived)

        layout.addStretch()

    def _on_tool(self, tool_id: str) -> None:
        """Handle tool button selection — ensure mutual exclusion."""
        self._active_tool = tool_id
        for btn in self._tool_buttons:
            btn.setChecked(btn.objectName() == f"Tool_{tool_id}")
        # The sender will be checked by Qt after this returns
        self.tool_selected.emit(tool_id)

    def reset_to_select(self) -> None:
        """Reset the active tool back to the pointer."""
        self._on_tool("select")

    def select_tool(self, tool_id: str) -> None:
        """Programmatically select a specific tool."""
        self._on_tool(tool_id)
