"""A re-read sample is compensated again only if it was compensated before."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from karcytics_plugins.flow_cytometry.analysis.compensation import CompensationMatrix
from karcytics_plugins.flow_cytometry.analysis.experiment import Sample
from karcytics_plugins.flow_cytometry.analysis.fcs_io import FCSData

MATRIX = CompensationMatrix(np.array([[1.0, 0.5], [0.0, 1.0]]), ["FITC-A", "PE-A"])


def fresh_data():
    events = pd.DataFrame({"FSC-A": [10.0], "FITC-A": [100.0], "PE-A": [150.0]})
    return FCSData(file_path=Path("s.fcs"), channels=list(events.columns), events=events)


@pytest.mark.parametrize("was_compensated", [True, False])
def test_reloaded_data_is_compensated_only_if_the_sample_was(was_compensated):
    sample = Sample(sample_id="s", display_name="s", is_compensated=was_compensated)
    data = fresh_data()

    sample.adopt_reloaded_data(data, MATRIX)

    assert sample.fcs_data is data
    assert data.is_compensated is was_compensated
    # PE-A carries half of FITC's signal; compensation takes it back out.
    assert data.events["PE-A"].iloc[0] == pytest.approx(100.0 if was_compensated else 150.0)
    assert data.events["FSC-A"].iloc[0] == 10.0


def test_data_compensated_in_the_file_is_left_alone():
    sample = Sample(sample_id="s", display_name="s", is_compensated=True)
    data = fresh_data()
    data.is_compensated = True

    sample.adopt_reloaded_data(data, MATRIX)

    assert data.events["PE-A"].iloc[0] == 150.0
