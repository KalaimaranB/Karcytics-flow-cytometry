"""Test fixtures for flow_cytometry module testing.

This module provides reusable fixtures for testing flow cytometry components.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from karcytics_plugins.flow_cytometry.analysis.experiment import Experiment as Experiment
from karcytics_plugins.flow_cytometry.analysis.experiment import Sample as Sample
from karcytics_plugins.flow_cytometry.analysis.fcs_io import load_fcs
from karcytics_plugins.flow_cytometry.analysis.gating import (
    EllipseGate,
    PolygonGate,
    QuadrantGate,
    RangeGate,
    RectangleGate,
)
from karcytics_plugins.flow_cytometry.analysis.population_service import PopulationService
from karcytics_plugins.flow_cytometry.analysis.scaling import AxisScale
from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.analysis.transforms import TransformType

# ── Mock Objects ──────────────────────────────────────────────────────────


class MockFcsData:
    """Mock for FCS data that implements the minimal interface needed for testing."""

    def __init__(self, events: pd.DataFrame):
        self.events = events
        self.parameters = {col: {} for col in events.columns}
        self.metadata = {}
        self.num_events = len(events)
        self.file_path = "test.fcs"

    @property
    def channels(self) -> list[str]:
        return list(self.events.columns)

    @property
    def markers(self) -> list[str]:
        return [""] * len(self.channels)


# ── FCS Data Fixtures ─────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def fcs_test_data_dir():
    """Path to FCS test data directory."""
    # Go up one level to tests directory, then into data/fcs
    return Path(__file__).parent.parent / "data" / "fcs"


@pytest.fixture
def sample_a_events(synthetic_events_medium):
    """Synthetic events (see `synthetic_events_medium`) — the real Specimen_001
    FCS files are exercised end-to-end in `functional/test_gating_pipeline.py`.
    """
    return synthetic_events_medium


@pytest.fixture
def sample_c_events(synthetic_events_medium):
    """Synthetic events (see `synthetic_events_medium`) — the real Specimen_001
    FCS files are exercised end-to-end in `functional/test_gating_pipeline.py`.
    """
    return synthetic_events_medium


# ── Axis Scale Fixtures ───────────────────────────────────────────────────


@pytest.fixture
def scale_linear():
    """Linear axis scale (identity transform)."""
    return AxisScale(TransformType.LINEAR)


@pytest.fixture
def scale_biexp_standard():
    """Standard BiExponential scale (M=5, W=1, T=262144, A=0)."""
    scale = AxisScale(TransformType.BIEXPONENTIAL)
    scale.logicle_m = 5.0
    scale.logicle_w = 1.0
    scale.logicle_t = 262144.0
    scale.logicle_a = 0.0
    return scale


# ── Gate Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def gate_rectangle_singlet():
    """Typical singlet gate (Rectangle on FSC-A vs SSC-A)."""
    return RectangleGate(
        x_param="FSC-A",
        y_param="SSC-A",
        x_min=50_000,
        x_max=200_000,
        y_min=1_000,
        y_max=50_000,
        x_scale=AxisScale(TransformType.LINEAR),
        y_scale=AxisScale(TransformType.LINEAR),
    )


@pytest.fixture
def gate_rectangle_lymph():
    """Typical lymphocyte gate (Rectangle on FSC-A vs SSC-A)."""
    return RectangleGate(
        x_param="FSC-A",
        y_param="SSC-A",
        x_min=40_000,
        x_max=150_000,
        y_min=500,
        y_max=30_000,
        x_scale=AxisScale(TransformType.LINEAR),
        y_scale=AxisScale(TransformType.LINEAR),
    )


@pytest.fixture
def gate_polygon_live():
    """Typical live cell gate (Polygon excluding debris and doublets)."""
    vertices = [
        (50_000, 1_000),
        (200_000, 1_000),
        (200_000, 50_000),
        (50_000, 50_000),
    ]
    return PolygonGate(
        x_param="FSC-A",
        y_param="SSC-A",
        vertices=vertices,
        x_scale=AxisScale(TransformType.LINEAR),
        y_scale=AxisScale(TransformType.LINEAR),
    )


@pytest.fixture
def gate_ellipse_cd4_plus():
    """Typical fluorescence gate (Ellipse on FITC vs PE)."""
    return EllipseGate(
        x_param="FITC-A",
        y_param="PE-A",
        center=(100, 100),
        width=80,
        height=60,
        angle=0.0,
        x_scale=AxisScale(TransformType.LINEAR),
        y_scale=AxisScale(TransformType.LINEAR),
    )


@pytest.fixture
def gate_quadrant_cd4_cd8():
    """Quadrant gate for fluorescence classification."""
    return QuadrantGate(
        x_param="FITC-A",
        y_param="PE-A",
        x_mid=100,
        y_mid=100,
        x_scale=AxisScale(TransformType.LINEAR),
        y_scale=AxisScale(TransformType.LINEAR),
    )


@pytest.fixture
def gate_range_cd3(scale_biexp_standard):
    """Range gate for fluorescence selection."""
    return RangeGate(
        x_param="CD3",
        low=100,
        high=262144,
        x_scale=scale_biexp_standard,
    )


# ── Synthetic Event Data Fixtures ─────────────────────────────────────────


@pytest.fixture
def synthetic_events_small():
    """Synthetic events DataFrame (1000 events, simple distribution)."""
    np.random.seed(42)
    n_events = 1000

    # Simulate typical flow cytometry data
    data = {
        "FSC-A": np.random.normal(100_000, 30_000, n_events).clip(0, 262144),
        "SSC-A": np.random.normal(80_000, 25_000, n_events).clip(0, 262144),
        "CD4": np.random.exponential(5000, n_events).clip(0, 262144),
        "CD8": np.random.exponential(3000, n_events).clip(0, 262144),
        "CD3": np.random.normal(50_000, 30_000, n_events).clip(0, 262144),
    }

    return pd.DataFrame(data)


@pytest.fixture
def synthetic_events_medium():
    """Synthetic events DataFrame (10,000 events, realistic distribution)."""
    np.random.seed(42)
    n_events = 10_000

    # More realistic simulation with population structure
    fsc = np.concatenate(
        [
            np.random.normal(50_000, 10_000, int(n_events * 0.1)),  # Debris
            np.random.normal(120_000, 20_000, int(n_events * 0.7)),  # Singlets (70%)
            np.random.normal(220_000, 10_000, int(n_events * 0.2)),  # Doublets
        ]
    ).clip(1, 262144)  # clip to 1 so min > 0

    # Singlet gate expects SSC-A between 1_000 and 50_000
    ssc = np.concatenate(
        [
            np.random.normal(10_000, 5_000, int(n_events * 0.1)),
            np.random.normal(25_000, 5_000, int(n_events * 0.7)),
            np.random.normal(80_000, 10_000, int(n_events * 0.2)),
        ]
    ).clip(1, 262144)

    # FITC-A needs some negative values so auto range goes < 0
    fitc = np.random.normal(5000, 5000, n_events)

    fitc = np.concatenate(
        [
            np.random.uniform(-500, 500, int(n_events * 0.5)),
            np.random.uniform(500, 150_000, int(n_events * 0.5)),
        ]
    )
    pe = np.concatenate(
        [
            np.random.uniform(0, 500, int(n_events * 0.5)),
            np.random.uniform(500, 150_000, int(n_events * 0.5)),
        ]
    )

    data = {
        "FSC-A": fsc,
        "SSC-A": ssc,
        "CD4": np.random.uniform(0, 150_000, n_events),
        "CD8": np.random.uniform(0, 150_000, n_events),
        "CD3": np.random.uniform(0, 150_000, n_events),
        "FITC-A": fitc,
        "PE-A": pe,
        "PerCP-Cy5-5-A": np.random.uniform(0, 150_000, n_events),
        "Pacific Blue-A": np.random.uniform(0, 150_000, n_events),
        "APC-Cy7-A": np.random.uniform(0, 150_000, n_events),
        "APC-A": np.random.uniform(0, 150_000, n_events),
        "Time": np.linspace(0, 3600, n_events),
    }

    return pd.DataFrame(data).iloc[:n_events]


@pytest.fixture
def flow_state(synthetic_events_small):
    """Returns a pre-populated FlowState with a test sample and services."""
    state = FlowState()
    sample = Sample(sample_id="test_sample_1", display_name="Test Sample")
    sample.fcs_data = MockFcsData(synthetic_events_small)
    state.data.experiment.samples[sample.sample_id] = sample

    # Initialize services
    from karcytics_plugins.flow_cytometry.analysis.axis_manager import AxisManager

    state.population_service = PopulationService(state)
    state.axis_manager = AxisManager(state)
    return state


# ── Utility Fixtures ───────────────────────────────────────────────────────


@pytest.fixture
def coordinate_mapper_linear(scale_linear):
    """CoordinateMapper with linear scales."""
    from karcytics_plugins.flow_cytometry.ui.graph.flow_services import CoordinateMapper

    return CoordinateMapper(scale_linear, scale_linear)


@pytest.fixture
def coordinate_mapper_biexp(scale_biexp_standard):
    """CoordinateMapper with biexponential scales."""
    from karcytics_plugins.flow_cytometry.ui.graph.flow_services import CoordinateMapper

    return CoordinateMapper(scale_biexp_standard, scale_biexp_standard)


@pytest.fixture
def gate_factory_linear(scale_linear):
    """GateFactory with linear scales."""
    from karcytics_plugins.flow_cytometry.ui.graph.flow_services import (
        CoordinateMapper,
        GateFactory,
    )

    mapper = CoordinateMapper(scale_linear, scale_linear)
    return GateFactory("FSC-A", "SSC-A", scale_linear, scale_linear, mapper)


@pytest.fixture
def gate_factory_biexp(scale_biexp_standard):
    """GateFactory with biexponential scales."""
    from karcytics_plugins.flow_cytometry.ui.graph.flow_services import (
        CoordinateMapper,
        GateFactory,
    )

    mapper = CoordinateMapper(scale_biexp_standard, scale_biexp_standard)
    return GateFactory("CD4", "CD8", scale_biexp_standard, scale_biexp_standard, mapper)
