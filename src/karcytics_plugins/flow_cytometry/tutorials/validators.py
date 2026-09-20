"""Validators for Karcytics Flow Cytometry tutorial steps.

Each class implements IValidator with a single validate(app_state) method
(SRP / OCP — new validators extend without modifying existing ones).

app_state is expected to be a FlowState instance from analysis.state.
"""

from abc import abstractmethod
from collections.abc import Callable
from typing import Any

from karcytics_sdk.plugin import get_logger
from karcytics_sdk.plugin.tutorial_models import IValidator, ValidationFailure

from ..analysis.state import FlowState

logger = get_logger(__name__, "flow_cytometry")


class LoggingValidator(IValidator):
    """Base validator that provides stateful logging to avoid spam during polling."""

    def log_failure(self, reason: str) -> bool:
        last_reason = getattr(self, "_last_log_reason", "")
        if reason != last_reason:
            logger.info("%s: %s", self.__class__.__name__, reason)
            self._last_log_reason = reason
        return False


_TUTORIAL_STATE: dict[str, Any] = {}


class FlowValidator(LoggingValidator):
    """Adapter that strongly types the IValidator interface to FlowState."""

    def validate(self, app_state: Any) -> bool:
        if not isinstance(app_state, FlowState):
            return self.log_failure(f"Expected FlowState, got {type(app_state).__name__}")
        try:
            return self.validate_flow(app_state)
        except Exception as exc:
            # The tutorial polling loop (workspace_window.timerEvent) only
            # print()s exceptions raised here — they never reach the app's
            # structured logs, so a step can silently stall forever with no
            # trace of why. Log it properly so a failure is diagnosable
            # instead of invisible.
            logger.exception(
                "%s: validate_flow raised an exception — treating as failed.",
                self.__class__.__name__,
            )
            return self.log_failure(f"Validator raised {type(exc).__name__}: {exc}")

    @abstractmethod
    def validate_flow(self, app_state: FlowState) -> bool:
        pass


class TabActiveValidator(FlowValidator):
    """Verifies that the user has navigated to a specific main tab index."""

    def __init__(self, expected_tab_index: int) -> None:
        self.expected = expected_tab_index

    def validate_flow(self, app_state: FlowState) -> bool:
        if app_state.view.active_main_tab_index != self.expected:
            return self.log_failure(
                f"Expected tab index {self.expected}, but got {app_state.view.active_main_tab_index}."
            )
        return True


class TutorialFilesProvisionedValidator(FlowValidator):
    """Polls the background tutorial-file provisioning job.

    See ``tutorial_assets.ensure_tutorial_files`` — this only reports
    whether that job (started by an earlier ActionStep) has finished; it
    never touches the filesystem or network itself.
    """

    def __init__(self, on_progress: Callable[[str], None] | None = None) -> None:
        """``on_progress``, if given, is called on every poll with a fresh
        status line while a download is in flight — lets the caller mutate
        its own step's ``.text`` in place so the tutorial bubble actually
        shows live progress instead of a static "may take a minute" message
        for the whole download (previously the only place this progress was
        visible at all was the log).
        """
        self._on_progress = on_progress

    def validate_flow(self, _app_state: FlowState) -> bool:
        from .tutorial_assets import MAX_PROVISION_ATTEMPTS, get_status, provisioning_has_stalled

        status = get_status()
        stalled = provisioning_has_stalled()

        if not status.done and not stalled:
            if self._on_progress is not None:
                if status.retry_count > 0:
                    self._on_progress(
                        "Getting your 10 tutorial files ready 📂\n\n"
                        f"Hit a snag ({status.error}) — retrying the download "
                        f"(attempt {status.retry_count + 1}/{MAX_PROVISION_ATTEMPTS})...\n\n"
                        f"{status.current_file_index}/{status.total_files} files done so far."
                    )
                else:
                    self._on_progress(
                        "Getting your 10 tutorial files ready 📂\n\n"
                        "Downloading from the tutorial dataset (~100MB, only "
                        f"happens once)... {status.current_file_index}/{status.total_files} files done."
                    )
            return self.log_failure(
                f"Downloading tutorial files... {status.current_file_index}/{status.total_files}"
            )

        if stalled or status.error:
            if self._on_progress is not None:
                self._on_progress(
                    "Couldn't get the tutorial files ready 😕\n\n"
                    f"{'This is taking far longer than expected.' if stalled else f'After {MAX_PROVISION_ATTEMPTS} attempts, the download kept failing ({status.error}).'} "
                    "Check your internet connection, then close this course "
                    "from the Academy hub and reopen it to try again."
                )
            return self.log_failure(
                "Provisioning stalled — exceeded max wait time."
                if stalled
                else f"Provisioning permanently failed after {MAX_PROVISION_ATTEMPTS} attempts: {status.error}"
            )

        return True


class FlowImportValidator(FlowValidator):
    """Verifies that ≥10 FCS files have been imported with data loaded."""

    def __init__(self):
        super().__init__()
        self.incorrect_sample_ids = []
        self.too_few = False
        self.too_many = False

    def validate_flow(self, app_state: FlowState) -> bool:
        expected_samples = {
            "Specimen_001_Blank.fcs": {"size": 11033493, "events": 306425},
            "Specimen_001_FMO APC.fcs": {"size": 11135029, "events": 309246},
            "Specimen_001_FMO APCCy7.fcs": {"size": 11150696, "events": 309681},
            "Specimen_001_FMO FITC.fcs": {"size": 11242707, "events": 312237},
            "Specimen_001_FMO PE.fcs": {"size": 11192665, "events": 310847},
            "Specimen_001_FMO e450.fcs": {"size": 11212000, "events": 311384},
            "Specimen_001_PI.fcs": {"size": 11116118, "events": 308721},
            "Specimen_001_Sample A.fcs": {"size": 10874785, "events": 302017},
            "Specimen_001_Sample B.fcs": {"size": 11382137, "events": 316110},
            "Specimen_001_Sample C.fcs": {"size": 11499099, "events": 319359},
        }

        samples = list(app_state.data.experiment.samples.values())

        self.incorrect_sample_ids = []
        self.too_few = False

        expected_signatures = {(v["events"], v["size"]) for v in expected_samples.values()}

        for s in samples:
            if s.has_data:
                # If it has data but fcs_data is missing or file doesn't exist, it's invalid.
                if not s.fcs_data or not s.fcs_data.file_path.exists():
                    self.incorrect_sample_ids.append(s.sample_id)
                else:
                    sig = (s.event_count, s.fcs_data.file_path.stat().st_size)
                    if sig not in expected_signatures:
                        self.incorrect_sample_ids.append(s.sample_id)

        if self.incorrect_sample_ids:
            return self.log_failure(f"Found {len(self.incorrect_sample_ids)} incorrect samples.")

        if len(samples) < 10:  # noqa: PLR2004
            self.too_few = True
            return self.log_failure(f"Expected at least 10 samples, found {len(samples)}.")

        missing_data = [s.display_name for s in samples if not s.has_data]
        if missing_data:
            return self.log_failure(f"Samples missing data: {', '.join(missing_data)}")

        return True


class UnstainedRoleValidator(FlowValidator):
    """Verifies an unstained control is assigned."""

    def validate_flow(self, app_state: FlowState) -> bool:
        from ..analysis.experiment import SampleRole

        for s in app_state.data.experiment.samples.values():
            if s.role == SampleRole.UNSTAINED:
                name = s.display_name.lower()
                if "blank" in name or "unstained" in name:
                    return True
        return self.log_failure(
            "No sample with role UNSTAINED and 'blank'/'unstained' in name was found."
        )


class SingleStainRoleValidator(FlowValidator):
    """Verifies a single stain control (PI) is assigned."""

    def validate_flow(self, app_state: FlowState) -> bool:
        from ..analysis.experiment import SampleRole

        for s in app_state.data.experiment.samples.values():
            if s.role == SampleRole.SINGLE_STAIN and "pi" in s.display_name.lower():
                return True
        return self.log_failure("No sample with role SINGLE_STAIN and 'pi' in name was found.")


class FmoRoleValidator(FlowValidator):
    """Verifies that 5 FMO controls are assigned."""

    def validate_flow(self, app_state: FlowState) -> bool:
        from ..analysis.experiment import SampleRole

        fmo_count = 0
        for s in app_state.data.experiment.samples.values():
            if s.role == SampleRole.FMO_CONTROL and "fmo" in s.display_name.lower():
                fmo_count += 1
        if fmo_count < 5:  # noqa: PLR2004
            return self.log_failure(f"Expected 5 FMO controls, found {fmo_count}.")
        return True


class RoleAssignmentValidator(FlowValidator):
    """Verifies that the 4 essential roles have been assigned to at least one sample each,
    and that there are at least 3 FULL_PANEL samples (A, B, C).
    """

    def validate_flow(self, app_state: FlowState) -> bool:
        from ..analysis.experiment import SampleRole

        samples = list(app_state.data.experiment.samples.values())
        roles = {s.role for s in samples}

        full_panel_count = 0
        for s in samples:
            if s.role == SampleRole.FULL_PANEL and "sample" in s.display_name.lower():
                full_panel_count += 1

        if full_panel_count < 3:  # noqa: PLR2004
            return self.log_failure(f"Expected 3 FULL_PANEL samples, found {full_panel_count}.")

        required_roles = {
            SampleRole.UNSTAINED,
            SampleRole.SINGLE_STAIN,
            SampleRole.FMO_CONTROL,
            SampleRole.FULL_PANEL,
        }

        missing_roles = required_roles - roles
        if missing_roles:
            return self.log_failure(f"Missing essential roles: {[r.name for r in missing_roles]}")

        return True


class CompensationAppliedValidator(FlowValidator):
    """Verifies a compensation matrix exists, and auto-applies it to all samples."""

    def validate_flow(self, app_state: FlowState) -> bool:
        if app_state.data.compensation is None:
            from karcytics_sdk.plugin import get_logger

            from ..analysis.compensation import extract_spill_from_fcs

            inner_logger = get_logger(__name__, "flow_cytometry")
            inner_logger.info(
                "CompensationAppliedValidator: Starting to search for $SPILL in %d samples",
                len(app_state.data.experiment.samples),
            )
            for sample in app_state.data.experiment.samples.values():
                if sample.fcs_data:
                    comp = extract_spill_from_fcs(sample.fcs_data)
                    if comp is not None:
                        inner_logger.info(
                            "CompensationAppliedValidator: Found matrix in sample %s",
                            sample.display_name,
                        )
                        app_state.data.compensation = comp
                        break
                    inner_logger.info(
                        "CompensationAppliedValidator: No matrix found in sample %s",
                        sample.display_name,
                    )

            if app_state.data.compensation is None:
                inner_logger.warning("CompensationAppliedValidator: Failed to find any matrix!")
                return self.log_failure(
                    "Failed to find any compensation matrix ($SPILL) in samples."
                )

        # The matrix exists! Auto-apply it so the tutorial can skip the manual application steps.
        applied_any = False
        for sample in app_state.data.experiment.samples.values():
            if not sample.is_compensated:
                sample.is_compensated = True
                applied_any = True

        if applied_any:
            try:
                from karcytics_sdk.plugin import CentralEventBus

                from ..analysis.events import EXPERIMENT_DATA_CHANGED

                CentralEventBus.publish(EXPERIMENT_DATA_CHANGED, {})
            except Exception:
                pass

        return True


class GateExistsValidator(FlowValidator):
    """Verifies that a gate with the given name exists on at least one Full Panel sample."""

    def __init__(self, target_gate_name: str) -> None:
        self._target = target_gate_name.lower()

    def validate_flow(self, app_state: FlowState) -> bool:
        from ..analysis.experiment import SampleRole

        samples = list(app_state.data.experiment.samples.values())
        full_panel = [s for s in samples if s.role == SampleRole.FULL_PANEL] or samples
        if not any(self._gate_found(s.gate_tree) for s in full_panel):
            return self.log_failure(f"Gate '{self._target}' not found in any FULL_PANEL samples.")
        return True

    def _gate_found(self, node: Any) -> bool:
        if (getattr(node, "name", "") or "").lower() == self._target:
            return True
        return any(self._gate_found(child) for child in getattr(node, "children", []))


class SampleOpenValidator(FlowValidator):
    """Verifies that the Blank (Unstained) sample is currently the active graph in the workspace."""

    def validate_flow(self, app_state: FlowState) -> bool:
        sample_id = getattr(app_state.view, "current_sample_id", None)
        if not sample_id:
            return self.log_failure("No active sample ID in view.")
        from ..analysis.experiment import SampleRole

        sample = app_state.data.experiment.samples.get(sample_id)
        if not sample:
            return self.log_failure(f"Sample ID {sample_id} not found in experiment.")
        if sample.role != SampleRole.UNSTAINED:
            return self.log_failure(
                f"Active sample role is {sample.role.name}, expected UNSTAINED."
            )
        return True


class SpecificSampleOpenValidator(FlowValidator):
    """Verifies that a sample with a specific SampleRole is currently open."""

    def __init__(self, role_name: str) -> None:
        """Args: role_name: e.g. 'SINGLE_STAIN' to match SampleRole.SINGLE_STAIN."""
        self._role_name = role_name.upper()

    def validate_flow(self, app_state: FlowState) -> bool:
        sample_id = getattr(app_state.view, "current_sample_id", None)
        if not sample_id:
            return self.log_failure("No active sample ID in view.")
        from ..analysis.experiment import SampleRole

        sample = app_state.data.experiment.samples.get(sample_id)
        if sample is None:
            return self.log_failure(f"Sample ID {sample_id} not found in experiment.")
        try:
            expected_role = SampleRole[self._role_name]
            if sample.role != expected_role:
                return self.log_failure(
                    f"Active sample role is {sample.role.name}, expected {expected_role.name}."
                )
            return True
        except KeyError:
            return self.log_failure(f"Unknown expected role: {self._role_name}")


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


class AxisTransformValidator(FlowValidator):
    """Verifies that the active X axis transform matches a specific type (e.g. 'biexponential')."""

    def __init__(self, transform_name: str) -> None:
        self._transform = transform_name.lower()

    def validate_flow(self, app_state: FlowState) -> bool:
        active = getattr(app_state.view, "active_transform_x", "") or ""
        if active.lower() != self._transform:
            return self.log_failure(
                f"Active X transform is '{active}', expected '{self._transform}'."
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
            from ..analysis.axis_manager import AxisManager

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
        from ..analysis.experiment import SampleRole

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


class ExactSampleOpenValidator(FlowValidator):
    """Verifies that a specific named sample is currently open."""

    def __init__(self, sample_name: str) -> None:
        self._sample_name = sample_name.lower()

    def validate_flow(self, app_state: FlowState) -> bool:
        sample_id = getattr(app_state.view, "current_sample_id", None)
        if not sample_id:
            return self.log_failure("No active sample ID in view.")
        sample = app_state.data.experiment.samples.get(sample_id)
        if not sample:
            return self.log_failure(f"Sample ID {sample_id} not found in experiment.")
        if self._sample_name not in sample.display_name.lower():
            return self.log_failure(
                f"Active sample '{sample.display_name}' does not match expected '{self._sample_name}'."
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
    """Verifies that a newly created gate matches the required target shape."""

    def __init__(
        self,
        target_bounds: tuple[float, float, float, float] | None = None,
        target_poly: list[tuple[float, float]] | None = None,
        target_name: str | None = None,
        misnamed_retry_step_id: str | None = None,
        shape_retry_step_id: str | None = None,
    ) -> None:
        """Args:
        target_bounds: (min_x, max_x, min_y, max_y). For 1D gates, use 0 for min_y, max_y.
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

        `GateMutationService.add_gate()` always ends by calling
        `GateSelectionService.select_gate()` on the node(s) it just created
        (see gate_mutation_service.py) — so `current_gate_id`/
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
            # _TUTORIAL_STATE is legacy: course2.py's own (not-yet-migrated)
            # gate-failure routing still reads it directly. Keep writing it
            # until that course is migrated to describe_failure() too —
            # course1 itself no longer reads it (see describe_failure below).
            _TUTORIAL_STATE["last_misnamed_node_id"] = None
            _TUTORIAL_STATE["last_failed_node_id"] = None
            _TUTORIAL_STATE["last_misnamed_sample_id"] = None

            # An immediate hit from `_handle_gate_created`
            # (main_panel_controller) already knows exactly which
            # freshly-drawn node failed shape validation — trust it over
            # re-deriving the same answer below.
            if getattr(self, "explicit_failed_node_id", None):
                self.last_failed_node_id = self.explicit_failed_node_id
                self.explicit_failed_node_id = None
                _TUTORIAL_STATE["last_failed_node_id"] = self.last_failed_node_id
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
                _TUTORIAL_STATE["last_failed_node_id"] = node_id
                return self.log_failure("No gate matching target shape bounds/polygon found.")

            if (
                self.target_name
                and (getattr(node, "name", "") or "").lower() != self.target_name.lower()
            ):
                self.last_misnamed_node_id = node_id
                self.last_misnamed_sample_id = sample_id
                _TUTORIAL_STATE["last_misnamed_node_id"] = node_id
                _TUTORIAL_STATE["last_misnamed_sample_id"] = sample_id
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
                panel._gate_coordinator.rename_population(target_sample_id, node_id, correct_name)
                # Supersede any active propagation (from the original add_gate
                # call) that snapshotted the tree with the old, incorrect name.
                panel._gate_coordinator.request_propagation(node_id, target_sample_id)

            return ValidationFailure(
                reason=f"Great shape! But you named it incorrectly. I renamed it to **{correct_name}** for you!",
                corrective=_rename,
                retry_step_id=self.misnamed_retry_step_id,
            )

        if self.last_failed_node_id:
            node_id = self.last_failed_node_id

            def _delete(panel: Any) -> None:
                panel.state.view.current_gate_id = node_id
                panel._on_delete_selected_gate(force_silent=True)

            return ValidationFailure(
                reason="That gate didn't quite capture the right range! I deleted it for you — try drawing it again.",
                corrective=_delete,
                retry_step_id=self.shape_retry_step_id,
            )

        return None

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
            gate = getattr(gate, "parent_gate", gate)
            gate_type = type(gate).__name__

        # Exact shape matching for Polygons via rasterization
        if gate_type == "PolygonGate" and self.target_poly:
            import numpy as np
            from matplotlib.path import Path

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

            # Ensure it is within 10% of the original shape
            return iou >= 0.90  # noqa: PLR2004

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
            # QuadrantGate stores its crosshair position as x_mid/y_mid (see
            # analysis/gating/quadrant.py) — this used to read the
            # nonexistent x_threshold/y_threshold, so getattr's default
            # silently made min_x/max_x/min_y/max_y always (0.0, 0.0),
            # meaning a quadrant gate's actual click position was never
            # really checked.
            x_mid, y_mid = getattr(gate, "x_mid", 0.0), getattr(gate, "y_mid", 0.0)
            # A single click point has no "edge" to apply the ±10%-of-axis
            # tolerance below to — that formula is for RangeGate/RectangleGate,
            # where min_x and max_x are two genuinely different edges each
            # compared to its own target edge. Naively reusing it here (by
            # setting min_x = max_x = x_mid) checked "close to either target
            # edge independently", which works out to accepting anywhere in
            # roughly a +/-26000-unit band regardless of the target window's
            # actual width (here, target_bounds = 3000-7000 — a 4000-unit
            # window) — over 12x more lenient than intended. A quadrant
            # target window is meant to already BE the acceptable region, so
            # just check containment directly, no extra tolerance layered on.
            return t_min_x <= x_mid <= t_max_x and t_min_y <= y_mid <= t_max_y
        else:
            return True  # skip unknown gate types

        if gate_type in {"RangeGate", "RectangleGate"}:
            # For 1D ranges, check relative error based on a typical flow axis range (262144)
            axis_range = 262144.0

            # Check X bounds
            if (
                abs(min_x - t_min_x) / axis_range > 0.10  # noqa: PLR2004
                or abs(max_x - t_max_x) / axis_range > 0.10  # noqa: PLR2004
            ):
                return False

            # Check Y bounds for Rectangle
            return not (
                gate_type == "RectangleGate"
                and (
                    abs(min_y - t_min_y) / axis_range > 0.10  # noqa: PLR2004
                    or abs(max_y - t_max_y) / axis_range > 0.10  # noqa: PLR2004
                )
            )

        return False


class WorkflowSavedValidator(FlowValidator):
    """Verifies that the user has saved a workflow and registers it as a prerequisite."""

    def __init__(self):
        self._saved_payload = None

        # Subscribe to save event across the plugin process
        try:
            from karcytics_sdk.plugin import CentralEventBus

            CentralEventBus.subscribe("flow.workflow.saved", self._on_workflow_saved)
        except ImportError:
            pass

    def _on_workflow_saved(self, payload: dict) -> None:
        self._saved_payload = payload

    def validate_flow(self, _app_state: FlowState) -> bool:
        if self._saved_payload:
            from karcytics_sdk.plugin.runtime_services import (
                tutorial_manager as global_tutorial_manager,
            )

            # The SDK expects a 'workflow_hash' parameter, but because the plugin is isolated
            # and Course 2 only validates the workspace state (via Course1StateValidator)
            # rather than strictly hashing the file, we can just use the filename/path.
            wf_id = (
                self._saved_payload.get("filename")
                or self._saved_payload.get("path")
                or "standalone_save"
            )

            # Always unlock Course 2 gating when Course 1 saves
            global_tutorial_manager.record_prerequisite("flow_course_2_gating", wf_id)

            # Also unlock Course 3 gating when Course 2 saves (as this validator is used in both)
            global_tutorial_manager.record_prerequisite("flow_course_3_pipeline", wf_id)

            return True

        return self.log_failure("Waiting for workflow to be saved...")


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


class Course1StateValidator(FlowValidator):
    """Verifies that the workspace state matches the expected Course 1 checkpoint."""

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


class PlotTypeValidator(FlowValidator):
    """Verifies that the active graph is displaying the specified plot type (e.g. 'Histogram', 'Pseudocolor')."""

    def __init__(self, expected_plot_type: str) -> None:
        self.expected = expected_plot_type.lower()

    def validate_flow(self, app_state: FlowState) -> bool:

        graph_manager = getattr(app_state.view, "_graph_manager", None)
        active_graph = (
            graph_manager.get_active_graph()
            if graph_manager and hasattr(graph_manager, "get_active_graph")
            else None
        )
        if not active_graph:
            return self.log_failure("No active graph found in graph manager.")

        axis_panel = getattr(active_graph, "_axis_panel", None)
        if not axis_panel or not hasattr(axis_panel, "_display_combo"):
            return self.log_failure("Active graph missing axis panel or display combo.")

        current_text = axis_panel._display_combo.currentText().lower()
        if current_text != self.expected:
            return self.log_failure(
                f"Active plot type is '{current_text}', expected '{self.expected}'."
            )
        return True


class PipelineOrientationValidator(FlowValidator):
    """Verifies that the pipeline canvas is set to a specific layout orientation (e.g., 'Horizontal')."""

    def __init__(self, expected_orientation: str) -> None:
        self.expected = expected_orientation.lower()

    def validate_flow(self, app_state: FlowState) -> bool:

        pipeline_ribbon = getattr(app_state.view, "_pipeline_ribbon", None)
        if not pipeline_ribbon or not hasattr(pipeline_ribbon, "_orientation_combo"):
            return self.log_failure("Pipeline ribbon or orientation combo missing.")

        current_text = pipeline_ribbon._orientation_combo.currentText().lower()
        if current_text != self.expected:
            return self.log_failure(
                f"Pipeline orientation is '{current_text}', expected '{self.expected}'."
            )
        return True


class LearningCompensationCompleteValidator(FlowValidator):
    """Verifies the user actually finished the Learning Compensation slide-
    deck's final reasoning task — not just paged through to the last slide."""

    def validate_flow(self, app_state: FlowState) -> bool:

        spectral_viewer = getattr(app_state.view, "_spectral_viewer", None)
        if not spectral_viewer or not hasattr(spectral_viewer, "_learning_tab"):
            return self.log_failure("Spectral viewer or learning tab missing.")

        learning_tab = spectral_viewer._learning_tab
        last_step = learning_tab._max_steps - 1
        if learning_tab._current_step < last_step:
            return self.log_failure(
                f"Currently on step {learning_tab._current_step}, expected >= {last_step}."
            )
        if last_step not in learning_tab._completed_steps:
            return self.log_failure(
                "Reached the last slide but hasn't answered both reasoning questions yet."
            )
        return True


class GateAbsentValidator(FlowValidator):
    """Verifies that a gate with the given name no longer exists on the active sample.

    Used to confirm a population was deleted (e.g. via the Pipeline canvas Delete key).
    """

    def __init__(self, target_gate_name: str) -> None:
        self._target = target_gate_name.lower()

    def validate_flow(self, app_state: FlowState) -> bool:
        sample_id = getattr(app_state.view, "current_sample_id", None)
        if not sample_id:
            return self.log_failure("No active sample ID in view.")
        sample = app_state.data.experiment.samples.get(sample_id)
        if not sample:
            return self.log_failure(f"Sample ID {sample_id} not found in experiment.")

        if self._gate_found(sample.gate_tree):
            return self.log_failure(f"Gate '{self._target}' still exists on the active sample.")
        return True

    def _gate_found(self, node: Any) -> bool:
        if (getattr(node, "name", "") or "").lower() == self._target:
            return True
        return any(self._gate_found(child) for child in getattr(node, "children", []))


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


class SpectralFluorsLoadedValidator(FlowValidator):
    """Verifies that at least N fluorophore spectra are currently loaded in the Spectral viewer."""

    def __init__(self, min_count: int = 6) -> None:
        self._min_count = min_count

    def validate_flow(self, app_state: FlowState) -> bool:
        spectral_viewer = getattr(app_state.view, "_spectral_viewer", None)
        if not spectral_viewer or not hasattr(spectral_viewer, "_active_fluors"):
            return self.log_failure("Spectral viewer or active fluors dict missing.")
        count = len(spectral_viewer._active_fluors)
        if count < self._min_count:
            return self.log_failure(
                f"Only {count} fluorophores loaded, expected >= {self._min_count}."
            )
        return True


class UmapClusterExportedValidator(FlowValidator):
    """Verifies a 'UMAP Reduction' node with at least one exported cluster child exists."""

    def validate_flow(self, app_state: FlowState) -> bool:
        for sample in app_state.data.experiment.samples.values():
            node = self._find_umap_parent(sample.gate_tree)
            if node is not None and len(getattr(node, "children", [])) > 0:
                return True
        return self.log_failure("No 'UMAP Reduction' node with exported clusters found.")

    def _find_umap_parent(self, node: Any) -> Any | None:
        if (getattr(node, "name", "") or "").lower() == "umap reduction":
            return node
        for child in getattr(node, "children", []):
            found = self._find_umap_parent(child)
            if found is not None:
                return found
        return None


class StatsChartTypeValidator(FlowValidator):
    """Verifies the Statistics tab's chart-type combo is set to a specific value (e.g. 'Heatmap')."""

    def __init__(self, expected_type: str) -> None:
        self._expected = expected_type.lower()

    def validate_flow(self, app_state: FlowState) -> bool:
        explorer = getattr(app_state.view, "_statistics_explorer", None)
        if not explorer or not hasattr(explorer, "_chart_type_combo"):
            return self.log_failure("Statistics explorer or chart type combo missing.")
        current = explorer._chart_type_combo.currentText().lower()
        if self._expected not in current:
            return self.log_failure(f"Chart type is '{current}', expected '{self._expected}'.")
        return True


class SampleAndGateOpenValidator(FlowValidator):
    """Verifies a specific sample is open with a specific gate/population as the active view.

    Reads directly from the live GraphManager's active GraphWindow rather than
    app_state.view.current_sample_id/current_gate_id: actions like the Sample
    List's right-click "open population" only update current_sample_id, not
    current_gate_id, so that pair can go stale after a context-menu jump.
    """

    def __init__(self, sample_substr: str, gate_substr: str) -> None:
        self._sample = sample_substr.lower()
        self._gate = gate_substr.lower()

    def validate_flow(self, app_state: FlowState) -> bool:
        graph_manager = getattr(app_state.view, "_graph_manager", None)
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


class ComparisonPlotTypeValidator(FlowValidator):
    """Verifies the Comparisons tab's plot-type combo is set to a specific chart (e.g. 'Violin')."""

    def __init__(self, expected_type: str) -> None:
        self._expected = expected_type.lower()

    def validate_flow(self, app_state: FlowState) -> bool:
        viewer = getattr(app_state.view, "_comparisons_viewer", None)
        if not viewer or not hasattr(viewer, "_plot_type_combo"):
            return self.log_failure("Comparisons viewer or plot type combo missing.")
        current = viewer._plot_type_combo.currentText().lower()
        if self._expected not in current:
            return self.log_failure(f"Plot type is '{current}', expected '{self._expected}'.")
        return True


class QuadrantGateExistsValidator(FlowValidator):
    """Verifies a QuadrantGate has actually been placed on the active sample.

    Used instead of a plain tool-click InteractionStep so the tutorial waits
    for the gate to exist, not just for the Quadrant tool to be selected.
    """

    def validate_flow(self, app_state: FlowState) -> bool:
        sample_id = getattr(app_state.view, "current_sample_id", None)
        if not sample_id:
            return self.log_failure("No active sample ID in view.")
        sample = app_state.data.experiment.samples.get(sample_id)
        if not sample:
            return self.log_failure(f"Sample ID {sample_id} not found in experiment.")

        def check_node(node: Any) -> bool:
            # A QuadrantGate never lands in the tree as a node's own .gate —
            # create_nodes() attaches 4 sibling leaves whose .gate is a
            # QuadrantSubGate wrapping the parent QuadrantGate instead.
            if type(getattr(node, "gate", None)).__name__ == "QuadrantSubGate":
                return True
            return any(check_node(child) for child in getattr(node, "children", []))

        if not check_node(sample.gate_tree):
            return self.log_failure("No QuadrantSubGate leaves found on active sample.")
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

        def find_node(node: Any) -> Any | None:
            gate = getattr(node, "gate", None)
            if (
                type(gate).__name__ == "QuadrantSubGate"
                and getattr(gate, "quadrant", "").strip().upper() == self._quadrant
            ):
                return node
            for child in getattr(node, "children", []):
                found = find_node(child)
                if found is not None:
                    return found
            return None

        node = find_node(sample.gate_tree)
        if node is None:
            return self.log_failure(f"No {self._quadrant} QuadrantSubGate leaf found.")
        actual = (getattr(node, "name", "") or "").strip().lower()
        if actual != self._expected:
            return self.log_failure(
                f"{self._quadrant} is named '{actual}', expected '{self._expected}'."
            )
        return True


class PopupClosedValidator(FlowValidator):
    """Verifies an ephemeral top-level popup (found by objectName) is no longer visible.

    Lets a step auto-advance once the user dismisses a popup (e.g. the
    All-Samples quick stats view) instead of requiring a manual Next click.
    """

    def __init__(self, popup_object_name: str) -> None:
        self._name = popup_object_name

    def validate_flow(self, _app_state: FlowState) -> bool:
        from PyQt6.QtWidgets import QApplication

        for w in QApplication.topLevelWidgets():
            if w.objectName() != self._name:
                continue
            try:
                from PyQt6 import sip

                if sip.isdeleted(w):
                    return True
                if w.isVisible():
                    return self.log_failure("Popup is still visible.")
            except Exception:
                return True
        return True
