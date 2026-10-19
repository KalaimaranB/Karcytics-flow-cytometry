from typing import Any

from karcytics_sdk.plugin import AnalysisBase, PluginState, get_logger

from .experiment import Sample
from .gating import GateNode

logger = get_logger(__name__, "flow_cytometry")


class _PropagationWorker(AnalysisBase):
    """Worker that runs via TaskScheduler in the background.

    Receives a gate tree snapshot and a list of target samples,
    then re-applies the tree to each sample and returns progress statistics.
    """

    def __init__(self, plugin_id: str = "flow_cytometry") -> None:
        super().__init__(plugin_id)
        self._gate_tree_dict: dict | None = None
        self._target_samples: list[Sample] = []

    def configure(
        self,
        gate_tree_dict: dict[str, Any],
        target_samples: list[Sample],
    ) -> None:
        """Set the work payload before submitting to the scheduler."""
        self._gate_tree_dict = gate_tree_dict
        self._target_samples = list(target_samples)

    def run(self, state: PluginState | None = None) -> dict[str, Any]:  # noqa: ARG002
        """Execute the propagation — called by the TaskScheduler."""
        logger.info(f"PropagationWorker.run started for {len(self._target_samples)} samples")
        if self._gate_tree_dict is None:
            logger.error("PropagationWorker: _gate_tree_dict is None!")
            return {}

        results: dict[str, Any] = {}
        for sample in self._target_samples:
            try:
                logger.info(
                    f"PropagationWorker: Applying tree to sample {sample.sample_id} ({sample.display_name})"
                )
                stats, new_tree = self._apply_tree_to_sample(self._gate_tree_dict, sample)
                logger.info(
                    f"PropagationWorker: Success for sample {sample.sample_id}. Tree root child count: {len(new_tree.children) if new_tree else 0}"
                )
                # Store sample results by ID
                results[sample.sample_id] = {"stats": stats, "tree": new_tree}
            except (ValueError, KeyError, RuntimeError, TypeError) as exc:
                logger.warning(
                    "Propagation failed for '%s': %s",
                    sample.display_name,
                    exc,
                )
                results[sample.sample_id] = {"error": str(exc)}
            except Exception as e:
                logger.error(
                    f"Propagation FATAL error for {sample.sample_id}: {e}",
                    exc_info=True,
                )
                results[sample.sample_id] = {"error": str(e)}

        logger.info(f"PropagationWorker.run completed. {len(results)} results.")
        return {"propagation_results": results}

    def _apply_tree_to_sample(
        self, tree_dict: dict[str, Any], sample: Sample
    ) -> tuple[dict[str, Any], GateNode]:
        """Reconstruct and apply the gate DAG to a single sample."""
        if sample.fcs_data is None or sample.fcs_data.events is None:
            return {}, GateNode()

        events = sample.fcs_data.events

        try:
            new_tree = GateNode.from_dict(tree_dict)
            if new_tree is None:
                return {}, GateNode()
            if "node_id" in tree_dict and new_tree.is_root:
                new_tree.node_id = tree_dict["node_id"]
            if "name" in tree_dict and new_tree.is_root:
                new_tree.name = tree_dict["name"]
        except (KeyError, TypeError, ValueError) as e:
            logger.error("Failed to deserialize DAG: %s", e)
            return {}, GateNode()

        from .compute import dag_evaluator

        all_stats = dag_evaluator.evaluate(new_tree, events)

        return all_stats, new_tree
