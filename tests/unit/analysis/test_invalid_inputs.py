"""Edge case tests for gate operations - handling invalid inputs, NaN, Inf, and boundary conditions.

Tests verify that gates handle edge cases gracefully:
- NaN values in data
- Inf values
- Empty data
- Missing parameters
- Extreme values
- Numerical instability
- Inverted bounds
- Single-event populations
"""

import numpy as np
import pandas as pd
import pytest

from karcytics_plugins.flow_cytometry.analysis.gating import (
    EllipseGate,
    PolygonGate,
    QuadrantGate,
    RangeGate,
    RectangleGate,
)


@pytest.mark.edge_case
class TestNaNHandling:
    """Test gate behavior with NaN values."""

    def test_gate_with_nan_in_x_parameter(self):
        """Apply gate to data with NaN in x parameter."""
        gate = RectangleGate(
            "FSC-A", "SSC-A", x_min=50_000, x_max=200_000, y_min=1_000, y_max=50_000
        )

        data = pd.DataFrame(
            {
                "FSC-A": [100_000, np.nan, 150_000, 120_000],
                "SSC-A": [5_000, 6_000, np.nan, 8_000],
            }
        )

        result = gate.contains(data)

        # Should handle NaN without crashing
        assert len(result) == len(data)
        # NaN rows should be False (not inside gate)
        assert not result[1]
        assert not result[2]

    def test_gate_with_all_nan(self):
        """Apply gate to data that's entirely NaN."""
        gate = RectangleGate(
            "FSC-A", "SSC-A", x_min=50_000, x_max=200_000, y_min=1_000, y_max=50_000
        )

        data = pd.DataFrame(
            {
                "FSC-A": [np.nan, np.nan, np.nan],
                "SSC-A": [np.nan, np.nan, np.nan],
            }
        )

        result = gate.contains(data)

        # All should be False
        assert np.sum(result) == 0

    def test_range_gate_with_nan(self):
        """Range gate with NaN values."""
        gate = RangeGate("FITC-A", low=50, high=250)

        data = pd.DataFrame(
            {
                "FITC-A": [100, np.nan, 200, 30, np.nan],
            }
        )

        result = gate.contains(data)

        # NaN should be False
        assert not result[1]
        assert not result[4]
        # Valid values should be evaluated
        assert result[0]  # 100 is in [50, 250]
        assert result[2]  # 200 is in [50, 250]
        assert not result[3]  # 30 is not in [50, 250]


@pytest.mark.edge_case
class TestInfinityHandling:
    """Test gate behavior with Inf values."""

    def test_gate_with_positive_infinity(self):
        """Apply gate to data with positive Inf."""
        gate = RectangleGate(
            "FSC-A", "SSC-A", x_min=50_000, x_max=200_000, y_min=1_000, y_max=50_000
        )

        data = pd.DataFrame(
            {
                "FSC-A": [100_000, np.inf, 150_000],
                "SSC-A": [5_000, 10_000, np.inf],
            }
        )

        result = gate.contains(data)

        # Inf should be False (outside gate bounds)
        assert not result[1]
        assert not result[2]

    def test_gate_with_negative_infinity(self):
        """Apply gate to data with negative Inf."""
        gate = RectangleGate(
            "FSC-A", "SSC-A", x_min=50_000, x_max=200_000, y_min=1_000, y_max=50_000
        )

        data = pd.DataFrame(
            {
                "FSC-A": [100_000, -np.inf, 150_000],
                "SSC-A": [5_000, 10_000, 20_000],
            }
        )

        result = gate.contains(data)

        # -Inf should be False (outside bounds)
        assert not result[1]

    def test_range_gate_with_infinity(self):
        """Range gate with Inf values."""
        gate = RangeGate("FITC-A", low=50, high=250)

        data = pd.DataFrame(
            {
                "FITC-A": [100, np.inf, 200, -np.inf, 150],
            }
        )

        result = gate.contains(data)

        # Inf values should be outside range
        assert not result[1]  # np.inf
        assert not result[3]  # -np.inf
        # Valid values should be True
        assert result[0]
        assert result[2]


@pytest.mark.edge_case
class TestEmptyDataHandling:
    """Test gate behavior with empty data."""

    def test_gate_on_empty_dataframe(self):
        """Apply gate to empty DataFrame."""
        gate = RectangleGate(
            "FSC-A", "SSC-A", x_min=50_000, x_max=200_000, y_min=1_000, y_max=50_000
        )

        empty = pd.DataFrame({"FSC-A": [], "SSC-A": []})
        result = gate.contains(empty)

        assert len(result) == 0
        assert isinstance(result, np.ndarray)

    def test_gate_on_single_event(self):
        """Apply gate to single event."""
        gate = RectangleGate(
            "FSC-A", "SSC-A", x_min=50_000, x_max=200_000, y_min=1_000, y_max=50_000
        )

        data = pd.DataFrame({"FSC-A": [100_000], "SSC-A": [5_000]})
        result = gate.contains(data)

        assert len(result) == 1
        assert result[0]

    def test_gate_on_zero_events(self):
        """Apply gate to zero-size arrays."""
        gate = RangeGate("FITC-A", low=50, high=250)

        data = pd.DataFrame({"FITC-A": []})
        result = gate.contains(data)

        assert len(result) == 0


@pytest.mark.edge_case
class TestBoundaryConditions:
    """Test gates at exact boundaries."""

    def test_rectangle_gate_point_on_boundary(self):
        """Points exactly on rectangle boundary."""
        gate = RectangleGate(
            "FSC-A", "SSC-A", x_min=100_000, x_max=200_000, y_min=10_000, y_max=50_000
        )

        # Test boundary points
        data = pd.DataFrame(
            {
                "FSC-A": [
                    100_000,
                    200_000,
                    150_000,
                    150_000,
                ],  # left, right, center, center
                "SSC-A": [
                    10_000,
                    50_000,
                    30_000,
                    10_000,
                ],  # bottom, top, center, bottom
            }
        )

        result = gate.contains(data)

        # Bounds are inclusive on every edge.
        assert result.tolist() == [True, True, True, True]

    def test_range_gate_at_boundaries(self):
        """Range gate at exact min/max boundaries."""
        gate = RangeGate("FITC-A", low=100, high=200)

        data = pd.DataFrame(
            {
                "FITC-A": [100, 200, 99, 201, 150],
            }
        )

        result = gate.contains(data)

        # Boundary behavior (typically inclusive)
        assert result[0]  # 100 (at min)
        assert result[1]  # 200 (at max)
        assert not result[2]  # 99 (below min)
        assert not result[3]  # 201 (above max)
        assert result[4]  # 150 (inside)

    def test_near_boundary_precision(self):
        """Test gates with values very close to boundaries."""
        gate = RectangleGate(
            "FSC-A", "SSC-A", x_min=100_000, x_max=200_000, y_min=10_000, y_max=50_000
        )

        data = pd.DataFrame(
            {
                "FSC-A": [99_999.999, 100_000.001, 200_000.001, 199_999.999],
                "SSC-A": [30_000, 30_000, 30_000, 30_000],
            }
        )

        result = gate.contains(data)

        assert result.tolist() == [False, True, False, True]


@pytest.mark.edge_case
class TestMissingParameters:
    """Test gate behavior with missing or invalid parameters."""

    def test_gate_with_missing_parameter_column(self):
        """Apply gate when parameter column is missing."""
        gate = RectangleGate(
            "FSC-A", "SSC-A", x_min=50_000, x_max=200_000, y_min=1_000, y_max=50_000
        )

        # Missing FSC-A column
        data = pd.DataFrame(
            {
                "SSC-A": [5_000, 10_000, 15_000],
            }
        )

        # Should raise error
        with pytest.raises((KeyError, ValueError)):
            gate.contains(data)

    def test_range_gate_with_missing_parameter(self):
        """Range gate with missing parameter column."""
        gate = RangeGate("FITC-A", low=50, high=250)

        data = pd.DataFrame(
            {
                "PE-A": [100, 150, 200],  # Wrong parameter
            }
        )

        with pytest.raises((KeyError, ValueError)):
            gate.contains(data)


@pytest.mark.edge_case
class TestExtremeValues:
    """Test gates with extreme numeric values."""

    def test_gate_with_very_small_values(self):
        """Gate with very small positive values."""
        gate = RectangleGate("FSC-A", "SSC-A", x_min=1, x_max=1000, y_min=0.1, y_max=100)

        data = pd.DataFrame(
            {
                "FSC-A": [0.5, 1.5, 500, 1001],
                "SSC-A": [0.05, 0.5, 50, 101],
            }
        )

        result = gate.contains(data)

        assert result.tolist() == [False, True, True, False]

    def test_gate_with_very_large_values(self):
        """Gate with very large values (typical for flow cytometry)."""
        gate = RectangleGate(
            "FSC-A", "SSC-A", x_min=100_000, x_max=262_143, y_min=1_000, y_max=262_143
        )

        data = pd.DataFrame(
            {
                "FSC-A": [150_000, 262_142, 262_143, 262_144],
                "SSC-A": [100_000, 150_000, 200_000, 300_000],
            }
        )

        result = gate.contains(data)

        assert result.tolist() == [True, True, True, False]

    def test_negative_values_in_data(self):
        """Gate on data with negative values (valid in flow cytometry)."""
        gate = RectangleGate("FSC-A", "SSC-A", x_min=-100, x_max=200_000, y_min=-50, y_max=50_000)

        data = pd.DataFrame(
            {
                "FSC-A": [-50, 0, 100_000, 200_001],
                "SSC-A": [-25, 0, 25_000, 50_001],
            }
        )

        result = gate.contains(data)

        assert result.tolist() == [True, True, True, False]


@pytest.mark.edge_case
class TestZeroWidthGates:
    """Test gates with zero width (line/point gates)."""

    def test_rectangle_zero_width_x(self):
        """Rectangle with x_min == x_max (vertical line)."""
        gate = RectangleGate(
            "FSC-A", "SSC-A", x_min=100_000, x_max=100_000, y_min=1_000, y_max=50_000
        )

        data = pd.DataFrame(
            {
                "FSC-A": [99_999, 100_000, 100_001],
                "SSC-A": [25_000, 25_000, 25_000],
            }
        )

        result = gate.contains(data)

        # A zero-width gate still matches events exactly on the line.
        assert result.tolist() == [False, True, False]

    def test_range_zero_width(self):
        """Range gate with min == max (single point)."""
        gate = RangeGate("FITC-A", low=100, high=100)

        data = pd.DataFrame(
            {
                "FITC-A": [99, 100, 101],
            }
        )

        result = gate.contains(data)

        assert result.tolist() == [False, True, False]


@pytest.mark.edge_case
class TestInvertedGateBounds:
    """Test gates with inverted min/max bounds."""

    def test_rectangle_inverted_x_bounds(self):
        """Rectangle with x_min > x_max matches nothing — bounds are not
        swapped and no error is raised. Pins current behavior; if inverted
        bounds should instead be normalized or rejected, change it here.
        """
        gate = RectangleGate(
            "FSC-A", "SSC-A", x_min=200_000, x_max=50_000, y_min=1_000, y_max=50_000
        )
        data = pd.DataFrame(
            {
                "FSC-A": [25_000, 100_000, 150_000, 250_000],
                "SSC-A": [25_000, 25_000, 25_000, 25_000],
            }
        )

        assert not gate.contains(data).any()

    def test_range_inverted_bounds(self):
        """Range gate with low > high matches nothing (same as rectangle)."""
        gate = RangeGate("FITC-A", low=250, high=50)
        data = pd.DataFrame({"FITC-A": [25, 100, 150, 300]})

        assert not gate.contains(data).any()


@pytest.mark.edge_case
class TestPolygonEdgeCases:
    """Edge cases specific to polygon gates."""

    def test_polygon_with_two_vertices(self):
        """Polygon with minimum vertices (degenerate)."""
        vertices = np.array(
            [
                [50_000, 1_000],
                [200_000, 50_000],
            ]
        )

        gate = PolygonGate("FSC-A", "SSC-A", vertices)

        data = pd.DataFrame(
            {
                "FSC-A": [100_000, 150_000],
                "SSC-A": [10_000, 30_000],
            }
        )

        # Two vertices enclose zero area, so nothing is inside.
        assert gate.contains(data).tolist() == [False, False]

    def test_polygon_with_many_vertices(self):
        """Polygon with very many vertices."""
        # Circle approximation
        n = 100
        angles = np.linspace(0, 2 * np.pi, n, endpoint=False)
        vertices = np.array(
            [[100_000 + 50_000 * np.cos(a), 25_000 + 20_000 * np.sin(a)] for a in angles]
        )

        gate = PolygonGate("FSC-A", "SSC-A", vertices)

        data = pd.DataFrame(
            {
                "FSC-A": [100_000, 120_000, 80_000, 160_000],
                "SSC-A": [25_000, 25_000, 25_000, 25_000],
            }
        )

        result = gate.contains(data)

        assert result.tolist() == [True, True, True, False]


@pytest.mark.edge_case
class TestEllipseEdgeCases:
    """Edge cases specific to ellipse gates."""

    def test_ellipse_zero_semi_axes(self):
        """Ellipse with zero-length semi-axes (point)."""
        gate = EllipseGate("FITC-A", "PE-A", center=(100, 100), width=0, height=0, angle=0)

        data = pd.DataFrame(
            {
                "FITC-A": [100, 101, 99],
                "PE-A": [100, 100, 100],
            }
        )

        # Zero semi-axes enclose zero area — even the center isn't inside.
        assert gate.contains(data).tolist() == [False, False, False]

    def test_ellipse_very_small_semi_axes(self):
        """Ellipse with very small semi-axes."""
        gate = EllipseGate("FITC-A", "PE-A", center=(100, 100), width=0.01, height=0.01, angle=0)

        data = pd.DataFrame(
            {
                "FITC-A": [100, 100.001, 100.1],
                "PE-A": [100, 100.001, 100.1],
            }
        )

        # Semi-axes are 0.01; (100.1, 100.1) is well outside.
        result = gate.contains(data)

        assert result.tolist() == [True, True, False]


@pytest.mark.edge_case
class TestQuadrantEdgeCases:
    """Edge cases specific to quadrant gates."""

    def test_quadrant_threshold_at_extreme(self):
        """Every event lands in exactly one quadrant; points on a midline go
        to the upper/right side (`>=`), never to both or neither.
        """
        gate = QuadrantGate("FITC-A", "PE-A", x_mid=0, y_mid=0)
        data = pd.DataFrame(
            {
                "FITC-A": [-100, 0, 100],
                "PE-A": [-100, 0, 100],
            }
        )

        masks = {q: gate.get_quadrant(data, q) for q in ("Q1", "Q2", "Q3", "Q4")}

        assert masks["Q3"].tolist() == [True, False, False]
        assert masks["Q2"].tolist() == [False, True, True]
        assert np.all(sum(m.astype(int) for m in masks.values()) == 1)

    def test_quadrant_with_identical_values(self):
        """Data sitting exactly on both midlines all goes to Q2 (upper right)."""
        gate = QuadrantGate("FITC-A", "PE-A", x_mid=100, y_mid=100)
        data = pd.DataFrame(
            {
                "FITC-A": [100, 100, 100],
                "PE-A": [100, 100, 100],
            }
        )

        assert gate.get_quadrant(data, "Q2").all()
        for q in ("Q1", "Q3", "Q4"):
            assert not gate.get_quadrant(data, q).any()
