"""Tests for the Properties panel's "Missing dye" choice on FMO controls."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest
from PyQt6.QtWidgets import QComboBox

from karcytics_plugins.flow_cytometry.analysis.experiment import Sample, SampleRole
from karcytics_plugins.flow_cytometry.analysis.fcs_io import FCSData
from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.ui.widgets.properties_panel import PropertiesPanel

pytestmark = pytest.mark.ui

CHANNELS = ["FSC-A", "FITC-A", "PE-A"]


@pytest.fixture
def state():
    state = FlowState()
    sample = Sample(sample_id="fmo", display_name="Tube 3")
    sample.role = SampleRole.FMO_CONTROL
    sample.fcs_data = FCSData(
        file_path=Path("tube3.fcs"),
        channels=list(CHANNELS),
        markers=["", "CD4", "CD8"],
        events=pd.DataFrame({ch: [1.0, 2.0] for ch in CHANNELS}),
    )
    state.data.experiment.samples["fmo"] = sample
    return state


@pytest.fixture
def panel(qtbot, state):
    panel = PropertiesPanel(state, MagicMock(), MagicMock(), MagicMock())
    qtbot.addWidget(panel)
    panel._show_sample_details(state.data.experiment.samples["fmo"])
    return panel


def _combo(panel) -> QComboBox:
    # The newest: a rebuilt panel's old widgets linger until the event loop runs.
    return panel.findChildren(QComboBox, "FmoMinusCombo")[-1]


def test_missing_dye_lists_the_fluorescence_channels_and_starts_on_auto(panel):
    combo = _combo(panel)

    assert [combo.itemData(i) for i in range(combo.count())] == [None, "FITC-A", "PE-A"]
    assert combo.itemText(1) == "CD4 (FITC-A)"
    assert combo.currentData() is None


def test_choosing_a_dye_records_it_and_auto_clears_it(panel, state):
    sample = state.data.experiment.samples["fmo"]
    combo = _combo(panel)

    combo.setCurrentIndex(2)
    assert sample.fmo_minus == "PE-A"

    combo.setCurrentIndex(0)
    assert sample.fmo_minus is None


def test_a_templates_marker_name_is_shown_as_its_channel(panel, state):
    sample = state.data.experiment.samples["fmo"]
    sample.fmo_minus = "CD8"

    panel._show_sample_details(sample)

    assert _combo(panel).currentData() == "PE-A"


def test_a_dye_found_from_the_data_is_shown_as_the_choice(panel, state):
    sample = state.data.experiment.samples["fmo"]
    sample.fmo_minus, sample.fmo_minus_detected = "FITC-A", True

    panel._show_sample_details(sample)

    assert _combo(panel).currentData() == "FITC-A"
    assert _combo(panel).itemText(0) == "Detect again"


def test_the_choice_is_only_offered_for_fmo_controls(panel, state):
    sample = state.data.experiment.samples["fmo"]
    sample.role = SampleRole.FULL_PANEL
    panel.show()

    panel._show_sample_details(sample)

    assert not _combo(panel).isVisible()
