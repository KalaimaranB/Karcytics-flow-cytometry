import numpy as np
import pandas as pd

from karcytics_plugins.flow_cytometry.analysis.compensation import CompensationMatrix


def test_compensation_matrix_init():
    detectors = ["FITC-A", "PE-A", "APC-A"]
    matrix = np.eye(3)
    comp = CompensationMatrix(matrix=matrix, channel_names=detectors)

    assert comp.channel_names == detectors
    assert comp.matrix.shape == (3, 3)
    assert comp.inverse.shape == (3, 3)


def test_calculate_spillover_matrix():
    from pathlib import Path

    from karcytics_plugins.flow_cytometry.analysis.compensation import (
        calculate_spillover_matrix,
    )

    class MockFCS:
        def __init__(self, events):
            self.events = events
            self.file_path = Path("mock.fcs")

    # FITC Single stain: high FITC, slight spillover into PE (10%)
    ss_fitc = MockFCS(
        pd.DataFrame({"FITC-A": [10000.0, 10000.0, 10000.0], "PE-A": [1000.0, 1000.0, 1000.0]})
    )

    # PE Single stain: high PE, slight spillover into FITC (5%)
    ss_pe = MockFCS(
        pd.DataFrame({"FITC-A": [500.0, 500.0, 500.0], "PE-A": [10000.0, 10000.0, 10000.0]})
    )

    comp = calculate_spillover_matrix(
        single_stains=[ss_fitc, ss_pe],
        unstained=None,
        fluorescence_channels=["FITC-A", "PE-A"],
    )

    assert comp.channel_names == ["FITC-A", "PE-A"]
    # FITC row: FITC=1.0, PE=0.1
    # PE row: FITC=0.05, PE=1.0
    expected_matrix = np.array([[1.0, 0.1], [0.05, 1.0]])
    assert np.allclose(comp.matrix, expected_matrix)
    assert comp.source == "computed"


def test_compensation_apply():
    detectors = ["FITC-A", "PE-A"]
    # 10% spillover from PE to FITC because row @ M^-1 combines columns
    matrix = np.array([[1.0, 0.0], [0.1, 1.0]])
    comp = CompensationMatrix(matrix=matrix, channel_names=detectors)

    class MockFCS:
        def __init__(self, events):
            self.events = events

    events = pd.DataFrame(
        {
            "FITC-A": [100.0, 1000.0],
            "PE-A": [1000.0, 0.0],
            "FSC-A": [50000.0, 50000.0],  # Uncompensated channel
        }
    )

    from karcytics_plugins.flow_cytometry.analysis.compensation import apply_compensation

    comp_events = apply_compensation(MockFCS(events), comp)

    # FITC = Raw_FITC - 0.1 * PE -> 100 - 100 = 0
    assert np.isclose(comp_events["FITC-A"].iloc[0], 0.0)
    assert np.isclose(comp_events["PE-A"].iloc[0], 1000.0)

    # Uncompensated channels pass through unchanged
    assert np.isclose(comp_events["FSC-A"].iloc[0], 50000.0)


def test_parse_spillover():
    from karcytics_plugins.flow_cytometry.analysis.compensation import (
        extract_spill_from_fcs,
    )

    class MockFCSData:
        def __init__(self):
            self.metadata = {"$SPILLOVER": "2,FITC-A,PE-A,1.0,0.0,0.1,1.0"}

    comp = extract_spill_from_fcs(MockFCSData())

    assert comp.channel_names == ["FITC-A", "PE-A"]
    assert np.allclose(comp.matrix, [[1.0, 0.0], [0.1, 1.0]])


def test_compensation_to_dict():
    detectors = ["FITC-A", "PE-A"]
    matrix = np.array([[1.0, 0.0], [0.1, 1.0]])
    comp = CompensationMatrix(matrix=matrix, channel_names=detectors)

    d = comp.to_dict()
    assert d["channel_names"] == detectors
    assert d["matrix"] == matrix.tolist()

    comp2 = CompensationMatrix.from_dict(d)
    assert comp2.channel_names == comp.channel_names
    assert np.allclose(comp2.matrix, comp.matrix)


def _fmo_controls(spillover, channels, missing, noise=0.0):
    from types import SimpleNamespace

    rng = np.random.default_rng(7)
    controls = {}
    for k in missing:
        true = np.abs(rng.normal(1000, 600, (4000, len(channels))))
        true[:, k] = 0.0
        raw = true @ spillover + 50.0 + rng.normal(0, noise, true.shape)  # + autofluorescence
        controls[channels[k]] = SimpleNamespace(
            events=pd.DataFrame(raw, columns=channels), raw_events=None
        )
    return controls


def test_fmo_controls_recover_the_spillover_matrix():
    from karcytics_plugins.flow_cytometry.analysis.compensation import (
        calculate_spillover_from_fmo,
    )

    channels = ["FITC-A", "PE-A", "APC-A"]
    spillover = np.array([[1.0, 0.15, 0.0], [0.02, 1.0, 0.08], [0.0, 0.01, 1.0]])

    exact = calculate_spillover_from_fmo(_fmo_controls(spillover, channels, range(3)), channels)
    np.testing.assert_allclose(exact.matrix, spillover, atol=1e-8)
    assert exact.source == "fmo" and not exact.fine_tuned

    noisy = calculate_spillover_from_fmo(
        _fmo_controls(spillover, channels, range(3), noise=5.0), channels
    )
    np.testing.assert_allclose(noisy.matrix, spillover, atol=0.01)


def test_a_detector_without_an_fmo_gets_no_spill_estimate():
    import pytest

    from karcytics_plugins.flow_cytometry.analysis.compensation import (
        calculate_spillover_from_fmo,
    )

    channels = ["FITC-A", "PE-A", "APC-A"]
    spillover = np.array([[1.0, 0.15, 0.0], [0.02, 1.0, 0.08], [0.0, 0.01, 1.0]])

    partial = calculate_spillover_from_fmo(_fmo_controls(spillover, channels, [1]), channels)
    assert partial.matrix[0, 1] == pytest.approx(0.15, abs=1e-6)  # FITC → PE, from the PE FMO
    assert partial.matrix[1, 2] == 0.0  # nothing known about spill into APC

    with pytest.raises(ValueError, match="No FMO control"):
        calculate_spillover_from_fmo({}, channels)


def test_fine_tuned_survives_serialisation_and_defaults_off_for_old_files():
    comp = CompensationMatrix(np.eye(2), ["A", "B"], source="cytometer", fine_tuned=True)

    assert CompensationMatrix.from_dict(comp.to_dict()).fine_tuned is True
    old = {"matrix": [[1, 0], [0, 1]], "channel_names": ["A", "B"], "source": "cytometer"}
    assert CompensationMatrix.from_dict(old).fine_tuned is False
