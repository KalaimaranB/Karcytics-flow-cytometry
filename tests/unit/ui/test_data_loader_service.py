"""Regression tests for DataLoaderService.reload_samples_batch().

Guards against reload_fcs_data() regressing back to fanning out one
load_fcs() call per sample across a thread pool: every load_fcs() call
serializes through fcs_io's single process-wide daemon IPC lock, so a
single slow/stuck file used to silently stall every other sample's reload
behind it — with no error surfaced anywhere (see the bug this fixes).
"""

from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from karcytics_plugins.flow_cytometry.analysis.compensation import CompensationMatrix
from karcytics_plugins.flow_cytometry.analysis.experiment import Sample
from karcytics_plugins.flow_cytometry.analysis.fcs_io import FCSData
from karcytics_plugins.flow_cytometry.ui.services.data_loader_service import (
    DataLoaderService,
)
from tests.fixtures.daemon import in_process_daemon


def _make_fcs_data(path: Path, n_events: int = 5) -> FCSData:
    events = pd.DataFrame({"FSC-A": [1.0] * n_events, "SSC-A": [2.0] * n_events})
    return FCSData(file_path=path, channels=["FSC-A", "SSC-A"], events=events, raw_events=events)


@pytest.fixture
def service() -> DataLoaderService:
    return DataLoaderService(None, in_process_daemon)


def test_reload_samples_batch_makes_a_single_batched_call(service: DataLoaderService):
    """The whole point of the fix: one load_fcs_batch() round-trip, not N."""
    sample_a = Sample(sample_id="a", display_name="Sample A")
    sample_b = Sample(sample_id="b", display_name="Sample B")
    path_a, path_b = Path("/data/a.fcs"), Path("/data/b.fcs")

    with patch(
        "karcytics_plugins.flow_cytometry.ui.services.data_loader_service.load_fcs_batch"
    ) as mock_batch:
        mock_batch.return_value = {
            path_a: _make_fcs_data(path_a),
            path_b: _make_fcs_data(path_b),
        }
        result = service.reload_samples_batch(
            [(sample_a, path_a), (sample_b, path_b)], compensation_matrix=None
        )

    mock_batch.assert_called_once()
    (called_paths, _daemon), _kwargs = mock_batch.call_args
    assert set(called_paths) == {path_a, path_b}
    assert result == {"loaded": ["Sample A", "Sample B"], "failed": []}
    assert sample_a.fcs_data is not None
    assert sample_b.fcs_data is not None


def test_reload_samples_batch_isolates_one_bad_file(service: DataLoaderService):
    """One stuck/broken file must not prevent the rest from loading."""
    good_sample = Sample(sample_id="good", display_name="Good Sample")
    bad_sample = Sample(sample_id="bad", display_name="Bad Sample")
    good_path, bad_path = Path("/data/good.fcs"), Path("/data/bad.fcs")

    with patch(
        "karcytics_plugins.flow_cytometry.ui.services.data_loader_service.load_fcs_batch"
    ) as mock_batch:
        mock_batch.return_value = {
            good_path: _make_fcs_data(good_path),
            bad_path: RuntimeError("daemon call timed out after 120.0s"),
        }
        result = service.reload_samples_batch(
            [(good_sample, good_path), (bad_sample, bad_path)], compensation_matrix=None
        )

    assert result == {"loaded": ["Good Sample"], "failed": ["Bad Sample"]}
    assert good_sample.fcs_data is not None
    assert bad_sample.fcs_data is None


def test_reload_samples_batch_handles_missing_result(service: DataLoaderService):
    """A path load_fcs_batch never returned a result for still fails cleanly."""
    sample = Sample(sample_id="s", display_name="Missing Sample")
    path = Path("/data/missing.fcs")

    with patch(
        "karcytics_plugins.flow_cytometry.ui.services.data_loader_service.load_fcs_batch"
    ) as mock_batch:
        mock_batch.return_value = {}
        result = service.reload_samples_batch([(sample, path)], compensation_matrix=None)

    assert result == {"loaded": [], "failed": ["Missing Sample"]}
    assert sample.fcs_data is None


def test_reload_samples_batch_empty_input_short_circuits(service: DataLoaderService):
    with patch(
        "karcytics_plugins.flow_cytometry.ui.services.data_loader_service.load_fcs_batch"
    ) as mock_batch:
        result = service.reload_samples_batch([], compensation_matrix=None)

    mock_batch.assert_not_called()
    assert result == {"loaded": [], "failed": []}


def test_reload_samples_batch_reapplies_compensation(service: DataLoaderService):
    sample = Sample(sample_id="s", display_name="Comp Sample", is_compensated=True)
    path = Path("/data/comp.fcs")
    fcs_data = _make_fcs_data(path)
    assert fcs_data.is_compensated is False

    comp = CompensationMatrix(matrix=np.eye(2), channel_names=["FSC-A", "SSC-A"])

    with patch(
        "karcytics_plugins.flow_cytometry.ui.services.data_loader_service.load_fcs_batch"
    ) as mock_batch:
        mock_batch.return_value = {path: fcs_data}
        service.reload_samples_batch([(sample, path)], compensation_matrix=comp)

    assert sample.fcs_data is not None
    assert sample.fcs_data.is_compensated is True
