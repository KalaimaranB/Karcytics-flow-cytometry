import csv
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from karcytics_plugins.flow_cytometry.analysis.compensation import (
    CompensationMatrix,
    apply_compensation,
    calculate_spillover_matrix,
    extract_spill_from_fcs,
    import_matrix_from_csv,
)
from karcytics_plugins.flow_cytometry.analysis.fcs_io import (
    FCSData,
    _auto_apply_spill,
    get_channel_marker_label,
    get_fluorescence_channels,
)
from karcytics_plugins.flow_cytometry.analysis.statistics import (
    StatDefinition,
    StatType,
    compute_population_stats,
    compute_statistic,
)
from karcytics_plugins.flow_cytometry.analysis.transforms import (
    TransformType,
    apply_transform,
    biexponential_transform,
    invert_log_transform,
    invert_transform,
    linear_transform,
    log_transform,
)


def test_linear_transform_returns_same_values():
    values = np.array([0.0, 1.0, 10.0])
    transformed = linear_transform(values)
    assert np.allclose(transformed, values)
    assert transformed.dtype == np.float64


def test_log_transform_clamps_and_scales_values():
    values = np.array([-5.0, 0.5, 10.0])
    transformed = log_transform(values, decades=2.0, min_value=1.0)

    assert transformed[0] == pytest.approx(0.0)
    assert transformed[1] == pytest.approx(0.0)
    assert transformed[2] == pytest.approx(np.log10(10.0) / 2.0)


def test_apply_transform_dispatches_to_correct_function():
    values = np.array([1.0, 10.0])
    assert np.allclose(apply_transform(values, TransformType.LINEAR), values)
    assert np.allclose(apply_transform(values, TransformType.LOG), log_transform(values))
    with pytest.raises(ValueError):
        apply_transform(values, "unsupported")  # type: ignore[arg-type]


def test_invert_transform_dispatches_to_correct_function():
    values = np.array([0.2, 0.5])
    assert np.allclose(invert_transform(values, TransformType.LINEAR), values)
    assert np.allclose(invert_transform(values, TransformType.LOG), invert_log_transform(values))
    with pytest.raises(ValueError):
        invert_transform(values, "unsupported")  # type: ignore[arg-type]


def test_rectangle_gate_contains_raises_key_error_for_missing_y_parameter():
    from karcytics_plugins.flow_cytometry.analysis.gating.rectangle import RectangleGate

    gate = RectangleGate("FSC-A", "SSC-A", x_min=0.0, x_max=1.0, y_min=0.0, y_max=1.0)
    events = pd.DataFrame({"FSC-A": [0.5]})

    with pytest.raises(KeyError, match="SSC-A"):
        gate.contains(events)


def test_quadrant_gate_get_quadrant_q1_upper_left():
    from karcytics_plugins.flow_cytometry.analysis.gating.quadrant import QuadrantGate

    gate = QuadrantGate("FSC-A", "SSC-A", x_mid=0.5, y_mid=0.5)
    events = pd.DataFrame(
        {
            "FSC-A": [0.2, 0.8, 0.2, 0.8],  # x < 0.5, x >= 0.5, x < 0.5, x >= 0.5
            "SSC-A": [0.8, 0.8, 0.2, 0.2],  # y >= 0.5, y >= 0.5, y < 0.5, y < 0.5
        }
    )

    mask = gate.get_quadrant(events, "Q1")
    expected = [True, False, False, False]  # Only first event: x<0.5, y>=0.5
    assert list(mask) == expected


def test_quadrant_gate_get_quadrant_q2_upper_right():
    from karcytics_plugins.flow_cytometry.analysis.gating.quadrant import QuadrantGate

    gate = QuadrantGate("FSC-A", "SSC-A", x_mid=0.5, y_mid=0.5)
    events = pd.DataFrame({"FSC-A": [0.2, 0.8, 0.2, 0.8], "SSC-A": [0.8, 0.8, 0.2, 0.2]})

    mask = gate.get_quadrant(events, "Q2")
    expected = [False, True, False, False]  # Second event: x>=0.5, y>=0.5
    assert list(mask) == expected


def test_quadrant_gate_get_quadrant_q3_lower_left():
    from karcytics_plugins.flow_cytometry.analysis.gating.quadrant import QuadrantGate

    gate = QuadrantGate("FSC-A", "SSC-A", x_mid=0.5, y_mid=0.5)
    events = pd.DataFrame({"FSC-A": [0.2, 0.8, 0.2, 0.8], "SSC-A": [0.8, 0.8, 0.2, 0.2]})

    mask = gate.get_quadrant(events, "Q3")
    expected = [False, False, True, False]  # Third event: x<0.5, y<0.5
    assert list(mask) == expected


def test_quadrant_gate_get_quadrant_q4_lower_right():
    from karcytics_plugins.flow_cytometry.analysis.gating.quadrant import QuadrantGate

    gate = QuadrantGate("FSC-A", "SSC-A", x_mid=0.5, y_mid=0.5)
    events = pd.DataFrame({"FSC-A": [0.2, 0.8, 0.2, 0.8], "SSC-A": [0.8, 0.8, 0.2, 0.2]})

    mask = gate.get_quadrant(events, "Q4")
    expected = [False, False, False, True]  # Fourth event: x>=0.5, y<0.5
    assert list(mask) == expected


def test_quadrant_gate_get_quadrant_with_biexponential_transform():
    from karcytics_plugins.flow_cytometry.analysis.gating.quadrant import QuadrantGate
    from karcytics_plugins.flow_cytometry.analysis.scaling import AxisScale, TransformType

    biexp_scale = AxisScale(transform_type=TransformType.BIEXPONENTIAL)
    biexp_scale.logicle_m = 5.0
    biexp_scale.logicle_w = 1.0
    biexp_scale.logicle_t = 262144.0
    biexp_scale.logicle_a = 0.0

    gate = QuadrantGate(
        "FSC-A",
        "SSC-A",
        x_mid=1000.0,
        y_mid=1000.0,
        x_scale=biexp_scale,
        y_scale=biexp_scale,
    )
    events = pd.DataFrame({"FSC-A": [500.0, 1500.0], "SSC-A": [1500.0, 500.0]})

    mask = gate.get_quadrant(events, "Q1")
    # With biexp transform, 500 < 1000 in display space, 1500 > 1000
    # Q1: x < mid_x, y >= mid_y → first event: x<, y>=
    assert list(mask) == [True, False]


def test_quadrant_gate_get_quadrant_invalid_quadrant():
    from karcytics_plugins.flow_cytometry.analysis.gating.quadrant import QuadrantGate

    gate = QuadrantGate("FSC-A", "SSC-A", x_mid=0.5, y_mid=0.5)
    events = pd.DataFrame({"FSC-A": [0.2], "SSC-A": [0.8]})

    with pytest.raises(ValueError, match="Invalid quadrant"):
        gate.get_quadrant(events, "Q5")


def test_quadrant_gate_get_quadrant_missing_columns():
    from karcytics_plugins.flow_cytometry.analysis.gating.quadrant import QuadrantGate

    gate = QuadrantGate("FSC-A", "SSC-A", x_mid=0.5, y_mid=0.5)
    events = pd.DataFrame({"FSC-A": [0.2]})  # Missing SSC-A

    mask = gate.get_quadrant(events, "Q1")
    assert list(mask) == [False]


def test_quadrant_gate_get_quadrant_with_space_in_quadrant_name():
    from karcytics_plugins.flow_cytometry.analysis.gating.quadrant import QuadrantGate

    gate = QuadrantGate("FSC-A", "SSC-A", x_mid=0.5, y_mid=0.5)
    events = pd.DataFrame({"FSC-A": [0.2, 0.8], "SSC-A": [0.8, 0.8]})

    mask = gate.get_quadrant(events, "Q1 Upper Left")
    expected = [True, False]
    assert list(mask) == expected


def test_invert_log_transform_reverses_log_transform():
    original = np.array([1.0, 10.0, 100.0])
    transformed = log_transform(original, decades=2.0, min_value=1.0)
    inverted = invert_log_transform(transformed, decades=2.0)

    assert np.allclose(inverted, original, atol=1e-8)


def test_compensation_matrix_serialization_round_trip():
    matrix = np.array([[1.0, 0.2], [0.1, 1.0]])
    comp = CompensationMatrix(matrix=matrix, channel_names=["FITC-A", "PE-A"], source="computed")
    restored = CompensationMatrix.from_dict(comp.to_dict())

    assert restored.source == comp.source
    assert restored.channel_names == comp.channel_names
    assert np.allclose(restored.matrix, matrix)


def test_extract_spill_from_fcs_returns_none_for_malformed_string():
    data = FCSData(
        Path("/tmp/test.fcs"),
        channels=["FITC-A", "PE-A"],
        markers=["CD4", "CD8"],
        events=pd.DataFrame(),
    )
    data.metadata = {"$SPILL": "2,FITC-A,PE-A,1.0,0.1"}

    assert extract_spill_from_fcs(data) is None


def test_extract_spill_from_fcs_parses_valid_spill_string():
    data = FCSData(
        Path("/tmp/test.fcs"),
        channels=["FITC-A", "PE-A"],
        markers=["CD4", "CD8"],
        events=pd.DataFrame(),
    )
    data.metadata = {"$SPILL": "2,FITC-A,PE-A,1.0,0.2,0.1,1.0"}

    comp = extract_spill_from_fcs(data)
    assert comp is not None
    assert comp.source == "cytometer"
    assert comp.channel_names == ["FITC-A", "PE-A"]
    assert np.allclose(comp.matrix, np.array([[1.0, 0.2], [0.1, 1.0]]))


def test_import_matrix_from_csv_with_row_labels(tmp_path):
    path = tmp_path / "spill.csv"
    rows = ["", "FITC-A", "PE-A"]
    values = [["FITC-A", "1.0", "0.2"], ["PE-A", "0.1", "1.0"]]
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(rows)
        writer.writerows(values)

    comp = import_matrix_from_csv(path)
    assert comp.channel_names == ["FITC-A", "PE-A"]
    assert np.allclose(comp.matrix, np.array([[1.0, 0.2], [0.1, 1.0]]))


def test_calculate_spillover_matrix_basic_two_stains():
    from pathlib import Path

    from karcytics_plugins.flow_cytometry.analysis.compensation import FCSData

    # Create mock FCS data for two single stains
    fcs1 = FCSData(
        file_path=Path("stain1.fcs"),
        channels=["FITC-A", "PE-A"],
        markers=["CD4", "CD8"],
        events=pd.DataFrame({"FITC-A": [1000, 1100], "PE-A": [10, 15]}),
    )
    fcs2 = FCSData(
        file_path=Path("stain2.fcs"),
        channels=["FITC-A", "PE-A"],
        markers=["CD4", "CD8"],
        events=pd.DataFrame({"FITC-A": [20, 25], "PE-A": [800, 900]}),
    )

    matrix = calculate_spillover_matrix([fcs1, fcs2], fluorescence_channels=["FITC-A", "PE-A"])

    assert matrix.source == "computed"
    assert matrix.channel_names == ["FITC-A", "PE-A"]
    # FITC-A primary for fcs1 (higher median), PE-A primary for fcs2
    # Spillover should be ratios
    assert matrix.matrix[0, 0] == pytest.approx(1.0)  # Diagonal
    assert matrix.matrix[1, 1] == pytest.approx(1.0)
    assert matrix.matrix[0, 1] < 1.0  # Off-diagonal < 1
    assert matrix.matrix[1, 0] < 1.0


def test_calculate_spillover_matrix_with_unstained_background():
    from pathlib import Path

    from karcytics_plugins.flow_cytometry.analysis.compensation import FCSData

    unstained = FCSData(
        file_path=Path("unstained.fcs"),
        channels=["FITC-A", "PE-A"],
        markers=["", ""],
        events=pd.DataFrame({"FITC-A": [50, 60], "PE-A": [40, 45]}),
    )

    fcs1 = FCSData(
        file_path=Path("stain1.fcs"),
        channels=["FITC-A", "PE-A"],
        markers=["CD4", "CD8"],
        events=pd.DataFrame({"FITC-A": [1050, 1160], "PE-A": [60, 75]}),
    )

    fcs2 = FCSData(
        file_path=Path("stain2.fcs"),
        channels=["FITC-A", "PE-A"],
        markers=["CD4", "CD8"],
        events=pd.DataFrame({"FITC-A": [20, 25], "PE-A": [800, 900]}),
    )

    matrix = calculate_spillover_matrix(
        [fcs1, fcs2], unstained=unstained, fluorescence_channels=["FITC-A", "PE-A"]
    )

    assert matrix.source == "computed"
    # Should subtract background before computing ratios
    assert matrix.matrix[0, 0] == pytest.approx(1.0)


def test_calculate_spillover_matrix_requires_at_least_two_stains():
    from pathlib import Path

    from karcytics_plugins.flow_cytometry.analysis.compensation import FCSData

    fcs1 = FCSData(
        file_path=Path("stain1.fcs"),
        channels=["FITC-A"],
        markers=["CD4"],
        events=pd.DataFrame({"FITC-A": [1000]}),
    )

    with pytest.raises(ValueError, match="At least 2 single-stain samples"):
        calculate_spillover_matrix([fcs1])


def test_calculate_spillover_matrix_skips_samples_without_events():
    from pathlib import Path

    from karcytics_plugins.flow_cytometry.analysis.compensation import FCSData

    fcs1 = FCSData(file_path=Path("empty.fcs"), channels=["FITC-A"], markers=[""], events=None)
    fcs2 = FCSData(
        file_path=Path("stain2.fcs"),
        channels=["FITC-A", "PE-A"],
        markers=["", "CD8"],
        events=pd.DataFrame({"FITC-A": [10, 15], "PE-A": [1000, 1100]}),
    )

    matrix = calculate_spillover_matrix([fcs1, fcs2], fluorescence_channels=["FITC-A", "PE-A"])

    # Should still work with one valid sample, but matrix will have unassigned rows
    assert matrix.matrix.shape == (2, 2)


def test_calculate_spillover_matrix_with_negative_median_after_bg():
    from pathlib import Path

    from karcytics_plugins.flow_cytometry.analysis.compensation import FCSData

    unstained = FCSData(
        file_path=Path("unstained.fcs"),
        channels=["FITC-A"],
        markers=[""],
        events=pd.DataFrame({"FITC-A": [1000, 1100]}),  # High background
    )

    fcs1 = FCSData(
        file_path=Path("stain1.fcs"),
        channels=["FITC-A"],
        markers=["CD4"],
        events=pd.DataFrame({"FITC-A": [900, 950]}),  # Lower than background
    )

    fcs2 = FCSData(
        file_path=Path("stain2.fcs"),
        channels=["FITC-A", "PE-A"],
        markers=["", "CD8"],
        events=pd.DataFrame({"FITC-A": [10, 15], "PE-A": [1000, 1100]}),
    )

    matrix = calculate_spillover_matrix(
        [fcs1, fcs2], unstained=unstained, fluorescence_channels=["FITC-A", "PE-A"]
    )

    # Should handle negative medians gracefully
    assert matrix.matrix[0, 0] == pytest.approx(1.0)


def test_extract_spill_from_fcs_with_malformed_string():
    from pathlib import Path

    from karcytics_plugins.flow_cytometry.analysis.compensation import (
        extract_spill_from_fcs,
    )
    from karcytics_plugins.flow_cytometry.analysis.fcs_io import FCSData

    data = FCSData(
        Path("test.fcs"),
        channels=["FITC-A", "PE-A"],
        markers=["", ""],
        events=pd.DataFrame(),
    )
    data.metadata = {"$SPILL": "2,FITC-A,PE-A,1.0,0.2"}  # Missing values

    result = extract_spill_from_fcs(data)
    assert result is None


def test_import_matrix_from_csv_with_no_row_labels(tmp_path):
    from karcytics_plugins.flow_cytometry.analysis.compensation import (
        import_matrix_from_csv,
    )

    path = tmp_path / "spill_no_labels.csv"
    with open(path, "w", newline="") as f:
        f.write("FITC-A,PE-A\n")
        f.write("1.0,0.2\n")
        f.write("0.1,1.0\n")

    matrix = import_matrix_from_csv(path)
    assert matrix.channel_names == ["FITC-A", "PE-A"]
    assert np.allclose(matrix.matrix, np.array([[1.0, 0.2], [0.1, 1.0]]))


def test_apply_compensation_with_no_matching_channels():
    from pathlib import Path

    from karcytics_plugins.flow_cytometry.analysis.fcs_io import FCSData

    events = pd.DataFrame({"FSC-A": [100, 200]})
    data = FCSData(Path("test.fcs"), channels=["FSC-A"], markers=[""], events=events)
    comp = CompensationMatrix(np.eye(2), channel_names=["FITC-A", "PE-A"], source="computed")

    result = apply_compensation(data, comp)
    # Should return unchanged since no matching channels
    assert np.allclose(result["FSC-A"], events["FSC-A"])


def test_calculate_auto_range_linear_basic():
    from karcytics_plugins.flow_cytometry.analysis.scaling import (
        TransformType,
        calculate_auto_range,
    )

    data = np.array([10, 20, 30, 100, 200])
    min_val, max_val = calculate_auto_range(data, TransformType.LINEAR)

    assert min_val <= 10
    assert max_val >= 200
    assert max_val > min_val


def test_calculate_auto_range_linear_with_negative():
    from karcytics_plugins.flow_cytometry.analysis.scaling import (
        TransformType,
        calculate_auto_range,
    )

    data = np.array([-5, 10, 20, 30])
    min_val, max_val = calculate_auto_range(data, TransformType.LINEAR)

    assert min_val < 0  # Should allow negative
    assert max_val >= 30


def test_calculate_auto_range_linear_high_range_snaps_to_262144():
    from karcytics_plugins.flow_cytometry.analysis.scaling import (
        TransformType,
        calculate_auto_range,
    )

    data = np.array([1000, 200000, 250000])
    min_val, max_val = calculate_auto_range(data, TransformType.LINEAR)

    assert max_val == 262144.0


def test_calculate_auto_range_log_positive_data():
    from karcytics_plugins.flow_cytometry.analysis.scaling import (
        TransformType,
        calculate_auto_range,
    )

    data = np.array([1, 10, 100, 1000])
    min_val, max_val = calculate_auto_range(data, TransformType.LOG)

    assert min_val > 0
    assert max_val > min_val
    assert min_val < 1
    assert max_val > 1000


def test_calculate_auto_range_log_all_zero_or_negative():
    from karcytics_plugins.flow_cytometry.analysis.scaling import (
        TransformType,
        calculate_auto_range,
    )

    data = np.array([0, -1, -10])
    min_val, max_val = calculate_auto_range(data, TransformType.LOG)

    assert min_val == 0.1
    assert max_val == 10.0


def test_calculate_auto_range_biexponential_positive():
    from karcytics_plugins.flow_cytometry.analysis.scaling import (
        TransformType,
        calculate_auto_range,
    )

    data = np.array([1, 10, 100, 1000])
    min_val, max_val = calculate_auto_range(data, TransformType.BIEXPONENTIAL)

    assert min_val < 1
    assert max_val > 1000


def test_calculate_auto_range_biexponential_with_negative():
    from karcytics_plugins.flow_cytometry.analysis.scaling import (
        TransformType,
        calculate_auto_range,
    )

    data = np.array([-10, 1, 10, 100])
    min_val, max_val = calculate_auto_range(data, TransformType.BIEXPONENTIAL)

    assert min_val < -10
    assert max_val > 100


def test_calculate_auto_range_empty_data():
    from karcytics_plugins.flow_cytometry.analysis.scaling import (
        TransformType,
        calculate_auto_range,
    )

    data = np.array([])
    min_val, max_val = calculate_auto_range(data, TransformType.LINEAR)

    assert min_val == 0.0
    assert max_val == 1.0


def test_calculate_auto_range_all_nan():
    from karcytics_plugins.flow_cytometry.analysis.scaling import (
        TransformType,
        calculate_auto_range,
    )

    data = np.array([np.nan, np.nan])
    min_val, max_val = calculate_auto_range(data, TransformType.LINEAR)

    assert min_val == 0.0
    assert max_val == 1.0


def test_calculate_auto_range_with_outlier_percentile():
    from karcytics_plugins.flow_cytometry.analysis.scaling import (
        TransformType,
        calculate_auto_range,
    )

    data = np.array([1, 2, 3, 1000])  # 1000 is outlier
    min_val, max_val = calculate_auto_range(data, TransformType.LINEAR, outlier_percentile=10.0)

    # With 10% percentile, should ignore the extreme outlier
    assert max_val < 1000


def test_invert_log_transform_reverses_log():
    from karcytics_plugins.flow_cytometry.analysis.transforms import invert_log_transform

    # Log transform some data
    original = np.array([1.0, 10.0, 100.0])
    transformed = log_transform(original, decades=2.0, min_value=1.0)
    inverted = invert_log_transform(transformed, decades=2.0, min_value=1.0)

    assert np.allclose(inverted, original, rtol=1e-10)


def test_biexponential_transform_with_dithering():
    """Test dithering prevents banding artifacts."""
    # This is hard to test directly, but we can check it doesn't crash
    data = np.array([0.0, 0.1, 0.2])
    result = biexponential_transform(data, enable_dithering=True)
    assert result.shape == data.shape
    assert not np.any(np.isnan(result))


def test_scale_factory_parse_none():
    from karcytics_plugins.flow_cytometry.analysis._utils import ScaleFactory

    scale = ScaleFactory.parse(None)
    assert scale.transform_type == TransformType.LINEAR


def test_scale_factory_parse_axis_scale():
    from karcytics_plugins.flow_cytometry.analysis._utils import ScaleFactory
    from karcytics_plugins.flow_cytometry.analysis.scaling import AxisScale

    original = AxisScale(TransformType.LOG)
    parsed = ScaleFactory.parse(original)
    assert parsed is original


def test_scale_factory_parse_dict():
    from karcytics_plugins.flow_cytometry.analysis._utils import ScaleFactory

    d = {"transform_type": "log", "min_val": 1.0, "max_val": 100.0}
    scale = ScaleFactory.parse(d)
    assert scale.transform_type == TransformType.LOG
    assert scale.min_val == 1.0
    assert scale.max_val == 100.0


def test_scale_factory_parse_invalid_dict():
    from karcytics_plugins.flow_cytometry.analysis._utils import ScaleFactory

    # Invalid dict should fall back to LINEAR
    scale = ScaleFactory.parse({"invalid": "data"})
    assert scale.transform_type == TransformType.LINEAR


def test_transform_type_resolver_resolve_enum():
    from karcytics_plugins.flow_cytometry.analysis._utils import TransformTypeResolver

    resolved = TransformTypeResolver.resolve(TransformType.BIEXPONENTIAL)
    assert resolved == TransformType.BIEXPONENTIAL


def test_transform_type_resolver_resolve_string():
    from karcytics_plugins.flow_cytometry.analysis._utils import TransformTypeResolver

    resolved = TransformTypeResolver.resolve("biexponential")
    assert resolved == TransformType.BIEXPONENTIAL

    resolved = TransformTypeResolver.resolve("BIEXPONENTIAL")
    assert resolved == TransformType.BIEXPONENTIAL


def test_transform_type_resolver_resolve_invalid():
    from karcytics_plugins.flow_cytometry.analysis._utils import TransformTypeResolver

    resolved = TransformTypeResolver.resolve("invalid")
    assert resolved == TransformType.LINEAR


def test_biexponential_parameters_from_scale():
    from karcytics_plugins.flow_cytometry.analysis._utils import BiexponentialParameters
    from karcytics_plugins.flow_cytometry.analysis.scaling import AxisScale

    scale = AxisScale(TransformType.BIEXPONENTIAL)
    scale.logicle_t = 1000.0
    scale.logicle_w = 2.0
    scale.logicle_m = 5.0
    scale.logicle_a = 1.0

    params = BiexponentialParameters(scale)
    assert params.top == 1000.0
    assert params.width == 2.0
    assert params.positive == 5.0
    assert params.negative == 1.0


def test_biexponential_parameters_defaults():
    from karcytics_plugins.flow_cytometry.analysis._utils import BiexponentialParameters
    from karcytics_plugins.flow_cytometry.analysis.scaling import AxisScale

    scale = AxisScale(TransformType.LINEAR)  # No logicle params

    params = BiexponentialParameters(scale)
    assert params.top == 262144
    assert params.width == 1.0
    assert params.positive == 4.5
    assert params.negative == 0.0


def test_biexponential_parameters_to_dict():
    from karcytics_plugins.flow_cytometry.analysis._utils import BiexponentialParameters
    from karcytics_plugins.flow_cytometry.analysis.scaling import AxisScale

    scale = AxisScale(TransformType.BIEXPONENTIAL)
    params = BiexponentialParameters(scale)
    d = params.to_dict()

    assert d["top"] == 262144
    assert d["width"] == 1.0
    assert d["positive"] == 4.5
    assert d["negative"] == 0.0


def test_scale_serializer_to_dict():
    from karcytics_plugins.flow_cytometry.analysis._utils import ScaleSerializer
    from karcytics_plugins.flow_cytometry.analysis.scaling import AxisScale

    scale = AxisScale(TransformType.LOG)
    d = ScaleSerializer.to_dict(scale)

    assert d["transform_type"] == "log"
    assert isinstance(d["transform_type"], str)


def test_statistics_builder_build():
    from karcytics_plugins.flow_cytometry.analysis._utils import StatisticsBuilder

    stats = StatisticsBuilder.build(count=100, pct_parent=50.123, pct_total=25.678)
    assert stats["count"] == 100
    assert stats["pct_parent"] == 50.12  # Rounded
    assert stats["pct_total"] == 25.68


def test_fcsdata_properties_count_channels():
    events = pd.DataFrame({"FSC-A": [1, 2], "FITC-A": [3, 4]})
    data = FCSData(Path("a.fcs"), channels=["FSC-A", "FITC-A"], markers=["", "CD4"], events=events)

    assert data.num_events == 2
    assert data.num_channels == 2


def test_get_fluorescence_channels_filters_scatter_and_time():
    data = FCSData(
        Path("a.fcs"),
        channels=["FSC-A", "SSC-A", "Time", "FITC-A"],
        markers=["", "", "", "CD4"],
        events=pd.DataFrame(),
    )
    assert get_fluorescence_channels(data) == ["FITC-A"]


def test_get_channel_marker_label_uses_marker_when_available():
    data = FCSData(Path("a.fcs"), channels=["FITC-A"], markers=["CD4"], events=pd.DataFrame())
    assert get_channel_marker_label(data, "FITC-A") == "CD4 (FITC-A)"
    assert get_channel_marker_label(data, "unknown") == "unknown"


def test_auto_apply_spill_returns_false_for_missing_metadata():
    events = pd.DataFrame({"FITC-A": [100.0, 200.0]})
    events_copy = events.copy()
    result = _auto_apply_spill("test.fcs", events_copy, {})
    assert result is False
    assert np.allclose(events_copy["FITC-A"], events["FITC-A"])


def test_auto_apply_spill_applies_compensation_to_present_channels():
    events = pd.DataFrame({"PE-A": [1.0, 2.0]})
    md = {"$SPILL": "2,FITC-A,PE-A,1.0,0.0,0.0,1.0"}
    result = _auto_apply_spill("test.fcs", events, md)

    assert result is True
    assert np.allclose(events["PE-A"], [1.0, 2.0])


def test_auto_apply_spill_applies_compensation_in_place():
    events = pd.DataFrame({"FITC-A": [1.0, 2.0], "PE-A": [1.0, 2.0]})
    md = {"$SPILL": "2,FITC-A,PE-A,1.0,0.5,0.5,1.0"}
    result = _auto_apply_spill("test.fcs", events, md)
    assert result is True
    assert not np.allclose(events["FITC-A"], [1.0, 2.0])


def test_compute_statistic_count_and_percentages():
    events = pd.DataFrame({"FITC-A": [10, 20, 30]})
    assert compute_statistic(events, None, StatType.COUNT) == 3.0
    assert compute_statistic(events, None, StatType.PERCENT_TOTAL, total_count=6) == 50.0
    assert compute_statistic(events, None, StatType.PERCENT_PARENT, parent_count=3) == 100.0
    assert (
        compute_statistic(events, None, StatType.PERCENT_GRANDPARENT, grandparent_count=6) == 50.0
    )


def test_compute_statistic_parameter_dependent_stats_and_errors():
    events = pd.DataFrame({"FITC-A": [1.0, 2.0, 3.0]})
    assert compute_statistic(events, "FITC-A", StatType.MFI) == pytest.approx(2.0)
    assert compute_statistic(events, "FITC-A", StatType.CV) == pytest.approx(
        np.std([1.0, 2.0, 3.0], ddof=1) / np.mean([1.0, 2.0, 3.0]) * 100
    )

    with pytest.raises(ValueError):
        compute_statistic(events, None, StatType.MEAN)
    with pytest.raises(ValueError):
        compute_statistic(events, "UNKNOWN", StatType.MEAN)


def test_compute_population_stats_logs_errors_without_failing():
    events = pd.DataFrame({"FITC-A": [1.0]})
    definitions = [
        StatDefinition(stat_type=StatType.MEAN, parameter="FITC-A"),
        StatDefinition(stat_type=StatType.MEAN, parameter="UNKNOWN"),
    ]
    results = compute_population_stats(events, definitions)

    assert len(results) == 2
    assert results[0].value == pytest.approx(1.0)
    assert results[1].value == 0.0
    assert results[1].formatted.startswith("Error:")


@pytest.mark.parametrize(
    ("stat_type", "expected"),
    [
        (StatType.MEAN, 20.0),
        (StatType.MEDIAN, 20.0),
        (StatType.SD, np.std([10.0, 20.0, 30.0], ddof=1)),
        (StatType.MIN, 10.0),
        (StatType.MAX, 30.0),
    ],
)
def test_compute_statistic_value_stats_dispatch_correctly(stat_type, expected):
    events = pd.DataFrame({"FITC-A": [10.0, 20.0, 30.0]})
    assert compute_statistic(events, "FITC-A", stat_type) == pytest.approx(expected)


def test_compute_statistic_geometric_mean():
    events = pd.DataFrame({"FITC-A": [1.0, 10.0, 100.0]})
    assert compute_statistic(events, "FITC-A", StatType.GEOMETRIC_MEAN) == pytest.approx(10.0)


def test_compute_statistic_geometric_mean_all_non_positive_returns_zero():
    events = pd.DataFrame({"FITC-A": [-1.0, 0.0, -5.0]})
    assert compute_statistic(events, "FITC-A", StatType.GEOMETRIC_MEAN) == 0.0


def test_compute_statistic_mode_returns_bin_center_of_densest_bin():
    events = pd.DataFrame({"FITC-A": [1.0] * 20 + [100.0]})
    mode = compute_statistic(events, "FITC-A", StatType.MODE)
    # The densest bin sits near the 20-point cluster at 1.0, far from the
    # single outlier at 100.0 — exact bin edges depend on numpy's "auto"
    # histogram binning, so just assert it lands on the populated side.
    assert mode < 50.0
