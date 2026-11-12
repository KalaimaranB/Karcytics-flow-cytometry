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
from karcytics_plugins.flow_cytometry.ui.widgets.spectral_slide4 import (
    grade_slide4_answer,
    slide4_cells,
    slide4_expected_dp,
)
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
def test_step_4_needs_the_proportional_rule_then_the_double_positive(viewer):
    deck = viewer.learning_tab
    deck._current_step = 3
    deck.update_view()

    deck._on_html_link_clicked(QUrl("s4_same"))
    assert not deck._slide4_mc_correct
    assert deck._slide4_mc_hint

    deck._on_html_link_clicked(QUrl("s4_proportional"))
    assert deck._slide4_mc_correct
    assert 3 not in deck._completed_steps

    _a, _b, pct = deck._teaching_pair()
    expected = slide4_expected_dp(pct, slide4_cells(pct))
    assert deck._answer_error.wordWrap()
    deck._answer_input.setText(f"{expected:.0f}")
    deck._check_slide4_answer()
    deck._finish_slide4()  # what the deferred callback runs
    assert 3 in deck._completed_steps


def test_step_4_grading_names_the_likely_mistake():
    pct = 30.0
    cells = slide4_cells(pct)
    (x3, y3) = cells[2]
    expected = slide4_expected_dp(pct, cells)

    assert grade_slide4_answer(expected, pct, cells) is None
    assert grade_slide4_answer(expected + 8, pct, cells) is None
    assert "raw reading" in grade_slide4_answer(y3, pct, cells)
    assert "floor" in grade_slide4_answer(40, pct, cells)
    assert "subtracted all" in grade_slide4_answer(y3 - x3, pct, cells)
    assert "subtract" in grade_slide4_answer(expected + 100, pct, cells)


def test_cell_3_stays_positive_after_compensation():
    for pct in (5.0, 38.0, 72.0):
        cells = slide4_cells(pct)
        for x, y in cells[:2]:
            assert abs((y - pct / 100 * x) - 40) <= 1  # pure leak lands on the floor
        assert slide4_expected_dp(pct, cells) > 300  # noqa: PLR2004
