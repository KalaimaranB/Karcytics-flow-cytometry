"""Derived parameters stay correct across the paths that replace event data.

Covers the Phase-2 wiring: compensation, workspace reload, new samples,
safety nets, transforms, gate formula records, templates and axis defaults.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from karcytics_plugins.flow_cytometry.analysis.axis_manager import AxisManager
from karcytics_plugins.flow_cytometry.analysis.compensation import (
    CompensationMatrix,
    apply_compensation,
)
from karcytics_plugins.flow_cytometry.analysis.derived import (
    DerivedParameter,
    sync_experiment,
)
from karcytics_plugins.flow_cytometry.analysis.experiment import (
    Experiment,
    Group,
    Sample,
    WorkflowTemplate,
)
from karcytics_plugins.flow_cytometry.analysis.experiment_io import ExperimentSerializer
from karcytics_plugins.flow_cytometry.analysis.fcs_io import FCSData
from karcytics_plugins.flow_cytometry.analysis.gating.gate_factory import gate_from_dict
from karcytics_plugins.flow_cytometry.analysis.gating.gate_node import GateNode
from karcytics_plugins.flow_cytometry.analysis.gating.quadrant import QuadrantGate
from karcytics_plugins.flow_cytometry.analysis.gating.range import RangeGate
from karcytics_plugins.flow_cytometry.analysis.population_service import PopulationService
from karcytics_plugins.flow_cytometry.analysis.services.derived_parameter_service import (
    DerivedParameterService,
)
from karcytics_plugins.flow_cytometry.analysis.services.gate_mutation_service import (
    GateMutationService,
)
from karcytics_plugins.flow_cytometry.analysis.services.gating_service import GatingService
from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.analysis.transforms import TransformType, apply_transform
from karcytics_plugins.flow_cytometry.ui.services.workflow_service import WorkflowService

RATIO_FORMULA = "[FITC-A] / [APC-A]"


def _fcs(fitc=(10.0, 4.0), apc=(2.0, 4.0), with_raw: bool = True) -> FCSData:
    df = pd.DataFrame({"FSC-A": [1.0, 2.0], "FITC-A": list(fitc), "APC-A": list(apc)})
    return FCSData(
        Path("s.fcs"),
        ["FSC-A", "FITC-A", "APC-A"],
        ["", "B220", "CD45"],
        df,
        df.copy() if with_raw else None,
    )


@pytest.fixture
def state() -> FlowState:
    st = FlowState()
    st.data.experiment.samples["a"] = Sample(sample_id="a", display_name="A", fcs_data=_fcs())
    return st


@pytest.fixture
def ratio(state) -> DerivedParameter:
    return DerivedParameterService(state).create("B220/CD45", RATIO_FORMULA)


def _ratio_gate(state, param_id: str) -> GateNode:
    """1-D gate keeping ratio >= 3 (event 0 has ratio 5, event 1 has ratio 1)."""
    gate = RangeGate(param_id, low=3.0, high=100.0)
    return state.data.experiment.samples["a"].gate_tree.add_child(gate, "Ratio hi")


# ── Compensation ──────────────────────────────────────────────────────────


def _spill(fitc_into_apc: float) -> CompensationMatrix:
    matrix = np.array([[1.0, fitc_into_apc], [0.0, 1.0]])
    return CompensationMatrix(matrix=matrix, channel_names=["FITC-A", "APC-A"])


def test_compensation_then_sync_updates_ratio_and_gate(state, ratio):
    sample = state.data.experiment.samples["a"]
    node = _ratio_gate(state, ratio.param_id)
    assert node.gate.contains(sample.fcs_data.events).tolist() == [True, False]

    # Remove 50% FITC spill from APC: APC' = APC - 0.5*FITC -> [-3, 2]
    sample.fcs_data.events = apply_compensation(sample.fcs_data, _spill(0.5))
    sync_experiment(state.data.experiment)

    ratios = sample.fcs_data.events[ratio.param_id]
    assert np.isnan(ratios.iloc[0])  # negative denominator -> invalid
    assert ratios.iloc[1] == pytest.approx(2.0)
    assert node.gate.contains(sample.fcs_data.events).tolist() == [False, False]


def test_compensation_without_raw_backup_drops_stale_derived_columns(state, ratio):
    sample = state.data.experiment.samples["a"]
    sample.fcs_data = _fcs(with_raw=False)
    sync_experiment(state.data.experiment)
    assert ratio.param_id in sample.fcs_data.events.columns

    compensated = apply_compensation(sample.fcs_data, _spill(0.5))
    assert ratio.param_id not in compensated.columns


def test_toggle_off_restores_uncompensated_ratio(state, ratio):
    sample = state.data.experiment.samples["a"]
    sample.fcs_data.events = apply_compensation(sample.fcs_data, _spill(0.5))
    sync_experiment(state.data.experiment)
    sample.fcs_data.events = sample.fcs_data.raw_events.copy()  # toggle OFF path
    sync_experiment(state.data.experiment)
    np.testing.assert_allclose(sample.fcs_data.events[ratio.param_id], [5.0, 1.0])


# ── Safety net, new samples, reload ───────────────────────────────────────


def test_population_service_resyncs_if_a_path_forgot(state, ratio):
    sample = state.data.experiment.samples["a"]
    node = _ratio_gate(state, ratio.param_id)
    sample.fcs_data.events = sample.fcs_data.raw_events.copy()  # no sync call
    gated = PopulationService(state).get_gated_events("a", node.node_id)
    assert len(gated) == 1


def test_population_service_untouched_without_derived_parameters():
    st = FlowState()
    fcs = _fcs()
    st.data.experiment.samples["a"] = Sample(sample_id="a", display_name="A", fcs_data=fcs)
    before = fcs.events
    assert PopulationService(st).get_gated_events("a") is before


def test_add_sample_gets_existing_definitions(state, ratio):
    new = Sample(sample_id="b", display_name="B", fcs_data=_fcs())
    state.data.experiment.add_sample(new)
    assert ratio.param_id in new.fcs_data.events.columns
    assert ratio.param_id in new.fcs_data.channels


def test_workflow_reload_resyncs_before_on_complete(state, ratio):
    sample = state.data.experiment.samples["a"]

    def _fake_reload(samples_with_paths, _comp):
        for s, _path in samples_with_paths:
            s.fcs_data = _fcs()  # freshly loaded, no derived columns
        return {"loaded": ["A"], "failed": []}

    loader = MagicMock()
    loader.reload_samples_batch.side_effect = _fake_reload
    loader._scheduler = None
    service = WorkflowService(state, loader, attachment_manager=MagicMock())

    seen = {}
    service.reload_fcs_data(
        {"a": "a.fcs"},
        on_complete=lambda _r: seen.setdefault("cols", list(sample.fcs_data.events.columns)),
    )
    assert ratio.param_id in seen["cols"]


def test_saved_workspace_round_trip_rebuilds_gate_on_derived(state, ratio):
    _ratio_gate(state, ratio.param_id)
    data = state.to_dict()
    restored = FlowState.from_dict(data)
    sample = restored.data.experiment.samples["a"]
    sample.fcs_data = _fcs()  # what reload attaches
    sync_experiment(restored.data.experiment)
    node = next(c for c in sample.gate_tree.children if c.name == "Ratio hi")
    assert node.gate.contains(sample.fcs_data.events).tolist() == [True, False]


# ── Transforms ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("transform", list(TransformType))
def test_apply_transform_keeps_nan_as_nan(transform):
    out = apply_transform(np.array([1.0, np.nan, 100.0]), transform)
    assert np.isnan(out[1])
    assert np.isfinite(out[[0, 2]]).all()


def test_apply_transform_finite_input_unchanged():
    # Logicle's default-parameter solver already jitters ~1e-4 between
    # calls, independent of the NaN guard — compare with a tolerance.
    data = np.array([-50.0, 0.0, 10.0, 1000.0])
    before = apply_transform(data.copy(), TransformType.BIEXPONENTIAL)
    after = apply_transform(data, TransformType.BIEXPONENTIAL)
    np.testing.assert_allclose(after, before, atol=1e-3)
    np.testing.assert_array_equal(data, [-50.0, 0.0, 10.0, 1000.0])  # input not mutated


# ── Gate formula record ───────────────────────────────────────────────────


def test_gate_records_formula_and_survives_serialization_and_clone(state, ratio):
    pop = PopulationService(state)
    svc = GateMutationService(state, MagicMock(), MagicMock(), MagicMock(), pop)
    gate = RangeGate(ratio.param_id, low=3.0, high=100.0)
    svc.add_gate(gate, "a", name="Ratio hi")
    assert gate.derived_formulas == {ratio.param_id: RATIO_FORMULA}

    again = gate_from_dict(gate.to_dict())
    assert again.derived_formulas == {ratio.param_id: RATIO_FORMULA}

    target = Sample(sample_id="b", display_name="B")
    GatingService.clone_gate_tree(state.data.experiment.samples["a"].gate_tree, target)
    cloned = next(c for c in target.gate_tree.children if c.name == "Ratio hi")
    assert cloned.gate.derived_formulas == {ratio.param_id: RATIO_FORMULA}


def test_plain_gate_serialization_unchanged():
    gate = RangeGate("FITC-A", low=0.0, high=1.0)
    assert "derived_formulas" not in gate.to_dict()
    assert gate_from_dict(gate.to_dict()).derived_formulas == {}


def test_quadrant_subgates_inherit_formula_record():
    quad = QuadrantGate("derived:q0000001", "FSC-A", x_mid=1.0, y_mid=1.0)
    quad.derived_formulas = {"derived:q0000001": RATIO_FORMULA}
    nodes = quad.create_nodes(GateNode())
    assert all(n.gate.derived_formulas == quad.derived_formulas for n in nodes)


# ── Axis defaults, templates, persistence ─────────────────────────────────


def test_axis_manager_uses_preferred_transform(state, ratio):
    axis = AxisManager(state)
    assert axis.get_scale(ratio.param_id).transform_type == TransformType.LOG
    assert axis.get_scale("FITC-A").transform_type == TransformType.BIEXPONENTIAL
    assert axis.get_scale("derived:unknown1").transform_type == TransformType.LINEAR


def test_template_carries_and_merges_definitions(ratio):
    template = WorkflowTemplate(name="T", derived_parameters=[ratio.to_dict()])
    data = ExperimentSerializer.serialize_workflow_template(template)
    loaded = ExperimentSerializer.deserialize_workflow_template(data)

    exp = Experiment()
    exp.apply_template(loaded)
    exp.apply_template(loaded)  # applying twice must not duplicate
    assert [d.param_id for d in exp.derived_parameters] == [ratio.param_id]


def test_existing_workspace_serializes_without_extra_gate_keys():
    exp = Experiment()
    sample = Sample(sample_id="a", display_name="A")
    sample.gate_tree.add_child(RangeGate("FITC-A", low=0.0, high=1.0), "Pos")
    exp.add_sample(sample)
    exp.add_group(Group(group_id="g", name="G"))
    data = ExperimentSerializer.serialize_experiment(exp)
    assert data["derived_parameters"] == []
    gate_dicts = [n["gate"] for n in data["samples"]["a"]["gate_tree"]["nodes"] if n["gate"]]
    assert all("derived_formulas" not in g for g in gate_dicts)
