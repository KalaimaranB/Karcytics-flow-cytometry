"""Checks on gates, axes, plot settings and the pipeline: drawing, naming, editing."""

from __future__ import annotations

from typing import Any

import numpy as np
from karcytics_sdk.plugin import get_logger
from karcytics_sdk.plugin.tutorial_models import ValidationFailure

from ...analysis.axis_manager import AxisManager
from ...analysis.experiment import SampleRole
from ...analysis.gating import QuadrantSubGate
from ...analysis.state import FlowState
from ...ui.academy_context import AcademyContext
from .base import FlowUIValidator, FlowValidator

logger = get_logger(__name__, "flow_cytometry")


class GateExistsValidator(FlowValidator):
    """Verifies that a gate with the given name exists on at least one Full Panel sample."""

    def __init__(self, target_gate_name: str) -> None:
        self._target = target_gate_name.lower()

    def validate_flow(self, app_state: FlowState) -> bool:
        samples = list(app_state.data.experiment.samples.values())
        full_panel = [s for s in samples if s.role == SampleRole.FULL_PANEL] or samples
        if not any(self._gate_found(s.gate_tree) for s in full_panel):
            return self.log_failure(f"Gate '{self._target}' not found in any FULL_PANEL samples.")
        return True

    def _gate_found(self, node: Any) -> bool:
        if (getattr(node, "name", "") or "").lower() == self._target:
            return True
        return any(self._gate_found(child) for child in getattr(node, "children", []))


class AxisChannelValidator(FlowValidator):
    """Verifies that the active X axis channel contains a specific keyword."""

    def __init__(self, channel_keyword: str) -> None:
        self._keyword = channel_keyword.lower()

    def validate_flow(self, app_state: FlowState) -> bool:
        x_param = getattr(app_state.view, "active_x_param", "") or ""
        if self._keyword not in x_param.lower():
            return self.log_failure(
                f"Active X channel '{x_param}' does not contain keyword '{self._keyword}'."
            )
        return True


class AxisOutlierValidator(FlowValidator):
    """Verifies that the active X axis outlier percentile matches a specific value."""

    def __init__(self, target_percentile: float) -> None:
        self._target = target_percentile

    def validate_flow(self, app_state: FlowState) -> bool:
        x_param = getattr(app_state.view, "active_x_param", None)
        sample_id = getattr(app_state.view, "current_sample_id", None)
        if not x_param:
            return self.log_failure("No active X channel parameter.")

        try:
            manager = AxisManager(app_state)
            scale = manager.get_scale(x_param, sample_id)
            # Use a small epsilon for float comparison
            if abs(scale.outlier_percentile - self._target) >= 0.001:  # noqa: PLR2004
                return self.log_failure(
                    f"Outlier percentile is {scale.outlier_percentile}, expected {self._target}."
                )
            return True
        except Exception as e:
            return self.log_failure(f"Failed to get scale: {e}")


class GateExistsOnAllValidator(GateExistsValidator):
    """Verifies that a gate with the given name exists on ALL Full Panel samples."""

    def validate_flow(self, app_state: FlowState) -> bool:
        samples = list(app_state.data.experiment.samples.values())
        full_panel = [s for s in samples if s.role == SampleRole.FULL_PANEL]
        if not full_panel:
            return self.log_failure("No FULL_PANEL samples found.")

        missing = [s.display_name for s in full_panel if not self._gate_found(s.gate_tree)]
        if missing:
            return self.log_failure(
                f"Gate '{self._target}' missing on FULL_PANEL samples: {', '.join(missing)}"
            )
        return True


class AxisYChannelValidator(FlowValidator):
    """Verifies that the active Y axis channel contains a specific keyword."""

    def __init__(self, channel_keyword: str) -> None:
        self._keyword = channel_keyword.lower()

    def validate_flow(self, app_state: FlowState) -> bool:
        y_param = getattr(app_state.view, "active_y_param", "") or ""
        if self._keyword not in y_param.lower():
            return self.log_failure(
                f"Active Y channel '{y_param}' does not contain keyword '{self._keyword}'."
            )
        return True


class GateShapeValidator(FlowValidator):
    """Verifies that a newly created gate matches the required target shape.

    Tolerances are meant to catch a gate in the wrong place, not to grade a
    hand-drawn one: learners draw with a mouse, often on log-scaled axes.
    """

    # Drawn polygon vs target, intersection over union.
    MIN_POLYGON_IOU = 0.80
    # A range/rectangle edge may sit this far from its target edge: a share of
    # the whole axis, or a share of the edge's own value, whichever is larger.
    # The second term matters for high edges on log-scaled axes, where a fixed
    # band is only a sliver (±26k around 200,000 barely shows on screen).
    EDGE_AXIS_FRACTION = 0.10
    EDGE_VALUE_FRACTION = 0.35
    # A quadrant crosshair may land this share of the target window's width
    # outside it, on each side.
    QUADRANT_MARGIN = 0.25

    def __init__(
        self,
        target_bounds: tuple[float, float, float, float] | None = None,
        target_poly: list[tuple[float, float]] | None = None,
        target_name: str | None = None,
        misnamed_retry_step_id: str | None = None,
        shape_retry_step_id: str | None = None,
        must_contain: tuple[float, float, float, float] | None = None,
        must_stay_within: tuple[float, float, float, float] | None = None,
    ) -> None:
        """Args:
        target_bounds: (min_x, max_x, min_y, max_y). For 1D gates, use 0 for min_y, max_y.
        must_contain: (min_x, max_x, min_y, max_y) a rectangle must hold whole: the
            population's core. The edge tolerance is a share of the whole axis, far
            too loose near zero on a biexponential axis, where a box can pass and
            still cut the population (the Sample Lens then reports the cut).
        must_stay_within: (min_x, max_x, min_y, max_y) a rectangle must not reach past:
            the neighbouring population.
        target_poly: List of (x, y) vertices for the target polygon shape.
        target_name: The expected name of the gate.
        misnamed_retry_step_id: step to route to (via `ValidationFailure.retry_step_id`)
            when the gate shape is right but the name is wrong — after this
            validator auto-renames it. Falls back to the step's own
            `on_fail_step_id` when unset.
        shape_retry_step_id: step to route to when the shape itself is
            wrong — after this validator deletes the bad gate. Falls back
            to the step's own `on_fail_step_id` when unset.
        """
        self.target_bounds = target_bounds
        self.target_poly = target_poly
        self.target_name = target_name
        self.misnamed_retry_step_id = misnamed_retry_step_id
        self.shape_retry_step_id = shape_retry_step_id
        self.must_contain = must_contain
        self.must_stay_within = must_stay_within
        self.last_misnamed_node_id: str | None = None
        self.last_failed_node_id: str | None = None
        self.last_misnamed_sample_id: str | None = None
        self.explicit_failed_node_id: str | None = None

    def set_explicit_failure(self, node_id: str) -> None:
        """Mark a gate as having explicitly failed shape validation upon creation."""
        self.explicit_failed_node_id = node_id

    def validate_flow(self, app_state: FlowState) -> bool:
        """Checks only the gate the user currently has selected — not every
        gate on every sample.

        Previously this walked the *entire* gate tree of every sample on
        every ~2s poll tick, hunting for any node whose bounds happened to
        match the target — expensive (grows with the whole experiment, not
        with the tutorial), and imprecise (a coincidentally-matching node
        left over from an earlier step could satisfy it).

        `GateCoordinator.add_gate()` always ends by calling
        `select_gate()` on the node(s) it just created
        (see gate_coordinator.py) — so `current_gate_id`/
        `current_sample_id` on the view already name exactly the gate the
        user just drew, for free, via the same mechanism every other
        selection-based validator here already relies on. No separate
        tracking needed: just read it. For a Quadrant, `select_gate` lands
        on one of the 4 sibling leaves, which is sufficient — they all
        share the same parent `QuadrantGate`, so shape validation (which
        checks the parent's threshold position, not the individual leaf)
        gives the same answer regardless of which leaf is selected.
        """
        try:
            self.last_misnamed_node_id = None
            self.last_failed_node_id = None
            self.last_misnamed_sample_id = None

            # An immediate hit from `_handle_gate_created`
            # (main_panel_controller) already knows exactly which
            # freshly-drawn node failed shape validation — trust it over
            # re-deriving the same answer below.
            if getattr(self, "explicit_failed_node_id", None):
                self.last_failed_node_id = self.explicit_failed_node_id
                self.explicit_failed_node_id = None
                return self.log_failure("Freshly drawn gate failed shape validation.")

            sample_id = app_state.view.current_sample_id
            node_id = app_state.view.current_gate_id
            if not sample_id or not node_id:
                return self.log_failure("No gate has been drawn yet.")

            sample = app_state.data.experiment.samples.get(sample_id)
            node = sample.gate_tree.find_node_by_id(node_id) if sample else None
            if node is None:
                return self.log_failure("No gate has been drawn yet.")

            shape_ok = self.validate_shape(app_state, node_id, sample_id)
            if not shape_ok:
                self.last_failed_node_id = node_id
                return self.log_failure("No gate matching target shape bounds/polygon found.")

            if (
                self.target_name
                and (getattr(node, "name", "") or "").lower() != self.target_name.lower()
            ):
                self.last_misnamed_node_id = node_id
                self.last_misnamed_sample_id = sample_id
                return self.log_failure("Gate shape is correct but misnamed.")

            logger.info(f"validate_flow succeeded on node {node_id} (sample {sample_id})")
            return True
        except Exception as e:
            logger.exception("Exception in validate_flow!")
            raise e

    def describe_failure(self, app_state: FlowState) -> ValidationFailure | None:  # noqa: ARG002
        """Diagnoses the most recent `validate_flow()` failure and returns a
        self-contained fix, so `AcademyStepDriver` can explain + auto-correct
        a misnamed or badly-shaped gate without a course wiring a bespoke
        ActionStep + reading validator state back out through a global.
        """
        if self.last_misnamed_node_id:
            node_id = self.last_misnamed_node_id
            sample_id = self.last_misnamed_sample_id
            correct_name = self.target_name

            def _rename(panel: Any) -> None:
                target_sample_id = sample_id or panel.state.view.current_sample_id
                panel.state.view.current_gate_id = node_id
                coordinator = panel.academy_context().gate_coordinator
                coordinator.rename_population(target_sample_id, node_id, correct_name)
                # Supersede any active propagation (from the original add_gate
                # call) that snapshotted the tree with the old, incorrect name.
                coordinator.request_propagation(node_id, target_sample_id)

            return ValidationFailure(
                reason=f"Great shape! But you named it incorrectly. I renamed it to **{correct_name}** for you!",
                corrective=_rename,
                retry_step_id=self.misnamed_retry_step_id,
            )

        if self.last_failed_node_id:
            node_id = self.last_failed_node_id

            def _delete(panel: Any) -> None:
                panel.state.view.current_gate_id = node_id
                sample_id = panel.state.view.current_sample_id
                panel.delete_gate_with_dialog(sample_id, node_id, force_silent=True)

            return ValidationFailure(
                reason="That gate didn't quite capture the right range! I deleted it for you — try drawing it again.",
                corrective=_delete,
                retry_step_id=self.shape_retry_step_id,
            )

        return None

    def _holds_core(self, min_x: float, max_x: float, min_y: float, max_y: float) -> bool:
        box = (min_x, max_x, min_y, max_y)
        if self.must_contain is not None and not _holds(box, self.must_contain):
            return False
        return self.must_stay_within is None or _holds(self.must_stay_within, box)

    def validate_shape(self, app_state: Any, node_id: str, sample_id: str) -> bool:  # noqa: PLR0911, PLR0912, PLR0915
        """Validates the shape of a specific gate node. Returns True if accurate."""
        if not self.target_bounds and not self.target_poly:
            return True  # No shape checking required

        if not hasattr(app_state, "data") or not hasattr(app_state.data, "experiment"):
            return False

        sample = app_state.data.experiment.samples.get(sample_id)
        if not sample:
            return False

        node = sample.gate_tree.find_node_by_id(node_id)
        if not node or not node.gate:
            return False

        gate = node.gate
        gate_type = type(gate).__name__

        if gate_type == "QuadrantSubGate":
            gate = getattr(gate, "parent", gate)
            gate_type = type(gate).__name__

        # Exact shape matching for Polygons via rasterization
        if gate_type == "PolygonGate" and self.target_poly:
            from matplotlib.path import Path  # karcytics: allow KS360 - heavy library

            gate_path = Path(gate.vertices)
            target_path = Path(self.target_poly)

            xs = [v[0] for v in gate.vertices] + [v[0] for v in self.target_poly]
            ys = [v[1] for v in gate.vertices] + [v[1] for v in self.target_poly]

            min_x, max_x = min(xs), max(xs)
            min_y, max_y = min(ys), max(ys)

            if max_x == min_x:
                max_x += 1
            if max_y == min_y:
                max_y += 1

            # 100x100 grid for fast and efficient rasterization
            gx = np.linspace(min_x, max_x, 100)
            gy = np.linspace(min_y, max_y, 100)
            grid_x, grid_y = np.meshgrid(gx, gy)
            points = np.column_stack((grid_x.ravel(), grid_y.ravel()))

            gate_mask = gate_path.contains_points(points)
            target_mask = target_path.contains_points(points)

            intersection = np.logical_and(gate_mask, target_mask).sum()
            union = np.logical_or(gate_mask, target_mask).sum()

            iou = intersection / union if union > 0 else 0

            return iou >= self.MIN_POLYGON_IOU

        if not self.target_bounds:
            return True
        t_min_x, t_max_x, t_min_y, t_max_y = self.target_bounds

        # Calculate bounding box of drawn gate
        min_x, max_x, min_y, max_y = 0.0, 0.0, 0.0, 0.0

        if gate_type == "PolygonGate":
            xs = [v[0] for v in gate.vertices]
            ys = [v[1] for v in gate.vertices]
            min_x, max_x = min(xs), max(xs)
            min_y, max_y = min(ys), max(ys)
        elif gate_type == "RangeGate":
            min_x, max_x = getattr(gate, "low", 0.0), getattr(gate, "high", 0.0)
        elif gate_type == "RectangleGate":
            min_x, max_x = getattr(gate, "x_min", 0.0), getattr(gate, "x_max", 0.0)
            min_y, max_y = getattr(gate, "y_min", 0.0), getattr(gate, "y_max", 0.0)
        elif gate_type == "QuadrantGate":
            # The crosshair (x_mid/y_mid) is one point, not two edges: the
            # per-edge tolerance below would accept a band ~12x the target
            # window, so check it lies in the (slightly widened) window.
            x_mid, y_mid = getattr(gate, "x_mid", 0.0), getattr(gate, "y_mid", 0.0)
            mx = (t_max_x - t_min_x) * self.QUADRANT_MARGIN
            my = (t_max_y - t_min_y) * self.QUADRANT_MARGIN
            return t_min_x - mx <= x_mid <= t_max_x + mx and t_min_y - my <= y_mid <= t_max_y + my
        else:
            return True  # skip unknown gate types

        if gate_type in {"RangeGate", "RectangleGate"}:
            # Fractions of a typical flow axis range (262144).
            axis_range = 262144.0

            def edge_ok(drawn: float, target: float) -> bool:
                tolerance = max(
                    self.EDGE_AXIS_FRACTION * axis_range, self.EDGE_VALUE_FRACTION * abs(target)
                )
                return abs(drawn - target) <= tolerance

            if not (edge_ok(min_x, t_min_x) and edge_ok(max_x, t_max_x)):
                return False
            if gate_type == "RectangleGate" and not self._holds_core(min_x, max_x, min_y, max_y):
                return False
            return gate_type != "RectangleGate" or (
                edge_ok(min_y, t_min_y) and edge_ok(max_y, t_max_y)
            )

        return False


def _holds(
    box: tuple[float, float, float, float], inner: tuple[float, float, float, float]
) -> bool:
    """``box`` (min_x, max_x, min_y, max_y) holds ``inner`` whole."""
    return box[0] <= inner[0] and box[1] >= inner[1] and box[2] <= inner[2] and box[3] >= inner[3]


class GateActiveValidator(FlowValidator):
    """Verifies that the user has double-clicked a specific gate in the hierarchy to enter it."""

    def __init__(self, target_gate_name: str) -> None:
        self.target = target_gate_name.lower()

    def validate_flow(self, app_state: FlowState) -> bool:  # noqa: PLR0911

        gate_id = getattr(app_state.view, "current_gate_id", None)
        sample_id = getattr(app_state.view, "current_sample_id", None)

        if not sample_id:
            return self.log_failure("No active sample ID in view.")

        sample = app_state.data.experiment.samples.get(sample_id)
        if not sample:
            return self.log_failure(f"Sample ID {sample_id} not found in experiment.")

        if not gate_id:
            # If no gate is selected, they are at the root
            if self.target not in sample.gate_tree.name.lower():
                return self.log_failure(
                    f"Target gate '{self.target}' is not active, root node is '{sample.gate_tree.name}'."
                )
            return True

        node = sample.gate_tree.find_node_by_id(gate_id)
        if node:
            if self.target not in node.name.lower():
                return self.log_failure(
                    f"Target gate '{self.target}' is not active, active node is '{node.name}'."
                )
            return True

        return self.log_failure(f"Gate ID {gate_id} not found in sample gate tree.")


class PlotTypeValidator(FlowUIValidator):
    """Verifies that the active graph is displaying the specified plot type (e.g. 'Histogram', 'Pseudocolor')."""

    def __init__(self, expected_plot_type: str) -> None:
        self.expected = expected_plot_type.lower()

    def validate_ui(self, _app_state: FlowState, ui: AcademyContext) -> bool:

        graph_manager = ui.graph_manager
        active_graph = (
            graph_manager.get_active_graph()
            if graph_manager and hasattr(graph_manager, "get_active_graph")
            else None
        )
        if not active_graph:
            return self.log_failure("No active graph found in graph manager.")

        current_text = active_graph.axis_panel.get_current_display_mode().value.lower()
        if current_text != self.expected:
            return self.log_failure(
                f"Active plot type is '{current_text}', expected '{self.expected}'."
            )
        return True


class PipelineOrientationValidator(FlowUIValidator):
    """Verifies that the pipeline canvas is set to a specific layout orientation (e.g., 'Horizontal')."""

    def __init__(self, expected_orientation: str) -> None:
        self.expected = expected_orientation.lower()

    def validate_ui(self, _app_state: FlowState, ui: AcademyContext) -> bool:

        pipeline_ribbon = ui.pipeline_ribbon
        if pipeline_ribbon is None:
            return self.log_failure("Pipeline ribbon missing.")

        current_text = pipeline_ribbon.orientation_label.lower()
        if current_text != self.expected:
            return self.log_failure(
                f"Pipeline orientation is '{current_text}', expected '{self.expected}'."
            )
        return True


class LogicGateExistsValidator(FlowValidator):
    """Verifies a boolean logic node (AND/OR/NOT) exists wiring in two named parent populations."""

    def __init__(self, operator: str, parent_names: list[str]) -> None:
        self._operator = operator.upper()
        self._parents = [p.lower() for p in parent_names]

    def validate_flow(self, app_state: FlowState) -> bool:
        sample_id = getattr(app_state.view, "current_sample_id", None)
        if not sample_id:
            return self.log_failure("No active sample ID in view.")
        sample = app_state.data.experiment.samples.get(sample_id)
        if not sample:
            return self.log_failure(f"Sample ID {sample_id} not found in experiment.")

        if not self._logic_found(sample.gate_tree):
            return self.log_failure(
                f"No {self._operator} node combining {self._parents} found on active sample."
            )
        return True

    def _logic_found(self, node: Any) -> bool:
        if (
            getattr(node, "gate", None) is None
            and getattr(node, "logic_operator", "") == self._operator
        ):
            parent_names = {p.name.lower() for p in getattr(node, "parents", [])}
            if all(any(target in name for name in parent_names) for target in self._parents):
                return True
        return any(self._logic_found(child) for child in getattr(node, "children", []))


class SampleAndGateOpenValidator(FlowUIValidator):
    """Verifies a specific sample is open with a specific gate/population as the active view.

    Reads directly from the live GraphManager's active GraphWindow rather than
    app_state.view.current_sample_id/current_gate_id: actions like the Sample
    List's right-click "open population" only update current_sample_id, not
    current_gate_id, so that pair can go stale after a context-menu jump.
    """

    def __init__(self, sample_substr: str, gate_substr: str) -> None:
        self._sample = sample_substr.lower()
        self._gate = gate_substr.lower()

    def validate_ui(self, app_state: FlowState, ui: AcademyContext) -> bool:
        graph_manager = ui.graph_manager
        if not graph_manager or not hasattr(graph_manager, "get_active_graph"):
            return self.log_failure("Graph manager not available.")

        graph = graph_manager.get_active_graph()
        if not graph:
            return self.log_failure("No active graph window.")

        sample = app_state.data.experiment.samples.get(graph.sample_id)
        if not sample:
            return self.log_failure(f"Sample ID {graph.sample_id} not found in experiment.")
        if self._sample not in sample.display_name.lower():
            return self.log_failure(
                f"Active sample '{sample.display_name}' does not match '{self._sample}'."
            )

        node = (
            sample.gate_tree.find_node_by_id(graph.node_id) if graph.node_id else sample.gate_tree
        )
        if not node or self._gate not in node.name.lower():
            found_name = node.name if node else "?"
            return self.log_failure(
                f"Active population '{found_name}' does not match '{self._gate}'."
            )
        return True


class QuadrantPositionNamedValidator(FlowValidator):
    """Verifies the specific geometric quadrant leaf carries the expected name.

    GateExistsValidator only checks that *some* node anywhere has the target
    name — for a quadrant gate that's not enough, since it's easy to rename
    the wrong leaf (e.g. type 'CD4+' on Q1 instead of Q4) and still pass. A
    QuadrantSubGate's `.quadrant` ("Q1"-"Q4") is fixed at creation and never
    changes on rename, so it's the reliable way to identify *which* leaf is
    which regardless of what the user has typed for its display name.
    """

    def __init__(self, quadrant: str, expected_name: str) -> None:
        self._quadrant = quadrant.strip().upper()
        self._expected = expected_name.strip().lower()

    def validate_flow(self, app_state: FlowState) -> bool:
        sample_id = getattr(app_state.view, "current_sample_id", None)
        if not sample_id:
            return self.log_failure("No active sample ID in view.")
        sample = app_state.data.experiment.samples.get(sample_id)
        if not sample:
            return self.log_failure(f"Sample ID {sample_id} not found in experiment.")

        node = next(
            (
                n
                for n in sample.gate_tree.iter_dag()
                if isinstance(n.gate, QuadrantSubGate)
                and n.gate.quadrant.strip().upper() == self._quadrant
            ),
            None,
        )
        if node is None:
            return self.log_failure(f"No {self._quadrant} QuadrantSubGate leaf found.")
        actual = (getattr(node, "name", "") or "").strip().lower()
        if actual != self._expected:
            return self.log_failure(
                f"{self._quadrant} is named '{actual}', expected '{self._expected}'."
            )
        return True


class LogicNodeStatsReadyValidator(FlowValidator):
    """Verifies a boolean logic node's live statistics have actually finished
    recomputing (non-zero count, both parents represented) after wiring —
    stats recompute asynchronously off an event, so a step reading them
    immediately after the wiring VerificationStep succeeds can otherwise
    show stale/zero numbers for a moment.
    """

    def __init__(self, operator: str, parent_names: list[str]) -> None:
        self._operator = operator.upper()
        self._parents = [p.lower() for p in parent_names]

    def validate_flow(self, app_state: FlowState) -> bool:
        sample_id = getattr(app_state.view, "current_sample_id", None)
        if not sample_id:
            return self.log_failure("No active sample ID in view.")
        sample = app_state.data.experiment.samples.get(sample_id)
        if not sample:
            return self.log_failure(f"Sample ID {sample_id} not found in experiment.")

        node = self._find_logic_node(sample.gate_tree)
        if node is None:
            return self.log_failure(f"No {self._operator} node combining {self._parents} found.")

        stats = getattr(node, "statistics", None) or {}
        if not stats.get("count"):
            return self.log_failure("Logic node stats haven't recomputed yet (count is 0).")
        if len(stats.get("per_parent_pcts", {})) < len(self._parents):
            return self.log_failure("Logic node per-parent stats haven't recomputed yet.")
        return True

    def _find_logic_node(self, node: Any) -> Any | None:
        if (
            getattr(node, "gate", None) is None
            and getattr(node, "logic_operator", "") == self._operator
        ):
            parent_names = {p.name.lower() for p in getattr(node, "parents", [])}
            if all(any(target in name for name in parent_names) for target in self._parents):
                return node
        for child in getattr(node, "children", []):
            found = self._find_logic_node(child)
            if found is not None:
                return found
        return None


class GateEditTracker:
    """Follows one named gate through "edit it, then undo the edit".

    ``edited()`` remembers the gate's geometry the first time it is polled
    and passes once the geometry differs; ``undone()`` passes when the
    geometry is back to what was remembered.
    """

    def __init__(self, gate_name: str) -> None:
        self._name = gate_name.casefold()
        self.baseline: dict | None = None  # the gate before the edit; shared by its two checks

    def edited(self) -> FlowValidator:
        return _GateEdited(self)

    def undone(self) -> FlowValidator:
        return _GateEditUndone(self)

    def geometry(self, app_state: FlowState) -> dict | None:
        """The gate as drawn on the open sample (any sample, if none is open)."""
        samples = app_state.data.experiment.samples
        current = samples.get(app_state.view.current_sample_id or "")
        for sample in [current] if current is not None else list(samples.values()):
            for node in sample.gate_tree.iter_dag():
                if (node.name or "").casefold() == self._name and node.gate is not None:
                    return node.gate.to_dict()
        return None


class _GateEdited(FlowValidator):
    def __init__(self, tracker: GateEditTracker) -> None:
        self._tracker = tracker

    def validate_flow(self, app_state: FlowState) -> bool:
        tracker = self._tracker
        now = tracker.geometry(app_state)
        if now is None:
            return self.log_failure("The gate to edit wasn't found.")
        if tracker.baseline is None:
            tracker.baseline = now
        if now == tracker.baseline:
            return self.log_failure("The gate hasn't been moved or resized yet.")
        return True


class _GateEditUndone(FlowValidator):
    def __init__(self, tracker: GateEditTracker) -> None:
        self._tracker = tracker

    def validate_flow(self, app_state: FlowState) -> bool:
        tracker = self._tracker
        if tracker.baseline is None:
            return self.log_failure("No edit has been made to undo.")
        if tracker.geometry(app_state) != tracker.baseline:
            return self.log_failure("The gate is still in its edited shape.")
        tracker.baseline = None  # a replay of the course starts afresh
        return True
