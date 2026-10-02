import numpy as np
import pandas as pd
import pytest

from karcytics_plugins.flow_cytometry.analysis.scaling import AxisScale
from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.analysis.transforms import TransformType
from karcytics_plugins.flow_cytometry.ui.graph.render_task import RenderTask


@pytest.fixture
def sample_c_events():
    """Real sample C data for robust rendering tests."""
    # Just need the events for the task
    df = pd.DataFrame(
        {
            "FSC-A": np.random.normal(50000, 10000, 1000),
            "SSC-A": np.random.normal(50000, 10000, 1000),
        }
    )
    return df


@pytest.mark.ui
class TestThumbnailRendering:
    def test_thumbnail_biex_different_from_linear(self, sample_c_events):
        """Biex and linear renders of same data must produce different images."""
        lin_scale = AxisScale(TransformType.LINEAR)
        lin_scale.min_val, lin_scale.max_val = 0, 100000

        biex_scale = AxisScale(TransformType.BIEXPONENTIAL)
        biex_scale.min_val, biex_scale.max_val = 0, 100000

        mock_state = pytest.importorskip("unittest.mock").MagicMock(spec=FlowState)

        # Linear
        task_lin = RenderTask()
        task_lin.configure(
            data=sample_c_events,
            x_param="FSC-A",
            y_param="SSC-A",
            x_scale=lin_scale,
            y_scale=lin_scale,
            x_range=(0, 100000),
            y_range=(0, 100000),
            width_px=100,
            height_px=100,
        )
        res_lin = task_lin.run(mock_state)["image_data"]

        # Biex
        task_biex = RenderTask()
        task_biex.configure(
            data=sample_c_events,
            x_param="FSC-A",
            y_param="SSC-A",
            x_scale=biex_scale,
            y_scale=biex_scale,
            x_range=(0, 100000),
            y_range=(0, 100000),
            width_px=100,
            height_px=100,
        )
        res_biex = task_biex.run(mock_state)["image_data"]

        assert res_lin != res_biex
