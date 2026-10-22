"""Shared test setup: the real SDK on Qt's offscreen platform."""

import os

# Before anything imports Qt or the SDK's runtime services: no window system,
# and Academy progress saved under a test-only plugin id, not the real one.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("KARCYTICS_PLUGIN_ID", "flow_cytometry_tests")

from unittest.mock import MagicMock  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402
from karcytics_sdk.plugin import ui_daemon_runtime  # noqa: E402

from karcytics_plugins.flow_cytometry.analysis.experiment import Experiment, Sample  # noqa: E402
from karcytics_plugins.flow_cytometry.analysis.state import FlowState  # noqa: E402

from .fixtures import *  # noqa: F403, E402

# Outside the UI daemon there is no Hub on stdout: keep the frames the SDK
# would send it (event_bus.emit, diagnostics) instead of writing them.
sent_frames: list[dict] = []
ui_daemon_runtime.write_frame = sent_frames.append


@pytest.fixture
def empty_state():
    """Returns a fresh FlowState with an empty experiment."""
    state = FlowState()
    state.data.experiment = Experiment()
    return state


@pytest.fixture
def sample_data():
    """Returns a dummy FCS DataFrame."""
    return pd.DataFrame(
        {
            "FSC-A": np.random.rand(1000) * 1024,
            "SSC-A": np.random.rand(1000) * 1024,
            "FL1-A": np.random.rand(1000) * 100,
        }
    )


@pytest.fixture
def sample_with_data(sample_data):
    """Returns a Sample object populated with dummy data."""
    sample = Sample(sample_id="s1", display_name="Sample 1")
    sample.fcs_data = MagicMock()
    sample.fcs_data.events = sample_data
    return sample


@pytest.fixture
def state_with_sample(empty_state, sample_with_data):
    """Returns a FlowState with one sample loaded."""
    empty_state.experiment.samples[sample_with_data.sample_id] = sample_with_data
    return empty_state
