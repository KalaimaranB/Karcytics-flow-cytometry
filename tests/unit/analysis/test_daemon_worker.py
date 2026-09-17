"""Unit tests for daemon_worker.py in Karcytics-flow-cytometry."""

import time
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from karcytics_sdk.plugin import PluginDaemon

from karcytics_plugins.flow_cytometry.analysis.daemon_worker import (
    _decode_array,
    _encode_array,
    handle_load_fcs_batch,
    handle_run_umap,
)


def test_array_serialization():
    arr = np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float64)
    b64 = _encode_array(arr)
    decoded = _decode_array(b64)
    np.testing.assert_array_equal(arr, decoded)


@pytest.mark.filterwarnings("ignore:n_jobs value 1 overridden to 1:UserWarning")
def test_handle_run_umap():
    np.random.seed(42)
    X = np.random.randn(100, 5).astype(np.float64)
    X_b64 = _encode_array(X)

    kwargs = {
        "x_b64": X_b64,
        "params": {
            "n_neighbors": 5,
            "min_dist": 0.1,
            "random_seed": 42,
        },
    }
    res = handle_run_umap(kwargs)
    assert res.get("status") == "ok"
    assert "embedding_b64" in res

    embedding = _decode_array(res["embedding_b64"])
    assert embedding.shape == (100, 2)


def test_handle_load_fcs_batch_isolates_a_stuck_file():
    """One hung file must not withhold the other files' already-finished results.

    Regression test for a real incident: switching FCS reload to a single
    batched daemon call made ANY hung/corrupt file block the *entire*
    batch's response — because the daemon's main loop is single-threaded
    and can't write back until handle_load_fcs_batch() returns, and a bare
    as_completed()/executor context manager blocks on the slowest future
    no matter how many others already finished. Previously (per-file
    calls) a stuck file only starved requests queued behind it; batching
    without a deadline made it starve the whole batch, including files
    that had already loaded.
    """
    real_paths = ["/data/fast1.fcs", "/data/fast2.fcs", "/data/stuck.fcs"]

    def fake_handle_load_fcs(kwargs):
        path = kwargs["path"]
        if path == "/data/stuck.fcs":
            time.sleep(30)  # simulates a hung FlowKit/fcsparser call
            return {"status": "ok"}  # pragma: no cover - never reached in test
        return {"status": "ok", "path": path}

    with (
        patch(
            "karcytics_plugins.flow_cytometry.analysis.daemon_worker.handle_load_fcs",
            side_effect=fake_handle_load_fcs,
        ),
        patch(
            "karcytics_plugins.flow_cytometry.analysis.daemon_worker._batch_deadline_seconds",
            return_value=0.5,
        ),
    ):
        start = time.monotonic()
        res = handle_load_fcs_batch({"paths": real_paths})
        elapsed = time.monotonic() - start

    assert elapsed < 5.0, f"batch should return promptly after the deadline, took {elapsed:.1f}s"
    assert res["results"]["/data/fast1.fcs"] == {"status": "ok", "path": "/data/fast1.fcs"}
    assert res["results"]["/data/fast2.fcs"] == {"status": "ok", "path": "/data/fast2.fcs"}
    assert "error" in res["results"]["/data/stuck.fcs"]
    assert "Timed out" in res["results"]["/data/stuck.fcs"]["error"]


@pytest.mark.filterwarnings("ignore:n_jobs value 1 overridden to 1:UserWarning")
def test_daemon_worker_end_to_end(tmp_path):
    daemon_script = (
        Path(__file__).resolve().parents[3]
        / "src"
        / "karcytics_plugins"
        / "flow_cytometry"
        / "analysis"
        / "daemon_worker.py"
    )
    if not daemon_script.exists():
        pytest.skip(f"daemon_worker.py not found at {daemon_script}")

    daemon = PluginDaemon.get_instance("flow_cytometry_test", daemon_script_path=daemon_script)

    # Ping test
    res = daemon.call("ping", {})
    assert res == {"status": "pong"}

    # UMAP test
    X = np.random.randn(50, 4).astype(np.float64)
    X_b64 = _encode_array(X)
    res_umap = daemon.call(
        "run_umap",
        {
            "x_b64": X_b64,
            "params": {"n_neighbors": 5, "min_dist": 0.1, "random_seed": 42},
        },
    )
    assert res_umap.get("status") == "ok"
    assert "embedding_b64" in res_umap

    PluginDaemon.stop_instance("flow_cytometry_test")
