"""Unit tests for population_matching: the grouping logic behind the shared
sample/population selector (Statistics + Comparisons tabs).
"""

import pytest

from karcytics_plugins.flow_cytometry.analysis.experiment import Sample
from karcytics_plugins.flow_cytometry.analysis.gating.gate_node import GateNode
from karcytics_plugins.flow_cytometry.analysis.population_matching import (
    ALL_EVENTS_LABEL,
    compute_population_groups,
    label_path_index,
)


def _make_sample(sample_id: str, tree_shape: list[tuple[str, str | None]]) -> Sample:
    """Build a Sample whose gate_tree has one linear chain per (name, parent_name) pair.

    ``tree_shape`` entries are (node_name, parent_name_or_None); None means
    "attach directly under the root".
    """
    root = GateNode()
    by_name: dict[str, GateNode] = {}
    for name, parent_name in tree_shape:
        parent = by_name[parent_name] if parent_name else root
        by_name[name] = parent.add_child(None, name=name)
    return Sample(sample_id=sample_id, display_name=sample_id, gate_tree=root)


@pytest.mark.unit
class TestLabelPathIndex:
    def test_includes_all_events_sentinel(self):
        sample = _make_sample("s1", [])
        idx = label_path_index(sample)
        assert idx == {ALL_EVENTS_LABEL: None}

    def test_nested_paths_use_full_ancestor_chain(self):
        sample = _make_sample(
            "s1",
            [("Lymphocytes", None), ("CD3+", "Lymphocytes"), ("CD4+", "CD3+")],
        )
        idx = label_path_index(sample)
        assert "Lymphocytes" in idx
        assert "Lymphocytes / CD3+" in idx
        assert "Lymphocytes / CD3+ / CD4+" in idx

    def test_disambiguates_same_leaf_name_in_different_branches(self):
        sample = _make_sample(
            "s1",
            [
                ("CD3+", None),
                ("CD8-", None),
                ("CD4+", "CD3+"),
                ("CD4+", "CD8-"),
            ],
        )
        idx = label_path_index(sample)
        assert "CD3+ / CD4+" in idx
        assert "CD8- / CD4+" in idx
        assert idx["CD3+ / CD4+"] != idx["CD8- / CD4+"]

    def test_multi_parent_logic_node_counted_once(self):
        """A logic node (AND/OR/NOT) is a genuine child of every parent it
        combines — the gate tree is a DAG there, not a strict tree. Without
        a visited-node-id guard, a naive walk reaches the same node once per
        parent, under two different label-paths, both resolving to the same
        node_id — the live "AND Logic shows up twice" bug.
        """
        root = GateNode()
        b_cells = root.add_child(None, name="B-cells")
        umap_b_cells = root.add_child(None, name="UMAP B Cells")
        and_node = GateNode(name="AND Logic", is_logic_node=True, parents=[b_cells, umap_b_cells])
        b_cells.children.append(and_node)
        umap_b_cells.children.append(and_node)
        sample = Sample(sample_id="s1", display_name="s1", gate_tree=root)

        idx = label_path_index(sample)
        node_ids = list(idx.values())
        assert node_ids.count(and_node.node_id) == 1


@pytest.mark.unit
class TestComputePopulationGroups:
    def test_empty_input(self):
        groups = compute_population_groups([])
        assert groups.shared == []
        assert groups.per_sample == {}

    def test_single_sample_everything_is_shared(self):
        sample = _make_sample("s1", [("Lymphocytes", None), ("CD3+", "Lymphocytes")])
        groups = compute_population_groups([sample])
        assert set(groups.shared) == {ALL_EVENTS_LABEL, "Lymphocytes", "Lymphocytes / CD3+"}
        assert groups.per_sample == {"s1": []}

    def test_fully_shared_gates_from_propagation(self):
        shape = [("Lymphocytes", None), ("CD3+", "Lymphocytes")]
        samples = [_make_sample("s1", shape), _make_sample("s2", shape), _make_sample("s3", shape)]
        groups = compute_population_groups(samples)
        assert set(groups.shared) == {ALL_EVENTS_LABEL, "Lymphocytes", "Lymphocytes / CD3+"}
        assert groups.per_sample == {"s1": [], "s2": [], "s3": []}

    def test_partially_shared_gates(self):
        s1 = _make_sample("s1", [("Lymphocytes", None), ("Debris", None)])
        s2 = _make_sample("s2", [("Lymphocytes", None), ("CD19+", "Lymphocytes")])
        groups = compute_population_groups([s1, s2])
        assert set(groups.shared) == {ALL_EVENTS_LABEL, "Lymphocytes"}
        assert groups.per_sample["s1"] == ["Debris"]
        assert groups.per_sample["s2"] == ["Lymphocytes / CD19+"]

    def test_no_overlap_still_shares_all_events(self):
        s1 = _make_sample("s1", [("Lymphocytes", None)])
        s2 = _make_sample("s2", [("Monocytes", None)])
        groups = compute_population_groups([s1, s2])
        assert groups.shared == [ALL_EVENTS_LABEL]
        assert groups.per_sample["s1"] == ["Lymphocytes"]
        assert groups.per_sample["s2"] == ["Monocytes"]

    def test_renamed_gate_drops_out_of_shared(self):
        """Known limitation: matching is by label text. Propagation rebuilds a
        fresh GateNode per sample, so a post-propagation rename on one sample
        breaks the match even though the gate is otherwise identical.
        """
        s1 = _make_sample("s1", [("Lymphocytes", None)])
        s2 = _make_sample("s2", [("Lymphocytes (renamed)", None)])
        groups = compute_population_groups([s1, s2])
        assert "Lymphocytes" not in groups.shared
        assert groups.per_sample["s1"] == ["Lymphocytes"]
        assert groups.per_sample["s2"] == ["Lymphocytes (renamed)"]

    def test_node_index_resolves_shared_label_to_each_samples_own_node_id(self):
        shape = [("Lymphocytes", None)]
        s1 = _make_sample("s1", shape)
        s2 = _make_sample("s2", shape)
        groups = compute_population_groups([s1, s2])
        node_id_1 = groups.node_index["s1"]["Lymphocytes"]
        node_id_2 = groups.node_index["s2"]["Lymphocytes"]
        assert node_id_1 is not None
        assert node_id_2 is not None
        assert node_id_1 != node_id_2  # distinct GateNode instances per sample
