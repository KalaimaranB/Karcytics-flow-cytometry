from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd
import pytest

from karcytics_plugins.flow_cytometry.analysis.experiment import (
    Experiment,
    Group,
    Sample,
    SampleRole,
)
from karcytics_plugins.flow_cytometry.analysis.experiment_io import ExperimentSerializer
from karcytics_plugins.flow_cytometry.analysis.fcs_io import FCSData
from karcytics_plugins.flow_cytometry.analysis.gate_coordinator import GateCoordinator
from karcytics_plugins.flow_cytometry.analysis.gating import gate_from_dict, tree_edits
from karcytics_plugins.flow_cytometry.analysis.gating.quadrant import QuadrantGate
from karcytics_plugins.flow_cytometry.analysis.gating.rectangle import RectangleGate
from karcytics_plugins.flow_cytometry.analysis.population_service import PopulationService
from karcytics_plugins.flow_cytometry.analysis.state import FlowState


def test_sample_serialization_round_trip():
    sample = Sample(
        sample_id="s1",
        display_name="Sample 1",
        role=SampleRole.SINGLE_STAIN,
        markers=["CD4"],
        keywords={"note": "test"},
        is_compensated=True,
        fmo_minus="PE-A",
        fmo_minus_detected=True,
    )

    data = ExperimentSerializer.serialize_sample(sample)
    restored = ExperimentSerializer.deserialize_sample(data)

    assert (restored.fmo_minus, restored.fmo_minus_detected) == ("PE-A", True)

    assert restored.sample_id == sample.sample_id
    assert restored.display_name == sample.display_name
    assert restored.role == sample.role
    assert restored.markers == sample.markers
    assert restored.keywords == sample.keywords
    assert restored.is_compensated is True
    assert restored.gate_tree is not None


def test_gate_from_dict_reconstructs_rectangle_gate():
    data = {
        "type": "RectangleGate",
        "x_param": "FSC-A",
        "y_param": "SSC-A",
        "x_min": 0,
        "x_max": 50,
        "y_min": 0,
        "y_max": 100,
    }

    gate = gate_from_dict(data)
    assert gate.x_param == "FSC-A"
    assert gate.y_param == "SSC-A"
    assert gate.x_min == 0
    assert gate.x_max == 50


def test_gate_from_dict_raises_on_unknown_type_and_missing_keys():
    with pytest.raises(ValueError):
        gate_from_dict({"type": "UnknownGate", "x_param": "FSC-A"})

    with pytest.raises(KeyError):
        gate_from_dict({"type": "RectangleGate"})


def test_population_service_finds_nodes_until_they_are_removed():
    sample = Sample(sample_id="s1", display_name="Sample 1")
    state = SimpleNamespace(
        data=SimpleNamespace(experiment=SimpleNamespace(samples={"s1": sample}, groups={}))
    )
    service = PopulationService(state)

    assert service.get_root_node("s1") is sample.gate_tree
    gate = RectangleGate("FSC-A", "SSC-A", x_min=0, x_max=1, y_min=0, y_max=2)
    [node] = gate.create_nodes(sample.gate_tree, "rect")

    assert service.find_node("s1", node.node_id) is node
    assert tree_edits.remove_subtree(sample, node.node_id) == {node.node_id}
    assert service.find_node("s1", node.node_id) is None


def test_quadrant_gate_creates_four_gated_children():
    sample = Sample(sample_id="s1", display_name="Sample 1")
    quad = QuadrantGate("FSC-A", "SSC-A", x_mid=0.0, y_mid=0.0)

    nodes = quad.create_nodes(sample.gate_tree, "quadrants")

    assert [n.name for n in nodes] == ["Q1", "Q2", "Q3", "Q4"]
    assert all(child.gate is not None for child in nodes)


def test_get_gated_events_applies_gate_hierarchy_correctly():
    events = pd.DataFrame({"FSC-A": [0.0, 0.5, 2.0], "SSC-A": [0.0, 1.0, 2.0]})
    fcs_data = FCSData(Path("a.fcs"), channels=["FSC-A", "SSC-A"], markers=["", ""], events=events)
    sample = Sample(sample_id="s1", display_name="Sample 1", fcs_data=fcs_data)
    state = SimpleNamespace(
        data=SimpleNamespace(experiment=SimpleNamespace(samples={"s1": sample}, groups={}))
    )
    service = PopulationService(state)

    [node] = RectangleGate(
        "FSC-A", "SSC-A", x_min=0.0, x_max=1.0, y_min=0.0, y_max=1.5
    ).create_nodes(sample.gate_tree, "rect")

    gated = service.get_gated_events("s1", node.node_id)
    assert list(gated["FSC-A"]) == [0.0, 0.5]


def test_copy_gates_to_group_clones_into_group_members():
    exp = Experiment()
    source = Sample(
        sample_id="source",
        display_name="Source",
        fcs_data=FCSData(
            Path("source.fcs"),
            channels=["FSC-A", "SSC-A"],
            markers=["", ""],
            events=pd.DataFrame({"FSC-A": [0.0], "SSC-A": [0.0]}),
        ),
    )
    target = Sample(
        sample_id="target",
        display_name="Target",
        fcs_data=FCSData(
            Path("target.fcs"),
            channels=["FSC-A", "SSC-A"],
            markers=["", ""],
            events=pd.DataFrame({"FSC-A": [1.0], "SSC-A": [1.0]}),
        ),
    )
    exp.add_sample(source)
    exp.add_sample(target)
    exp.add_group(Group(group_id="g1", name="Group", sample_ids=["source", "target"]))

    source.gate_tree.add_child(
        RectangleGate("FSC-A", "SSC-A", x_min=0.0, x_max=1.0, y_min=0.0, y_max=1.0),
        name="rect",
    )

    assert tree_edits.copy_gates_to_group(exp, "source") == [target]
    assert len(target.gate_tree.children) == 1
    assert target.gate_tree.children[0].gate is not source.gate_tree.children[0].gate


def test_background_stats_land_on_the_node_when_their_task_finishes(monkeypatch):
    import karcytics_plugins.flow_cytometry.analysis.gate_coordinator as coordinator_module

    class Scheduler:
        def __init__(self):
            self.submitted = []
            self.listeners = []
            self.task_finished = SimpleNamespace(
                connect=self.listeners.append, disconnect=self.listeners.remove
            )

        def submit(self, analyzer, state):
            self.submitted.append(analyzer)
            return SimpleNamespace(task_id="task-123")

    scheduler = Scheduler()
    monkeypatch.setattr(coordinator_module, "task_scheduler", scheduler)
    state = FlowState()
    sample = Sample(
        sample_id="s1",
        display_name="Sample 1",
        fcs_data=FCSData(
            Path("a.fcs"), channels=["FSC-A"], markers=[""], events=pd.DataFrame({"FSC-A": [1.0]})
        ),
    )
    state.data.experiment.samples["s1"] = sample
    coordinator = GateCoordinator(state, MagicMock(), PopulationService(state))

    coordinator.recompute_all_stats("s1")

    assert [a.target_sample_id for a in scheduler.submitted] == ["s1"]
    stats = {"count": 1, "pct_parent": 100.0, "pct_total": 100.0}
    root_id = sample.gate_tree.node_id
    scheduler.listeners[0]("other-task", {"sample_id": "s1", "stats": {root_id: {"count": 9}}})
    scheduler.listeners[0]("task-123", {"sample_id": "s1", "stats": {root_id: stats}})
    assert sample.gate_tree.statistics == stats
    assert scheduler.listeners == []
