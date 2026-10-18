"""FlowSOM's own settings in the Population Analysis sidebar."""

from __future__ import annotations

from typing import Any

from karcytics_sdk.plugin.components import BioHelpButton, BioSpinBox
from karcytics_sdk.plugin.theme_fallback import Colors
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

# (key, label, range, default, objectName, help)
FIELDS = (
    (
        "grid",
        "Grid size",
        (5, 20),
        10,
        "FlowsomGridSpin",
        "FlowSOM first sorts the cells into a square grid of small groups called nodes "
        "(10 gives 10 × 10 = 100 nodes). More nodes show finer detail and rarer cells; "
        "100 suits most panels.",
    ),
    (
        "k",
        "Metaclusters (k)",
        (2, 40),
        10,
        "FlowsomKInput",
        "How many populations to group the nodes into: roughly how many cell types you "
        "expect. Too high splits one population in two, too low merges two. You can "
        "change it after the run, instantly.",
    ),
    (
        "passes",
        "Training passes",
        (1, 50),
        10,
        "FlowsomPassesSpin",
        "How many times the grid learns from the cells. 10 is FlowSOM's default; more "
        "rarely changes the result.",
    ),
)


class FlowsomParamsPanel(QWidget):
    """Grid size, metaclusters and training passes, each with a plain-language help."""

    def __init__(self, title: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("FlowsomParams")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(title)
        self._spins: dict[str, BioSpinBox] = {}
        for key, label, (lo, hi), default, name, help_text in FIELDS:
            row = QHBoxLayout()
            caption = QLabel(f"{label}:")
            caption.setStyleSheet(f"color: {Colors.FG_PRIMARY}; font-size: 11px;")
            row.addWidget(caption)
            help_btn = BioHelpButton()
            help_btn.setHelpText(help_text, label)
            row.addWidget(help_btn)
            row.addStretch()
            spin = BioSpinBox()
            spin.setObjectName(name)
            spin.setRange(lo, hi)
            spin.setValue(default)
            row.addWidget(spin)
            layout.addLayout(row)
            self._spins[key] = spin
        self._nodes_lbl = QLabel()
        self._nodes_lbl.setStyleSheet(f"color: {Colors.FG_SECONDARY}; font-size: 10px;")
        layout.addWidget(self._nodes_lbl)
        self._spins["grid"].valueChanged.connect(self._show_nodes)
        self._show_nodes(self._spins["grid"].value())

    def _show_nodes(self, side: int) -> None:
        self._nodes_lbl.setText(f"{side} × {side} = {side * side} nodes")

    def values(self) -> dict[str, int]:
        side = self._spins["grid"].value()
        return {
            "xdim": side,
            "ydim": side,
            "k": self._spins["k"].value(),
            "passes": self._spins["passes"].value(),
        }

    def show_run(self, run: dict[str, Any]) -> None:
        self._spins["grid"].setValue(int(run.get("xdim", 10)))
        self._spins["k"].setValue(int(run.get("k", 10)))
        self._spins["passes"].setValue(int(run.get("passes", 10)))

    def set_read_only(self, read_only: bool) -> None:
        for spin in self._spins.values():
            spin.setEnabled(not read_only)
