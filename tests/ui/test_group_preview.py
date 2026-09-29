from unittest.mock import MagicMock

import numpy as np
import pandas as pd

from karcytics_plugins.flow_cytometry.analysis.state import FlowState

# Real construction + rebuild behavior for GroupPreviewPanel/PreviewThumbnail
# is exercised by tests/ui/test_main_panel_smoke.py::test_group_preview_panel_initialization
# (asserts `len(panel._thumbnails) > 0` after a real rebuild) — pure
# construction/attribute-existence checks were removed as no-unique-signal
# per SDK_Abstraction_Performance_Plan.md Priority 4.


def test_render_task_for_preview():
    from karcytics_plugins.flow_cytometry.analysis.scaling import AxisScale
    from karcytics_plugins.flow_cytometry.analysis.transforms import TransformType
    from karcytics_plugins.flow_cytometry.ui.graph.render_task import RenderTask

    data = pd.DataFrame(
        {
            "FSC-A": np.random.normal(50000, 10000, 100),
            "SSC-A": np.random.normal(50000, 10000, 100),
        }
    )

    scale = AxisScale(TransformType.LINEAR)
    scale.min_val, scale.max_val = 0, 100000

    task = RenderTask()
    task.configure(
        data=data,
        x_param="FSC-A",
        y_param="SSC-A",
        x_scale=scale,
        y_scale=scale,
        x_range=(0, 100000),
        y_range=(0, 100000),
        width_px=100,
        height_px=100,
        plot_type="pseudocolor",
    )

    # Mock state for AnalysisBase.run
    mock_state = MagicMock(spec=FlowState)

    result = task.run(mock_state)

    assert "image_data" in result
    assert isinstance(result["image_data"], bytes)
    assert len(result["image_data"]) > 0
    assert result["width"] == 100
    assert result["height"] == 100
