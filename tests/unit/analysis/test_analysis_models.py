from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from karcytics_plugins.flow_cytometry.analysis.experiment import (
    Experiment,
    Group,
    GroupRole,
    GroupTemplate,
    MarkerMapping,
    Sample,
    SampleRole,
    TubeDefinition,
    WorkflowTemplate,
)
from karcytics_plugins.flow_cytometry.analysis.experiment_io import ExperimentSerializer
from karcytics_plugins.flow_cytometry.analysis.fcs_io import FCSData
from karcytics_plugins.flow_cytometry.analysis.gating import gate_from_dict
from karcytics_plugins.flow_cytometry.analysis.gating.quadrant import QuadrantGate
from karcytics_plugins.flow_cytometry.analysis.gating.rectangle import RectangleGate
from karcytics_plugins.flow_cytometry.analysis.population_service import PopulationService
from karcytics_plugins.flow_cytometry.analysis.services.gating_service import GatingService
from karcytics_plugins.flow_cytometry.analysis.services.stats_service import StatsService


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


def test_workflow_template_save_and_load(tmp_path):
    template = WorkflowTemplate(
        name="Example Template",
        description="A simple workflow",
        markers=["CD4", "CD8"],
        marker_mappings=[MarkerMapping("CD4", "FITC", "FL1-A", "#00FF00")],
        groups=[GroupTemplate("Compensation", SampleRole.SINGLE_STAIN, [TubeDefinition(["CD4"])])],
        protocol_notes="Collect single-stain controls.",
    )

    output = tmp_path / "workflow.json"
    ExperimentSerializer.save_template(template, output)
    loaded = ExperimentSerializer.load_template(output)

    assert loaded.name == template.name
    assert loaded.description == template.description
    assert loaded.markers == template.markers
    assert loaded.groups[0].name == template.groups[0].name
    assert loaded.protocol_notes == template.protocol_notes


def test_experiment_apply_template_creates_group_and_samples():
    exp = Experiment()
    template = WorkflowTemplate(
        name="Template",
        groups=[
            GroupTemplate(
                "Comp",
                SampleRole.SINGLE_STAIN,
                [TubeDefinition(["CD4"]), TubeDefinition(["CD8"])],
            )
        ],
    )

    exp.apply_template(template)

    assert len(exp.groups) == 1
    assert len(exp.samples) == 2
    group = next(iter(exp.groups.values()))
    assert group.role == GroupRole.COMPENSATION
    assert group.size == 2


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


def test_population_service_add_and_remove_population():
    sample = Sample(sample_id="s1", display_name="Sample 1")
    state = SimpleNamespace(
        data=SimpleNamespace(experiment=SimpleNamespace(samples={"s1": sample}, groups={}))
    )
    service = PopulationService(state)

    assert service.get_root_node("s1") is sample.gate_tree
    gate = RectangleGate("FSC-A", "SSC-A", x_min=0, x_max=1, y_min=0, y_max=2)
    node = service.add_population("s1", gate, name="rect")

    assert node is not None
    assert node.name == "rect"
    assert service.find_node("s1", node.node_id) is node
    assert service.remove_population("s1", node.node_id)
    assert service.find_node("s1", node.node_id) is None


def test_population_service_add_quadrant_gate_creates_four_children():
    sample = Sample(sample_id="s1", display_name="Sample 1")
    state = SimpleNamespace(
        data=SimpleNamespace(experiment=SimpleNamespace(samples={"s1": sample}, groups={}))
    )
    service = PopulationService(state)

    quad = QuadrantGate("FSC-A", "SSC-A", x_mid=0.0, y_mid=0.0)
    quad_node = service.add_population("s1", quad, name="quadrants")

    assert quad_node is not None
    assert isinstance(quad_node, list)
    assert len(quad_node) == 4
    assert all(child.gate is not None for child in quad_node)


def test_get_gated_events_applies_gate_hierarchy_correctly():
    events = pd.DataFrame({"FSC-A": [0.0, 0.5, 2.0], "SSC-A": [0.0, 1.0, 2.0]})
    fcs_data = FCSData(Path("a.fcs"), channels=["FSC-A", "SSC-A"], markers=["", ""], events=events)
    sample = Sample(sample_id="s1", display_name="Sample 1", fcs_data=fcs_data)
    state = SimpleNamespace(
        data=SimpleNamespace(experiment=SimpleNamespace(samples={"s1": sample}, groups={}))
    )
    service = PopulationService(state)

    node = service.add_population(
        "s1",
        RectangleGate("FSC-A", "SSC-A", x_min=0.0, x_max=1.0, y_min=0.0, y_max=1.5),
        name="rect",
    )
    assert node is not None

    gated = service.get_gated_events("s1", node.node_id)
    assert list(gated["FSC-A"]) == [0.0, 0.5]


def test_gating_service_copy_gates_to_group_and_clone():
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

    copied = GatingService.copy_gates_to_group(exp, "source")
    assert copied == 1
    assert len(target.gate_tree.children) == 1
    assert target.gate_tree.children[0].gate is not source.gate_tree.children[0].gate


def test_stats_service_submits_background_task(monkeypatch):
    class DummyWorker:
        def __init__(self):
            self.task_id = "task-123"
            self.finished = self

        def connect(self, callback):
            self.callback = callback

    class DummyScheduler:
        def __init__(self):
            from unittest.mock import MagicMock

            self.task_finished = MagicMock()

        def submit(self, analyzer, state):
            assert analyzer is not None
            return DummyWorker()

    import karcytics_plugins.flow_cytometry.analysis.services.stats_service as stats_module

    monkeypatch.setattr(stats_module, "task_scheduler", DummyScheduler())

    state = SimpleNamespace(
        data=SimpleNamespace(
            experiment=SimpleNamespace(
                samples={
                    "s1": Sample(
                        sample_id="s1",
                        display_name="Sample 1",
                        fcs_data=FCSData(
                            Path("a.fcs"),
                            channels=["FSC-A"],
                            markers=[""],
                            events=pd.DataFrame({"FSC-A": [1.0]}),
                        ),
                    )
                }
            )
        )
    )

    task_id = StatsService.recompute_all_stats(state, "s1", callback=lambda: None)
    assert task_id == "task-123"
