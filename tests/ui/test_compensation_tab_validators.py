"""Tests for the Academy validators that read the Compensation tab."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from karcytics_plugins.flow_cytometry.analysis.compensation import SavedMatrix
from karcytics_plugins.flow_cytometry.analysis.experiment import Sample, SampleRole
from karcytics_plugins.flow_cytometry.analysis.fcs_io import FCSData
from karcytics_plugins.flow_cytometry.analysis.gating import RectangleGate
from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.tutorials.validators import (
    CompensationFitGateValidator,
    CompensationMethodValidator,
    CompensationPageValidator,
    EditorMatrixValidator,
    EmbeddedMatrixInUseValidator,
    IllustrationPlayedValidator,
    PreviewShowsValidator,
    SavedMatrixValidator,
)
from karcytics_plugins.flow_cytometry.ui.widgets import compensation_view
from karcytics_plugins.flow_cytometry.ui.widgets.compensation_editor import ALL_SAMPLES
from karcytics_plugins.flow_cytometry.ui.widgets.compensation_preview import VIEW_BOTH
from karcytics_plugins.flow_cytometry.ui.widgets.compensation_view import (
    PAGE_MATRICES,
    PAGE_MATRIX,
    PAGE_SETUP,
    CompensationView,
)

pytestmark = pytest.mark.ui

DYES = ["FITC-A", "PE-A", "APC-A"]
CHANNELS = ["FSC-A", *DYES]
SPILLOVER = np.array([[1.0, 0.15, 0.0], [0.02, 1.0, 0.08], [0.0, 0.01, 1.0]])
SPILL_KEYWORD = ",".join(["3", *DYES, *(str(v) for v in SPILLOVER.ravel())])


def _fmo(name: str, missing: int) -> Sample:
    rng = np.random.default_rng(missing + 1)
    true = np.abs(rng.normal(900, 400, (600, 3)))
    true[:, missing] = 0.0
    raw = true @ SPILLOVER + rng.normal(0, 25, (600, 3))
    events = pd.DataFrame(np.column_stack([np.full(600, 500.0), raw]), columns=CHANNELS)
    sample = Sample(sample_id=name, display_name=name)
    sample.role = SampleRole.FMO_CONTROL
    sample.fcs_data = FCSData(
        file_path=Path(f"{name}.fcs"),
        channels=list(CHANNELS),
        markers=[""] * 4,
        events=events,
        metadata={"$SPILLOVER": SPILL_KEYWORD},
    )
    sample.gate_tree.add_child(RectangleGate("FSC-A", x_min=100, x_max=1000), "Cells")
    return sample


@pytest.fixture(autouse=True)
def quiet_edits(monkeypatch):
    monkeypatch.setattr(compensation_view.experiment_edits, "sync_experiment", lambda _exp: None)


@pytest.fixture
def state():
    state = FlowState()
    for name, missing in (("FMO FITC", 0), ("FMO PE", 1), ("FMO APC", 2)):
        state.data.experiment.samples[name] = _fmo(name, missing)
    return state


@pytest.fixture
def view(qtbot, state):
    view = CompensationView(state)
    qtbot.addWidget(view)
    view.show()
    state.view._compensation_view = view
    return view


def _pick(combo, data) -> None:
    combo.setCurrentIndex(combo.findData(data))


def test_validators_fail_quietly_before_the_tab_exists(state):
    assert CompensationPageValidator(PAGE_SETUP).validate(state) is False


def test_method_and_page_follow_the_tab(view, state):
    assert CompensationMethodValidator("cytometer").validate(state)  # the files carry a matrix
    assert CompensationPageValidator(PAGE_SETUP).validate(state)

    view._btn_run.click()

    assert CompensationPageValidator(PAGE_MATRIX).validate(state)
    assert EditorMatrixValidator("cytometer").validate(state)
    assert not EditorMatrixValidator("fmo").validate(state)

    view._btn_library_page.click()
    _pick(view._method_combo, "fmo")

    assert CompensationPageValidator(PAGE_MATRICES).validate(state)
    assert CompensationMethodValidator("fmo").validate(state)


def test_the_fit_gate_and_the_step_by_step_picture(view, state):
    _pick(view._method_combo, "fmo")
    assert not CompensationFitGateValidator("Cells").validate(state)
    assert not IllustrationPlayedValidator().validate(state)

    _pick(view._setup._gate_combo, "Cells")
    view._setup._illustration.go_to(3)

    assert CompensationFitGateValidator("cells").validate(state)
    assert IllustrationPlayedValidator().validate(state)


def test_a_hand_edited_cell_is_recognised(view, state):
    _pick(view._method_combo, "fmo")
    view._btn_run.click()
    filled = EditorMatrixValidator("fmo", "PE-A", "APC-A", 0.30)
    assert EditorMatrixValidator("fmo").validate(state)
    assert not filled.validate(state)  # estimated, not typed
    assert SavedMatrixValidator("fmo").validate(state)  # every run is kept
    assert not SavedMatrixValidator("fmo", fine_tuned=True).validate(state)

    view.editor._table.item(1, 2).setText("0.5")
    assert not filled.validate(state)  # edited, but to the wrong value
    view.editor._table.item(1, 2).setText("0.31")
    assert filled.validate(state)

    state.data.matrix_library.append(SavedMatrix("Mine", view.editor.matrix))
    assert SavedMatrixValidator("fmo", fine_tuned=True).validate(state)


def test_the_preview_selection_is_checked_field_by_field(view, state):
    view._btn_run.click()
    editor = view.editor
    editor._x_combo.setCurrentText("PE-A")
    editor._y_combo.setCurrentText("APC-A")

    assert PreviewShowsValidator(x="PE-A", y="APC-A").validate(state)
    assert not PreviewShowsValidator(x="PE-A", view=VIEW_BOTH).validate(state)
    assert not PreviewShowsValidator(sample=ALL_SAMPLES).validate(state)

    _pick(editor._view_combo, VIEW_BOTH)
    _pick(editor._sample_combo, ALL_SAMPLES)

    assert PreviewShowsValidator(x="PE-A", view=VIEW_BOTH, sample=ALL_SAMPLES).validate(state)


def test_only_the_files_matrix_applied_to_every_sample_passes_the_handover(view, state):
    handover = EmbeddedMatrixInUseValidator()
    assert not handover.validate(state)  # nothing in use yet

    view._btn_run.click()  # the file's matrix
    view._on_apply(None)
    assert handover.validate(state)

    _pick(view._method_combo, "fmo")
    view._btn_run.click()
    view._on_apply(None)
    assert not handover.validate(state)  # the learner's own matrix is in use

    saved = next(s for s in state.data.matrix_library if s.matrix.source == "cytometer")
    view._on_apply(saved)
    assert handover.validate(state)


def test_the_course_constants_match_the_widgets():
    from karcytics_plugins.flow_cytometry.tutorials import constants

    assert constants.PREVIEW_ALL_SAMPLES == ALL_SAMPLES
    assert constants.PREVIEW_VIEW_BOTH == VIEW_BOTH


def test_the_preview_sample_can_be_named(view, state):
    view._btn_run.click()
    _pick(view.editor._sample_combo, "FMO PE")

    assert PreviewShowsValidator(sample_name="fmo pe").validate(state)
    assert not PreviewShowsValidator(sample_name="FMO APC").validate(state)
