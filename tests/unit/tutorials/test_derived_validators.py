"""Course 4 derived-parameter validators."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from karcytics_plugins.flow_cytometry.analysis.derived import DerivedParameter
from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.tutorials.validators import (
    ActiveGraphDerivedAxisValidator,
    AllOf,
    ComparisonsDerivedChannelValidator,
    DerivedEditorClosedValidator,
    DerivedRatioExistsValidator,
    ExportDoneValidator,
    StatsDerivedChannelValidator,
)

RATIO = DerivedParameter("derived:ratio001", "B220/CD45", "[FITC-A] / [APC-A]")
REVERSED = DerivedParameter("derived:revrs001", "CD45/B220", "[APC-A] / [FITC-A]")
OTHER = DerivedParameter("derived:other001", "Sum", "[FITC-A] + [APC-A]")


def _state(*defs: DerivedParameter) -> FlowState:
    st = FlowState()
    st.data.experiment.derived_parameters = list(defs)
    return st


class TestDerivedRatioExists:
    def test_passes_regardless_of_name_and_spacing(self):
        spaced = DerivedParameter("derived:x0000001", "anything", " [FITC-A]/[APC-A] ")
        assert DerivedRatioExistsValidator("FITC-A", "APC-A").validate(_state(spaced))

    @pytest.mark.parametrize("defs", [(), (OTHER,), (REVERSED,)])
    def test_fails_without_the_exact_ratio(self, defs):
        assert not DerivedRatioExistsValidator("FITC-A", "APC-A").validate(_state(*defs))

    def test_reversed_ratio_explains_the_swap(self):
        v = DerivedRatioExistsValidator("FITC-A", "APC-A")
        failure = v.describe_failure(_state(REVERSED))
        assert failure is not None
        assert "swap A and B" in failure.reason

    def test_no_diagnosis_when_nothing_built(self):
        v = DerivedRatioExistsValidator("FITC-A", "APC-A")
        assert v.describe_failure(_state(OTHER)) is None
        assert v.describe_failure(app_state=None) is None


class TestDerivedEditorClosed:
    @pytest.mark.parametrize(
        ("editor", "expected"),
        [
            (None, True),
            (SimpleNamespace(is_open=False), True),
            (SimpleNamespace(is_open=True), False),
        ],
    )
    def test_open_state(self, editor, expected):
        st = _state()
        st.view._derived_editor = editor
        assert DerivedEditorClosedValidator().validate(st) is expected


def _with_active_graph(st: FlowState, x_param: str) -> FlowState:
    graph = SimpleNamespace(_axis_panel=SimpleNamespace(get_current_x=lambda: x_param))
    st.view._graph_manager = SimpleNamespace(get_active_graph=lambda: graph)
    return st


class TestActiveGraphDerivedAxis:
    def test_passes_on_ratio_axis(self):
        st = _with_active_graph(_state(RATIO), RATIO.param_id)
        assert ActiveGraphDerivedAxisValidator("FITC-A", "APC-A").validate(st)

    @pytest.mark.parametrize("x_param", ["FITC-A", OTHER.param_id, REVERSED.param_id])
    def test_fails_on_other_axes(self, x_param):
        st = _with_active_graph(_state(RATIO, OTHER, REVERSED), x_param)
        assert not ActiveGraphDerivedAxisValidator("FITC-A", "APC-A").validate(st)

    def test_fails_without_graph(self):
        st = _state(RATIO)
        st.view._graph_manager = SimpleNamespace(get_active_graph=lambda: None)
        assert not ActiveGraphDerivedAxisValidator("FITC-A", "APC-A").validate(st)


class TestStatsDerivedChannel:
    def _explorer_state(self, channel: str) -> FlowState:
        st = _state(RATIO)
        combo = MagicMock()
        combo.currentData.return_value = channel
        st.view._statistics_explorer = SimpleNamespace(_channel_combo=combo)
        return st

    def test_passes_when_ratio_selected(self):
        st = self._explorer_state(RATIO.param_id)
        assert StatsDerivedChannelValidator("FITC-A", "APC-A").validate(st)

    def test_fails_on_detector_channel(self):
        st = self._explorer_state("FITC-A")
        assert not StatsDerivedChannelValidator("FITC-A", "APC-A").validate(st)

    def test_fails_without_explorer(self):
        assert not StatsDerivedChannelValidator("FITC-A", "APC-A").validate(_state(RATIO))


class TestComparisonsDerivedChannel:
    @pytest.mark.parametrize(
        ("checked", "expected"),
        [
            (["derived:ratio001"], True),
            (["FITC-A"], False),
            (["derived:ratio001", "FITC-A"], False),
            ([], False),
        ],
    )
    def test_only_the_ratio_checked(self, checked, expected):
        st = _state(RATIO)
        st.view._comparisons_viewer = SimpleNamespace(_get_checked_channels=lambda: checked)
        assert ComparisonsDerivedChannelValidator("FITC-A", "APC-A").validate(st) is expected


class TestExportDone:
    def test_needs_a_completed_export_of_that_kind(self):
        st = FlowState()
        st.view._statistics_explorer = SimpleNamespace(completed_exports={"copy"})
        assert not ExportDoneValidator("_statistics_explorer", "csv").validate(st)
        st.view._statistics_explorer.completed_exports.add("csv")
        assert ExportDoneValidator("_statistics_explorer", "csv").validate(st)

    def test_missing_tab_fails(self):
        assert not ExportDoneValidator("_comparisons_viewer", "plot").validate(FlowState())


def test_all_of_needs_every_validator():
    st = _state(RATIO)
    assert AllOf(DerivedRatioExistsValidator("FITC-A", "APC-A")).validate(st)
    assert not AllOf(
        DerivedRatioExistsValidator("FITC-A", "APC-A"),
        DerivedRatioExistsValidator("APC-A", "FITC-A"),
    ).validate(st)
