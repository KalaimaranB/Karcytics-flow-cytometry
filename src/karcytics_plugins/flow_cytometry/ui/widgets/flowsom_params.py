"""The clustering methods' own settings in the Population Analysis sidebar.

FlowSOM and PhenoGraph each get a panel of spin boxes with plain-language
help; UMAP + HDBSCAN's settings live in the viewer itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from karcytics_sdk.plugin.components import BioDoubleSpinBox, BioHelpButton, BioSpinBox
from karcytics_sdk.plugin.theme_fallback import Colors
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    minimum: float
    maximum: float
    default: float
    object_name: str
    help: str
    step: float = 1
    decimals: int = 0  # 0: a whole-number spin box


FLOWSOM_FIELDS = (
    Field(
        "grid",
        "Grid size",
        5,
        20,
        10,
        "FlowsomGridSpin",
        "FlowSOM first sorts the cells into a square grid of small groups called nodes "
        "(10 gives 10 × 10 = 100 nodes). More nodes show finer detail and rarer cells; "
        "100 suits most panels.",
    ),
    Field(
        "k",
        "Metaclusters (k)",
        2,
        40,
        10,
        "FlowsomKInput",
        "How many populations to group the nodes into: roughly how many cell types you "
        "expect. Too high splits one population in two, too low merges two. You can "
        "change it after the run, instantly.",
    ),
    Field(
        "passes",
        "Training passes",
        1,
        50,
        10,
        "FlowsomPassesSpin",
        "How many times the grid learns from the cells. 10 is FlowSOM's default; more "
        "rarely changes the result.",
    ),
)

PHENOGRAPH_FIELDS = (
    Field(
        "n_neighbors",
        "Neighbours (k)",
        5,
        100,
        30,
        "PhenographNeighborsSpin",
        "PhenoGraph links each cell to its k most similar cells, then links two cells by "
        "how many of those neighbours they share. 30 is PhenoGraph's default. Lower finds "
        "smaller, finer groups; higher merges small groups into bigger ones.",
    ),
    Field(
        "resolution",
        "Resolution",
        0.1,
        5.0,
        1.0,
        "PhenographResolutionInput",
        "How finely the linked cells are divided into clusters. Higher gives more, smaller "
        "clusters; lower merges them. You don't choose a number of clusters: the data does, "
        "at this resolution. You can change it after the run (a few seconds).",
        step=0.1,
        decimals=1,
    ),
    Field(
        "min_cluster_size",
        "Minimum cluster size",
        2,
        1000,
        10,
        "PhenographMinSizeSpin",
        "Clusters with fewer cells than this are not kept: their cells are marked as "
        "outliers. 10 is PhenoGraph's default.",
    ),
)


class MethodParamsPanel(QWidget):
    """A titled column of settings, each with a plain-language help button."""

    def __init__(
        self, title: QWidget, fields: tuple[Field, ...], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(title)
        self._fields = fields
        self._spins: dict[str, BioSpinBox | BioDoubleSpinBox] = {}
        for field in fields:
            row = QHBoxLayout()
            caption = QLabel(f"{field.label}:")
            caption.setStyleSheet(f"color: {Colors.FG_PRIMARY}; font-size: 11px;")
            row.addWidget(caption)
            help_btn = BioHelpButton()
            help_btn.setHelpText(field.help, field.label)
            row.addWidget(help_btn)
            row.addStretch()
            spin: BioSpinBox | BioDoubleSpinBox
            if field.decimals:
                spin = BioDoubleSpinBox()
                spin.setDecimals(field.decimals)
                spin.setSingleStep(field.step)
                spin.setRange(field.minimum, field.maximum)
                spin.setValue(field.default)
            else:
                spin = BioSpinBox()
                spin.setRange(int(field.minimum), int(field.maximum))
                spin.setValue(int(field.default))
            spin.setObjectName(field.object_name)
            row.addWidget(spin)
            layout.addLayout(row)
            self._spins[field.key] = spin
        self._note = QLabel()
        self._note.setStyleSheet(f"color: {Colors.FG_SECONDARY}; font-size: 10px;")
        layout.addWidget(self._note)

    def raw_values(self) -> dict[str, float]:
        return {key: spin.value() for key, spin in self._spins.items()}

    def show_run(self, run: dict[str, Any]) -> None:
        for field in self._fields:
            if run.get(field.key) is not None:
                self._spins[field.key].setValue(run[field.key])

    def set_read_only(self, read_only: bool) -> None:
        for spin in self._spins.values():
            spin.setEnabled(not read_only)


class FlowsomParamsPanel(MethodParamsPanel):
    """Grid size, metaclusters and training passes."""

    def __init__(self, title: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(title, FLOWSOM_FIELDS, parent)
        self.setObjectName("FlowsomParams")
        self._spins["grid"].valueChanged.connect(self._show_nodes)
        self._show_nodes(self._spins["grid"].value())

    def _show_nodes(self, side: float) -> None:
        side = int(side)
        self._note.setText(f"{side} × {side} = {side * side} nodes")

    def values(self) -> dict[str, int]:
        side = int(self._spins["grid"].value())
        return {
            "xdim": side,
            "ydim": side,
            "k": int(self._spins["k"].value()),
            "passes": int(self._spins["passes"].value()),
        }

    def show_run(self, run: dict[str, Any]) -> None:
        super().show_run({**run, "grid": run.get("xdim", 10)})


class PhenographParamsPanel(MethodParamsPanel):
    """Neighbours, resolution and minimum cluster size."""

    def __init__(self, title: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(title, PHENOGRAPH_FIELDS, parent)
        self.setObjectName("PhenographParams")

    def values(self) -> dict[str, Any]:
        raw = self.raw_values()
        return {
            "n_neighbors": int(raw["n_neighbors"]),
            "resolution": round(float(raw["resolution"]), 2),
            "min_cluster_size": int(raw["min_cluster_size"]),
        }
