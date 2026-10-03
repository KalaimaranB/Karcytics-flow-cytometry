"""Tests for projecting a gate onto a single axis (`axis_interval`)."""

from __future__ import annotations

import pytest

from karcytics_plugins.flow_cytometry.analysis.gating import (
    EllipseGate,
    PolygonGate,
    QuadrantGate,
    QuadrantSubGate,
    RangeGate,
    RectangleGate,
)
from karcytics_plugins.flow_cytometry.analysis.gating.projection import axis_interval

pytestmark = pytest.mark.unit


def test_rectangle_projects_onto_each_of_its_axes():
    gate = RectangleGate("FSC-A", "SSC-A", x_min=10, x_max=20, y_min=1, y_max=2)

    assert axis_interval(gate, "FSC-A") == (10, 20)
    assert axis_interval(gate, "SSC-A") == (1, 2)


def test_range_projects_onto_its_axis():
    assert axis_interval(RangeGate("FITC-A", low=5, high=50), "FITC-A") == (5, 50)


def test_quadrant_and_its_sub_gates_project_to_the_divider():
    quadrant = QuadrantGate("FSC-A", "SSC-A", x_mid=100, y_mid=7)
    sub_gate = QuadrantSubGate(quadrant, "Q1")

    for gate in (quadrant, sub_gate):
        assert axis_interval(gate, "FSC-A") == (100, 100)
        assert axis_interval(gate, "SSC-A") == (7, 7)


def test_gate_on_another_axis_has_no_interval():
    gate = RectangleGate("FSC-A", "SSC-A", x_min=10, x_max=20, y_min=1, y_max=2)

    assert axis_interval(gate, "FITC-A") is None


def test_open_ended_bounds_have_no_interval():
    assert axis_interval(RangeGate("FITC-A", low=5), "FITC-A") is None


@pytest.mark.parametrize(
    "gate",
    [
        PolygonGate("FSC-A", "SSC-A", vertices=[(0, 0), (1, 0), (1, 1)]),
        EllipseGate("FSC-A", "SSC-A", center=(1, 1), width=2, height=2),
    ],
)
def test_shapes_without_straight_edges_have_no_interval(gate):
    assert axis_interval(gate, "FSC-A") is None
