"""Derived Parameters editor, dialog, axis-dropdown entry and controller."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest
from PyQt6.QtWidgets import QWidget

from karcytics_plugins.flow_cytometry.analysis.axis_manager import AxisManager
from karcytics_plugins.flow_cytometry.analysis.derived import DerivedParameterDraft
from karcytics_plugins.flow_cytometry.analysis.experiment import Sample
from karcytics_plugins.flow_cytometry.analysis.fcs_io import FCSData
from karcytics_plugins.flow_cytometry.analysis.gating.range import RangeGate
from karcytics_plugins.flow_cytometry.analysis.services.derived_parameter_service import (
    DerivedParameterService,
)
from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.ui.controllers.derived_editor_controller import (
    DerivedEditorController,
)
from karcytics_plugins.flow_cytometry.ui.dialogs import derived_parameter_dialog as dialog_mod
from karcytics_plugins.flow_cytometry.ui.dialogs.derived_parameter_dialog import (
    DerivedParameterDialog,
)
from karcytics_plugins.flow_cytometry.ui.graph.components.axis_control_panel import (
    NEW_DERIVED_LABEL,
    NEW_DERIVED_SENTINEL,
    AxisControlPanel,
)
from karcytics_plugins.flow_cytometry.ui.widgets.derived_formula_editor import (
    CUSTOM_TEMPLATE,
    DerivedParameterEditor,
)
from karcytics_plugins.flow_cytometry.ui.widgets.tutorial_highlight import IN_WINDOW_TARGETS_KEY

pytestmark = pytest.mark.ui

RATIO = DerivedParameterDraft("B220/CD45", "[FITC-A] / [APC-A]")


def _fcs(name: str) -> FCSData:
    df = pd.DataFrame(
        {
            "FSC-A": [100.0, 200.0, 300.0, 400.0],
            "FITC-A": [10.0, 4.0, 8.0, 1.0],
            "APC-A": [2.0, 4.0, 2.0, 1.0],
        }
    )
    return FCSData(
        Path(f"{name}.fcs"), ["FSC-A", "FITC-A", "APC-A"], ["", "B220", "CD45"], df, df.copy()
    )


@pytest.fixture
def state() -> FlowState:
    st = FlowState()
    st.axis_manager = AxisManager(st)
    for sid in ("a", "b"):
        st.data.experiment.samples[sid] = Sample(
            sample_id=sid, display_name=f"Sample {sid.upper()}", fcs_data=_fcs(sid)
        )
    st.view.current_sample_id = "a"
    return st


@pytest.fixture
def service(state) -> DerivedParameterService:
    return DerivedParameterService(state)


@pytest.fixture
def editor(qtbot, state, service) -> DerivedParameterEditor:
    ed = DerivedParameterEditor(state, service)
    qtbot.addWidget(ed)
    ed.refresh_sources()
    ed.load(None)
    return ed


@pytest.fixture
def dialog(qtbot, state, service, monkeypatch) -> DerivedParameterDialog:
    remover = MagicMock(
        side_effect=lambda sid, nid: state.data.experiment.samples[sid].gate_tree.remove_child(nid)
    )
    dlg = DerivedParameterDialog(state, service, remove_population=remover)
    qtbot.addWidget(dlg)
    monkeypatch.setattr(dialog_mod, "ask_yes_no", MagicMock(return_value=True))
    monkeypatch.setattr(dialog_mod, "ask_ok_cancel", MagicMock(return_value=True))
    monkeypatch.setattr(dialog_mod, "show_warning", MagicMock())
    return dlg


def _gate_on(state, sample_id: str, param_id: str):
    gate = RangeGate(param_id, low=3.0, high=100.0)
    return state.data.experiment.samples[sample_id].gate_tree.add_child(gate, "Ratio hi")


# ── Axis dropdown entry ───────────────────────────────────────────────────


def test_axis_dropdown_new_entry_emits_and_snaps_back(qtbot):
    panel = AxisControlPanel()
    qtbot.addWidget(panel)
    for ch in ("FSC-A", "FITC-A"):
        panel.add_channel(ch, ch)
    panel.add_new_derived_entry()
    panel.set_current_x("FITC-A")

    requested, changed = [], []
    panel.new_derived_requested.connect(requested.append)
    panel.axis_changed.connect(lambda: changed.append(True))

    combo = panel._x_combo
    combo.setCurrentIndex(combo.findData(NEW_DERIVED_SENTINEL))

    assert requested == ["x"]
    assert changed == []
    assert panel.get_current_x() == "FITC-A"
    assert combo.itemText(combo.count() - 1) == NEW_DERIVED_LABEL


def test_axis_dropdown_normal_change_still_emits(qtbot):
    panel = AxisControlPanel()
    qtbot.addWidget(panel)
    for ch in ("FSC-A", "FITC-A"):
        panel.add_channel(ch, ch)
    panel.add_new_derived_entry()
    changed = []
    panel.axis_changed.connect(lambda: changed.append(True))
    panel._y_combo.setCurrentIndex(panel._y_combo.findData("FITC-A"))
    assert changed == [True]
    assert panel.get_current_y() == "FITC-A"


# ── Editor ────────────────────────────────────────────────────────────────


def test_new_draft_prefills_ratio_of_first_two_fluorescence_channels(editor):
    draft = editor.draft()
    assert draft.formula == "[FITC-A] / [APC-A]"
    assert draft.name == "B220/CD45"
    assert draft.preferred_transform == "log"
    assert draft.positive_denominators
    assert editor.is_valid
    assert editor.is_new and not editor.is_dirty()
    assert editor.can_save


def test_changing_template_channels_rewrites_formula_and_name(editor):
    editor._template_combo.setCurrentIndex(editor._template_combo.findData("fraction"))
    editor._chan_a.setCurrentIndex(editor._chan_a.findData("APC-A"))
    editor._chan_b.setCurrentIndex(editor._chan_b.findData("FITC-A"))
    assert editor.draft().formula == "[APC-A] / ([APC-A] + [FITC-A])"
    assert editor.draft().name == "CD45 fraction"
    assert editor.draft().preferred_transform == "linear"


def test_typed_name_is_not_overwritten_by_template(qtbot, editor):
    editor._name_edit.clear()
    qtbot.keyClicks(editor._name_edit, "My ratio")
    editor._chan_b.setCurrentIndex(editor._chan_b.findData("FSC-A"))
    assert editor.draft().name == "My ratio"


def test_hand_edit_switches_template_to_custom(qtbot, editor):
    editor._formula_edit.end(False)
    qtbot.keyClicks(editor._formula_edit, " * 2")
    assert editor._template_combo.currentData() == CUSTOM_TEMPLATE
    assert not editor._chan_a.isEnabled()


def test_formula_error_shows_message_and_position(editor):
    editor._formula_edit.setText("[FITC-A] / [CD999]")
    editor.revalidate()
    assert not editor.is_valid
    status = editor._formula_status.text()
    assert "Unknown channel" in status
    assert "character 12" in status
    assert editor._formula_status.property("state") == "error"


def test_marker_names_are_accepted_and_previewed(editor):
    editor._formula_edit.setText("[B220] / [CD45]")
    editor.revalidate()
    assert editor.is_valid
    assert "B220 (FITC-A)" in editor._formula_status.text()
    assert "median" in editor._preview_summary.text()
    assert editor._histogram.message == ""


def test_name_clashing_with_channel_is_invalid(editor):
    editor._name_edit.setText("FITC-A")
    editor.revalidate()
    assert not editor.is_valid
    assert "channel" in editor._name_status.text()


def test_denominator_option_only_for_division(editor):
    editor._formula_edit.setText("[FITC-A] + [APC-A]")
    editor.revalidate()
    assert not editor._positive_denominators.isEnabled()
    editor._formula_edit.setText("[FITC-A] / [APC-A]")
    editor.revalidate()
    assert editor._positive_denominators.isEnabled()


def test_palette_inserts_channel_and_function(editor):
    editor._template_combo.setCurrentIndex(editor._template_combo.findData(CUSTOM_TEMPLATE))
    editor._formula_edit.clear()
    editor._insert("log10()", 1)
    editor._insert("[PE-A]", 0)
    assert editor._formula_edit.text() == "log10([PE-A])"


def test_preview_warns_when_sample_lacks_channel(state, editor):
    state.data.experiment.samples["a"].fcs_data = FCSData(
        Path("x.fcs"), ["FITC-A"], ["B220"], pd.DataFrame({"FITC-A": [1.0]}), None
    )
    editor.revalidate()
    assert "has no APC-A" in editor._histogram.message


# ── Dialog ────────────────────────────────────────────────────────────────


def test_dialog_creates_and_emits(dialog, service):
    saved = []
    dialog.parameter_saved.connect(lambda pid, created: saved.append((pid, created)))
    dialog.open_new()
    assert dialog._btn_save.isEnabled()
    dialog._on_save()
    assert len(service.definitions) == 1
    pid = service.definitions[0].param_id
    assert saved == [(pid, True)]
    assert dialog._list.count() == 1
    assert dialog.editor.editing_id == pid
    assert not dialog._btn_save.isEnabled()


def test_editing_used_parameter_asks_before_recomputing(dialog, service, state):
    defn = service.create(RATIO)
    _gate_on(state, "a", defn.param_id)
    dialog.open_existing(defn.param_id)
    assert "Ratio hi (Sample A)" in dialog._dependents.text()

    dialog.editor._formula_edit.setText("[APC-A] / [FITC-A]")
    dialog.editor.revalidate()
    dialog_mod.ask_ok_cancel.return_value = False
    dialog._on_save()
    assert service.get(defn.param_id).formula == "[FITC-A] / [APC-A]"

    dialog_mod.ask_ok_cancel.return_value = True
    dialog._on_save()
    assert service.get(defn.param_id).formula == "[APC-A] / [FITC-A]"


def test_rename_only_does_not_ask(dialog, service, state):
    defn = service.create(RATIO)
    _gate_on(state, "a", defn.param_id)
    dialog.open_existing(defn.param_id)
    dialog.editor._name_edit.setText("Renamed")
    dialog.editor.revalidate()
    dialog._on_save()
    dialog_mod.ask_ok_cancel.assert_not_called()
    assert service.get(defn.param_id).name == "Renamed"


def test_delete_with_dependents_removes_gates_then_parameter(dialog, service, state):
    defn = service.create(RATIO)
    node_a = _gate_on(state, "a", defn.param_id)
    node_b = _gate_on(state, "b", defn.param_id)
    dialog.open_existing(defn.param_id)
    dialog._on_delete()
    dialog._remove_population.assert_any_call("a", node_a.node_id)
    dialog._remove_population.assert_any_call("b", node_b.node_id)
    assert service.definitions == []
    assert dialog._list.count() == 0


def test_delete_declined_keeps_everything(dialog, service, state):
    defn = service.create(RATIO)
    _gate_on(state, "a", defn.param_id)
    dialog_mod.ask_yes_no.return_value = False
    dialog.open_existing(defn.param_id)
    dialog._on_delete()
    dialog._remove_population.assert_not_called()
    assert service.get(defn.param_id) is not None


def test_switching_with_unsaved_edits_can_be_cancelled(dialog, service):
    first = service.create(RATIO)
    second = service.create(DerivedParameterDraft("Sum", "[FITC-A] + [APC-A]"))
    dialog.open_existing(first.param_id)
    dialog.editor._name_edit.setText("Edited")
    dialog.editor.revalidate()

    dialog_mod.ask_yes_no.return_value = False
    dialog._list.setCurrentRow(1)
    assert dialog.editor.editing_id == first.param_id
    assert dialog._list.currentRow() == 0

    dialog_mod.ask_yes_no.return_value = True
    dialog._list.setCurrentRow(1)
    assert dialog.editor.editing_id == second.param_id


def test_duplicate_starts_new_copy(dialog, service):
    service.create(RATIO)
    dialog.open_existing()
    dialog._on_duplicate()
    assert dialog.editor.is_new
    assert dialog.editor.draft().name == "B220/CD45 copy"
    dialog._on_save()
    assert [d.name for d in service.definitions] == ["B220/CD45", "B220/CD45 copy"]


def test_new_disabled_at_limit(dialog, service, monkeypatch):
    monkeypatch.setattr(dialog_mod, "MAX_DERIVED_PARAMETERS", 1)
    service.create(RATIO)
    dialog.open_existing()
    assert not dialog._btn_new.isEnabled()


# ── Controller + GraphWindow ──────────────────────────────────────────────


class _FakeGraph:
    def __init__(self) -> None:
        self.select_axis_param = MagicMock()


def test_parameter_created_from_axis_lands_on_that_axis(qtbot, state, service, monkeypatch):
    monkeypatch.setattr(dialog_mod, "ask_yes_no", MagicMock(return_value=True))
    ctrl = DerivedEditorController(state, service, MagicMock(), parent=None)
    graph = _FakeGraph()
    ctrl.open_for_axis(graph, "y")
    qtbot.addWidget(ctrl.dialog)
    ctrl.dialog._on_save()
    graph.select_axis_param.assert_called_once_with("y", service.definitions[0].param_id)


def test_ribbon_open_does_not_assign_axis(qtbot, state, service):
    ctrl = DerivedEditorController(state, service, MagicMock(), parent=None)
    graph = _FakeGraph()
    ctrl.open_for_axis(graph, "x")
    ctrl.open()  # a later plain open cancels the pending axis assignment
    qtbot.addWidget(ctrl.dialog)
    ctrl.dialog.open_new()
    ctrl.dialog._on_save()
    graph.select_axis_param.assert_not_called()


def test_graph_window_lists_derived_and_selects_new_param(qtbot, state, service):
    from karcytics_plugins.flow_cytometry.ui.graph.graph_window import GraphWindow

    pop = MagicMock()
    pop.get_gated_events.side_effect = lambda sid, nid=None: (
        state.data.experiment.samples[sid].fcs_data.events
    )
    win = GraphWindow(
        state, "a", axis_manager=state.axis_manager, population_service=pop, controller=MagicMock()
    )
    qtbot.addWidget(win)
    combo = win._axis_panel._x_combo
    assert combo.itemData(combo.count() - 1) == NEW_DERIVED_SENTINEL

    defn = service.create(RATIO)
    win.select_axis_param("x", defn.param_id)

    assert win._axis_panel.get_current_x() == defn.param_id
    assert combo.findText("ƒ B220/CD45") >= 0
    assert combo.itemData(combo.count() - 1) == NEW_DERIVED_SENTINEL
    assert win._x_scale.transform_type.value == "log"


def test_gating_ribbon_button_requests_editor(qtbot, state):
    from PyQt6.QtWidgets import QPushButton

    from karcytics_plugins.flow_cytometry.ui.ribbons.gating_ribbon import GatingRibbon

    ribbon = GatingRibbon(state)
    qtbot.addWidget(ribbon)
    button = ribbon.findChild(QPushButton, "DerivedParamsButton")
    assert button is not None
    with qtbot.waitSignal(ribbon.derived_params_requested, timeout=1000):
        button.click()


# ── Preview populations ──────────────────────────────────────────────────


def test_population_preview_shows_whole_sample_behind_on_same_axis(state, editor):
    _gate_on(state, "a", "FITC-A")
    editor.refresh_sources()
    editor._preview_population.setCurrentIndex(1)
    editor.revalidate()
    assert editor._histogram._reference is not None
    assert editor._histogram.ticks
    assert editor._histogram.legend == ("Ratio hi", "Whole sample")
    assert "\n" not in editor._preview_summary.text()
    editor._histogram.grab()  # paints reference bars and tick labels


# ── Academy highlight inside the dialog ──────────────────────────────────


def _step(**metadata):
    return SimpleNamespace(metadata=metadata)


def test_dialog_spotlights_its_own_widgets_for_the_academy(dialog):
    dialog.open_new()
    rects = dialog.get_tutorial_target_rects(
        _step(**{IN_WINDOW_TARGETS_KEY: ["DerivedCloseButton", "DerivedSaveButton"]})
    )
    assert rects == [dialog.frameGeometry()]
    assert dialog._tutorial_highlight.visible_count == 2  # noqa: PLR2004

    assert dialog.get_tutorial_target_rects(_step()) == []
    assert dialog._tutorial_highlight.visible_count == 0


def test_dialog_highlight_expires_when_driver_stops_asking(qtbot, dialog):
    dialog.open_new()
    dialog.get_tutorial_target_rects(_step(**{IN_WINDOW_TARGETS_KEY: ["DerivedCloseButton"]}))
    qtbot.waitUntil(lambda: dialog._tutorial_highlight.visible_count == 0, timeout=2000)


def test_hidden_dialog_offers_no_targets(dialog):
    assert (
        dialog.get_tutorial_target_rects(_step(**{IN_WINDOW_TARGETS_KEY: ["DerivedCloseButton"]}))
        == []
    )


def test_course4_in_window_targets_exist_in_the_dialog(dialog):
    from karcytics_plugins.flow_cytometry.tutorials.courses import course_4_reporting

    dialog.open_new()
    named = [
        (step.id, name)
        for step in course_4_reporting.steps
        for name in (getattr(step, "metadata", None) or {}).get(IN_WINDOW_TARGETS_KEY, [])
    ]
    assert named, "course 4 should spotlight widgets inside the Derived Parameters dialog"
    missing = [(sid, n) for sid, n in named if dialog.findChild(QWidget, n) is None]
    assert missing == []


# ── Comparisons histogram overlay ────────────────────────────────────────


def test_comparisons_log_floor_only_drops_for_sub_one_data():
    from karcytics_plugins.flow_cytometry.ui.widgets.comparisons.renderers import (
        histogram_overlay_renderer as hor,
    )

    detector = [np.array([-50.0, 5.0, 300.0, 5000.0, 20000.0])]
    assert hor._log_floor_kwargs(detector) == {}
    ratio = [np.array([0.004, 0.01, 0.02, 0.5, 0.7])]
    assert hor._log_floor_kwargs(ratio) == {"min_value": pytest.approx(1e-3)}


def test_dialog_stays_above_the_main_window(dialog):
    """Clicking the main window (e.g. the Academy's Next) mustn't bury it."""
    from PyQt6.QtCore import Qt

    assert dialog.windowType() == Qt.WindowType.Tool
    dialog.open_new()
    assert dialog.isVisible() and dialog.isWindow()
    assert dialog.windowTitle() == "Derived Parameters"
