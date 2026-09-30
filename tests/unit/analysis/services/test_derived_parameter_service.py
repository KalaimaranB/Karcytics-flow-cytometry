"""Tests for DerivedParameterService (validation, CRUD, dependents, sync)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from karcytics_plugins.flow_cytometry.analysis import events as flow_events
from karcytics_plugins.flow_cytometry.analysis.constants import MAX_DERIVED_PARAMETERS
from karcytics_plugins.flow_cytometry.analysis.derived import FormulaError
from karcytics_plugins.flow_cytometry.analysis.experiment import Group, Sample
from karcytics_plugins.flow_cytometry.analysis.experiment_io import ExperimentSerializer
from karcytics_plugins.flow_cytometry.analysis.fcs_io import FCSData
from karcytics_plugins.flow_cytometry.analysis.gating.rectangle import RectangleGate
from karcytics_plugins.flow_cytometry.analysis.scaling import AxisScale
from karcytics_plugins.flow_cytometry.analysis.services import derived_parameter_service as mod
from karcytics_plugins.flow_cytometry.analysis.services.derived_parameter_service import (
    DerivedParameterError,
    DerivedParameterInUseError,
    DerivedParameterService,
)
from karcytics_plugins.flow_cytometry.analysis.state import FlowState


def _sample(sid: str, with_apc: bool = True) -> Sample:
    cols = {"FSC-A": [1.0, 2.0], "FITC-A": [10.0, 4.0]}
    channels, markers = ["FSC-A", "FITC-A"], ["", "B220"]
    if with_apc:
        cols["APC-A"] = [2.0, 4.0]
        channels.append("APC-A")
        markers.append("CD45")
    df = pd.DataFrame(cols)
    fcs = FCSData(Path(f"{sid}.fcs"), channels, markers, df, df.copy())
    return Sample(sample_id=sid, display_name=f"Sample {sid.upper()}", fcs_data=fcs)


@pytest.fixture
def state() -> FlowState:
    st = FlowState()
    st.data.experiment.samples = {"a": _sample("a"), "b": _sample("b")}
    return st


@pytest.fixture
def service(state) -> DerivedParameterService:
    return DerivedParameterService(state)


def test_create_syncs_every_sample_and_publishes(service, state, monkeypatch):
    published = []
    monkeypatch.setattr(mod.CentralEventBus, "publish", lambda t, p: published.append((t, p)))
    d = service.create("B220/CD45", "[FITC-A] / [APC-A]")
    assert d.param_id.startswith("derived:")
    for sample in state.data.experiment.samples.values():
        np.testing.assert_array_equal(sample.fcs_data.events[d.param_id], [5.0, 1.0])
        assert d.param_id in sample.fcs_data.channels
    assert published == [
        (flow_events.DERIVED_PARAMS_CHANGED, {"param_id": d.param_id, "action": "created"})
    ]


def test_marker_labels_canonicalize_to_channels(service):
    d = service.create("Ratio", "[b220] / [CD45]")
    assert d.formula == "[FITC-A] / [APC-A]"


def test_unknown_channel_rejected_with_position(service):
    with pytest.raises(FormulaError, match="Unknown channel") as info:
        service.create("Bad", "[FITC-A] / [CD999]")
    assert info.value.position == 11


def test_derived_reference_rejected(service):
    d = service.create("R", "[FITC-A] / [APC-A]")
    with pytest.raises(FormulaError, match="other derived"):
        service.create("R2", f"[{d.param_id}] * 2")


@pytest.mark.parametrize(
    ("name", "match"),
    [("", "required"), ("   ", "required"), ("x" * 61, "too long"), ("FITC-A", "channel")],
)
def test_bad_names(service, name, match):
    with pytest.raises(DerivedParameterError, match=match):
        service.create(name, "[FITC-A] * 2")


def test_name_clashing_with_marker_label_rejected(service):
    with pytest.raises(DerivedParameterError, match="channel"):
        service.create("B220 (FITC-A)", "[FITC-A] * 2")


def test_duplicate_name_case_insensitive(service):
    service.create("Ratio", "[FITC-A] / [APC-A]")
    with pytest.raises(DerivedParameterError, match="already exists"):
        service.create("ratio", "[FITC-A] * 2")


def test_limit(service):
    for i in range(MAX_DERIVED_PARAMETERS):
        service.create(f"P{i}", "[FITC-A] * 2")
    with pytest.raises(DerivedParameterError, match="Limit"):
        service.create("One more", "[FITC-A] * 2")


def test_biexponential_not_allowed(service):
    with pytest.raises(DerivedParameterError, match="scale"):
        service.create("R", "[FITC-A] * 2", preferred_transform="biexponential")


def test_update_recomputes_and_resets_scales(service, state):
    d = service.create("R", "[FITC-A] / [APC-A]")
    group = Group(group_id="g", name="G", sample_ids=["a"])
    group.channel_scales[d.param_id] = AxisScale(min_val=0.0, max_val=10.0)
    state.data.experiment.groups["g"] = group

    service.update(
        d.param_id,
        name="R renamed",
        formula="[APC-A] / [FITC-A]",
        preferred_transform="linear",
        positive_denominators=True,
    )
    events = state.data.experiment.samples["a"].fcs_data.events
    np.testing.assert_allclose(events[d.param_id], [0.2, 1.0])
    assert d.param_id not in group.channel_scales
    assert d.name == "R renamed"
    assert state.data.experiment.samples["a"].fcs_data.derived_labels[d.param_id] == "ƒ R renamed"


def test_update_allows_keeping_own_name(service):
    d = service.create("R", "[FITC-A] / [APC-A]")
    service.update(
        d.param_id,
        name="R",
        formula=d.formula,
        preferred_transform="log",
        positive_denominators=False,
    )
    assert not d.positive_denominators


def _gate_on(state, sample_id, param_id):
    gate = RectangleGate(param_id, None, x_min=0.0, x_max=3.0)
    return state.data.experiment.samples[sample_id].gate_tree.add_child(gate, "Ratio lo")


def test_find_dependents_and_delete_refused(service, state):
    d = service.create("R", "[FITC-A] / [APC-A]")
    node = _gate_on(state, "b", d.param_id)
    deps = service.find_dependents(d.param_id)
    assert [(x.sample_id, x.node_id, x.node_name) for x in deps] == [
        ("b", node.node_id, "Ratio lo")
    ]
    with pytest.raises(DerivedParameterInUseError) as info:
        service.delete(d.param_id)
    assert info.value.dependents == deps
    assert service.get(d.param_id) is not None


def test_delete_removes_columns(service, state):
    d = service.create("R", "[FITC-A] / [APC-A]")
    service.delete(d.param_id)
    assert service.definitions == []
    for sample in state.data.experiment.samples.values():
        assert d.param_id not in sample.fcs_data.events.columns
        assert d.param_id not in sample.fcs_data.channels


def test_gate_on_derived_parameter_evaluates(service, state):
    d = service.create("R", "[FITC-A] / [APC-A]")
    node = _gate_on(state, "a", d.param_id)
    events = state.data.experiment.samples["a"].fcs_data.events
    mask = node.gate.contains(events)
    np.testing.assert_array_equal(mask, [False, True])  # ratios 5.0 and 1.0


def test_sample_missing_input_gets_nan_column(state):
    state.data.experiment.samples["c"] = _sample("c", with_apc=False)
    service = DerivedParameterService(state)
    d = service.create("R", "[FITC-A] / [APC-A]")
    results = service.sync_all()
    assert results["c"].missing == {d.param_id: ["APC-A"]}
    node = _gate_on(state, "c", d.param_id)
    events = state.data.experiment.samples["c"].fcs_data.events
    assert not node.gate.contains(events).any()


def test_serialization_round_trip_and_old_workspace(service, state):
    d = service.create("R", "[FITC-A] / [APC-A]", preferred_transform="linear")
    data = ExperimentSerializer.serialize_experiment(state.data.experiment)
    restored = ExperimentSerializer.deserialize_experiment(data)
    assert [x.to_dict() for x in restored.derived_parameters] == [d.to_dict()]

    del data["derived_parameters"]
    assert ExperimentSerializer.deserialize_experiment(data).derived_parameters == []


def test_ensure_sample_without_data(service):
    assert not service.ensure_sample(Sample(sample_id="z", display_name="Z")).changed
