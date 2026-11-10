"""The tab's left sidebar: what to split, how, and when to stop.

It only holds the user's choices. The tab fills its lists from the
experiment and reads the choices back as a ``StepRequest``.
"""

from __future__ import annotations

from typing import Any

from karcytics_sdk.plugin.components import (
    BioComboBox,
    BioDoubleSpinBox,
    BioListWidget,
    BioScrollArea,
    BioSpinBox,
    PrimaryButton,
    SecondaryButton,
    repopulate_combo,
)
from karcytics_sdk.plugin.theme_fallback import theme_manager
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QCheckBox, QFormLayout, QListWidgetItem, QVBoxLayout, QWidget

from ....analysis.autogate import StepRequest, method
from ..panel_style import section_header
from .method_picker import MethodPicker

SIDEBAR_WIDTH = 300
CHANNEL_LIST_HEIGHT = 130


class SetupSidebar(QWidget):
    group_changed = Signal()
    sample_changed = Signal()
    choices_changed = Signal()  # anything that changes what a proposal would be
    propose_clicked = Signal()
    run_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("auto_gate_sidebar")
        self.setFixedWidth(SIDEBAR_WIDTH)
        theme_manager.apply_style(
            self,
            "QWidget#auto_gate_sidebar { background: {BG_DARKEST}; border-right: 1px solid {BORDER}; }",
        )
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = BioScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        self._add_inputs(layout)
        self._add_method(layout)
        self._add_rules(layout)
        self._add_buttons(layout)
        layout.addStretch()
        scroll.setWidget(content)
        outer.addWidget(scroll)
        self._on_method_changed(self._methods.method_key())

    def _add_inputs(self, layout: QVBoxLayout) -> None:
        layout.addWidget(
            section_header("Group", "Accepted gates are added to every sample in this group.")
        )
        self._group = self._combo("AutoGateGroupCombo", self.group_changed)
        layout.addWidget(self._group)
        layout.addWidget(
            section_header(
                "Reference sample",
                "Splits are found on this sample, then the same gates go to the rest of the group.",
            )
        )
        self._sample = self._combo("AutoGateSampleCombo", self.sample_changed)
        layout.addWidget(self._sample)
        layout.addWidget(
            section_header(
                "Start from population",
                "The population to split. Usually your last clean-up gate (e.g. Live singlets): "
                "debris and dead cells would otherwise be split off as populations of their own.",
            )
        )
        self._population = self._combo("AutoGatePopulationCombo", self.choices_changed)
        layout.addWidget(self._population)
        layout.addWidget(section_header("Channels", "The markers the split may use."))
        self._channels = BioListWidget()
        self._channels.setObjectName("AutoGateChannels")
        self._channels.setFixedHeight(CHANNEL_LIST_HEIGHT)
        self._channels.itemChanged.connect(lambda _item: self.choices_changed.emit())
        layout.addWidget(self._channels)

    def _add_method(self, layout: QVBoxLayout) -> None:
        layout.addSpacing(8)
        layout.addWidget(
            section_header(
                "Method",
                "All three make ordinary gates and record why. They differ only in how the view "
                "to split is chosen: by you, by searching marker pairs, or by PCA.",
            )
        )
        self._methods = MethodPicker()
        self._methods.method_changed.connect(self._on_method_changed)
        layout.addWidget(self._methods)
        self._cells_first = QCheckBox("Cells and singlets first")
        self._cells_first.setObjectName("AutoGateCellsFirst")
        self._cells_first.setChecked(StepRequest.cells_first)
        self._cells_first.setToolTip(
            "By convention, before any marker: from All Events the cells gate (debris cut off "
            "below the forward-scatter valley), then from it the singlets gate (doublets left out "
            "by forward-scatter area against height). Then the method searches the markers."
        )
        self._cells_first.toggled.connect(lambda _on: self.choices_changed.emit())
        layout.addWidget(self._cells_first)

        self._axes = QWidget()
        axes_form = QFormLayout(self._axes)
        axes_form.setContentsMargins(0, 4, 0, 0)
        self._x_axis = self._combo("AutoGateXAxis", self.choices_changed)
        self._y_axis = self._combo("AutoGateYAxis", self.choices_changed)
        axes_form.addRow("X axis", self._x_axis)
        axes_form.addRow("Y axis", self._y_axis)
        layout.addWidget(self._axes)

    def _add_rules(self, layout: QVBoxLayout) -> None:
        layout.addSpacing(8)
        layout.addWidget(
            section_header(
                "Stopping rules", "When run to the end, splitting stops at any of these."
            )
        )
        rules = QFormLayout()
        self._min_events = BioSpinBox()
        self._min_events.setRange(50, 100_000)
        self._min_events.setSingleStep(50)
        self._min_events.setValue(500)
        self._min_events.setSuffix(" events")
        self._max_depth = BioSpinBox()
        self._max_depth.setRange(1, 8)
        self._max_depth.setValue(4)
        self._min_valley = BioDoubleSpinBox()
        self._min_valley.setRange(0.1, 0.95)
        self._min_valley.setSingleStep(0.05)
        self._min_valley.setValue(StepRequest.min_valley)
        self._min_valley.setToolTip(
            "How empty the gap between two peaks must be to split there (1 = no events between them)."
        )
        self._min_events.valueChanged.connect(lambda _v: self.choices_changed.emit())
        self._min_valley.valueChanged.connect(lambda _v: self.choices_changed.emit())
        rules.addRow("Smallest population", self._min_events)
        rules.addRow("Deepest level", self._max_depth)
        rules.addRow("Clear valley at least", self._min_valley)
        layout.addLayout(rules)

    def _add_buttons(self, layout: QVBoxLayout) -> None:
        layout.addSpacing(8)
        self._propose = PrimaryButton("Propose next split")
        self._propose.setObjectName("AutoGateProposeButton")
        self._propose.clicked.connect(self.propose_clicked)
        self._run = SecondaryButton("Run to the stopping rules")
        self._run.setObjectName("AutoGateRunButton")
        self._run.clicked.connect(self.run_clicked)
        self._run.setEnabled(False)
        self._run.setToolTip(
            "Coming next: proposes and accepts splits until a stopping rule is met."
        )
        layout.addWidget(self._propose)
        layout.addWidget(self._run)

    @staticmethod
    def _combo(name: str, signal: Any) -> BioComboBox:
        combo = BioComboBox()
        combo.setObjectName(name)
        combo.currentIndexChanged.connect(lambda _i: signal.emit())
        return combo

    def _on_method_changed(self, key: str) -> None:
        self._axes.setVisible(method(key).user_picks_axes)
        self.choices_changed.emit()

    # ── Filled by the tab ─────────────────────────────────────────────

    def set_groups(self, items: list[tuple[str, Any]]) -> None:
        repopulate_combo(self._group, items, restore_data=self._group.currentData())

    def set_samples(self, items: list[tuple[str, Any]]) -> None:
        repopulate_combo(self._sample, items, restore_data=self._sample.currentData())

    def set_populations(self, items: list[tuple[str, Any]]) -> None:
        repopulate_combo(self._population, items, restore_data=self._population.currentData())

    def set_channels(
        self, channels: list[tuple[str, str]], start_unticked: frozenset[str] = frozenset()
    ) -> None:
        """Show (label, channel) pairs, keeping the user's ticks.

        A channel shown for the first time starts ticked, unless it is in
        ``start_unticked`` (scatter: there for the cells split, kept out of marker splits).
        """
        shown = {
            self._channels.item(i).data(Qt.ItemDataRole.UserRole): self._channels.item(
                i
            ).checkState()
            for i in range(self._channels.count())
        }
        self._channels.blockSignals(True)
        self._channels.clear()
        for label, channel in channels:
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, channel)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            first = Qt.CheckState.Unchecked if channel in start_unticked else Qt.CheckState.Checked
            item.setCheckState(shown.get(channel, first))
            self._channels.addItem(item)
        self._channels.blockSignals(False)
        x, y = self._x_axis.currentData(), self._y_axis.currentData()
        repopulate_combo(self._x_axis, channels, restore_data=x)
        repopulate_combo(self._y_axis, channels, restore_data=y)
        if x is None and y is None:  # first fill: FSC-A × SSC-A, the usual first split
            keys = [ch for _label, ch in channels]
            for combo, preferred, fallback in (
                (self._x_axis, "FSC-A", 0),
                (self._y_axis, "SSC-A", 1),
            ):
                index = combo.findData(preferred)
                combo.setCurrentIndex(index if index >= 0 else min(fallback, len(keys) - 1))

    def set_population(self, node_id: str | None) -> None:
        index = self._population.findData(node_id)
        if index >= 0:
            self._population.setCurrentIndex(index)

    # ── Read by the tab ───────────────────────────────────────────────

    def group_id(self) -> Any:
        return self._group.currentData()

    def sample_id(self) -> Any:
        return self._sample.currentData()

    def sample_name(self) -> str:
        return self._sample.currentText()

    def population(self) -> tuple[Any, str]:
        """(node id, name) of the population to split."""
        return self._population.currentData(), self._population.currentText().strip()

    def channels(self) -> tuple[str, ...]:
        """The ticked channels' keys."""
        return tuple(
            self._channels.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self._channels.count())
            if self._channels.item(i).checkState() == Qt.CheckState.Checked
        )

    def method_key(self) -> str:
        return self._methods.method_key()

    def set_method(self, key: str) -> None:
        self._methods.set_method(key)

    def axes(self) -> tuple[str, str]:
        """The density-valley axes' channel keys."""
        return self._x_axis.currentData() or "", self._y_axis.currentData() or ""

    def cells_first(self) -> bool:
        return self._cells_first.isChecked()

    def stopping_rules(self) -> tuple[int, float]:
        """(smallest population in events, clearest valley needed)."""
        return self._min_events.value(), self._min_valley.value()
