"""Course 4 derived-parameter validators."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from karcytics_plugins.flow_cytometry.analysis.derived import DerivedParameter
from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.tutorials.validators.base import AllOf
from karcytics_plugins.flow_cytometry.tutorials.validators.derived import (
    ActiveGraphDerivedAxisValidator,
    ComparisonsDerivedChannelValidator,
    DerivedEditorClosedValidator,
    DerivedRatioExistsValidator,
    StatsDerivedChannelValidator,
)
from karcytics_plugins.flow_cytometry.tutorials.validators.reports import ExportDoneValidator
from karcytics_plugins.flow_cytometry.ui.academy_context import AcademyContext

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
        ui = AcademyContext(derived_editor=editor)
        assert DerivedEditorClosedValidator().check(_state(), ui) is expected


def _active_graph(x_param: str) -> AcademyContext:
    graph = SimpleNamespace(axis_panel=SimpleNamespace(get_current_x=lambda: x_param))
    return AcademyContext(graph_manager=SimpleNamespace(get_active_graph=lambda: graph))


class TestActiveGraphDerivedAxis:
    def test_passes_on_ratio_axis(self):
        ui = _active_graph(RATIO.param_id)
        assert ActiveGraphDerivedAxisValidator("FITC-A", "APC-A").check(_state(RATIO), ui)

    @pytest.mark.parametrize("x_param", ["FITC-A", OTHER.param_id, REVERSED.param_id])
    def test_fails_on_other_axes(self, x_param):
        st = _state(RATIO, OTHER, REVERSED)
        assert not ActiveGraphDerivedAxisValidator("FITC-A", "APC-A").check(
            st, _active_graph(x_param)
        )

    def test_fails_without_graph(self):
        ui = AcademyContext(graph_manager=SimpleNamespace(get_active_graph=lambda: None))
        assert not ActiveGraphDerivedAxisValidator("FITC-A", "APC-A").check(_state(RATIO), ui)


class TestStatsDerivedChannel:
    def _explorer(self, channel: str) -> AcademyContext:
        snapshot = SimpleNamespace(channel=channel)
        explorer = SimpleNamespace(academy_snapshot=lambda: snapshot)
        return AcademyContext(statistics_explorer=explorer)

    def test_passes_when_ratio_selected(self):
        ui = self._explorer(RATIO.param_id)
        assert StatsDerivedChannelValidator("FITC-A", "APC-A").check(_state(RATIO), ui)

    def test_fails_on_detector_channel(self):
        ui = self._explorer("FITC-A")
        assert not StatsDerivedChannelValidator("FITC-A", "APC-A").check(_state(RATIO), ui)

    def test_fails_without_explorer(self):
        assert not StatsDerivedChannelValidator("FITC-A", "APC-A").check(_state(RATIO))


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
        ui = AcademyContext(
            comparisons_viewer=SimpleNamespace(
                academy_snapshot=lambda: SimpleNamespace(checked_channels=tuple(checked))
            )
        )
        assert (
            ComparisonsDerivedChannelValidator("FITC-A", "APC-A").check(_state(RATIO), ui)
            is expected
        )


class TestExportDone:
    def test_needs_a_completed_export_of_that_kind(self):
        explorer = SimpleNamespace(completed_exports={"copy"})
        ui = AcademyContext(statistics_explorer=explorer)
        assert not ExportDoneValidator("statistics_explorer", "csv").check(FlowState(), ui)
        explorer.completed_exports.add("csv")
        assert ExportDoneValidator("statistics_explorer", "csv").check(FlowState(), ui)

    def test_missing_tab_fails(self):
        assert not ExportDoneValidator("comparisons_viewer", "plot").check(FlowState())

    def test_an_unknown_tab_is_rejected_when_the_course_is_built(self):
        with pytest.raises(ValueError, match="no field"):
            ExportDoneValidator("_statistics_explorer", "csv")


def test_all_of_needs_every_validator():
    st = _state(RATIO)
    assert AllOf(DerivedRatioExistsValidator("FITC-A", "APC-A")).validate(st)
    assert not AllOf(
        DerivedRatioExistsValidator("FITC-A", "APC-A"),
        DerivedRatioExistsValidator("APC-A", "FITC-A"),
    ).validate(st)


def test_all_of_hands_the_context_to_widget_checks():
    closed = AcademyContext(derived_editor=SimpleNamespace(is_open=False))
    open_ = AcademyContext(derived_editor=SimpleNamespace(is_open=True))
    check = AllOf(DerivedRatioExistsValidator("FITC-A", "APC-A"), DerivedEditorClosedValidator())

    assert check.check(_state(RATIO), closed)
    assert not check.check(_state(RATIO), open_)
