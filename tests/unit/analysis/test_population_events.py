"""The event-data gateway: population_events, channel_values, uncompensated_events."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from karcytics_plugins.flow_cytometry.analysis.experiment import Experiment, Sample
from karcytics_plugins.flow_cytometry.analysis.fcs_io import FCSData
from karcytics_plugins.flow_cytometry.analysis.gating import RectangleGate
from karcytics_plugins.flow_cytometry.analysis.population_service import (
    channel_values,
    population_events,
    uncompensated_events,
)


@pytest.fixture
def sample():
    events = pd.DataFrame({"FSC-A": [0.5, 2.0, np.inf], "SSC-A": [0.5, 2.0, 0.5]})
    fcs = FCSData(Path("a.fcs"), channels=["FSC-A", "SSC-A"], markers=["", ""], events=events)
    return Sample(sample_id="s1", display_name="S1", fcs_data=fcs)


def test_population_events_applies_every_gate_down_to_the_node(sample):
    gate = RectangleGate("FSC-A", "SSC-A", x_min=0, x_max=1, y_min=0, y_max=1)
    [node] = gate.create_nodes(sample.gate_tree, "Small")

    assert list(population_events(Experiment(), sample, node)["FSC-A"]) == [0.5]
    assert len(population_events(Experiment(), sample)) == 3


def test_population_events_without_data():
    assert population_events(Experiment(), None) is None
    assert population_events(Experiment(), Sample(sample_id="s", display_name="S")) is None


def test_channel_values_are_float_and_none_for_a_missing_channel(sample):
    values = channel_values(Experiment(), sample, "SSC-A")
    assert values.dtype == np.float64
    assert values.tolist() == [0.5, 2.0, 0.5]
    assert channel_values(Experiment(), sample, "APC-A") is None


def test_uncompensated_events_prefer_raw_and_fall_back_to_events(sample):
    assert uncompensated_events(sample) is sample.fcs_data.events
    raw = sample.fcs_data.events * 2
    sample.fcs_data.raw_events = raw
    assert uncompensated_events(sample) is raw
    assert uncompensated_events(None) is None
