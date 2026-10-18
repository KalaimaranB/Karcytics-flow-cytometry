"""A tutorial guide naming its channels is drawn only on plots of those channels."""

from types import SimpleNamespace

from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.ui.graph.flow_canvas import FlowCanvas


def _step(**metadata):
    return SimpleNamespace(metadata={"guide_rect": (0.0, 10.0, 0.0, 10.0), **metadata})


def test_a_guide_for_other_channels_is_not_drawn(qtbot):
    canvas = FlowCanvas(state=FlowState())
    qtbot.addWidget(canvas)
    canvas.set_axes("FSC-A", "SSC-A")

    canvas.set_tutorial_guide(_step(guide_axes=("FITC-A", "Pacific Blue-A")))
    assert canvas._guide_patches == []
    canvas.set_tutorial_guide(_step(guide_axes=("FSC-A", "SSC-A")))
    assert len(canvas._guide_patches) == 1
    canvas.set_tutorial_guide(_step())  # no channels named: drawn as before
    assert len(canvas._guide_patches) == 1
