"""The node canvas's overlay: the SDK zoom strip plus its own Pan toggle."""

import pytest
from karcytics_sdk.plugin import ZoomControls
from PySide6.QtWidgets import QGraphicsView

from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.ui.widgets.node_canvas.canvas_view import NodeCanvas


@pytest.mark.ui
def test_the_zoom_strip_zooms_the_view_and_pan_toggles_dragging(qtbot):
    canvas = NodeCanvas(FlowState())
    qtbot.addWidget(canvas)
    strip = canvas.findChild(ZoomControls)
    view = canvas._view

    before = view.transform().m11()
    strip.zoom_in_button.click()
    assert view.transform().m11() > before
    strip.zoom_out_button.click()
    assert view.transform().m11() == pytest.approx(before)

    canvas.btn_pan.click()
    assert view.dragMode() == QGraphicsView.DragMode.ScrollHandDrag
    canvas.btn_pan.click()
    assert view.dragMode() == QGraphicsView.DragMode.NoDrag
