from unittest.mock import MagicMock

import numpy as np
import pytest

from karcytics_plugins.flow_cytometry.ui.graph.renderers.cdf import CdfStrategy
from karcytics_plugins.flow_cytometry.ui.graph.renderers.contour import ContourStrategy
from karcytics_plugins.flow_cytometry.ui.graph.renderers.dotplot import DotPlotStrategy
from karcytics_plugins.flow_cytometry.ui.graph.renderers.factory import (
    RenderStrategyFactory,
)
from karcytics_plugins.flow_cytometry.ui.graph.renderers.histogram import HistogramStrategy
from karcytics_plugins.flow_cytometry.ui.graph.renderers.pseudocolor import (
    PseudocolorStrategy,
)


@pytest.fixture
def mock_ax():
    ax = MagicMock()
    ax.get_xlim.return_value = (0.0, 100000.0)
    ax.get_ylim.return_value = (0.0, 100000.0)
    ax.hist.return_value = (np.array([1]), np.array([0, 1]), [MagicMock()])
    return ax


@pytest.fixture
def dummy_data():
    x = np.random.normal(100000, 20000, 1000)
    y = np.random.normal(50000, 10000, 1000)
    return x, y


def test_strategy_factory():
    """Verify the factory returns the correct strategies and falls back gracefully."""
    assert type(RenderStrategyFactory.get_strategy("Pseudocolor")) is PseudocolorStrategy

    # Unknown strategy falls back to Dot Plot
    assert type(RenderStrategyFactory.get_strategy("UnknownStrategyName")) is DotPlotStrategy


def test_pseudocolor_strategy_render(mock_ax, dummy_data):
    x, y = dummy_data
    strategy = PseudocolorStrategy()

    data = strategy.compute(x, y, xlim=mock_ax.get_xlim(), ylim=mock_ax.get_ylim())
    strategy.draw(mock_ax, data)
    # Pseudocolor uses ax.scatter
    mock_ax.scatter.assert_called_once()


def test_dotplot_strategy_render(mock_ax, dummy_data):
    x, y = dummy_data
    strategy = DotPlotStrategy()

    data = strategy.compute(x, y)
    strategy.draw(mock_ax, data)
    mock_ax.scatter.assert_called_once()

    # Check that performance optimization configs are passed
    call_kwargs = mock_ax.scatter.call_args[1]
    assert call_kwargs.get("rasterized") is True


def test_histogram_strategy_render(mock_ax, dummy_data):
    x, _ = dummy_data
    strategy = HistogramStrategy()

    # Histogram only uses x data, but API takes y=None or ignores it
    data = strategy.compute(x, None, bins=128)
    strategy.draw(mock_ax, data, bins=128)
    # Histogram uses ax.hist
    assert mock_ax.hist.called


def test_histogram_bins_span_the_visible_range_not_the_outliers():
    strategy = HistogramStrategy()
    x = np.append(np.linspace(0, 100, 1000), [1e6])  # one far outlier

    unbounded = strategy.compute(x, None, bins=10)
    assert unbounded.bin_edges[-1] == 1e6  # no axis range given: the data's extent

    data = strategy.compute(x, None, xlim=(0, 100), bins=10)
    assert (data.bin_edges[0], data.bin_edges[-1]) == (0, 100)
    assert len(data.valid_x) == 1000  # the off-screen outlier isn't counted

    # An unusable range falls back to the data's extent.
    assert strategy.compute(x, None, xlim=(5, 5), bins=10).bin_edges[-1] == 1e6
    # Nothing in view: nothing to draw.
    assert strategy.compute(x, None, xlim=(2e6, 3e6), bins=10) is None


def test_histogram_without_highlight_draws_one_series_in_bar_color(mock_ax, dummy_data):
    x, _ = dummy_data
    strategy = HistogramStrategy()

    data = strategy.compute(x, None)
    strategy.draw(mock_ax, data, color="#2196F3")

    assert data.highlight_x is None
    assert mock_ax.hist.call_count == 1
    assert mock_ax.hist.call_args.kwargs["color"] == "#2196F3"


def test_histogram_highlight_shares_bins_and_takes_the_bar_color(mock_ax, dummy_data):
    x, _ = dummy_data
    strategy = HistogramStrategy()
    gated = np.append(x[x > 100000], np.nan)  # non-finite values are dropped

    data = strategy.compute(x, None, highlight_x=gated)
    strategy.draw(mock_ax, data, color="#2196F3")

    population, highlight = mock_ax.hist.call_args_list
    assert population.kwargs["color"] != "#2196F3"  # the population becomes the backdrop
    assert highlight.kwargs["color"] == "#2196F3"
    assert highlight.kwargs["bins"] is population.kwargs["bins"]
    assert len(highlight.args[0]) == len(gated) - 1
    assert highlight.kwargs["weights"] is None


def test_histogram_highlight_is_scaled_to_the_population_in_frequency_mode(mock_ax, dummy_data):
    x, _ = dummy_data
    strategy = HistogramStrategy()
    gated = x[: len(x) // 4]

    data = strategy.compute(x, None, highlight_x=gated, y_axis_mode="frequency")
    strategy.draw(mock_ax, data)

    weights = mock_ax.hist.call_args_list[1].kwargs["weights"]
    bin_width = data.bin_edges[1] - data.bin_edges[0]
    # A quarter of the events must cover a quarter of the population's unit area.
    assert weights.sum() * bin_width == pytest.approx(0.25)


def test_histogram_empty_highlight_draws_only_the_backdrop(mock_ax, dummy_data):
    x, _ = dummy_data
    strategy = HistogramStrategy()

    data = strategy.compute(x, None, highlight_x=np.array([]))
    strategy.draw(mock_ax, data, color="#2196F3")

    assert mock_ax.hist.call_count == 1
    assert mock_ax.hist.call_args.kwargs["color"] != "#2196F3"


def _render_state(df, highlight_gate=None, display_mode=None, backgate_mask=None):
    from karcytics_plugins.flow_cytometry.analysis.scaling import AxisScale
    from karcytics_plugins.flow_cytometry.analysis.transforms import TransformType
    from karcytics_plugins.flow_cytometry.ui.graph.canvas.data_layer import FlowRenderState
    from karcytics_plugins.flow_cytometry.ui.graph.flow_canvas import DisplayMode

    return FlowRenderState(
        current_data=df,
        x_param="FSC-A",
        y_param="SSC-A",
        x_scale=AxisScale(TransformType.LINEAR),
        y_scale=AxisScale(TransformType.LINEAR),
        display_mode=display_mode or DisplayMode.HISTOGRAM,
        x_label="FSC-A",
        y_label="SSC-A",
        fmo_sample_id=None,
        flow_state=None,
        quality_multiplier=1.0,
        max_events=None,
        render_config=None,
        highlight_gate=highlight_gate,
        backgate_mask=backgate_mask,
    )


def test_compute_stage_highlights_the_events_inside_the_gate():
    import pandas as pd

    from karcytics_plugins.flow_cytometry.analysis.gating import RangeGate, RectangleGate
    from karcytics_plugins.flow_cytometry.ui.graph.canvas.data_layer import FlowDataComputeStage

    df = pd.DataFrame({"FSC-A": [10.0, 20.0, 30.0, 40.0], "SSC-A": [1.0, 2.0, 3.0, 4.0]})
    stage = FlowDataComputeStage()

    assert stage.compute(_render_state(df)).strategy_data.highlight_x is None

    gate = RectangleGate("FSC-A", "SSC-A", x_min=15, x_max=45, y_min=0, y_max=3.5)
    inside = stage.compute(_render_state(df, gate)).strategy_data.highlight_x
    assert sorted(inside) == [20.0, 30.0]

    # A gate on a channel the frame doesn't carry is skipped, not fatal.
    result = stage.compute(_render_state(df, RangeGate("APC-A", low=0, high=1)))
    assert result.mode == "1d"
    assert result.strategy_data.highlight_x is None


def test_compute_stage_backgates_the_masked_rows():
    import pandas as pd

    from karcytics_plugins.flow_cytometry.analysis.gating import RangeGate
    from karcytics_plugins.flow_cytometry.ui.graph.canvas.data_layer import FlowDataComputeStage
    from karcytics_plugins.flow_cytometry.ui.graph.flow_canvas import DisplayMode

    df = pd.DataFrame({"FSC-A": [10.0, 20.0, 30.0, 40.0], "SSC-A": [1.0, 2.0, 3.0, 4.0]})
    mask = np.array([True, False, True, False])
    stage = FlowDataComputeStage()

    dots = stage.compute(_render_state(df, display_mode=DisplayMode.DOT_PLOT, backgate_mask=mask))
    assert dots.backgate_xy.tolist() == [[10.0, 1.0], [30.0, 3.0]]

    # In 1-D the backgated rows are the highlight, ahead of any highlight gate.
    gate = RangeGate("FSC-A", low=35, high=45)
    hist = stage.compute(_render_state(df, gate, backgate_mask=mask))
    assert sorted(hist.strategy_data.highlight_x) == [10.0, 30.0]

    # A mask for another frame (wrong length) is ignored rather than misapplied.
    stale = stage.compute(
        _render_state(df, display_mode=DisplayMode.DOT_PLOT, backgate_mask=mask[:2])
    )
    assert stale.backgate_xy is None


def test_contour_strategy_render(mock_ax, dummy_data):
    x, y = dummy_data
    strategy = ContourStrategy()

    data = strategy.compute(x, y, xlim=mock_ax.get_xlim(), ylim=mock_ax.get_ylim(), levels=10)
    strategy.draw(mock_ax, data, levels=10)
    # Contour uses ax.contour or ax.contourf
    assert mock_ax.contour.called or mock_ax.contourf.called


def test_cdf_strategy_render(mock_ax, dummy_data):
    x, _ = dummy_data
    strategy = CdfStrategy()

    data = strategy.compute(x, None)
    strategy.draw(mock_ax, data)
    # CDF usually uses ax.plot
    assert mock_ax.plot.called
