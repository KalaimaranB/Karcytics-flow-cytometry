"""Academy checks against the real Statistics, Comparisons, Pipeline, Spectral and graph widgets.

The checks read each widget's public state (``academy_snapshot()`` and a few
properties); these tests drive the widget the way a learner would and watch
the check follow.
"""

from unittest.mock import MagicMock

import pytest

from karcytics_plugins.flow_cytometry.analysis.experiment import Sample
from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.analysis.statistics import StatType
from karcytics_plugins.flow_cytometry.tutorials.validators.gating import (
    PipelineOrientationValidator,
    PlotTypeValidator,
)
from karcytics_plugins.flow_cytometry.tutorials.validators.reports import (
    ComparisonsPlotGeneratedValidator,
    HistogramOverlayLayoutValidator,
    PopulationsCheckedValidator,
    StatsChartTypeValidator,
    StatsCheckedValidator,
    StatsResultsReadyValidator,
)
from karcytics_plugins.flow_cytometry.tutorials.validators.setup import (
    LearningCompensationCompleteValidator,
)
from karcytics_plugins.flow_cytometry.ui.academy_context import AcademyContext
from karcytics_plugins.flow_cytometry.ui.widgets.comparisons.plot_spec import PlotType


@pytest.fixture
def state():
    state = FlowState()
    for sid in ("s1", "s2"):
        sample = Sample(sample_id=sid, display_name=sid)
        sample.gate_tree.add_child(None, name="Lymphocytes")
        state.data.experiment.samples[sid] = sample
    return state


def select_by_text(combo, text):
    combo.setCurrentIndex(next(i for i in range(combo.count()) if text in combo.itemText(i)))


@pytest.mark.ui
def test_statistics_checks_follow_the_tab(qtbot, state):
    from karcytics_plugins.flow_cytometry.ui.widgets.statistics_explorer import StatisticsExplorer

    explorer = StatisticsExplorer(state)
    qtbot.addWidget(explorer)
    explorer.refresh_samples()
    ui = AcademyContext(statistics_explorer=explorer)
    populations = PopulationsCheckedValidator("statistics_explorer", "lymphocytes")

    explorer._selector.population_selector.check_all(False)
    assert not populations.check(state, ui)
    explorer._selector.population_selector.check_all(True)
    assert populations.check(state, ui)
    assert not PopulationsCheckedValidator("statistics_explorer", "cd4").check(state, ui)

    explorer._stat_picker.set_selected([StatType.MEDIAN])
    assert StatsCheckedValidator(StatType.MEDIAN, max_checked=1).check(state, ui)
    assert not StatsCheckedValidator(StatType.MEAN).check(state, ui)

    select_by_text(explorer._chart_type_combo, "Heatmap")
    assert StatsChartTypeValidator("heatmap").check(state, ui)
    assert not StatsResultsReadyValidator().check(state, ui)


@pytest.mark.ui
def test_comparisons_checks_follow_the_tab(qtbot, state):
    from karcytics_plugins.flow_cytometry.ui.widgets.comparisons_viewer import ComparisonsViewer

    viewer = ComparisonsViewer(state)
    qtbot.addWidget(viewer)
    ui = AcademyContext(comparisons_viewer=viewer)

    assert HistogramOverlayLayoutValidator("ridge").check(state, ui)
    overlay = viewer._options_panels[PlotType.HISTOGRAM_OVERLAY]
    overlay._layout_combo.setCurrentIndex(overlay._layout_combo.findData("overlay"))
    assert HistogramOverlayLayoutValidator("overlay").check(state, ui)

    assert not ComparisonsPlotGeneratedValidator(PlotType.RADAR).check(state, ui)
    viewer._last_generated_plot_type = PlotType.RADAR  # what Generate leaves behind
    assert ComparisonsPlotGeneratedValidator(PlotType.RADAR).check(state, ui)


@pytest.mark.ui
def test_pipeline_orientation_check_reads_the_ribbon(qtbot, state):
    from karcytics_plugins.flow_cytometry.ui.ribbons.pipeline_ribbon import PipelineRibbon

    ribbon = PipelineRibbon(state)
    qtbot.addWidget(ribbon)
    ui = AcademyContext(pipeline_ribbon=ribbon)

    select_by_text(ribbon._orientation_combo, "Horizontal")
    assert PipelineOrientationValidator("Horizontal").check(state, ui)
    assert not PipelineOrientationValidator("Vertical").check(state, ui)


@pytest.mark.ui
def test_the_learning_deck_counts_only_once_its_last_task_is_done(qtbot, state):
    from karcytics_plugins.flow_cytometry.ui.widgets.spectral_viewer import SpectralViewer

    viewer = SpectralViewer(state=state, fluor_service=MagicMock())
    qtbot.addWidget(viewer)
    ui = AcademyContext(spectral_viewer=viewer)
    deck = viewer.learning_tab
    last = deck.academy_snapshot().last_step

    assert not LearningCompensationCompleteValidator().check(state, ui)
    deck._current_step = last
    assert not LearningCompensationCompleteValidator().check(state, ui)
    deck._completed_steps.add(last)
    assert LearningCompensationCompleteValidator().check(state, ui)


@pytest.mark.ui
def test_plot_type_check_reads_the_active_graph(qtbot, flow_state):
    from karcytics_plugins.flow_cytometry.ui.graph.graph_manager import GraphManager

    controller = MagicMock()
    controller.get_gates_for_display.return_value = ([], [])
    manager = GraphManager(flow_state, None, MagicMock(), controller)
    qtbot.addWidget(manager)
    ui = AcademyContext(graph_manager=manager)
    assert not PlotTypeValidator("histogram").check(flow_state, ui)

    manager.open_graph_for_sample("test_sample_1")
    manager.get_open_graph("test_sample_1").axis_panel.set_display_mode("histogram")

    assert PlotTypeValidator("histogram").check(flow_state, ui)
    assert not PlotTypeValidator("contour").check(flow_state, ui)
