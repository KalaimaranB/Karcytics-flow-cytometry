"""FigureView: figures drawn off the GUI thread, newest request wins."""

from __future__ import annotations

import threading

import pytest
import shiboken6
from matplotlib.figure import Figure

from karcytics_plugins.flow_cytometry.ui.graph.figure_renderer import IPlotRenderer
from karcytics_plugins.flow_cytometry.ui.widgets.figure_view import FigureView

pytestmark = pytest.mark.ui


class _TitleRenderer(IPlotRenderer):
    """A figure titled ``title``; waits for ``gate`` first, if given."""

    def __init__(self) -> None:
        self.drawn: list[str] = []

    def render(self, **kwargs) -> Figure:
        if (gate := kwargs.get("gate")) is not None:
            assert gate.wait(10)
        if kwargs.get("fail"):
            raise ValueError("no figure")
        self.drawn.append(kwargs["title"])
        fig = Figure()
        fig.add_subplot(111).set_title(kwargs["title"])
        return fig


@pytest.fixture
def view(qtbot):
    widget = FigureView()
    qtbot.addWidget(widget)
    return widget


def _settled(view, qtbot) -> str:
    qtbot.waitUntil(lambda: not view.is_rendering())
    return view.figure.axes[0].get_title() if view.figure is not None else ""


def test_a_drawn_figure_is_shown_and_announced(view, qtbot):
    with qtbot.waitSignal(view.figure_shown) as shown:
        view.draw(_TitleRenderer(), {"title": "one"})

    assert shown.args[0] is view.figure
    assert view.canvas is not None and view.canvas.parent() is view


def test_requests_made_while_drawing_collapse_into_the_newest(view, qtbot):
    renderer, gate = _TitleRenderer(), threading.Event()
    view.draw(renderer, {"title": "first", "gate": gate})
    for title in ("second", "third", "last"):
        view.draw(renderer, {"title": title})
    gate.set()

    assert _settled(view, qtbot) == "last"
    assert renderer.drawn == ["first", "last"]  # the two in between were never drawn


def test_a_message_shown_while_drawing_wins(view, qtbot):
    gate = threading.Event()
    view.draw(_TitleRenderer(), {"title": "late", "gate": gate})
    view.show_message("Nothing to show")
    gate.set()

    assert _settled(view, qtbot) == ""
    assert view._message.text() == "Nothing to show" and not view._message.isHidden()


def test_a_failed_draw_is_reported_and_keeps_the_last_figure(view, qtbot):
    renderer = _TitleRenderer()
    view.draw(renderer, {"title": "good"})
    assert _settled(view, qtbot) == "good"

    with qtbot.waitSignal(view.render_failed) as failed:
        view.draw(renderer, {"title": "bad", "fail": True})

    assert failed.args == ["no figure"]
    assert _settled(view, qtbot) == "good"


def test_closing_mid_draw_waits_for_the_thread(qtbot):
    view, gate = FigureView(), threading.Event()
    view.draw(_TitleRenderer(), {"title": "x", "gate": gate})
    worker = view._workers.current
    threading.Timer(0.2, gate.set).start()

    view.deleteLater()
    # Qt aborts the process if a running QThread is destroyed with its parent.
    qtbot.waitUntil(lambda: not shiboken6.isValid(worker), timeout=5000)
    assert gate.is_set()  # the view's teardown waited the render out
