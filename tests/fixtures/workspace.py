"""A realistic, fully populated workspace for serializer / undo / load tests.

Every kind of model content the flow module persists appears at least once,
so a round-trip or restore test over this state covers the whole schema:
every geometric gate type, a quadrant (4 sub-nodes), a wired logic node, a
UMAP container with subset-index clusters, a gate on a derived parameter,
groups with channel scales, sample roles/markers/keywords, marker mappings,
an active template, and a compensation matrix.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from karcytics_plugins.flow_cytometry.analysis.compensation import CompensationMatrix
from karcytics_plugins.flow_cytometry.analysis.derived.models import DerivedParameter
from karcytics_plugins.flow_cytometry.analysis.experiment import (
    Group,
    GroupRole,
    MarkerMapping,
    Sample,
    SampleRole,
    WorkflowTemplate,
)
from karcytics_plugins.flow_cytometry.analysis.fcs_io import FCSData
from karcytics_plugins.flow_cytometry.analysis.gating import (
    EllipseGate,
    GateNode,
    PolygonGate,
    QuadrantGate,
    RangeGate,
    RectangleGate,
    SubsetGate,
)
from karcytics_plugins.flow_cytometry.analysis.scaling import AxisScale
from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.analysis.transforms import TransformType

CHANNELS = ["FSC-A", "SSC-A", "FITC-A", "APC-A"]
RATIO_ID = "derived:ratio0001"


def make_fcs(name: str, n: int = 200, seed: int = 0) -> FCSData:
    rng = np.random.default_rng(seed)
    df = pd.DataFrame({ch: rng.uniform(1, 1000, n) for ch in CHANNELS})
    return FCSData(
        Path(f"/data/{name}.fcs"), list(CHANNELS), ["", "", "B220", "CD45"], df, df.copy()
    )


def _wire(child: GateNode, *parents: GateNode) -> None:
    for parent in parents:
        child.parents.append(parent)
        parent.children.append(child)


def build_gate_tree(root: GateNode) -> dict[str, GateNode]:
    """Populate `root` with one of everything; returns the nodes by name."""
    nodes: dict[str, GateNode] = {}
    lymph = root.add_child(
        PolygonGate("FSC-A", "SSC-A", [(10.0, 10.0), (900.0, 20.0), (500.0, 900.0)]),
        name="Lymphocytes",
    )
    nodes["Lymphocytes"] = lymph
    nodes["Singlets"] = lymph.add_child(
        RectangleGate("FSC-A", "SSC-A", x_min=0.0, x_max=800.0, y_min=5.0, y_max=700.0),
        name="Singlets",
    )
    nodes["Blob"] = lymph.add_child(
        EllipseGate(
            "FITC-A", "APC-A", center=(400.0, 400.0), width=200.0, height=120.0, angle=15.0
        ),
        name="Blob",
    )
    nodes["FITC+"] = nodes["Singlets"].add_child(
        RangeGate("FITC-A", low=300.0, high=900.0), name="FITC+"
    )
    for q in QuadrantGate("FITC-A", "APC-A", x_mid=500.0, y_mid=500.0).create_nodes(
        nodes["Singlets"]
    ):
        nodes[q.name] = q
    ratio_gate = RangeGate(RATIO_ID, low=0.5, high=2.0)
    ratio_gate.derived_formulas = {RATIO_ID: "[FITC-A] / [APC-A]"}
    nodes["Ratio hi"] = lymph.add_child(ratio_gate, name="Ratio hi")

    both = GateNode(name="FITC+ AND Blob", logic_operator="AND", is_logic_node=True)
    _wire(both, nodes["FITC+"], nodes["Blob"])
    nodes["FITC+ AND Blob"] = both

    umap = lymph.add_child(SubsetGate(indices=list(range(0, 150))), name="UMAP Reduction")
    umap.is_umap_parent = True
    nodes["UMAP Reduction"] = umap
    for i, (lo, hi) in enumerate([(0, 60), (60, 150)]):
        cluster = umap.add_child(SubsetGate(indices=list(range(lo, hi))), name=f"Cluster {i}")
        cluster.scale_factor = 1.25
        cluster.is_estimated = True
        nodes[cluster.name] = cluster
    return nodes


def build_rich_state(n_samples: int = 3) -> FlowState:
    state = FlowState()
    exp = state.data.experiment
    exp.name = "Rich Experiment"
    exp.derived_parameters = [
        DerivedParameter(param_id=RATIO_ID, name="FITC/APC", formula="[FITC-A] / [APC-A]")
    ]
    exp.marker_mappings = [
        MarkerMapping("B220", fluorophore="FITC", channel="FITC-A", color="#00FF00"),
        MarkerMapping("CD45", fluorophore="APC", channel="APC-A", color="#FF0000"),
    ]
    exp.active_template = WorkflowTemplate(
        name="Panel A", description="B cells", markers=["B220", "CD45"], protocol_notes="notes"
    )
    roles = [SampleRole.UNSTAINED, SampleRole.FULL_PANEL, SampleRole.FMO_CONTROL]
    for i in range(n_samples):
        sid = f"s{i}"
        sample = Sample(
            sample_id=sid,
            display_name=f"Sample {i}",
            fcs_data=make_fcs(sid, seed=i),
            role=roles[i % len(roles)],
            markers=["B220", "CD45"],
            fmo_minus="CD45" if roles[i % len(roles)] == SampleRole.FMO_CONTROL else None,
            keywords={"$TOT": "200", "$CYT": "Aurora"},
        )
        sample.last_viewed_axes = {"root": {"x_param": "FSC-A", "y_param": "SSC-A"}}
        exp.samples[sid] = sample
        build_gate_tree(sample.gate_tree)

    group = Group(group_id="g1", name="Tests", role=GroupRole.TEST, color="#123456")
    group.channel_scales = {"FITC-A": AxisScale(TransformType.BIEXPONENTIAL)}
    exp.groups["g1"] = group
    for sid in list(exp.samples)[:2]:
        group.sample_ids.append(sid)
        exp.samples[sid].group_ids.append("g1")

    state.data.compensation = CompensationMatrix(
        matrix=np.array([[1.0, 0.1], [0.05, 1.0]]),
        channel_names=["FITC-A", "APC-A"],
        source="computed",
    )
    set_real_view_defaults(state)
    state.view.current_sample_id = "s0"
    return state


def set_real_view_defaults(state: FlowState) -> None:
    """Give view settings concrete values.

    Their defaults come from FlowConfig, which reads the (mocked-out in
    tests) PluginConfig — in the app they're plain strings/bools.
    """
    state.view.active_x_param = "FSC-A"
    state.view.active_y_param = "SSC-A"
    state.view.auto_range_on_quality = True


def fake_umap_run(sample_id: str = "s0", n: int = 50) -> dict[str, Any]:
    return {
        "sample_id": sample_id,
        "node_id": None,
        "embedding": np.zeros((n, 2), dtype=np.float32),
        "indices": np.arange(n),
        "name": "run",
    }


class FakeBus:
    """Synchronous stand-in for CentralEventBus (which is mocked in tests)."""

    def __init__(self) -> None:
        self.subscribers: dict[str, list[Callable[[Any], None]]] = {}
        self.published: list[tuple[str, Any]] = []

    def subscribe(self, topic: str, callback: Callable[[Any], None]) -> None:
        self.subscribers.setdefault(topic, []).append(callback)

    def unsubscribe(self, topic: str, callback: Callable[[Any], None]) -> None:
        if callback in self.subscribers.get(topic, []):
            self.subscribers[topic].remove(callback)

    def publish(self, topic: str, data: Any = None) -> None:
        self.published.append((topic, data))
        for callback in list(self.subscribers.get(topic, [])):
            callback(data)

    def topics(self) -> list[str]:
        return [t for t, _ in self.published]


class ManualDefer:
    """Collects deferred callbacks; `run()` plays them like an event-loop turn."""

    def __init__(self) -> None:
        self.pending: list[Callable[[], None]] = []

    def __call__(self, fn: Callable[[], None]) -> None:
        self.pending.append(fn)

    def run(self) -> None:
        pending, self.pending = self.pending, []
        for fn in pending:
            fn()
