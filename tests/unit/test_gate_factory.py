"""Unit tests for GateFactory service.

Tests gate creation logic independently from UI/matplotlib.
"""

import numpy as np
import pytest

from karcytics_plugins.flow_cytometry.analysis.gating import (
    EllipseGate,
    PolygonGate,
    QuadrantGate,
    RangeGate,
    RectangleGate,
)
from karcytics_plugins.flow_cytometry.analysis.scaling import AxisScale
from karcytics_plugins.flow_cytometry.analysis.transforms import TransformType


class TestGateFactoryRectangle:
    """Test RectangleGate creation."""

    @pytest.mark.unit
    def test_create_rectangle_basic(self, gate_factory_linear):
        """Create basic rectangle gate."""
        gate = gate_factory_linear.create_rectangle(0, 0, 100, 100)

        assert isinstance(gate, RectangleGate)
        assert gate.x_min == 0
        assert gate.x_max == 100
        assert gate.y_min == 0
        assert gate.y_max == 100

    @pytest.mark.unit
    def test_create_rectangle_normalizes_coords(self, gate_factory_linear):
        """Rectangle should normalize coordinates (min/max order)."""
        gate = gate_factory_linear.create_rectangle(200, 150, 50, 30)

        assert gate.x_min == 50, "x_min should be smaller value"
        assert gate.x_max == 200, "x_max should be larger value"
        assert gate.y_min == 30, "y_min should be smaller value"
        assert gate.y_max == 150, "y_max should be larger value"

    @pytest.mark.unit
    def test_create_rectangle_with_biexp(self, gate_factory_biexp):
        """Create rectangle with biexponential transform."""
        gate = gate_factory_biexp.create_rectangle(0, 0, 1000, 1000)

        assert isinstance(gate, RectangleGate)
        # With biexp, coordinates should be transformed
        # (exact values depend on biexp parameters)
        assert gate.x_param == "CD4"
        assert gate.y_param == "CD8"

    @pytest.mark.unit
    def test_create_rectangle_parameters_set(self, gate_factory_linear):
        """Rectangle should have correct parameters and scales."""
        gate = gate_factory_linear.create_rectangle(0, 0, 100, 100)

        assert gate.x_param == "FSC-A"
        assert gate.y_param == "SSC-A"
        assert gate.x_scale.transform_type == TransformType.LINEAR
        assert gate.y_scale.transform_type == TransformType.LINEAR


class TestGateFactoryPolygon:
    """Test PolygonGate creation."""

    @pytest.mark.unit
    def test_create_polygon_triangle(self, gate_factory_linear):
        """Create triangle polygon gate."""
        vertices = [(0, 0), (100, 0), (50, 100)]
        gate = gate_factory_linear.create_polygon(vertices)

        assert isinstance(gate, PolygonGate)
        assert len(gate.vertices) == 3

    @pytest.mark.unit
    def test_create_polygon_square(self, gate_factory_linear):
        """Create square polygon gate."""
        vertices = [(0, 0), (100, 0), (100, 100), (0, 100)]
        gate = gate_factory_linear.create_polygon(vertices)

        assert isinstance(gate, PolygonGate)
        assert len(gate.vertices) == 4

    @pytest.mark.unit
    def test_create_polygon_minimum_vertices(self, gate_factory_linear):
        """Polygon should require at least 3 vertices."""
        vertices = [(0, 0), (100, 0), (50, 100)]
        gate = gate_factory_linear.create_polygon(vertices)
        assert isinstance(gate, PolygonGate)
        assert len(gate.vertices) == 3

    @pytest.mark.unit
    def test_create_polygon_too_few_vertices(self, gate_factory_linear):
        """Polygon with < 3 vertices should raise error."""
        vertices = [(0, 0), (100, 0)]
        with pytest.raises(ValueError):
            gate_factory_linear.create_polygon(vertices)

    @pytest.mark.unit
    def test_create_polygon_many_vertices(self, gate_factory_linear):
        """Polygon can have many vertices."""
        # Create circle approximation
        n = 32
        theta = np.linspace(0, 2 * np.pi, n, endpoint=False)
        cx, cy = 50, 50
        r = 30
        vertices = [(cx + r * np.cos(t), cy + r * np.sin(t)) for t in theta]

        gate = gate_factory_linear.create_polygon(vertices)
        assert len(gate.vertices) == n


class TestGateFactoryEllipse:
    """Test EllipseGate creation."""

    @pytest.mark.unit
    def test_create_ellipse_basic(self, gate_factory_linear):
        """Create basic ellipse gate."""
        gate = gate_factory_linear.create_ellipse(0, 0, 100, 100)

        assert isinstance(gate, EllipseGate)
        assert gate.center == (50, 50), "Center should be midpoint"
        assert gate.width == 50, "Width should be half of x extent"
        assert gate.height == 50, "Height should be half of y extent"

    @pytest.mark.unit
    def test_create_ellipse_asymmetric(self, gate_factory_linear):
        """Create asymmetric ellipse."""
        gate = gate_factory_linear.create_ellipse(0, 0, 200, 100)

        assert gate.center == (100, 50)
        assert gate.width == 100
        assert gate.height == 50

    @pytest.mark.unit
    def test_create_ellipse_negative_coords(self, gate_factory_linear):
        """Create ellipse from negative coordinates."""
        gate = gate_factory_linear.create_ellipse(-100, -100, 100, 100)

        assert gate.center == (0, 0)
        assert gate.width == 100
        assert gate.height == 100


class TestGateFactoryQuadrant:
    """Test QuadrantGate creation."""

    @pytest.mark.unit
    def test_create_quadrant_basic(self, gate_factory_linear):
        """Create basic quadrant gate."""
        gate = gate_factory_linear.create_quadrant(50, 50)

        assert isinstance(gate, QuadrantGate)
        assert gate.x_mid == 50
        assert gate.y_mid == 50

    @pytest.mark.unit
    def test_create_quadrant_zero(self, gate_factory_linear):
        """Create quadrant at origin."""
        gate = gate_factory_linear.create_quadrant(0, 0)

        assert gate.x_mid == 0
        assert gate.y_mid == 0

    @pytest.mark.unit
    def test_create_quadrant_large_values(self, gate_factory_linear):
        """Create quadrant with large values."""
        gate = gate_factory_linear.create_quadrant(100_000, 80_000)

        assert gate.x_mid == 100_000
        assert gate.y_mid == 80_000


class TestGateFactoryRange:
    """Test RangeGate creation."""

    @pytest.mark.unit
    def test_create_range_basic(self, gate_factory_linear):
        """Create basic range gate."""
        gate = gate_factory_linear.create_range(100, 200)

        assert isinstance(gate, RangeGate)
        assert gate.low == 100
        assert gate.high == 200

    @pytest.mark.unit
    def test_create_range_normalizes_coords(self, gate_factory_linear):
        """Range should normalize coordinates."""
        gate = gate_factory_linear.create_range(200, 100)

        assert gate.low == 100, "Low should be smaller"
        assert gate.high == 200, "High should be larger"

    @pytest.mark.unit
    def test_create_range_single_point(self, gate_factory_linear):
        """Create range gate with same bounds."""
        gate = gate_factory_linear.create_range(100, 100)

        assert gate.low == 100
        assert gate.high == 100


class TestGateFactoryParameterUpdates:
    """Test updating factory parameters."""

    @pytest.mark.unit
    def test_update_params(self, gate_factory_linear):
        """Update parameters should affect created gates."""
        gate1 = gate_factory_linear.create_rectangle(0, 0, 100, 100)
        assert gate1.x_param == "FSC-A"

        gate_factory_linear.update_params("CD4", "CD8")
        gate2 = gate_factory_linear.create_rectangle(0, 0, 100, 100)
        assert gate2.x_param == "CD4"
        assert gate2.y_param == "CD8"

    @pytest.mark.unit
    def test_update_scales(self, gate_factory_linear):
        """Update scales should affect coordinate transforms."""
        gate_factory_linear.create_rectangle(1000, 1000, 2000, 2000)

        # Update to biexp
        scale_biexp = AxisScale(TransformType.BIEXPONENTIAL)
        scale_biexp.logicle_m = 5.0
        scale_biexp.logicle_w = 1.0
        scale_biexp.logicle_t = 262144.0
        scale_biexp.logicle_a = 0.0

        gate_factory_linear.update_scales(scale_biexp, scale_biexp)
        gate2 = gate_factory_linear.create_rectangle(1000, 1000, 2000, 2000)

        assert isinstance(gate2, RectangleGate)
        assert gate2.x_scale.transform_type == TransformType.BIEXPONENTIAL
        assert gate2.y_scale.transform_type == TransformType.BIEXPONENTIAL


class TestGateFactoryEdgeCases:
    """Test edge cases."""

    @pytest.mark.unit
    def test_zero_size_rectangle(self, gate_factory_linear):
        """Create zero-size rectangle."""
        gate = gate_factory_linear.create_rectangle(100, 100, 100, 100)
        assert gate.x_min == 100
        assert gate.x_max == 100

    @pytest.mark.unit
    def test_very_small_gate(self, gate_factory_linear):
        """Create very small gate."""
        gate = gate_factory_linear.create_rectangle(100, 100, 100.1, 100.1)
        assert abs(gate.x_max - gate.x_min) < 1

    @pytest.mark.unit
    def test_very_large_gate(self, gate_factory_linear):
        """Create very large gate."""
        gate = gate_factory_linear.create_rectangle(0, 0, 1e6, 1e6)
        assert gate.x_max > 1e5
        assert gate.y_max > 1e5

    @pytest.mark.unit
    def test_negative_coordinates(self, gate_factory_linear):
        """Create gate from negative coordinates."""
        gate = gate_factory_linear.create_rectangle(-100, -100, 100, 100)
        assert gate.x_min == -100
        assert gate.x_max == 100
