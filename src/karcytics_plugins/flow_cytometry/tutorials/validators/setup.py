"""Checks for loading the tutorial files, opening samples and assigning their roles."""

from __future__ import annotations

from collections.abc import Callable

from karcytics_sdk.plugin import CentralEventBus, get_logger

from ...analysis import events
from ...analysis.compensation import extract_spill_from_fcs
from ...analysis.experiment import SampleRole
from ...analysis.state import FlowState
from ...ui.academy_context import AcademyContext
from ..tutorial_assets import MAX_PROVISION_ATTEMPTS, get_status, provisioning_has_stalled
from .base import FlowUIValidator, FlowValidator


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
        for s in app_state.data.experiment.samples.values():
            if s.role == SampleRole.SINGLE_STAIN and "pi" in s.display_name.lower():
                return True
        return self.log_failure("No sample with role SINGLE_STAIN and 'pi' in name was found.")


class FmoRoleValidator(FlowValidator):
    """Verifies that 5 FMO controls are assigned."""

    def validate_flow(self, app_state: FlowState) -> bool:
        fmo_count = 0
        for s in app_state.data.experiment.samples.values():
            if s.role == SampleRole.FMO_CONTROL and "fmo" in s.display_name.lower():
                fmo_count += 1
        if fmo_count < 5:  # noqa: PLR2004
            return self.log_failure(f"Expected 5 FMO controls, found {fmo_count}.")
        return True


class FmoOverlayValidator(FlowValidator):
    """Verifies that the active FMO overlay is set to a specific control."""

    def __init__(self, expected_fmo_name: str) -> None:
        self.expected_fmo_name = expected_fmo_name.lower()

    def validate_flow(self, app_state: FlowState) -> bool:
        fmo_sample_id = app_state.view.active_fmo_sample_id
        if not fmo_sample_id:
            return self.log_failure("No FMO overlay is active.")

        fmo_sample = app_state.data.experiment.samples.get(fmo_sample_id)
        if not fmo_sample:
            return self.log_failure(f"Active FMO sample '{fmo_sample_id}' not found in experiment.")

        if self.expected_fmo_name not in fmo_sample.display_name.lower():
            return self.log_failure(
                f"Expected FMO containing '{self.expected_fmo_name}', but got '{fmo_sample.display_name}'."
            )

        return True


class RoleAssignmentValidator(FlowValidator):
    """Verifies that the 4 essential roles have been assigned to at least one sample each,
    and that there are at least 3 FULL_PANEL samples (A, B, C).
    """

    def validate_flow(self, app_state: FlowState) -> bool:
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
            CentralEventBus.publish(events.EXPERIMENT_DATA_CHANGED, {})

        return True


class SampleOpenValidator(FlowValidator):
    """Verifies that the Blank (Unstained) sample is currently the active graph in the workspace."""

    def validate_flow(self, app_state: FlowState) -> bool:
        sample_id = getattr(app_state.view, "current_sample_id", None)
        if not sample_id:
            return self.log_failure("No active sample ID in view.")

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


class LearningCompensationCompleteValidator(FlowUIValidator):
    """Verifies the user actually finished the Learning Compensation slide-
    deck's final reasoning task — not just paged through to the last slide."""

    def validate_ui(self, _app_state: FlowState, ui: AcademyContext) -> bool:

        spectral_viewer = ui.spectral_viewer
        if spectral_viewer is None:
            return self.log_failure("Spectral viewer missing.")

        deck = spectral_viewer.learning_tab.academy_snapshot()
        last_step = deck.last_step
        if deck.step < last_step:
            return self.log_failure(f"Currently on step {deck.step}, expected >= {last_step}.")
        if last_step not in deck.completed:
            return self.log_failure(
                "Reached the last slide but hasn't answered both reasoning questions yet."
            )
        return True
