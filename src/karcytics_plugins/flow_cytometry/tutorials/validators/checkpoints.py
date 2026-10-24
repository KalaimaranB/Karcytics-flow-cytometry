"""Checks that a course's prerequisites (earlier courses' work) are in place."""

from __future__ import annotations

from typing import Any

from ...analysis.experiment import SampleRole
from ...analysis.state import FlowState
from .base import FlowValidator
from .gating import GateExistsOnAllValidator, GateExistsValidator
from .setup import FlowImportValidator, RoleAssignmentValidator


class SetupAndCellsStateValidator(FlowValidator):
    """The workspace as Course 1 leaves it: all samples loaded, roles
    assigned, the Cells gate drawn and every sample compensated.
    """

    def __init__(self) -> None:
        self._flow_import = FlowImportValidator()
        self._role_assign = RoleAssignmentValidator()
        self._cells_gate = GateExistsValidator("cells")

    def validate_flow(self, app_state: FlowState) -> bool:
        if not (
            self._flow_import.validate(app_state)
            and self._role_assign.validate(app_state)
            and self._cells_gate.validate(app_state)
        ):
            return False
        raw = [
            s.display_name
            for s in app_state.data.experiment.samples.values()
            if s.fcs_data is not None and not s.is_compensated
        ]
        if raw:
            return self.log_failure(f"Not compensated: {', '.join(raw)}.")
        return True


class BaseGatesStateValidator(FlowValidator):
    """The workspace as Course 2 leaves it: samples, roles, and the base
    gates Cells → Live Cells → Leukocytes.
    """

    def __init__(self) -> None:
        self._flow_import = FlowImportValidator()
        self._role_assign = RoleAssignmentValidator()
        self._cells_gate = GateExistsValidator("cells")
        self._live_gate = GateExistsValidator("live cells")
        self._leukocytes = GateExistsValidator("leukocytes")

    def validate_flow(self, app_state: FlowState) -> bool:
        if not self._flow_import.validate(app_state):
            return False
        if not self._role_assign.validate(app_state):
            return False
        if not self._cells_gate.validate(app_state):
            return False
        if not self._live_gate.validate(app_state):
            return False
        return self._leukocytes.validate(app_state)


class LineageGatingCompleteValidator(FlowValidator):
    """Verifies Course 3's core gating (Leukocytes, T-cells, B-cells) exists
    on every FULL_PANEL sample, before Course 4 starts leaning on it.

    Same AND-composition pattern as ``BaseGatesStateValidator`` above.
    """

    def __init__(self) -> None:
        self._leukocytes = GateExistsOnAllValidator("leukocytes")
        self._tcells = GateExistsOnAllValidator("t-cells")
        self._bcells = GateExistsOnAllValidator("b-cells")

    def validate_flow(self, app_state: FlowState) -> bool:
        if not self._leukocytes.validate(app_state):
            return False
        if not self._tcells.validate(app_state):
            return False
        return self._bcells.validate(app_state)


class PopulationAnalysisCompleteValidator(FlowValidator):
    """Verifies Course 4's population-analysis output — the exported
    "UMAP B Cells" gate and the AND node cross-checking it against the
    manual B-cells gate — actually exists, before Course 7's Statistics/
    Comparisons walkthrough starts leaning on both.

    Checks every FULL_PANEL sample directly, the same "any sample, not
    just whichever one happens to be open" reach `GateExistsValidator`
    uses — Course 7 can launch with a different sample selected than
    whichever one the UMAP run was on, and this shouldn't false-fail
    just because of that.
    """

    def __init__(self) -> None:
        self._umap_bcells = GateExistsValidator("UMAP B Cells")

    def validate_flow(self, app_state: FlowState) -> bool:
        if not self._umap_bcells.validate_flow(app_state):
            return False

        samples = list(app_state.data.experiment.samples.values())
        full_panel = [s for s in samples if s.role == SampleRole.FULL_PANEL] or samples
        if not any(self._and_node_found(s.gate_tree) for s in full_panel):
            return self.log_failure(
                "No AND node combining B-cells and UMAP B Cells found on any sample."
            )
        return True

    def _and_node_found(self, node: Any) -> bool:
        if getattr(node, "gate", None) is None and getattr(node, "logic_operator", "") == "AND":
            parent_names = {p.name.lower() for p in getattr(node, "parents", [])}
            targets = ["b-cells", "umap b cells"]
            if all(any(target in name for name in parent_names) for target in targets):
                return True
        return any(self._and_node_found(child) for child in getattr(node, "children", []))
