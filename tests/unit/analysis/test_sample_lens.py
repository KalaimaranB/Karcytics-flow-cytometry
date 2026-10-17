"""Sample Lens analysis on a synthetic sample with planted gating mistakes.

Cell types sit at known spots, so the expected findings are known:
NK cells are never gated (missed), the CD8+ gate also catches NKT cells
(merges), and the CD4+ gate's left edge runs through the CD4 T cells (cuts).
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from karcytics_plugins.flow_cytometry.analysis.experiment import Sample
from karcytics_plugins.flow_cytometry.analysis.fcs_io import FCSData
from karcytics_plugins.flow_cytometry.analysis.gating import (
    GateNode,
    PolygonGate,
    RectangleGate,
    SubsetGate,
)
from karcytics_plugins.flow_cytometry.analysis.sample_lens import (
    FindingKind,
    audit,
    build_scope,
    check_across,
    edge_fraction,
    final_populations,
    propose_gates,
)
from karcytics_plugins.flow_cytometry.analysis.scaling import AxisScale
from karcytics_plugins.flow_cytometry.analysis.transforms import TransformType

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
    }


@pytest.fixture
def planted():
    sample, events, truth = make_sample("s1")
    return sample, events, truth, build_scope(sample, make_run(events, truth), events)


def test_final_populations_are_leaves_without_cluster_exports(planted):
    sample, *_ = planted
    paths = [p.path for p in final_populations(sample)]
    assert paths == ["Lymphocytes / T cells / CD4+", "Lymphocytes / T cells / CD8+"]


def test_scope_aligns_run_rows_by_event_label(planted):
    sample, events, truth, scope = planted
    assert scope.n == 4000
    labels = events.index.to_numpy()[scope.rows]
    np.testing.assert_array_equal(labels, scope.run["indices"])
    np.testing.assert_array_equal(truth[scope.rows], scope.clusters)
    cd4 = sample.gate_tree.children[0].children[0].children[0]
    np.testing.assert_array_equal(
        scope.masks["Lymphocytes / T cells / CD4+"], cd4.mask(events)[scope.rows]
    )


def test_audit_finds_the_planted_mistakes(planted):
    *_, scope = planted
    found = {(f.kind, f.population, f.clusters) for f in audit(scope)}
    assert found == {
        (FindingKind.MISSED, None, (4,)),
        (FindingKind.MERGES, "Lymphocytes / T cells / CD8+", (2, 3)),
        (FindingKind.CUTS, "Lymphocytes / T cells / CD4+", (1,)),
    }


def test_audit_without_clusters_says_nothing(planted):
    *_, scope = planted
    scope.clusters = None
    assert audit(scope) == []


def test_parent_mask_is_the_population_before_its_own_gate(planted):
    sample, events, *_ = planted
    t_cells = sample.gate_tree.children[0].children[0]
    cd4 = t_cells.children[0]
    np.testing.assert_array_equal(cd4.parent_mask(events), t_cells.mask(events))


def test_edge_fraction_is_high_only_where_an_edge_cuts_a_population(planted):
    sample, events, *_ = planted
    t_cells = sample.gate_tree.children[0].children[0]
    parent = events.loc[t_cells.mask(events)]
    cd4, cd8 = t_cells.children[0].gate, t_cells.children[1].gate
    assert edge_fraction(cd4, parent) > 0.05
    assert edge_fraction(cd8, parent) < 0.05

    # Shape-independent: the same CD8+ region as a polygon behaves the same.
    poly = PolygonGate("CD8", "CD4", [(2200, 0), (TOP, 0), (TOP, 1600), (2200, 1600)])
    assert edge_fraction(poly, parent) == pytest.approx(edge_fraction(cd8, parent), abs=0.01)


def test_check_across_flags_the_sample_with_shifted_staining():
    entries = [
        make_sample(f"s{i}", seed=i, cd4_shift=-700.0 if i == 3 else 0.0)[:2] for i in range(5)
    ]
    checks = check_across(entries, "Lymphocytes / T cells / CD4+")
    assert [c.sample_id for c in checks] == [f"s{i}" for i in range(5)]
    outliers = [c.sample_id for c in checks if any("outlier" in f for f in c.flags)]
    assert outliers == ["s3"]
    # The edge runs through the CD4 T cells everywhere except s3, whose dimmer
    # staining moved them mostly off the gate (that's why it is an outlier).
    on_edge = [c.sample_id for c in checks if "edge in a dense region" in c.flags]
    assert on_edge == ["s0", "s1", "s2", "s4"]


def test_check_across_skips_samples_without_the_population(planted):
    sample, events, *_ = planted
    assert check_across([(sample, events)], "Nope / Missing") == []


@pytest.mark.parametrize("transform", [TransformType.LINEAR, TransformType.BIEXPONENTIAL])
def test_proposed_gates_recover_the_missed_cluster(planted, transform):
    sample, events, truth, scope = planted
    run_events = events.iloc[scope.rows]
    target = scope.clusters == 4  # noqa: PLR2004
    scales = {ch: AxisScale(transform_type=transform, logicle_t=TOP) for ch in CHANNELS}

    proposal = propose_gates(run_events, target, scales)

    assert proposal
    assert proposal[-1].f1 > 0.95  # noqa: PLR2004
    # The gates, applied as a chain to the raw events, select what was scored.
    selected = np.ones(len(run_events), dtype=bool)
    for step in proposal:
        selected &= step.gate.contains(run_events)
    tp = (selected & target).sum()
    assert 2 * tp / (selected.sum() + target.sum()) == pytest.approx(proposal[-1].f1, abs=0.02)


def test_gate_node_mask_matches_apply_hierarchy(planted):
    sample, events, *_ = planted
    node: GateNode = sample.gate_tree.children[0].children[0]
    assert node.mask(events).sum() == len(node.apply_hierarchy(events))
