"""Tests for the step-by-step picture of a fit."""

from __future__ import annotations

import numpy as np
import pytest

from karcytics_plugins.flow_cytometry.ui.widgets import method_illustration
from karcytics_plugins.flow_cytometry.ui.widgets.matrix_sources import FitIllustration
from karcytics_plugins.flow_cytometry.ui.widgets.method_illustration import (
    STEP_PLAIN_FIT,
    STEP_RECORDED,
    STEP_REMOVED,
    STEP_ROBUST_FIT,
    FitIllustrationView,
)

pytestmark = pytest.mark.ui


@pytest.fixture
def fit():
    rng = np.random.default_rng(1)
    x = rng.uniform(0, 5000, 400)
    y = 0.2 * x + rng.normal(0, 20, 400)
    ignored = np.zeros(400, dtype=bool)
    ignored[:20] = True
    y[:20] += 3000
    return FitIllustration(
        tube="FMO PE",
        missing="PE-A",
        other="FITC-A",
        x=x,
        y=y,
        ignored=ignored,
        slope=0.2,
        plain_slope=0.26,
        events=400,
    )


@pytest.fixture
def view(qtbot, fit):
    view = FitIllustrationView()
    qtbot.addWidget(view)
    view.show_fit(fit)
    return view


def _points(view) -> np.ndarray:
    return np.asarray(view._ax.collections[0].get_offsets())


def _lines(view) -> list[str]:
    return [line.get_label() for line in view._ax.lines if not line.get_label().startswith("_")]


def test_it_opens_on_the_raw_events_with_no_fit_drawn(view, fit):
    assert view.step == STEP_RECORDED
    np.testing.assert_allclose(_points(view)[:, 1], fit.y)
    assert _lines(view) == []
    assert "1 · What the tube recorded" in view._caption.text()
    assert not view._btn_back.isEnabled() and view._btn_next.isEnabled()


def test_each_step_adds_its_part_of_the_story(view, fit):
    view.go_to(STEP_PLAIN_FIT)
    assert _lines(view) == ["ordinary fit: slope 0.260"]

    view.go_to(STEP_ROBUST_FIT)
    assert _lines(view) == ["robust fit: slope 0.200"]
    assert "grey: 5.0% of this tube" in view._caption.text()

    view.go_to(STEP_REMOVED)
    removed = _points(view)[:, 1]
    np.testing.assert_allclose(removed, fit.y - 0.2 * fit.x)
    # The cloud is flat: nothing left that climbs with the other dye.
    assert abs(np.polyfit(fit.x[20:], removed[20:], 1)[0]) < 0.01
    assert not view._btn_next.isEnabled()


def test_next_animates_the_step_and_the_view_does_not_jump(view, fit, monkeypatch):
    view.go_to(STEP_ROBUST_FIT)
    limits = view._ax.get_ylim()

    view._btn_next.click()  # into "remove it", starting from nothing removed
    np.testing.assert_allclose(_points(view)[:, 1], fit.y)
    assert view._timer.isActive()

    for _ in range(method_illustration._FRAMES_PER_STEP):
        view._tick()
    np.testing.assert_allclose(_points(view)[:, 1], fit.y - 0.2 * fit.x)
    assert not view._timer.isActive()
    assert view._ax.get_ylim() == limits


def test_play_runs_every_step_then_stops(view):
    view.go_to(STEP_REMOVED)

    view.play()
    assert view.step == STEP_RECORDED and view._timer.isActive()

    seen = [view.step]
    for _ in range(200):
        if not view._timer.isActive():
            break
        view._tick()
        seen.append(view.step)
    assert seen[-1] == STEP_REMOVED and sorted(set(seen)) == [0, 1, 2, 3]
    assert not view._timer.isActive()


def test_stepping_by_hand_interrupts_playback(view):
    view.play()

    view.go_to(STEP_PLAIN_FIT)

    assert view.step == STEP_PLAIN_FIT and not view._timer.isActive()


def test_no_fit_clears_the_picture(view):
    view.show_fit(None)

    assert view._caption.text() == "" and not view._btn_play.isEnabled()
