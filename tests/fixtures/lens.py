"""Synthetic samples with planted gating mistakes, for the Sample Lens tests.

Cell types sit at known spots, so the expected findings are known:
NK cells are never gated (missed), the CD8+ gate also catches NKT cells
(merges), and the CD4+ gate's left edge runs through the CD4 T cells (cuts).
"""

from pathlib import Path

import numpy as np
import pandas as pd

from karcytics_plugins.flow_cytometry.analysis.experiment import Sample
from karcytics_plugins.flow_cytometry.analysis.fcs_io import FCSData
from karcytics_plugins.flow_cytometry.analysis.gating import RectangleGate, SubsetGate

CHANNELS = ["FSC-A", "SSC-A", "CD3", "CD4", "CD8", "CD56"]
TOP = 6000.0
# name: (cluster, means in thousands for CHANNELS, share)
CELL_TYPES = {
    "debris": (-1, (0.6, 0.5, 0.5, 0.5, 0.5, 0.5), 0.08),
    "CD4 T": (1, (2.0, 0.9, 3.4, 3.0, 0.5, 0.5), 0.40),
    "CD8 T": (2, (2.0, 0.9, 3.4, 0.5, 3.4, 0.5), 0.22),
    "NKT": (3, (2.0, 0.9, 3.0, 0.5, 2.9, 3.2), 0.08),
    "NK": (4, (2.0, 0.9, 0.5, 0.5, 1.5, 3.0), 0.22),
}


def make_sample(sid: str, n: int = 6000, seed: int = 0, cd4_shift: float = 0.0):
    """A sample with the planted gating; returns (sample, events, true cluster per row)."""
    rng = np.random.default_rng(seed)
    blocks, labels = [], []
    for cluster, means, share in CELL_TYPES.values():
        m = np.array(means) * 1000
        if cluster == 1:
            m[3] += cd4_shift
        count = int(n * share)
        blocks.append(rng.normal(m, 280, size=(count, len(CHANNELS))))
        labels.append(np.full(count, cluster))
    values = np.clip(np.vstack(blocks), 0, TOP)
    # Non-trivial row labels, so alignment by label (not position) is exercised.
    events = pd.DataFrame(values, columns=CHANNELS, index=np.arange(len(values)) * 3 + 7)
    fcs = FCSData(Path(f"/{sid}.fcs"), list(CHANNELS), [""] * len(CHANNELS), events, events)

    sample = Sample(sample_id=sid, display_name=sid.upper(), fcs_data=fcs)
    root = sample.gate_tree
    lymph = root.add_child(
        RectangleGate("FSC-A", "SSC-A", x_min=1300, x_max=2800, y_min=300, y_max=1600),
        "Lymphocytes",
    )
    t_cells = lymph.add_child(
        RectangleGate("CD3", "CD56", x_min=2200, x_max=TOP, y_min=0, y_max=TOP), "T cells"
    )
    t_cells.add_child(
        RectangleGate("CD4", "CD8", x_min=2800, x_max=TOP, y_min=0, y_max=1600), "CD4+"
    )
    t_cells.add_child(
        RectangleGate("CD8", "CD4", x_min=2200, x_max=TOP, y_min=0, y_max=1600), "CD8+"
    )
    umap = lymph.add_child(SubsetGate(indices=[7, 10]), "UMAP Reduction")
    umap.is_umap_parent = True
    umap.add_child(SubsetGate(indices=[7]), "Cluster 0")
    return sample, events, np.concatenate(labels)


def make_run(events: pd.DataFrame, clusters: np.ndarray, n: int = 4000, seed: int = 1) -> dict:
    rng = np.random.default_rng(seed)
    pick = rng.choice(len(events), n, replace=False)
    return {
        "node_id": None,
        "indices": events.index.to_numpy()[pick],
        "embedding": rng.normal(size=(n, 2)),
        "clusters": clusters[pick],
        "channels": CHANNELS[2:],  # the markers, as a real run records them
    }


def build_lens_state(n_samples: int = 4, shifted: int = 2):
    """A FlowState of planted samples in one group; s0 has a clustering run.

    Sample ``shifted`` has dimmer CD4, so it is the cross-sample outlier.
    """
    from karcytics_plugins.flow_cytometry.analysis.experiment import Group
    from karcytics_plugins.flow_cytometry.analysis.state import FlowState

    state = FlowState()
    exp = state.data.experiment
    group = Group(group_id="g", name="Tests")
    exp.groups["g"] = group
    for i in range(n_samples):
        sample, events, truth = make_sample(
            f"s{i}", seed=i, cd4_shift=-700.0 if i == shifted else 0.0
        )
        sample.group_ids.append("g")
        group.sample_ids.append(sample.sample_id)
        exp.samples[sample.sample_id] = sample
        if i == 0:
            run = make_run(events, truth)
            run.update(sample_id="s0", name="Sample Lens")
            state.data.umap_results["s0::root"] = [run]
    state.view.current_sample_id = "s0"
    return state


class TreeController:
    """Adds gates to the real tree, like the gate coordinator (minus events)."""

    def __init__(self, state) -> None:
        from karcytics_plugins.flow_cytometry.analysis.population_service import PopulationService

        self._population_service = PopulationService(state)
        self.added: list = []

    def add_gate(self, gate, sample_id, name=None, parent_node_id=None):
        node = self._population_service.add_population(sample_id, gate, parent_node_id, name)
        self.added.append((name, parent_node_id))
        return node.node_id

    def get_gates_for_display(self, sample_id, parent_node_id=None):
        return [], []


class FakeUmapService:
    def __init__(self) -> None:
        self.calls: list = []

    def run_analysis(self, params, on_done, on_error_cb, on_progress=None):
        self.calls.append((params, on_done, on_error_cb))
