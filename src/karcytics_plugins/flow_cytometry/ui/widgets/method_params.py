"""The clustering methods' own settings in the Population Analysis sidebar.

FlowSOM and PhenoGraph each get a panel of spin boxes, UMAP + HDBSCAN one of
sliders; every setting has plain-language help. `param_group` is the shared
"caption, help button, control" row, so a tutorial step can spotlight a
whole setting by one objectName.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from karcytics_sdk.plugin import BioSectionLabel
from karcytics_sdk.plugin.components import (
    BioComboBox,
    BioDoubleSpinBox,
    BioHelpButton,
    BioSpinBox,
)
from karcytics_sdk.plugin.theme_fallback import theme_manager
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QSlider, QVBoxLayout, QWidget

from .checkbox_style import checkbox_qss

# Theme-token templates (theme_manager.apply_style keeps them current).
CAPTION_STYLE = "color: {FG_PRIMARY}; font-size: 11px;"
_VALUE_STYLE = "color: {DNA_PRIMARY}; font-weight: bold; font-size: 11px;"
_NOTE_STYLE = "color: {FG_SECONDARY}; font-size: 10px;"


def _help_row(control: QWidget, help_text: str, help_title: str, object_name: str) -> QWidget:
    """`control` with a help button beside it, as one spotlight target."""
    row_widget = QWidget()
    row_widget.setObjectName(object_name)
    row = QHBoxLayout(row_widget)
    row.setContentsMargins(0, 0, 0, 0)
    row.addWidget(control)
    help_btn = BioHelpButton()
    help_btn.setHelpText(help_text, help_title)
    row.addWidget(help_btn)
    row.addStretch()
    return row_widget


def param_group(
    caption: str | QWidget,
    help_text: str,
    control: QWidget,
    *,
    object_name: str = "",
    help_title: str = "",
    value: QLabel | None = None,
) -> QWidget:
    """One setting: caption, help button and (optionally) its value above the control."""
    if isinstance(caption, str):
        help_title = help_title or caption.rstrip(":")
        caption = QLabel(caption)
        theme_manager.apply_style(caption, CAPTION_STYLE)
    help_btn = BioHelpButton()
    help_btn.setHelpText(help_text, help_title)
    row = QHBoxLayout()
    row.addWidget(caption)
    row.addWidget(help_btn)
    row.addStretch()
    if value is not None:
        theme_manager.apply_style(value, _VALUE_STYLE)
        row.addWidget(value)
    group = QWidget()
    group.setObjectName(object_name)
    layout = QVBoxLayout(group)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addLayout(row)
    layout.addWidget(control)
    return group


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
            theme_manager.apply_style(caption, CAPTION_STYLE)
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
        theme_manager.apply_style(self._note, _NOTE_STYLE)
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

    def values(self) -> dict[str, Any]:
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


_NEIGHBORS_HELP = (
    "Higher values (e.g., 30-50) preserve more global structure. Lower values (e.g., 5-15) "
    "focus on finer local clusters."
)
_MIN_DIST_HELP = (
    "Controls how tightly UMAP packs points together. \n\nLower values (0.0 - 0.1) pack "
    "points densely, useful for identifying highly similar cell subtypes or resolving rare "
    "populations. \n\nHigher values (0.3 - 0.5) spread points out, preserving broader "
    "topological relationships across major cell lineages (e.g. T-cells vs B-cells)."
)
_METRIC_HELP = (
    "The mathematical method used to measure distance between cells in high-dimensional "
    "space.\n\n• Euclidean: Straight-line distance (default, good for general use)\n• Cosine: "
    "Measures angle instead of magnitude (good when absolute fluorescence intensity varies "
    "due to staining artifacts)\n• Manhattan: Grid-like distance (more robust to outliers)"
)
_HDBSCAN_HELP = (
    "Automatically clusters the high-dimensional biological data (not the 2D plot), "
    "producing statistically robust populations that you can use as downstream gates. Does "
    "not rely on the UMAP projection."
)
_MIN_CLUSTER_HELP = (
    "The minimum number of cells required to form a cluster. Larger values will merge "
    "smaller groups into bigger populations or label them as noise. Smaller values will "
    "detect rarer populations but may over-segment."
)


def _slider(object_name: str, low: int, high: int, value: int, tip: str) -> QSlider:
    slider = QSlider(Qt.Orientation.Horizontal)
    slider.setObjectName(object_name)
    slider.setRange(low, high)
    slider.setValue(value)
    slider.setToolTip(tip)
    return slider


class UmapParamsPanel(QWidget):
    """Neighbours, minimum distance, metric, and the optional HDBSCAN clustering."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("UmapParams")
        self._read_only = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        self._neighbors_value = QLabel("15")
        self._neighbors = _slider(
            "UmapNeighborsSlider",
            5,
            50,
            15,
            "Higher = more global structure. Lower = finer local clusters.",
        )
        self._neighbors.valueChanged.connect(lambda v: self._neighbors_value.setText(str(v)))
        layout.addWidget(
            param_group(
                "Neighbors:",
                _NEIGHBORS_HELP,
                self._neighbors,
                object_name="UmapNeighborsGroup",
                value=self._neighbors_value,
            )
        )

        self._min_dist_value = QLabel("0.10")
        self._min_dist = _slider(  # hundredths: 0.01 to 0.50
            "UmapMinDistSlider", 1, 50, 10, "Lower = tighter packed islands."
        )
        self._min_dist.valueChanged.connect(
            lambda v: self._min_dist_value.setText(f"{v / 100:.2f}")
        )
        layout.addWidget(
            param_group(
                "Min Distance:",
                _MIN_DIST_HELP,
                self._min_dist,
                object_name="UmapMinDistGroup",
                help_title="Minimum Distance",
                value=self._min_dist_value,
            )
        )

        self._metric = BioComboBox()
        self._metric.setObjectName("UmapMetricCombo")
        self._metric.addItems(["euclidean", "cosine", "manhattan"])
        layout.addWidget(
            param_group(
                "Distance Metric:", _METRIC_HELP, self._metric, object_name="UmapMetricGroup"
            )
        )

        layout.addWidget(BioSectionLabel("Clustering"))
        self._hdbscan = QCheckBox("Run HDBSCAN Auto-Clustering")
        self._hdbscan.setObjectName("UmapHdbscanCheckbox")
        self._hdbscan.setStyleSheet(checkbox_qss())
        self._hdbscan.setToolTip("Perform automatic density-based clustering.")
        self._hdbscan.toggled.connect(self._on_hdbscan_toggled)
        layout.addWidget(
            _help_row(self._hdbscan, _HDBSCAN_HELP, "HDBSCAN Auto-Clustering", "UmapHdbscanGroup")
        )

        # The spin box's prefix already reads "Min Cluster Size: 100", so its row
        # only adds the help button (and is the parameter's spotlight target).
        self._min_cluster_size = BioSpinBox()
        self._min_cluster_size.setObjectName("UmapMinClusterSizeBox")
        self._min_cluster_size.setRange(2, 500)
        self._min_cluster_size.setValue(100)
        self._min_cluster_size.setPrefix("Min Cluster Size: ")
        self._min_cluster_row = _help_row(
            self._min_cluster_size, _MIN_CLUSTER_HELP, "Minimum Cluster Size", "UmapMinClusterGroup"
        )
        self._min_cluster_row.setVisible(False)
        layout.addWidget(self._min_cluster_row)

    @property
    def hdbscan_enabled(self) -> bool:
        return self._hdbscan.isChecked()

    def values(self) -> dict[str, Any]:
        return {
            "n_neighbors": self._neighbors.value(),
            "min_dist": self._min_dist.value() / 100.0,
            "metric": self._metric.currentText(),
            "run_hdbscan": self._hdbscan.isChecked(),
            "min_cluster_size": self._min_cluster_size.value(),
        }

    def show_run(self, run: dict[str, Any]) -> None:
        if "n_neighbors" in run:
            self._neighbors.setValue(run["n_neighbors"])
        if "min_dist" in run:
            self._min_dist.setValue(int(run["min_dist"] * 100))
        if (index := self._metric.findText(run.get("metric", ""))) >= 0:
            self._metric.setCurrentIndex(index)
        # Runs saved before "run_hdbscan" was stored ran it when they have clusters.
        self._hdbscan.blockSignals(True)
        self._hdbscan.setChecked(bool(run.get("run_hdbscan", "clusters" in run)))
        self._hdbscan.blockSignals(False)
        self._min_cluster_row.setVisible(self._hdbscan.isChecked())
        if "min_cluster_size" in run:
            self._min_cluster_size.setValue(int(run["min_cluster_size"]))

    def set_read_only(self, read_only: bool) -> None:
        # The checkbox stays enabled (macOS draws a disabled one blank whatever its
        # state); _on_hdbscan_toggled reverts clicks instead.
        self._read_only = read_only
        for control in (self._neighbors, self._min_dist, self._metric, self._min_cluster_size):
            control.setEnabled(not read_only)
        self._min_cluster_row.setVisible(self._hdbscan.isChecked())

    def _on_hdbscan_toggled(self, checked: bool) -> None:
        if self._read_only:
            self._hdbscan.blockSignals(True)
            self._hdbscan.setChecked(not checked)
            self._hdbscan.blockSignals(False)
            return
        self._min_cluster_row.setVisible(checked)

    def _apply_theme_styles(self) -> None:
        self._hdbscan.setStyleSheet(checkbox_qss())
