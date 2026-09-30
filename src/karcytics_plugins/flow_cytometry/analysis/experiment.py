"""Experiment model — samples, groups, roles, and workflow templates.

This is the scientist-centric data model that distinguishes Karcytics's
flow module from traditional data-centric tools.  Instead of treating
FCS files as undifferentiated data, the experiment model captures the
scientist's intent: which samples are controls, what markers are on
each tube, and what analysis steps should be applied.

Workflow templates capture the full experimental protocol and analysis
pipeline so that a scientist can re-run the same assay on new data
with one click.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from karcytics_sdk.plugin import get_logger

from .derived.models import DerivedParameter
from .fcs_io import FCSData
from .gating import GateNode
from .scaling import AxisScale

logger = get_logger(__name__, "flow_cytometry")


# ── Enums ────────────────────────────────────────────────────────────────────


class SampleRole(Enum):
    """Role of a sample in the experimental design."""

    UNSTAINED = "unstained"
    SINGLE_STAIN = "single_stain"
    FMO_CONTROL = "fmo_control"
    ISOTYPE_CONTROL = "isotype_control"
    FULL_PANEL = "full_panel"
    OTHER = "other"


class GroupRole(Enum):
    """Role of a sample group."""

    COMPENSATION = "compensation"
    CONTROL = "control"
    TEST = "test"
    ALL_SAMPLES = "all_samples"
    CUSTOM = "custom"


# ── Data classes ─────────────────────────────────────────────────────────────


@dataclass
class MarkerMapping:
    """Mapping of a biological marker to its fluorophore and channel.

    Attributes:
        marker_name:  Biological target (e.g., ``"CD4"``).
        fluorophore:  Dye/conjugate name (e.g., ``"FITC"``).
        channel:      Cytometer channel (e.g., ``"FL1-A"``).
        color:        Display color for plots (hex string).
    """

    marker_name: str
    fluorophore: str = ""
    channel: str = ""
    color: str = "#00FF00"


@dataclass
class Sample:
    """A single sample in the experiment.

    Attributes:
        sample_id:     Unique identifier.
        display_name:  Human-readable name shown in the sample tree.
        fcs_data:      Loaded FCS data (None if not yet loaded).
        role:          The role this sample plays (unstained, FMO, etc.).
        markers:       Which markers are present on this sample.
        fmo_minus:     If this is an FMO control, which marker is excluded.
        group_ids:     Groups this sample belongs to.
        gate_tree:     Hierarchical gating tree rooted at this sample.
        keywords:      Annotation keywords (from FCS metadata or user).
        is_compensated: Whether compensation has been applied.
    """

    sample_id: str
    display_name: str
    fcs_data: FCSData | None = None
    role: SampleRole = SampleRole.OTHER
    markers: list[str] = field(default_factory=list)
    fmo_minus: str | None = None
    group_ids: list[str] = field(default_factory=list)
    gate_tree: GateNode = field(default_factory=GateNode)
    keywords: dict[str, str] = field(default_factory=dict)
    is_compensated: bool = False
    last_viewed_axes: dict[str, dict] = field(default_factory=dict)

    @property
    def has_data(self) -> bool:
        """Return True if FCS data has been loaded for this sample."""
        return self.fcs_data is not None

    @property
    def event_count(self) -> int:
        """Total number of events (0 if no data loaded)."""
        return self.fcs_data.num_events if self.fcs_data else 0


@dataclass
class Group:
    """A named collection of samples with a role.

    Attributes:
        group_id:    Unique identifier.
        name:        Display name (e.g., ``"FMO Controls"``).
        role:        The group's functional role.
        color:       Display color (hex string).
        sample_ids:  IDs of samples in this group.
    """

    group_id: str
    name: str
    role: GroupRole = GroupRole.CUSTOM
    color: str = "#4A90D9"
    sample_ids: list[str] = field(default_factory=list)
    channel_scales: dict[str, AxisScale] = field(default_factory=dict)

    @property
    def size(self) -> int:
        return len(self.sample_ids)


# ── Workflow Template ────────────────────────────────────────────────────────


@dataclass
class TubeDefinition:
    """Defines one tube in a workflow template.

    Attributes:
        markers:    List of marker names present in this tube.
        fmo_minus:  If this is an FMO tube, the marker that was excluded.
    """

    markers: list[str] = field(default_factory=list)
    fmo_minus: str | None = None


@dataclass
class GroupTemplate:
    """Defines a group of tubes in a workflow template.

    Attributes:
        name:   Group name (e.g., ``"FMO Controls"``).
        role:   Sample role for tubes in this group.
        tubes:  List of tube specifications.
    """

    name: str
    role: SampleRole
    tubes: list[TubeDefinition] = field(default_factory=list)


@dataclass
class WorkflowTemplate:
    """A reusable experiment protocol and analysis pipeline.

    Captures the complete experimental design: which markers, which tube
    groups (unstained, single stains, FMOs, full panel), and optionally
    a saved gating strategy that can be adapted to new data.

    Attributes:
        name:            Template display name.
        description:     What this template is for.
        markers:         The full marker panel.
        marker_mappings: Marker → fluorophore → channel mappings.
        groups:          Group definitions with tube layouts.
        gate_template:   Optional saved gating tree (serialized).
        protocol_notes:  Free-text protocol instructions.
        derived_parameters: Serialized derived-parameter definitions the
                         gate template may reference.
    """

    name: str
    description: str = ""
    markers: list[str] = field(default_factory=list)
    marker_mappings: list[MarkerMapping] = field(default_factory=list)
    groups: list[GroupTemplate] = field(default_factory=list)
    gate_template: dict | None = None
    protocol_notes: str = ""
    derived_parameters: list[dict] = field(default_factory=list)


# ── Experiment ───────────────────────────────────────────────────────────────


@dataclass
class Experiment:
    """Top-level container for the entire workspace state.

    Holds all samples, groups, marker mappings, and the active workflow
    template.

    Attributes:
        name:             Experiment/workspace name.
        samples:          All loaded samples, keyed by sample_id.
        groups:           All defined groups, keyed by group_id.
        marker_mappings:  The panel's marker-to-channel mappings.
        active_template:  The workflow template currently in use.
        derived_parameters: Experiment-wide per-event formulas, appended to
                          every sample's channels (see analysis/derived/).
    """

    name: str = "Untitled Experiment"
    samples: dict[str, Sample] = field(default_factory=dict)
    groups: dict[str, Group] = field(default_factory=dict)
    marker_mappings: list[MarkerMapping] = field(default_factory=list)
    active_template: WorkflowTemplate | None = None
    derived_parameters: list[DerivedParameter] = field(default_factory=list)

    def add_sample(self, sample: Sample) -> None:
        """Add a sample to the experiment.

        Args:
            sample: The sample to add.
        """
        self.samples[sample.sample_id] = sample

    def remove_sample(self, sample_id: str) -> None:
        """Remove a sample and clean up its group memberships.

        Args:
            sample_id: The ID of the sample to remove.
        """
        self.samples.pop(sample_id, None)
        for group in self.groups.values():
            if sample_id in group.sample_ids:
                group.sample_ids.remove(sample_id)

    def add_group(self, group: Group) -> None:
        """Add a group to the experiment.

        Args:
            group: The group to add.
        """
        self.groups[group.group_id] = group

    def get_samples_in_group(self, group_id: str) -> list[Sample]:
        """Return all samples belonging to a group.

        Args:
            group_id: The group identifier.

        Returns:
            List of :class:`Sample` instances.
        """
        group = self.groups.get(group_id)
        if not group:
            return []
        return [self.samples[sid] for sid in group.sample_ids if sid in self.samples]

    def get_samples_by_role(self, role: SampleRole) -> list[Sample]:
        """Return all samples with a specific role.

        Args:
            role: The :class:`SampleRole` to filter by.

        Returns:
            List of matching samples.
        """
        return [s for s in self.samples.values() if s.role == role]

    def apply_template(self, template: WorkflowTemplate) -> None:
        """Apply a workflow template — creates groups and sample slots.

        This sets up the expected structure from the template but does
        NOT load any FCS data.  The scientist then maps FCS files into
        the pre-created slots.

        Args:
            template: The workflow template to apply.
        """
        import uuid

        self.active_template = template
        self.marker_mappings = list(template.marker_mappings)

        for gt in template.groups:
            group = Group(
                group_id=str(uuid.uuid4()),
                name=gt.name,
                role=_sample_role_to_group_role(gt.role),
            )

            for tube in gt.tubes:
                sample = Sample(
                    sample_id=str(uuid.uuid4()),
                    display_name=_tube_display_name(gt, tube),
                    role=gt.role,
                    markers=list(tube.markers),
                    fmo_minus=tube.fmo_minus,
                )
                sample.group_ids.append(group.group_id)
                group.sample_ids.append(sample.sample_id)
                self.add_sample(sample)

            self.add_group(group)

        logger.info(
            "Applied workflow template '%s': %d groups, %d sample slots.",
            template.name,
            len(template.groups),
            sum(len(gt.tubes) for gt in template.groups),
        )


# ── Helpers ──────────────────────────────────────────────────────────────────


def _sample_role_to_group_role(role: SampleRole) -> GroupRole:
    """Map a sample role to a group role."""
    mapping = {
        SampleRole.UNSTAINED: GroupRole.CONTROL,
        SampleRole.SINGLE_STAIN: GroupRole.COMPENSATION,
        SampleRole.FMO_CONTROL: GroupRole.CONTROL,
        SampleRole.ISOTYPE_CONTROL: GroupRole.CONTROL,
        SampleRole.FULL_PANEL: GroupRole.TEST,
        SampleRole.OTHER: GroupRole.CUSTOM,
    }
    return mapping.get(role, GroupRole.CUSTOM)


def _tube_display_name(group: GroupTemplate, tube: TubeDefinition) -> str:
    """Generate a human-readable name for a tube slot."""
    if not tube.markers:
        return f"{group.name} (no markers)"
    if tube.fmo_minus:
        return f"FMO minus {tube.fmo_minus}"
    if len(tube.markers) == 1:
        return f"{tube.markers[0]} only"
    return ", ".join(tube.markers)
