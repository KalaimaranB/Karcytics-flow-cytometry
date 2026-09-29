"""Unit tests for UmapAnalysis background worker."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from karcytics_plugins.flow_cytometry.analysis.axis_manager import AxisManager
from karcytics_plugins.flow_cytometry.analysis.experiment import Sample
from karcytics_plugins.flow_cytometry.analysis.fcs_io import FCSData
from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.analysis.umap_analysis import UmapAnalysis

# Skip entire module if umap/numba is incompatible with the installed NumPy
pytest.importorskip(
    "umap",
    reason="umap-learn requires numba which is incompatible with this NumPy version",
)


@pytest.fixture
def test_state():
    """Create a fully populated FlowState for UMAP testing."""
    state = FlowState()

    # Instantiate actual AxisManager
    state.axis_manager = AxisManager(state)

    # Construct a sample with real FCSData
    sample = Sample(sample_id="s1", display_name="Sample 1")

    # 100 events, 4 channels (2 scatter, 2 fluorescence)
    np.random.seed(42)
    events_df = pd.DataFrame(
        {
            "FSC-A": np.random.rand(100) * 1000,
            "SSC-A": np.random.rand(100) * 1000,
            "FL1-A": np.random.rand(100) * 100,
            "FL2-A": np.random.rand(100) * 100,
        }
    )

    sample.fcs_data = FCSData(
        file_path=Path("test.fcs"),
        channels=["FSC-A", "SSC-A", "FL1-A", "FL2-A"],
        markers=["", "", "CD4", "CD8"],
        events=events_df,
    )

    state.data.experiment.add_sample(sample)
    state.view.current_sample_id = "s1"

    return state


def test_umap_validation_missing_sample(test_state):
    """Verify validation fails if no sample is selected or present."""
    analysis = UmapAnalysis()
    analysis.target_sample_id = "nonexistent"

    is_valid, err = analysis.validate(test_state)
    assert not is_valid
    assert "not found" in err


def test_umap_validation_too_few_events(test_state):
    """Verify validation fails if the sample has too few events."""
    sample = test_state.data.experiment.samples["s1"]

    # Re-assign events with only 10 rows
    events_df = pd.DataFrame(
        {"FSC-A": np.random.rand(10) * 1000, "FL1-A": np.random.rand(10) * 100}
    )
    sample.fcs_data = FCSData(
        file_path=Path("test.fcs"),
        channels=["FSC-A", "FL1-A"],
        markers=["", "CD4"],
        events=events_df,
    )

    analysis = UmapAnalysis()
    analysis.target_sample_id = "s1"

    is_valid, err = analysis.validate(test_state)
    assert not is_valid
    assert "too few events" in err


def test_umap_validation_success(test_state):
    """Verify validation passes on a valid loaded sample."""
    analysis = UmapAnalysis()
    analysis.target_sample_id = "s1"

    is_valid, err = analysis.validate(test_state)
    assert is_valid
    assert err == ""


def test_umap_run_success(test_state):
    """Verify UMAP runs successfully and returns correct structures."""
    analysis = UmapAnalysis()
    analysis.target_sample_id = "s1"
    analysis.n_events = 50
    analysis.n_neighbors = 5
    analysis.min_dist = 0.1
    analysis.random_seed = 42

    # Mock/hook progress signal
    progress_calls = []
    analysis.signals.analysis_progress.connect(progress_calls.append)

    # Run
    results = analysis.run(test_state)

    # Check results
    assert "error" not in results
    assert results["sample_id"] == "s1"
    assert results["n_events"] == 50
    # 100 events in the fixture sample, only 50 subsampled — needed downstream
    # to compute the scale_factor correction (parent_total_events / n_events).
    assert results["parent_total_events"] == 100

    # Embedding must be shape (50, 2)
    embedding = results["embedding"]
    assert isinstance(embedding, np.ndarray)
    assert embedding.shape == (50, 2)

    # Output channels list
    assert results["channels"] == ["FL1-A", "FL2-A"]

    # Intensities must be (50, 2)
    assert results["intensities"].shape == (50, 2)

    # Verify progress was emitted
    assert analysis.signals.analysis_progress.emit.call_count > 0
