"""Course 1's Spectral steps against the real viewer: the Learning Compensation
sub-tab spotlight and check, the FPbase citation, and the deck's Step 4
(one compensation rule for every cell).
"""

from unittest.mock import MagicMock

import numpy as np
import pytest
from karcytics_sdk.plugin.runtime_services import tutorial_manager
from PySide6.QtCore import QUrl

from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.tutorials.course1 import course_1_fundamentals
from karcytics_plugins.flow_cytometry.tutorials.validators.setup import (
    LearningCompensationTabOpenValidator,
)
from karcytics_plugins.flow_cytometry.ui.academy_context import (
    SPECTRAL_TAB_HIGHLIGHT_KEY,
    AcademyContext,
)
from karcytics_plugins.flow_cytometry.ui.widgets.spectral_learning.one_rule import (
    compensated_dp,
    grade_dp_answer,
    spillover,
    three_cells,
)
from karcytics_plugins.flow_cytometry.ui.widgets.spectral_learning.slide import AnswerBox
from karcytics_plugins.flow_cytometry.ui.widgets.spectral_viewer import SpectralViewer


def _gaussian_em(peak: float) -> list[list[float]]:
    xs = np.arange(350, 800)
    return [[float(x), float(np.exp(-(((x - peak) / 30) ** 2)))] for x in xs]


@pytest.fixture
def viewer(qtbot, monkeypatch):
    monkeypatch.setattr(tutorial_manager, "active_course", course_1_fundamentals)
    widget = SpectralViewer(FlowState(), MagicMock(), None)
    qtbot.addWidget(widget)
    widget._active_fluors = {
        "pe": {"em_data": _gaussian_em(575), "display_label": "PE"},
        "percp": {"em_data": _gaussian_em(620), "display_label": "PerCP"},
    }
    widget.show()
    qtbot.waitExposed(widget)
    return widget


def _step(**metadata):
    return MagicMock(metadata=metadata)


@pytest.mark.ui
def test_the_sub_tab_check_follows_the_open_sub_tab(viewer):
    ui = AcademyContext(spectral_viewer=viewer)
    assert not LearningCompensationTabOpenValidator().check(FlowState(), ui)
    viewer._tabs.setCurrentWidget(viewer.learning_tab)
    assert LearningCompensationTabOpenValidator().check(FlowState(), ui)


@pytest.mark.ui
def test_only_the_learning_tab_is_spotlit(viewer):
    assert viewer.get_tutorial_target_rects(_step()) == []

    (rect,) = viewer.get_tutorial_target_rects(_step(**{SPECTRAL_TAB_HIGHLIGHT_KEY: "learning"}))
    bar = viewer._tabs.tabBar()
    tab = bar.tabRect(viewer._tabs.indexOf(viewer.learning_tab))
    assert rect.size() == tab.size()
    assert rect.topLeft() == bar.mapToGlobal(tab.topLeft())


@pytest.mark.ui
def test_the_viewer_cites_fpbase(viewer):
    from PySide6.QtWidgets import QLabel

    citation = viewer.findChild(QLabel, "SpectralCitation")
    assert citation is not None and citation.isVisible()
    assert "fpbase.org" in citation.text()
    assert "10.1038/s41592-019-0352-8" in citation.text()


@pytest.mark.ui
def test_step_5_needs_the_proportional_rule_then_both_cells(viewer):
    deck = viewer.learning_tab
    deck._go_to(4)
    slide = deck.slides[4]

    deck._on_link(QUrl("s4_same"))
    assert slide.stage == "rule"
    assert slide.wrong_hint

    deck._on_link(QUrl("s4_proportional"))
    for answer in (
        spillover(deck.pair.pct, 900),
        compensated_dp(deck.pair.pct, three_cells(deck.pair.pct)),
    ):
        assert 4 not in deck._completed_steps
        box = next(b for b in deck.findChildren(AnswerBox) if b.isVisibleTo(deck))
        assert box.error.wordWrap()
        box.input.setText(f"{answer:.0f}")
        box.submitted.emit()
    assert 4 in deck._completed_steps


def test_step_5_grading_names_the_likely_mistake():
    pct = 30.0
    cells = three_cells(pct)
    (x3, y3) = cells[2]
    expected = compensated_dp(pct, cells)

    assert grade_dp_answer(expected, pct, cells) is None
    assert grade_dp_answer(expected + 8, pct, cells) is None
    assert "before compensation" in grade_dp_answer(y3, pct, cells)
    assert "spillover itself" in grade_dp_answer(spillover(pct, x3), pct, cells)
    assert "background" in grade_dp_answer(40, pct, cells)
    assert "took off all" in grade_dp_answer(y3 - x3, pct, cells)
    assert "🧮" in grade_dp_answer(expected + 100, pct, cells)


def test_the_really_both_cell_stays_positive_after_compensation():
    for pct in (5.0, 20.03, 38.0, 72.0):
        cells = three_cells(pct)
        for x, y in cells[:2]:
            assert y - spillover(pct, x) == 40  # single-dye cells land exactly on the background
        assert compensated_dp(pct, cells) > 300
