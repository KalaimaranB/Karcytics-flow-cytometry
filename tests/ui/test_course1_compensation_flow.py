"""Course 1's compensation phase, walked in course order on the real tutorial files.

Loads the ten tutorial FCS files into a FlowState, builds the real Compensation
tab, and does what each step asks, checking that step's own validator as it
goes: the switch OFF for the mystery, Sample A on PE vs PI, the switch back ON,
the guided matrix read, and the hand-over Course 2 depends on (the embedded
matrix in use, applied to every sample). Also checks the step graph runs from
the phase's first step to graduation, through the deck.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from karcytics_sdk.plugin.tutorial_models import BaseStep

from karcytics_plugins.flow_cytometry.analysis.compensation import extract_spill_from_fcs
from karcytics_plugins.flow_cytometry.analysis.experiment import Sample
from karcytics_plugins.flow_cytometry.analysis.fcs_io import load_fcs
from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.main_tabs import MainTab
from karcytics_plugins.flow_cytometry.tutorials.course1 import (
    DECK_DONE_STEP_ID,
    course_1_fundamentals,
)
from karcytics_plugins.flow_cytometry.tutorials.validators.compensation import (
    EmbeddedMatrixInUseValidator,
)
from karcytics_plugins.flow_cytometry.ui.academy_context import (
    MATRIX_HIGHLIGHT_KEY,
    AcademyContext,
)
from karcytics_plugins.flow_cytometry.ui.widgets import compensation_view
from karcytics_plugins.flow_cytometry.ui.widgets.compensation_switch import compensation_on
from karcytics_plugins.flow_cytometry.ui.widgets.compensation_view import CompensationView
from tests.fixtures.daemon import in_process_daemon

pytestmark = pytest.mark.ui

STEPS: dict[str, BaseStep] = {s.id: s for s in course_1_fundamentals.steps}


@pytest.fixture(autouse=True)
def quiet_edits(monkeypatch):
    monkeypatch.setattr(compensation_view.experiment_edits, "sync_experiment", lambda _exp: None)


@pytest.fixture
def tutorial_files(fcs_test_data_dir):
    return {
        path.stem.replace("Specimen_001_", ""): path
        for path in sorted(fcs_test_data_dir.glob("*.fcs"))
    }


@pytest.fixture
def state(tutorial_files):
    """The ten tutorial files as Course 1 has them after import: compensated on load."""
    state = FlowState()
    for name, path in tutorial_files.items():
        sample = Sample(sample_id=name, display_name=name)
        sample.fcs_data = load_fcs(str(path), in_process_daemon)
        sample.is_compensated = sample.fcs_data.is_compensated
        state.data.experiment.samples[name] = sample
    state.data.compensation = extract_spill_from_fcs(
        state.data.experiment.samples["Blank"].fcs_data
    )
    return state


@pytest.fixture
def view(qtbot, state):
    view = CompensationView(state)
    qtbot.addWidget(view)
    return view


def _passes(step_id: str, state: FlowState, view: CompensationView) -> bool:
    return STEPS[step_id].validator.check(state, AcademyContext(compensation_view=view))


def test_the_mystery_and_its_payoff_on_the_real_files(state, view):
    assert compensation_on(state)  # Course 1 meets compensation already ON (the ✦ tags)
    assert not _passes("c1_c03_switch_off", state, view)

    view._switch.button.click()  # the mystery: compensation OFF
    assert _passes("c1_c03_switch_off", state, view)
    sample_a = state.data.experiment.samples["Sample A"]
    assert (sample_a.fcs_data.events.to_numpy() == sample_a.fcs_data.raw_events.to_numpy()).all()

    state.view.current_sample_id = "Sample A"
    assert not _passes("c1_c05_open_sample_a", state, view)  # still on another tab
    state.view.active_main_tab_index = MainTab.GATING
    state.view.active_x_param, state.view.active_y_param = "PE-A", "PerCP-Cy5-5-A"
    assert _passes("c1_c05_open_sample_a", state, view)
    assert _passes("c1_c06_set_axes", state, view)
    state.view.active_x_param = "PerCP-Cy5-5-A"  # the axes swapped don't count
    state.view.active_y_param = "PE-A"
    assert not _passes("c1_c06_set_axes", state, view)

    assert not _passes("c1_c21_switch_on", state, view)
    view._switch.button.click()  # the payoff: compensation back ON
    assert _passes("c1_c21_switch_on", state, view)

    # The hand-over Course 2 depends on: the embedded matrix, applied everywhere.
    assert EmbeddedMatrixInUseValidator().check(state, AcademyContext(compensation_view=view))


def test_saving_with_compensation_off_does_not_finish_the_course(state, view):
    view._switch.button.click()
    saved = STEPS["c1_s33b_save_interaction"].validator
    assert not saved.check(state, AcademyContext(compensation_view=view))


def test_the_guided_matrix_read_finds_its_row_column_and_cell(qtbot, view):
    view._btn_matrix_page.setChecked(True)
    view.show()
    qtbot.waitExposed(view)
    rects = {
        step_id: view._editor.get_tutorial_target_rects(STEPS[step_id])
        for step_id in ("c1_c26_matrix_row", "c1_c27_matrix_column", "c1_m03_read_matrix")
    }
    (row,), (column,), (cell,) = rects.values()
    assert row.contains(cell) and column.contains(cell)
    assert MATRIX_HIGHLIGHT_KEY in STEPS["c1_m03_read_matrix"].metadata
    assert view._editor.get_tutorial_target_rects(SimpleNamespace(metadata={})) == []


def _next_ids(step: BaseStep) -> list[str]:
    ids = [getattr(step, name, None) for name in ("next_step_id", "on_success_step_id")]
    return [i for i in ids if i]


def test_the_compensation_phase_runs_from_the_mystery_to_graduation():
    """Following each step's success path from the phase's start reaches the
    end, passing the mystery, the deck, the payoff and the save.
    """
    seen: list[str] = []
    step_id: str | None = "c1_c02_comp_tab"
    while step_id:
        assert step_id not in seen, f"loop at {step_id}"
        seen.append(step_id)
        nxt = _next_ids(STEPS[step_id])
        step_id = nxt[-1] if nxt else None
    for must in (
        "c1_c03_switch_off",
        "c1_c07_mystery",
        "c1_sp46c_laser_question",
        "c1_sp49_work_through_deck",
        DECK_DONE_STEP_ID,
        "c1_c23_payoff",
        "c1_m03_read_matrix",
        "c1_c30_recap",
        "c1_s33b_save_interaction",
    ):
        assert any(s.startswith(must) for s in seen), must
    assert seen[-1] == "c1_s34_graduation"
