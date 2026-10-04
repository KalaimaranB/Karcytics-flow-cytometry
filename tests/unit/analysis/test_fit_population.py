"""Tests for choosing which events of a control a spillover fit uses."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from karcytics_plugins.flow_cytometry.analysis.experiment import Sample
from karcytics_plugins.flow_cytometry.analysis.fcs_io import FCSData
from karcytics_plugins.flow_cytometry.analysis.fit_population import (
    fit_events,
    population_gates,
    population_rows,
    scatter_gates,
)
from karcytics_plugins.flow_cytometry.analysis.gating.rectangle import RectangleGate

pytestmark = pytest.mark.unit

CHANNELS = ["FSC-A", "SSC-A", "FITC-A"]


@pytest.fixture
def sample():
    raw = pd.DataFrame(
        {
            "FSC-A": [10.0, 50.0, 60.0, 500.0],
            "SSC-A": [5.0, 20.0, 80.0, 30.0],
            "FITC-A": [100.0, 200.0, 300.0, 400.0],
        }
    )
    compensated = raw.assign(**{"FITC-A": raw["FITC-A"] * 0.5})
    sample = Sample(sample_id="s", display_name="Tube")
    sample.fcs_data = FCSData(
        file_path=Path("tube.fcs"), channels=list(CHANNELS), events=compensated, raw_events=raw
    )
    cells = sample.gate_tree.add_child(
        RectangleGate("FSC-A", "SSC-A", x_min=20, x_max=100, y_min=0, y_max=100), "Cells"
    )
    cells.add_child(RectangleGate("SSC-A", x_min=0, x_max=50), "Low SSC")
    cells.add_child(RectangleGate("FITC-A", x_min=0, x_max=250), "FITC low")
    sample.gate_tree.add_child(RectangleGate("FITC-A", x_min=150), "FITC+").add_child(
        RectangleGate("FSC-A", x_min=0), "Scatter under fluorescence"
    )
    return sample


def test_only_gates_on_scatter_all_the_way_up_are_offered(sample):
    assert list(scatter_gates(sample)) == ["Cells", "Cells › Low SSC"]


def test_without_a_gate_every_uncompensated_event_is_used(sample):
    fit = fit_events(sample)

    assert fit.events is sample.fcs_data.raw_events
    assert not fit.gated and fit.describe(None) == "4 — all events"


def test_a_gate_restricts_the_fit_to_its_population_in_raw_values(sample):
    fit = fit_events(sample, "Cells › Low SSC")

    assert fit.gated and fit.total == 4
    # One event: in Cells and low SSC — and its raw FITC, not the compensated value.
    assert fit.events["FITC-A"].tolist() == [200.0]
    assert fit.describe("Cells › Low SSC") == "1 of 4 (in 'Cells › Low SSC')"


def test_a_sample_without_the_gate_is_used_whole_and_says_so(sample):
    fit = fit_events(sample, "Singlets")

    assert not fit.gated and len(fit.events) == 4
    assert fit.describe("Singlets") == "4 — all events: no 'Singlets' gate on this sample"


def test_a_sample_without_data_has_nothing_to_fit():
    assert fit_events(Sample(sample_id="x", display_name="x")) is None


def test_fit_events_keep_their_row_alignment_after_compensation(sample):
    """The gate is evaluated on the working events and applied to the raw ones."""
    fit = fit_events(sample, "Cells")

    np.testing.assert_array_equal(fit.events.index, [1, 2])


def test_any_gate_can_be_looked_at_as_a_population(sample):
    assert list(population_gates(sample)) == [
        "Cells",
        "Cells › Low SSC",
        "Cells › FITC low",
        "FITC+",
        "FITC+ › Scatter under fluorescence",
    ]
    # FITC+ is judged on the working (compensated) events: 150 and 200 pass, of 50/100/150/200.
    assert population_rows(sample, "FITC+").tolist() == [2, 3]
    assert population_rows(sample, "No such gate") is None
    assert population_rows(sample, None) is None
