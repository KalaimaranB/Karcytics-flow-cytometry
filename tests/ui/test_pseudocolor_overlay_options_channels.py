"""Tests for `PseudocolorOverlayOptionsPanel.populate_channels`'s axis-combo
repopulation, migrated to the shared `repopulate_combo` helper
(SDK_Abstraction_Performance_Plan.md Priority 1 UI #4).

Behavior preserved from the hand-rolled blockSignals/clear/addItem dance:
X defaults to index 0, Y defaults to index 1, and a still-valid prior
selection is restored for either axis after the channel list changes.
"""

import pytest

from karcytics_plugins.flow_cytometry.ui.widgets.comparisons.options.pseudocolor_overlay_options import (
    PseudocolorOverlayOptionsPanel,
)


@pytest.fixture
def panel(qtbot):
    widget = PseudocolorOverlayOptionsPanel()
    qtbot.addWidget(widget)
    return widget


@pytest.mark.ui
def test_populate_channels_defaults_x_to_first_and_y_to_second(panel):
    panel.populate_channels([("FSC-A", "fsc"), ("SSC-A", "ssc"), ("FITC-A", "fitc")])

    assert panel._x_combo.currentData() == "fsc"
    assert panel._y_combo.currentData() == "ssc"


@pytest.mark.ui
def test_populate_channels_restores_a_still_valid_prior_selection(panel):
    panel.populate_channels([("FSC-A", "fsc"), ("SSC-A", "ssc"), ("FITC-A", "fitc")])
    panel._x_combo.setCurrentIndex(2)  # "fitc"

    panel.populate_channels([("FSC-A", "fsc"), ("SSC-A", "ssc"), ("FITC-A (renamed)", "fitc")])

    assert panel._x_combo.currentData() == "fitc"
    assert panel._x_combo.currentText() == "FITC-A (renamed)"


@pytest.mark.ui
def test_populate_channels_falls_back_to_default_when_prior_selection_gone(panel):
    panel.populate_channels([("FSC-A", "fsc"), ("SSC-A", "ssc"), ("FITC-A", "fitc")])
    panel._y_combo.setCurrentIndex(2)  # "fitc"

    panel.populate_channels([("FSC-A", "fsc"), ("SSC-A", "ssc")])  # "fitc" gone

    assert panel._y_combo.currentData() == "ssc"  # default index 1


@pytest.mark.ui
def test_populate_channels_does_not_emit_signals_while_rebuilding(panel):
    panel.populate_channels([("FSC-A", "fsc"), ("SSC-A", "ssc")])

    fired = []
    panel._x_combo.currentIndexChanged.connect(lambda idx: fired.append(idx))
    panel._y_combo.currentIndexChanged.connect(lambda idx: fired.append(idx))

    panel.populate_channels([("FSC-A", "fsc"), ("SSC-A", "ssc"), ("FITC-A", "fitc")])

    assert fired == []
