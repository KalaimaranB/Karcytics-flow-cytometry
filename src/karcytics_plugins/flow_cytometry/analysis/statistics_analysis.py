"""Statistics Analysis — SDK-aligned background worker for population stats."""

from __future__ import annotations

from typing import Any

from karcytics_sdk.plugin import AnalysisBase, PluginState, get_logger

logger = get_logger(__name__, "flow_cytometry")


class StatisticsAnalysis(AnalysisBase):
    """Background analyzer for computing population statistics."""

    def __init__(self, plugin_id: str = "flow_cytometry"):
        super().__init__(plugin_id)
        self.target_sample_id: str | None = None

    def run(self, state: PluginState | None = None) -> dict[str, Any]:
        """Compute statistics for a sample.

        The 'state' here is the FlowState.
        """
        sample_id = getattr(self, "target_sample_id", None)
        if not sample_id and state and hasattr(state, "view"):
            sample_id = state.view.current_sample_id

        if not sample_id:
            return {"error": "No sample ID specified"}

        if not state or not hasattr(state, "data"):
            return {"error": "No state data available"}

        sample = state.data.experiment.samples.get(sample_id)
        if not sample or sample.fcs_data is None:
            return {"error": f"Sample {sample_id} not found or has no data"}

        logger.info(f"StatisticsAnalysis: Starting compute for sample {sample_id}")
        events = sample.fcs_data.events
        if events is None:
            return {"error": "No events found"}

        total_count = len(events)
        results = {}

        # Ensure root node has base stats
        results[sample.gate_tree.node_id] = {
            "count": total_count,
            "pct_parent": 100.0,
            "pct_total": 100.0,
        }

        # Walk the tree and compute stats — pass root_events so logic nodes
        # can compute per-parent overlap percentages against the full dataset
        self._walk_and_compute(
            sample.gate_tree,
            events,
            total_count,
            total_count,
            results,
            root_events=events,
        )

        logger.info(
            f"StatisticsAnalysis: Done for sample {sample_id}, {len(results)} nodes computed"
        )
        return {"sample_id": sample_id, "stats": results}

    def _walk_and_compute(  # noqa: C901, PLR0913
        self, node, parent_events, parent_count, total_count, results, root_events=None
    ):
        """Recursively compute stats for all nodes under ``node``."""
        if self.is_cancelled():
            return

        for child in node.children:
            try:
                is_logic_node = child.is_logic_node

                if is_logic_node:
                    # Logic nodes (AND/OR/NOT) have no physical gate, so we
                    # use apply_hierarchy which resolves the DAG logic across parents.
                    gated_events = child.apply_hierarchy(
                        root_events if root_events is not None else parent_events
                    )
                elif child.gate is not None:
                    # Regular gate node: apply the gate mask to the parent events
                    mask = child.gate.contains(parent_events)
                    if child.negated:
                        mask = ~mask
                    gated_events = parent_events[mask]
                else:
                    # Skip pure root nodes if recursed into
                    continue

            except Exception as exc:
                logger.exception(f"Background Stat computation failed for {child.name}: {exc}")
                self.signals.analysis_error.emit(f"Stat computation failed for {child.name}: {exc}")
                results[child.node_id] = {
                    "count": 0,
                    "pct_parent": 0.0,
                    "pct_total": 0.0,
                }
                continue

            count = len(gated_events)
            node_stats = {
                "count": count,
                "pct_parent": (count / parent_count * 100.0) if parent_count > 0 else 0.0,
                "pct_total": (count / total_count * 100.0) if total_count > 0 else 0.0,
            }

            # For logic nodes, also compute per-parent overlap percentages:
            # "X% of <Parent A> also appear in this intersection"
            if is_logic_node and child.parents and root_events is not None:
                per_parent_pcts = {}
                for p in child.parents:
                    if p.is_root:
                        p_count = total_count
                    else:
                        try:
                            p_events = p.apply_hierarchy(root_events)
                            p_count = len(p_events)
                        except Exception:
                            p_count = 0
                    per_parent_pcts[p.node_id] = {
                        "name": p.name,
                        "parent_count": p_count,
                        "pct_overlap": (count / p_count * 100.0) if p_count > 0 else 0.0,
                    }
                node_stats["per_parent_pcts"] = per_parent_pcts

            results[child.node_id] = node_stats

            # Recurse — pass gated_events so children are scoped to this node's population
            self._walk_and_compute(
                child,
                gated_events,
                count,
                total_count,
                results,
                root_events=root_events,
            )
