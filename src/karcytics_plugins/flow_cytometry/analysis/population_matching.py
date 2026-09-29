"""Population identity matching across samples.

Backs the shared sample/population selector (ui/widgets/selection/) used by
the Statistics and Comparisons tabs: given the set of currently checked
samples, partition each sample's gated populations into those present under
the same name in *every* sample ("shared" — the result of group gate
propagation) versus those unique to one sample. Kept free of Qt imports so it
can be unit tested without a QApplication.

This also replaces three independent copies of the same label-path
composition that used to live in StatisticsExplorer._compute_results,
ComparisonsViewer._build_render_kwargs, and GroupPreviewPanel._get_parallel_node.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from karcytics_plugins.flow_cytometry.analysis.experiment import Sample
    from karcytics_plugins.flow_cytometry.analysis.gating.gate_node import GateNode

# Sentinel label for the synthetic "All Events" (ungated) pseudo-population,
# matching the sentinel (node_id=None) already used throughout both tabs.
ALL_EVENTS_LABEL = "All Events"
PATH_SEP = " / "


@dataclass
class PopulationRow:
    """One row's display data: tree-branch connector, depth, colour, name.

    Lives here (not in `ui/widgets/gate_hierarchy/all_samples_model.py`,
    where it originated) so this Qt-free analysis module can build rows for
    the population selection grid without importing from `ui/widgets/` —
    `all_samples_model.py` now imports it from here instead, keeping the
    conventional analysis-has-no-ui-dependency direction. Reused as-is by
    both the read-only Quick-Stats popup (`cells` = per-sample float % or
    None) and the interactive selection popup (`node_id`/`cells` unused —
    see `PopulationSelectionRow`), so both share the same `_BranchLabel`
    row-rendering widget.
    """

    node_id: str
    name: str
    depth: int
    branch_str: str  # e.g. "├─" or "└─" or "│  ├─"
    color_index: int
    cells: dict[str, float | None] = field(default_factory=dict)
    # cells[sample_id] = pct_parent float, or None if gate not applied


def _walk(node: GateNode, prefix: str, visited: set[str]) -> list[tuple[str, GateNode]]:
    """Depth-first (label_path, node) pairs for every non-root node under `node`.

    Unwired/under-wired logic nodes (AND/OR/NOT missing required parents) have
    no valid population yet, so they — and any subtree hanging off them — are
    skipped entirely, matching the gating hierarchy view.

    `visited` guards against a node being emitted twice: the gate tree is
    structurally a DAG, not a strict tree — a logic node (AND/OR/NOT) is a
    genuine child of *every* parent it combines (`GateNode.parents`,
    `from_dict` wiring both directions), so a naive walk reaches the same
    node once per parent, under a different label-path each time, even
    though it's the same real population. `GateNode.to_dict()` already
    guards the identical case with the same node_id-keyed visited set; this
    mirrors that. The node keeps whichever parent's path reaches it first.
    """
    out: list[tuple[str, GateNode]] = []
    for child in node.children:
        if getattr(child, "is_incomplete", False):
            continue
        if child.node_id in visited:
            continue
        visited.add(child.node_id)
        path = f"{prefix}{PATH_SEP}{child.name}" if prefix else child.name
        out.append((path, child))
        out.extend(_walk(child, path, visited))
    return out


def label_path_index(sample: Sample) -> dict[str, str | None]:
    """Map every population label-path in `sample` to its GateNode.node_id.

    The path is the full ancestor chain (e.g. "Lymphocytes / CD3+ / CD4+"),
    not just the leaf name, so two differently-nested populations that happen
    to share a leaf name are never confused with each other.
    """
    index: dict[str, str | None] = {ALL_EVENTS_LABEL: None}
    if sample.gate_tree is None:
        return index
    for path, node in _walk(sample.gate_tree, "", set()):
        index[path] = node.node_id
    return index


@dataclass
class PopulationGroups:
    """Result of grouping populations across a set of checked samples.

    ``shared``: label-paths present in every sample, in first-seen order —
        checking one of these applies to every sample that has it.
    ``per_sample``: label-paths present in only some of the samples, keyed by
        sample_id — everything not in ``shared``.
    ``node_index``: sample_id -> {label_path: node_id}, needed to resolve a
        shared label back to each sample's own GateNode.node_id.

    Known limitation, not fixed here: matching is by display-label text, not
    a stable cross-sample population ID. Gate propagation
    (analysis/gate_propagator.py) rebuilds a fresh GateNode per target sample
    from a serialized dict rather than sharing a reference, so a gate renamed
    on one sample after propagation silently drops out of ``shared``. Fixing
    that needs a stable population ID in the data model — a follow-up, not
    part of this selector.
    """

    shared: list[str] = field(default_factory=list)
    per_sample: dict[str, list[str]] = field(default_factory=dict)
    node_index: dict[str, dict[str, str | None]] = field(default_factory=dict)


def compute_population_groups(samples: list[Sample]) -> PopulationGroups:
    """Partition each sample's populations into 'shared across all' vs 'sample-specific'."""
    node_index = {s.sample_id: label_path_index(s) for s in samples}

    if not node_index:
        return PopulationGroups()

    label_sets = [set(idx.keys()) for idx in node_index.values()]
    shared_set = set.intersection(*label_sets)

    # Stable, human-friendly order: each sample's own discovery (tree walk)
    # order, first sample first.
    ordered_shared: list[str] = []
    seen: set[str] = set()
    for idx in node_index.values():
        for label in idx:
            if label in shared_set and label not in seen:
                ordered_shared.append(label)
                seen.add(label)

    per_sample = {
        sid: [label for label in idx if label not in shared_set] for sid, idx in node_index.items()
    }

    return PopulationGroups(shared=ordered_shared, per_sample=per_sample, node_index=node_index)


@dataclass
class PopulationSelectionRow:
    """One row of the population selection grid (`population_selection_popup.py`).

    ``row``: display data — reuses `all_samples_model.PopulationRow` as-is
        (same branch-connector/depth/color-index shape the read-only
        Quick-Stats popup already renders via `_BranchLabel`) so both popups
        share the exact same row-label widget. Its `node_id`/`cells` fields
        are unused here (this grid resolves per-sample node_ids via
        ``label_path`` + ``PopulationGroups.node_index`` instead, since a
        selection row spans many samples, not one).
    ``label_path``: the full label-path key into ``PopulationGroups.shared``/
        ``.per_sample``/``.node_index`` — not just the leaf name shown by
        ``row``.
    ``is_shared``: whether this label is present in every currently-checked
        sample (checking/toggling it fans out to all of them) versus only
        some (a sample-specific row — every other sample's cell in this row
        is simply absent/disabled, which is what actually communicates "this
        only applies here," no separate section needed).
    """

    row: PopulationRow
    label_path: str
    is_shared: bool


def _branch_rows_for(labels: list[str], *, is_shared: bool) -> list[PopulationSelectionRow]:
    """Compute tree-branch connector strings for a flat list of label-paths,
    grouping by each label's own parent path (same parent lookup
    `population_tree.py`'s `_build_nested_rows` uses) rather than walking a
    real `GateNode` tree — these labels may come from different samples'
    trees entirely (see `build_row_order`). Mirrors
    `AllSamplesModel._make_branch`'s ├─/└─ style so both popups look the
    same.
    """
    label_set = set(labels)
    children_of: dict[str | None, list[str]] = {}
    for label in labels:
        parent = label.rsplit(PATH_SEP, 1)[0] if PATH_SEP in label else None
        if parent is not None and parent not in label_set:
            parent = None  # parent not present in this group -> treat as a root
        children_of.setdefault(parent, []).append(label)

    rows: list[PopulationSelectionRow] = []

    def _walk_labels(parent: str | None, depth: int, is_last_flags: list[bool]) -> None:
        siblings = children_of.get(parent, [])
        for i, label in enumerate(siblings):
            is_last = i == len(siblings) - 1
            parts = ["   " if flag else "│  " for flag in is_last_flags]
            parts.append("└─" if is_last else "├─")
            leaf = label.rsplit(PATH_SEP, 1)[-1]
            rows.append(
                PopulationSelectionRow(
                    row=PopulationRow(
                        node_id="",
                        name=leaf,
                        depth=depth,
                        branch_str="".join(parts),
                        color_index=min(depth, 5),
                    ),
                    label_path=label,
                    is_shared=is_shared,
                )
            )
            _walk_labels(label, depth + 1, [*is_last_flags, is_last])

    _walk_labels(None, 0, [])
    return rows


def build_row_order(groups: PopulationGroups) -> list[PopulationSelectionRow]:
    """Order every population across ``groups`` into branch-connected rows
    for the selection grid: shared labels first (in `compute_population_groups`'s
    existing tree-discovery order), then each sample's own sample-specific
    labels appended after.
    """
    rows = _branch_rows_for(groups.shared, is_shared=True)
    for labels in groups.per_sample.values():
        if labels:
            rows.extend(_branch_rows_for(labels, is_shared=False))
    return rows
