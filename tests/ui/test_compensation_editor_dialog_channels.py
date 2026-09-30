"""Tests for `CompensationEditorDialog._populate_matrix`'s X/Y channel-combo
repopulation, migrated to the shared `repopulate_combo` helper
(SDK_Abstraction_Performance_Plan.md Priority 1 UI #4).

Behavior preserved: X always defaults to the first channel, Y to the
second when there are at least two channels (else the first, same as X) —
this dialog has never restored a prior selection across matrix-size
changes, so the migration must not start doing that.
"""

import numpy as np
import pytest

from karcytics_plugins.flow_cytometry.analysis.compensation import CompensationMatrix
from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.ui.widgets.compensation_editor_dialog import (
    CompensationEditorDialog,
)


def _make_dialog(qtbot, channel_names):
    state = FlowState()
    n = len(channel_names)
    state.data.compensation = CompensationMatrix(
        matrix=np.eye(n), channel_names=list(channel_names)
    )
    dialog = CompensationEditorDialog(state)
    qtbot.addWidget(dialog)
    return dialog


@pytest.mark.ui
def test_populate_matrix_defaults_x_to_first_and_y_to_second(qtbot):
    dialog = _make_dialog(qtbot, ["FL1-A", "FL2-A", "FL3-A"])

    assert dialog._x_combo.currentText() == "FL1-A"
    assert dialog._y_combo.currentText() == "FL2-A"


@pytest.mark.ui
def test_populate_matrix_y_falls_back_to_first_when_only_one_channel(qtbot):
    dialog = _make_dialog(qtbot, ["FL1-A"])

    assert dialog._x_combo.currentText() == "FL1-A"
    assert dialog._y_combo.currentText() == "FL1-A"


@pytest.mark.ui
def test_populate_matrix_rebuild_resets_to_defaults_not_prior_selection(qtbot):
    dialog = _make_dialog(qtbot, ["FL1-A", "FL2-A", "FL3-A"])
    dialog._x_combo.setCurrentIndex(2)  # "FL3-A"

    dialog._temp_matrix = CompensationMatrix(matrix=np.eye(2), channel_names=["FL1-A", "FL2-A"])
    dialog._populate_matrix()

    # Always resets to the default, unlike repopulate_combo's usual
    # restore-prior-selection call sites — this dialog never had that
    # behavior, so the migration must not introduce it.
    assert dialog._x_combo.currentText() == "FL1-A"
