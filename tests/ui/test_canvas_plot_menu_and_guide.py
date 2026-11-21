"""A gating plot's right-click menu (copy, download) and the Academy's guide shapes."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from karcytics_sdk.plugin.components import BioMenu
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication

from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.ui.graph.canvas import plot_export
from karcytics_plugins.flow_cytometry.ui.graph.flow_canvas import FlowCanvas


@pytest.fixture
def canvas(qtbot):
    canvas = FlowCanvas(state=FlowState())
    qtbot.addWidget(canvas)
    canvas.set_axes("FSC-A", "SSC-A")
    return canvas


def _choose(action_text: str):
    """A BioMenu.exec stand-in that triggers the action with this text (submenus too)."""

    def exec_(menu, *_args):
        actions = list(menu.actions())
        while actions:
            action = actions.pop(0)
            if action.text() == action_text:
                action.trigger()
                return
            if action.menu() is not None:
                actions += action.menu().actions()
        raise AssertionError(f"no {action_text!r} in the menu")

    return exec_


@pytest.mark.ui
def test_right_click_copies_the_plot_as_an_image(canvas, monkeypatch):
    QApplication.clipboard().clear()
    monkeypatch.setattr(BioMenu, "exec", _choose("📋  Copy to Clipboard (PNG)"))

    canvas.customContextMenuRequested.emit(QPoint(5, 5))

    assert not QApplication.clipboard().image().isNull()


@pytest.mark.ui
@pytest.mark.parametrize("fmt", ["png", "pdf", "svg"])
def test_right_click_downloads_the_plot(canvas, monkeypatch, tmp_path, fmt):
    path = tmp_path / f"plot.{fmt}"
    monkeypatch.setattr(BioMenu, "exec", _choose(fmt.upper()))

    with patch.object(plot_export, "get_save_path", return_value=str(path)):
        canvas.customContextMenuRequested.emit(QPoint(5, 5))

    assert path.stat().st_size > 0


@pytest.mark.ui
def test_cancelling_the_save_dialog_writes_nothing(canvas, tmp_path):
    with patch.object(plot_export, "get_save_path", return_value=None):
        assert plot_export.save_plot(canvas, canvas._fig, "png") is None


def _step(**metadata):
    return SimpleNamespace(metadata=metadata)


@pytest.mark.ui
def test_every_guide_shape_is_drawn_and_cleared(canvas):
    canvas.set_tutorial_guide(
        _step(
            guide_data_poly=[(0, 0), (10, 0), (5, 10)],
            guide_rect=(0.0, 10.0, 0.0, 10.0),
            guide_range=(1.0, 5.0),  # a shaded span and its two edges
            guide_quadrant=(3.0, 3.0),  # two lines
        )
    )
    assert len(canvas.guide.artists) == 7  # noqa: PLR2004
    assert all(artist.axes is canvas._ax for artist in canvas.guide.artists)

    canvas.set_tutorial_guide(None)

    assert canvas.guide.artists == []
    assert not canvas._ax.patches


@pytest.mark.ui
def test_a_step_polygon_in_plot_coordinates_is_drawn(canvas):
    canvas.set_tutorial_guide(SimpleNamespace(guide_poly=[(0, 0), (1, 0), (1, 1)], metadata={}))
    assert len(canvas.guide.artists) == 1


@pytest.mark.ui
def test_the_guide_comes_back_after_a_data_render(canvas):
    canvas.set_tutorial_guide(_step(guide_rect=(0.0, 10.0, 0.0, 10.0)))
    canvas._ax.clear()  # what each data render does
    canvas.guide.forget()

    canvas._on_data_layer_finished()

    assert len(canvas.guide.artists) == 1
    assert canvas.guide.artists[0] in canvas._ax.patches
