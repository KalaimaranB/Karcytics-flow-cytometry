"""The Compensation tab's ON / OFF switch: the matrix in use on every sample, or none.

ON is the same as Apply to all samples, so turning it on calls back into the
view that owns that action. OFF takes compensation off every sample through
``experiment_edits.toggle_compensation`` (undoable) and emits ``turned_off`` so
the view can refresh. Either way ``announced`` carries a sentence for the
view's note line.
"""

from __future__ import annotations

from collections.abc import Callable

from karcytics_sdk.plugin.components import BioToggleButton
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QWidget

from karcytics_plugins.flow_cytometry.analysis.services import experiment_edits
from karcytics_plugins.flow_cytometry.analysis.state import FlowState

ON_TEXT = "Compensation: ON ✦"
OFF_TEXT = "Compensation: OFF"


def compensation_on(state: FlowState) -> bool:
    """Every loaded sample's data is compensated: what the switch shows as ON."""
    data = [s.fcs_data for s in state.data.experiment.samples.values() if s.fcs_data]
    return bool(data) and all(fcs.is_compensated for fcs in data)


class CompensationSwitch(QWidget):
    """A switch showing whether compensation is on, which turns it on or off when clicked."""

    turned_off = Signal()
    announced = Signal(str)

    def __init__(
        self, state: FlowState, apply_all: Callable[[], None], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("CompensationSwitch")
        self._state = state
        self._apply_all = apply_all
        self.button = BioToggleButton(OFF_TEXT)
        self.button.setToolTip(
            "Turn compensation on or off for every sample. Off shows the raw data in every"
            " plot and statistic; on applies the matrix in use."
        )
        self.button.clicked.connect(self._on_click)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.button)

    def sync(self) -> None:
        """Show the samples' current state; disabled while there's no matrix to apply."""
        on = compensation_on(self._state)
        self.button.setChecked(on)
        self.button.setText(ON_TEXT if on else OFF_TEXT)
        self.button.setEnabled(self._state.data.compensation is not None)

    def _on_click(self) -> None:
        if not compensation_on(self._state):
            self._apply_all()  # the view refreshes and announces the change itself
            self.announced.emit("Compensation ON: every sample uses the matrix in use.")
            return
        toggled, _state = experiment_edits.toggle_compensation(self._state)
        self.announced.emit(
            f"Compensation OFF: {toggled} sample(s) show their raw data. Turn it back on"
            " before you analyse."
        )
        self.turned_off.emit()
