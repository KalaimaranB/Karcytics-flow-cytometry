"""The Learning Compensation deck, played through slide by slide with real plot events."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QSlider

from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.ui.widgets.spectral_learning.calculator import evaluate
from karcytics_plugins.flow_cytometry.ui.widgets.spectral_learning.one_rule import (
    compensated_dp,
    spillover,
    three_cells,
)
from karcytics_plugins.flow_cytometry.ui.widgets.spectral_learning.scenes import (
    spill_fraction,
    spill_matrix,
    teaching_pair,
)
from karcytics_plugins.flow_cytometry.ui.widgets.spectral_learning.slide import AnswerBox
from karcytics_plugins.flow_cytometry.ui.widgets.spectral_viewer import SpectralViewer

pytestmark = pytest.mark.ui


def _em(peak: float) -> list[list[float]]:
    return [[float(x), float(np.exp(-(((x - peak) / 30) ** 2)))] for x in np.arange(350, 800)]


TWO_DYES = {
    "fitc": {"em_data": _em(520), "display_label": "FITC"},
    "pe": {"em_data": _em(560), "display_label": "PE"},
}


@pytest.fixture
def deck(qtbot):
    viewer = SpectralViewer(FlowState(), MagicMock(), None)
    qtbot.addWidget(viewer)
    viewer._active_fluors = dict(TWO_DYES)
    deck = viewer.learning_tab
    deck.update_view()
    return deck


def _place_filter(deck):
    """Slide 1: drag the filter band from where it starts onto the detector dye's peak."""
    slide = deck.slides[0]
    _press(deck, slide._filter_x, 0.5)
    _drag(deck, slide._peak_x + 1, 0.5)
    _release(deck)


def _press(deck, x, y):
    deck._on_press(SimpleNamespace(inaxes=deck._ax, xdata=x, ydata=y))


def _drag(deck, x, y):
    deck._on_move(SimpleNamespace(inaxes=deck._ax, xdata=x, ydata=y))


def _release(deck):
    deck._on_release(SimpleNamespace(inaxes=None, xdata=None, ydata=None))


def _answer(deck, text: str) -> AnswerBox:
    box = next(b for b in deck.findChildren(AnswerBox) if b.isVisibleTo(deck))
    box.input.setText(text)
    box.submitted.emit()
    return box


def _next(deck):
    assert deck._btn_next.isEnabled()
    deck._btn_next.click()


def _done(deck) -> bool:
    return deck._current_step in deck._completed_steps


def test_with_one_dye_the_deck_waits_and_ignores_clicks(deck):
    deck._viewer._active_fluors = {"fitc": TWO_DYES["fitc"]}
    deck.update_view()

    assert deck._step_label.text() == "Waiting for Selection..."
    _press(deck, 0.5, 0.5)  # no slide to pass it to
    _release(deck)


def test_step_1_drag_the_filter_onto_the_peak_then_pick_the_leaking_dye(deck):
    slide = deck.slides[0]
    assert not deck._btn_next.isEnabled()
    assert abs(slide._filter_x - slide._peak_x) > 30  # it starts away from the peak

    _place_filter(deck)
    assert slide.filter_placed

    _press(deck, slide._peak_x + 150, 0.5)
    assert slide.wrong_hint == "Click inside the shaded detector band."
    _press(deck, slide._peak_x, slide._heights[deck.pair.dye_a])

    assert _done(deck)
    assert "Correct!" in deck._explanation.toPlainText()


def test_step_1_a_filter_dropped_off_the_peak_stays_unplaced(deck):
    slide = deck.slides[0]
    _press(deck, slide._filter_x, 0.5)
    _drag(deck, slide._peak_x + 100, 0.5)
    _release(deck)

    assert not deck.slides[0].filter_placed


def test_step_2_predict_first_then_clear_the_cloud(deck):
    deck._go_to(1)
    slide = deck.slides[1]

    deck._on_link(QUrl("predict_wrong"))
    assert slide.wrong_hint and not slide.predicted
    deck._on_link(QUrl("predict_correct"))

    _press(deck, 800, 800)
    _drag(deck, 600, 600)
    _release(deck)
    assert not _done(deck)  # inside the cloud's reach: try again from where it was dropped
    assert slide._at == (600, 600)

    _press(deck, 600, 600)
    _drag(deck, 200, 210)
    _release(deck)
    assert _done(deck)


def test_step_3_measure_the_slope_then_type_what_it_implies(deck):
    deck._go_to(2)
    slide = deck.slides[2]
    slope = deck.pair.pct / 100

    _press(deck, 700, 700 * slope)
    _drag(deck, 760, 760 * slope)
    _release(deck)
    assert slide.wrong_hint == "Drag your two points further apart for a reliable reading."

    _press(deck, 650, 650 * slope)
    _drag(deck, 950, 950 * slope)
    assert "Rise" in deck._readout.text() and "Run" in deck._readout.text()
    assert "%" not in deck._readout.text()  # the learner works the % out
    _release(deck)
    assert slide.measured

    box = _answer(deck, "999")
    assert box.error.isVisibleTo(box)
    assert not _done(deck)
    _answer(deck, f"{deck.pair.pct:.1f}%")
    assert _done(deck)


def _level(deck, pct: float) -> None:
    """Slide 4: set the slider to ``pct``."""
    slider = deck.findChild(QSlider, "LevelSlider")
    slider.setValue(round(pct * 2))


def test_step_4_the_slider_counts_only_when_held_level(deck, qtbot):
    deck._go_to(3)
    slide = deck.slides[3]

    _level(deck, 0)
    assert "under-compensated" in slide._status.text()
    _level(deck, deck.pair.pct * 2)
    assert "over-compensated" in slide._status.text()
    assert not deck._ticker.isActive()

    _level(deck, deck.pair.pct)
    assert "level" in slide._status.text() and deck._ticker.isActive()
    qtbot.waitUntil(lambda: _done(deck), timeout=3000)
    assert "Step 3" in deck._explanation.toPlainText()


def test_step_4_moving_off_level_before_the_hold_does_not_count(deck):
    deck._go_to(3)
    _level(deck, deck.pair.pct)
    _level(deck, 0)
    deck.slides[3].on_tick()  # a late tick from the first, abandoned hold

    assert not _done(deck)
    assert not deck._ticker.isActive()


def test_step_5_worked_then_half_done_then_alone(deck):
    deck._go_to(4)
    slide = deck.slides[4]
    pct = deck.pair.pct

    deck._on_link(QUrl("s4_same"))
    assert slide.stage == "rule" and slide.wrong_hint
    deck._on_link(QUrl("s4_proportional"))
    assert slide.stage == "bright"

    box = _answer(deck, "lots")
    assert box.error.text() == "Enter a number, e.g. 90"
    assert "dim cell" in _answer(deck, f"{spillover(pct, 300):.0f}").error.text()
    _answer(deck, f"{spillover(pct, 900):.0f}")
    assert slide.stage == "both"

    _answer(deck, f"{compensated_dp(pct, three_cells(pct)):.0f}")
    assert _done(deck)


def test_step_6_a_gate_released_off_the_plot_still_counts(deck):
    deck._go_to(5)
    _press(deck, 50, 50)  # takes in the background too
    _drag(deck, 900, 900)
    _release(deck)
    assert not _done(deck)

    _press(deck, 420, 420)
    _drag(deck, 850, 850)
    _release(deck)  # off the plot: judged on the gate as last drawn

    assert _done(deck)


def test_step_7_the_single_stain_tube_then_one_tube_per_dye_plus_unstained(deck):
    deck._go_to(6)
    slide = deck.slides[6]
    deck._on_link(QUrl("mc_full"))
    assert "isolate" in slide.wrong_hint
    deck._on_link(QUrl("mc_single"))

    assert _answer(deck, "2.5").error.text() == "Enter a whole number."
    _answer(deck, "3")

    assert _done(deck)
    snapshot = deck.academy_snapshot()
    assert snapshot.step == snapshot.last_step
    assert snapshot.last_step in snapshot.completed


def test_next_unlocks_only_once_the_slide_is_done(deck):
    deck._go_to(1)
    deck._on_link(QUrl("predict_correct"))
    assert not deck._btn_next.isEnabled()
    _press(deck, 800, 800)
    _drag(deck, 200, 200)
    _release(deck)

    _next(deck)

    assert deck._current_step == 2


def test_new_dyes_bring_a_new_teaching_pair(deck):
    assert {deck.pair.dye_a, deck.pair.dye_b} == {"fitc", "pe"}

    deck._viewer._active_fluors = {
        "bv421": {"em_data": _em(421), "display_label": "BV421"},
        "bv510": {"em_data": _em(470), "display_label": "BV510"},
    }
    deck.update_view()

    assert {deck.pair.dye_a, deck.pair.dye_b} == {"bv421", "bv510"}


def test_the_matrix_reads_dye_by_row_detector_by_column_and_holds_the_pair():
    names = list(LASER_PANEL)
    matrix = spill_matrix(LASER_PANEL, names)

    assert np.allclose(np.diag(matrix), 100)
    assert matrix[0, 1] == spill_fraction(LASER_PANEL, "fitc", "pe") * 100  # FITC into PE
    assert matrix[2, 1] < 1  # Red is dark on PE's laser
    pair = teaching_pair(LASER_PANEL)
    off_diagonal = matrix[~np.eye(len(names), dtype=bool)]
    assert pair.pct == pytest.approx(off_diagonal.max())


def test_a_dye_without_a_spectrum_cannot_make_a_pair():
    assert teaching_pair({"fitc": TWO_DYES["fitc"], "x": {"display_label": "X"}}) is None


# ── Guidance: the "Your turn" strip, Show me, and hints for every wrong move ──


def _strip(deck) -> str:
    return deck.guide.strip.text()


def _show_me(deck) -> str:
    """Press Show me; return what it added to the strip.

    It must also show something: a ghost on the plot, or an outline round the
    readout and answer box when the next move is there rather than on the plot.
    """
    before = len(deck._ax.patches) + len(deck._ax.lines) + len(deck._ax.texts)
    deck.guide.button.click()
    after = len(deck._ax.patches) + len(deck._ax.lines) + len(deck._ax.texts)
    pointed = "transparent" not in deck.guide._answer_area.styleSheet()
    assert after > before or pointed, "Show me showed nothing on the plot or the answer area"
    assert deck.guide.help_text
    return deck.guide.help_text


def test_the_header_counts_the_steps(deck):
    assert deck._step_label.text() == "Step 1 of 7: The Physics of Overlap"


def test_the_strip_says_what_to_do_then_points_at_next(deck):
    assert "Your turn" in _strip(deck)
    assert deck._btn_next.toolTip()  # locked Next explains itself

    deck._go_to(3)
    deck.slides[3].finish()

    assert "Next Step" in _strip(deck)
    assert deck._btn_next.isEnabled() and not deck._btn_next.toolTip()
    assert not deck.guide.button.isEnabled()


@pytest.mark.parametrize(
    ("step", "advance"),
    [
        (0, None),
        (0, _place_filter),
        (1, None),
        (1, lambda d: d._on_link(QUrl("predict_correct"))),
        (
            2,
            lambda d: (
                _press(d, 650, 650 * d.pair.pct / 100),
                _drag(d, 950, 950 * d.pair.pct / 100),
                _release(d),
            ),
        ),
        (2, None),
        (3, None),
        (4, None),
        (4, lambda d: d._on_link(QUrl("s4_proportional"))),
        (
            4,
            lambda d: (
                d._on_link(QUrl("s4_proportional")),
                _answer(d, f"{spillover(d.pair.pct, 900):.0f}"),
            ),
        ),
        (5, None),
        (6, None),
        (6, lambda d: d._on_link(QUrl("mc_single"))),
    ],
)
def test_show_me_draws_a_hint_at_every_stage(deck, step, advance):
    deck._go_to(step)
    if advance is not None:
        advance(deck)

    text = _show_me(deck)

    assert text in _strip(deck)
    assert deck.guide.button.text() == "🙈 Hide help"


def test_show_me_switches_off_on_another_slide(deck):
    _show_me(deck)
    deck._go_to(1)

    assert not deck.guide.help_text
    assert deck.guide.button.text() == "💡 Show me"


def test_step_1_a_missed_drop_says_which_way_and_stays_put(deck):
    slide = deck.slides[0]
    missed = slide._peak_x + 100
    _press(deck, slide._filter_x, 0.5)
    _drag(deck, missed, 0.5)
    _release(deck)

    assert "to the right" in slide.wrong_hint and "left" in slide.wrong_hint
    assert slide._filter_x == missed
    assert slide.wrong_hint in _strip(deck)


def test_step_1_a_press_off_the_band_says_to_grab_it(deck):
    _press(deck, deck.slides[0]._filter_x - 100, 0.5)

    assert "dashed band" in deck.slides[0].wrong_hint


def _ex(peak: float) -> list[list[float]]:
    return [[float(x), float(np.exp(-(((x - peak) / 20) ** 2)))] for x in np.arange(350, 800)]


LASER_PANEL = {  # FITC and PE both on the blue laser; "red" emits near PE but only red excites it
    "fitc": {"em_data": _em(520), "ex_data": _ex(495), "display_label": "FITC"},
    "pe": {"em_data": _em(560), "ex_data": _ex(490), "display_label": "PE"},
    "red": {"em_data": _em(565), "ex_data": _ex(640), "display_label": "Red"},
}


def test_a_dye_the_detectors_laser_cannot_excite_neither_leaks_nor_gets_a_marker(deck):
    # Red's emission sits almost on PE's peak, but the blue laser PE is read on
    # leaves Red dark: the leak, and Slide 1's answer, is FITC.
    assert spill_fraction(LASER_PANEL, "red", "pe") < 0.01
    deck._viewer._active_fluors = dict(LASER_PANEL)
    deck.update_view()
    assert (deck.pair.dye_a, deck.pair.dye_b) == ("fitc", "pe")

    _place_filter(deck)
    slide = deck.slides[0]
    assert set(slide._heights) == {"fitc"}
    _press(deck, slide._peak_x, slide._heights["fitc"])

    assert _done(deck)
    assert "FITC leaks the most into PE's detector" in deck._explanation.toPlainText()


def test_step_2_too_far_and_not_far_enough_each_get_a_reason(deck):
    deck._go_to(1)
    deck._on_link(QUrl("predict_correct"))
    slide = deck.slides[1]

    _press(deck, 800, 800)
    _drag(deck, 500, 500)
    _release(deck)
    assert "far past" in slide.wrong_hint

    _press(deck, 500, 500)
    _drag(deck, 120, 120)
    _release(deck)
    assert "grey cells still sit" in slide.wrong_hint

    _press(deck, 120, 120)
    _drag(deck, 230, 230)
    _release(deck)
    assert _done(deck)


def test_step_3_an_off_slant_ruler_says_steeper_or_flatter(deck):
    deck._go_to(2)
    _press(deck, 650, 0)
    _drag(deck, 950, 900)
    _release(deck)

    assert "steeper" in deck.slides[2].wrong_hint


def test_step_6_a_wrong_gate_says_what_is_wrong(deck):
    deck._go_to(5)
    slide = deck.slides[5]

    _press(deck, 600, 600)
    _release(deck)
    assert "click, not a drag" in slide.wrong_hint

    _press(deck, 50, 50)
    _drag(deck, 900, 900)
    _release(deck)
    assert "grey negative cells" in slide.wrong_hint

    _press(deck, 300, 800)
    _drag(deck, 450, 950)
    _release(deck)
    assert "misses the blue cluster" in slide.wrong_hint
    assert slide.wrong_hint in _strip(deck)


def test_a_slow_slide_suggests_show_me(deck):
    assert deck.guide.nudge_timer.isActive()
    deck.guide.nudge()

    assert "Stuck?" in _strip(deck)

    deck._go_to(1)
    assert "Stuck?" not in _strip(deck)


def test_step_2_show_me_square_is_exactly_what_the_check_accepts(deck):
    slide = deck.slides[1]
    edge = slide._edge()

    assert slide._judge(edge, edge) is None
    assert slide._judge(300, 300) is None
    assert slide._judge(edge - 5, edge - 5) is not None


@pytest.mark.parametrize(
    ("typed", "value"),
    [
        ("750 × 20%", 150.0),
        ("190 ÷ 950", 0.2),
        ("(400 - 40) / 1000 * 100", 36.0),
        ("1,000 x 2", 2000.0),
        ("-3 + 5", 2.0),
    ],
)
def test_the_calculator_does_the_sums_the_deck_asks_for(typed, value):
    assert evaluate(typed) == pytest.approx(value)


@pytest.mark.parametrize("typed", ["", "2 ** 10", "__import__('os')", "1 / 0", "abc", "True + 1"])
def test_the_calculator_refuses_anything_but_arithmetic(typed):
    assert evaluate(typed) is None
