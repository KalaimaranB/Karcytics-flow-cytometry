"""The Population Analysis run's setup: method, data, and settings.

The sidebar form above the Run button. It reads the chosen sample, population,
channels and settings into the run's parameters (`request`), shows a stored
run's settings read-only (`show_run`), and tells the viewer when the target
population or the method changes.
"""

from __future__ import annotations

from typing import Any

from karcytics_sdk.plugin import BioSectionLabel
from karcytics_sdk.plugin.components import (
    BioComboBox,
    BioLineEdit,
    BioListWidget,
    repopulate_combo,
)
from karcytics_sdk.plugin.theme_fallback import theme_manager
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import QLabel, QListWidgetItem, QSlider, QVBoxLayout, QWidget

from ...analysis.clustering import (
    FLOWSOM,
    METHODS,
    PHENOGRAPH,
    UMAP_HDBSCAN,
    ClusteringMethod,
    method_of,
)
from ...analysis.fcs_io import get_channel_marker_label, get_fluorescence_channels
from ...analysis.population_service import population_events
from ...analysis.state import FlowState
from ..services.umap_service import FlowsomParams, PhenographParams, UmapParams
from .method_params import (
    CAPTION_STYLE,
    FlowsomParamsPanel,
    PhenographParamsPanel,
    UmapParamsPanel,
    param_group,
)

RunParams = UmapParams | FlowsomParams | PhenographParams

_MIN_SUBSAMPLE = 50  # a run never uses fewer events than this, when there are more

_ALGORITHM_HELP = (
    "UMAP + HDBSCAN: UMAP draws every cell on a 2-D map where similar cells sit "
    "together; HDBSCAN (optional) then finds dense groups and can leave scattered "
    "cells out as noise.\n\nFlowSOM: sorts the cells into about 100 small groups "
    "(nodes), links similar nodes into a tree, and groups the nodes into k "
    "populations (metaclusters). Every cell gets a population. Fast enough for all "
    "events, and a useful second opinion next to UMAP + HDBSCAN.\n\nPhenoGraph: "
    "links each cell to its most similar cells, then finds groups of cells that link "
    "mostly to each other. You set a resolution, not a number of clusters; it shows "
    "which clusters are linked (one population split) and which stand apart."
)
_SAMPLE_HELP = (
    "Select the flow cytometry sample to run the analysis on. UMAP will reduce the "
    "dimensionality of the single-cell events within this sample."
)
_GATE_HELP = (
    "Select a specific gated population to run the analysis on. It is highly recommended to "
    "run UMAP on pre-gated populations (e.g. Live, Singlets) to exclude debris and dead cells "
    "which can negatively distort the projection."
)
_CHANNELS_HELP = (
    "Select the fluorescence parameters to include in the dimensionality reduction. You "
    "should UNCHECK channels that were already used for gating upstream (like Viability/"
    "Live-Dead dyes or Scatter parameters) as they do not provide useful variance for "
    "sub-population clustering."
)
_EVENTS_HELP = (
    "The share of the population's events the run uses, picked at random.\n\n"
    "UMAP slows down sharply on large data: 10-20% is typical and keeps the "
    "structure.\n\nFlowSOM and PhenoGraph are fast enough for all events, their "
    "default. Lower it to compare with a UMAP run on the same share of events."
)
_SEED_HELP = (
    "Fixes the random choices a run makes: which events are picked when using fewer "
    "than all of them, UMAP's starting layout, FlowSOM's starting nodes and "
    "PhenoGraph's neighbour search and grouping. The same "
    "seed on the same data gives the same result; another seed gives another valid "
    "result, a quick way to check a finding isn't a fluke."
)


class ClusteringSetup(QWidget):
    """Method, sample, population, channels, run name, events used, seed and settings."""

    target_changed = Signal()  # another sample or population was chosen
    method_changed = Signal()

    def __init__(self, state: FlowState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = state
        self._total_events = 0  # in the chosen population
        self._read_only = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        self._add_target_section(layout)
        self._add_configuration_section(layout)

    def _add_target_section(self, layout: QVBoxLayout) -> None:
        """Algorithm, sample, population and channels."""
        layout.addWidget(BioSectionLabel("Target Data"))
        self._algo_combo = BioComboBox()
        self._algo_combo.setObjectName("ClusteringMethodCombo")
        for method in (UMAP_HDBSCAN, FLOWSOM, PHENOGRAPH):
            self._algo_combo.addItem(method.name, method.key)
        self._algo_combo.currentIndexChanged.connect(self._on_method_changed)
        layout.addWidget(param_group("Algorithm:", _ALGORITHM_HELP, self._algo_combo))

        self._sample_combo = BioComboBox()
        self._sample_combo.setObjectName("UmapSampleCombo")
        self._sample_combo.currentIndexChanged.connect(self._on_sample_combo_changed)
        layout.addWidget(param_group("Sample:", _SAMPLE_HELP, self._sample_combo))

        self._gate_combo = BioComboBox()
        self._gate_combo.setObjectName("UmapGateCombo")
        self._gate_combo.currentIndexChanged.connect(self._on_gate_combo_changed)
        layout.addWidget(param_group("Population (Gate):", _GATE_HELP, self._gate_combo))

        self._channel_list = BioListWidget()
        self._channel_list.setObjectName("UmapChannelList")
        self._channel_list.setMaximumHeight(150)
        layout.addWidget(
            param_group(
                "Select Channels:", _CHANNELS_HELP, self._channel_list, help_title="Channels"
            )
        )
        layout.addSpacing(10)

    def _add_configuration_section(self, layout: QVBoxLayout) -> None:
        """Run name, events used, seed, and the chosen method's own settings."""
        layout.addWidget(BioSectionLabel("Configuration"))
        name_lbl = QLabel("Run Name:")
        theme_manager.apply_style(name_lbl, CAPTION_STYLE)
        layout.addWidget(name_lbl)
        self._run_name_input = BioLineEdit("")
        self._run_name_input.setObjectName("UmapRunNameInput")
        self._run_name_input.setPlaceholderText("e.g., Global Overview")
        layout.addWidget(self._run_name_input)

        self._n_events_title_lbl = QLabel("Events used: 10% (0 events)")
        self._n_events_title_lbl.setToolTip(
            "Randomly downsample the input events before running analysis."
        )
        self._n_events_slider = QSlider(Qt.Orientation.Horizontal)
        self._n_events_slider.setObjectName("UmapSubsampleSlider")
        self._n_events_slider.setRange(1, 100)
        self._n_events_slider.setValue(10)
        self._n_events_slider.setToolTip("Percentage of events to subsample. Max is all events.")
        self._n_events_slider.valueChanged.connect(self._on_subsample_changed)
        theme_manager.apply_style(self._n_events_title_lbl, CAPTION_STYLE)
        layout.addWidget(
            param_group(
                self._n_events_title_lbl,
                _EVENTS_HELP,
                self._n_events_slider,
                object_name="UmapSubsampleGroup",
                help_title="Events used",
            )
        )

        self._seed_input = BioLineEdit("42")
        self._seed_input.setObjectName("UmapSeedInput")
        self._seed_input.setValidator(QIntValidator(0, 999999))
        layout.addWidget(
            param_group("Random Seed:", _SEED_HELP, self._seed_input, object_name="UmapSeedGroup")
        )
        layout.addSpacing(10)

        self._umap_params = UmapParamsPanel()
        self._flowsom_params = FlowsomParamsPanel(BioSectionLabel("FlowSOM"))
        self._flowsom_params.hide()
        self._phenograph_params = PhenographParamsPanel(BioSectionLabel("PhenoGraph"))
        self._phenograph_params.hide()
        layout.addWidget(self._umap_params)
        layout.addWidget(self._flowsom_params)
        layout.addWidget(self._phenograph_params)

    # ── What is chosen ─────────────────────────────────────────────────

    @property
    def sample_id(self) -> str | None:
        return self._sample_combo.currentData()

    @property
    def gate_id(self) -> str | None:
        return self._gate_combo.currentData()

    @property
    def method(self) -> ClusteringMethod:
        return METHODS.get(self._algo_combo.currentData(), UMAP_HDBSCAN)

    def academy_fields(self) -> dict[str, Any]:
        """This form's half of the viewer's PopulationAnalysisSnapshot."""
        items = filter(None, map(self._channel_list.item, range(self._channel_list.count())))
        checked = Qt.CheckState.Checked
        return {
            "sample_label": self._sample_combo.currentText(),
            "gate_label": self._gate_combo.currentText(),
            "channel_checks": {
                i.data(Qt.ItemDataRole.UserRole) or "": i.checkState() == checked for i in items
            },
            "run_name": self._run_name_input.text(),
            "subsample_percent": self._n_events_slider.value(),
            "hdbscan_enabled": self._umap_params.hdbscan_enabled,
            "method_key": self._algo_combo.currentData(),
        }

    def request(self) -> RunParams | None:
        """The run the form describes; None without a sample.

        Raises ValueError, with a message for the user, when it can't run.
        """
        sample_id = self.sample_id
        if not sample_id:
            return None
        channels = [
            item.data(Qt.ItemDataRole.UserRole)
            for item in filter(
                None, map(self._channel_list.item, range(self._channel_list.count()))
            )
            if item.checkState() == Qt.CheckState.Checked
        ]
        if not channels:
            raise ValueError(
                "No channels selected. Please select at least one channel for analysis."
            )
        name = self._run_name_input.text().strip()
        if not name:
            raise ValueError("Please provide a name for this run.")
        total, percent = self._total_events, self._n_events_slider.value()
        n_events = (
            max(_MIN_SUBSAMPLE, int(total * percent / 100)) if total > _MIN_SUBSAMPLE else total
        )
        common: dict[str, Any] = {
            "target_sample_id": sample_id,
            "target_node_id": self.gate_id,
            "name": name,
            "percentage": float(percent),
            "n_events": n_events,
            "random_seed": int(self._seed_input.text() or "42"),
            "channels": channels,
        }
        method = self.method
        if method is FLOWSOM:
            return FlowsomParams(**common, **self._flowsom_params.values())
        if method is PHENOGRAPH:
            return PhenographParams(**common, **self._phenograph_params.values())
        # HDBSCAN clusters the channels themselves, not the 2-D map.
        return UmapParams(**common, hdbscan_space="high_dim", **self._umap_params.values())

    # ── Showing samples and runs ───────────────────────────────────────

    def refresh_samples(self) -> None:
        """Re-lists the experiment's samples and the chosen sample's populations."""
        prev_sample = self.sample_id
        items = [
            (sample.display_name, sample_id)
            for sample_id, sample in self._state.data.experiment.samples.items()
        ]
        target = prev_sample or self._state.view.current_sample_id
        repopulate_combo(self._sample_combo, items, restore_data=target)
        self.refresh_gates()
        current = self.sample_id
        if current and (current != prev_sample or self._channel_list.count() == 0):
            self._list_channels(current)
        if current:
            self._count_events()

    def refresh_gates(self) -> None:
        """Lists every population in the chosen sample's gate tree."""
        prev_gate = self.gate_id
        items: list[tuple[str, str | None]] = [("⬡  All Events (no gate)", None)]
        sample = self._state.data.experiment.samples.get(self.sample_id or "")
        if sample is not None:

            def _add_nodes(node, depth: int = 0) -> None:
                if not node.is_root:
                    icon = "⊘ " if node.negated else "◆ "
                    items.append((f"{'  ' * depth}{icon}{node.name}", node.node_id))
                for child in node.children:
                    # Unwired logic nodes have no population yet (as in the gate tree).
                    if not getattr(child, "is_incomplete", False):
                        _add_nodes(child, depth + (0 if node.is_root else 1))

            _add_nodes(sample.gate_tree)
        repopulate_combo(self._gate_combo, items, restore_data=prev_gate)

    def select(self, sample_id: str, gate_id: str | None) -> None:
        """Picks a sample and population without announcing it."""
        self._pick(self._sample_combo, sample_id)
        self.refresh_gates()
        self._pick(self._gate_combo, gate_id)

    @staticmethod
    def _pick(combo: BioComboBox, value: Any) -> None:
        combo.blockSignals(True)
        if (index := combo.findData(value)) >= 0:
            combo.setCurrentIndex(index)
        combo.blockSignals(False)

    def show_run(self, run: dict[str, Any]) -> None:
        """Shows a stored run's settings, read-only."""
        # Freeze first: on macOS, disabling a QCheckBox after setChecked(True)
        # repaints it unchecked, so values go onto already-disabled widgets.
        self.set_read_only(True)
        method = method_of(run)
        self._pick(self._algo_combo, method.key)
        self._show_method_params()
        self.method_changed.emit()
        if method is FLOWSOM:
            self._flowsom_params.show_run(run)
        elif method is PHENOGRAPH:
            self._phenograph_params.show_run(run)
        else:  # the other methods reuse some key names for their own settings
            self._umap_params.show_run(run)
        if run.get("name"):
            self._run_name_input.setText(run["name"])
        if "percentage" in run:
            self._n_events_slider.setValue(int(run["percentage"]))
        if "random_seed" in run:
            self._seed_input.setText(str(run["random_seed"]))
        if used := run.get("channels", []):
            for item in filter(
                None, map(self._channel_list.item, range(self._channel_list.count()))
            ):
                used_here = item.data(Qt.ItemDataRole.UserRole) in used
                item.setCheckState(Qt.CheckState.Checked if used_here else Qt.CheckState.Unchecked)

    def start_new_run(self) -> None:
        self.set_read_only(False)
        self._run_name_input.setText("")

    def set_read_only(self, read_only: bool) -> None:
        self._read_only = read_only
        for control in (self._algo_combo, self._sample_combo, self._gate_combo):
            control.setEnabled(not read_only)
        self._n_events_slider.setEnabled(not read_only)
        self._run_name_input.setReadOnly(read_only)
        self._seed_input.setReadOnly(read_only)
        self._umap_params.set_read_only(read_only)
        self._flowsom_params.set_read_only(read_only)
        self._phenograph_params.set_read_only(read_only)
        checkable = Qt.ItemFlag.ItemIsUserCheckable
        for item in filter(None, map(self._channel_list.item, range(self._channel_list.count()))):
            item.setFlags(item.flags() & ~checkable if read_only else item.flags() | checkable)

    def set_busy(self, busy: bool) -> None:
        """While a run computes, its target can't change."""
        self._sample_combo.setEnabled(not busy)
        self._gate_combo.setEnabled(not busy)

    # ── Reactions ──────────────────────────────────────────────────────

    def _on_method_changed(self, _index: int) -> None:
        self._show_method_params()
        if not self._read_only:
            # FlowSOM and PhenoGraph are fast enough for every event; UMAP needs a subsample.
            self._n_events_slider.setValue(10 if self.method is UMAP_HDBSCAN else 100)
        self.method_changed.emit()

    def _show_method_params(self) -> None:
        method = self.method
        self._umap_params.setVisible(method is UMAP_HDBSCAN)
        self._flowsom_params.setVisible(method is FLOWSOM)
        self._phenograph_params.setVisible(method is PHENOGRAPH)

    def _on_sample_combo_changed(self, _index: int) -> None:
        self.refresh_gates()
        if self.sample_id:
            self._list_channels(self.sample_id)
            self._count_events()
        self.target_changed.emit()

    def _on_gate_combo_changed(self, _index: int) -> None:
        if self.sample_id:
            self._count_events()
        self.target_changed.emit()

    def _list_channels(self, sample_id: str) -> None:
        """The sample's fluorescence channels, all ticked."""
        self._channel_list.clear()
        sample = self._state.data.experiment.samples.get(sample_id)
        if not sample or sample.fcs_data is None:
            return
        for channel in get_fluorescence_channels(sample.fcs_data):
            item = QListWidgetItem(get_channel_marker_label(sample.fcs_data, channel))
            item.setData(Qt.ItemDataRole.UserRole, channel)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            self._channel_list.addItem(item)

    def _count_events(self) -> None:
        sample = self._state.data.experiment.samples.get(self.sample_id or "")
        gate_id = self.gate_id
        node = sample.gate_tree.find_node_by_id(gate_id) if sample and gate_id else None
        events = population_events(self._state.data.experiment, sample, node)
        self._total_events = len(events) if events is not None else 0
        self._on_subsample_changed(self._n_events_slider.value())

    def _on_subsample_changed(self, value: int) -> None:
        used = int(self._total_events * value / 100)
        self._n_events_title_lbl.setText(f"Events used: {value}% ({used:,} events)")

    def _apply_theme_styles(self) -> None:
        self._umap_params._apply_theme_styles()
