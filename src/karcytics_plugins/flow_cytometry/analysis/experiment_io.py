"""Serialization and deserialization for the experiment model."""

import json
from pathlib import Path
from typing import Any

from karcytics_sdk.plugin import get_logger

from .derived.models import DerivedParameter
from .experiment import (
    Experiment,
    Group,
    GroupRole,
    GroupTemplate,
    MarkerMapping,
    Sample,
    SampleRole,
    TubeDefinition,
    WorkflowTemplate,
)
from .gating import GateNode
from .scaling import AxisScale

logger = get_logger(__name__, "flow_cytometry")


class ExperimentSerializer:
    """Handles serialization and deserialization of the experiment model."""

    @classmethod
    def serialize_marker_mapping(cls, mapping: MarkerMapping) -> dict[str, Any]:
        return {
            "marker_name": mapping.marker_name,
            "fluorophore": mapping.fluorophore,
            "channel": mapping.channel,
            "color": mapping.color,
        }

    @classmethod
    def deserialize_marker_mapping(cls, data: dict[str, Any]) -> MarkerMapping:
        return MarkerMapping(**data)

    @classmethod
    def serialize_tube_definition(cls, tube: TubeDefinition) -> dict[str, Any]:
        d: dict[str, Any] = {"markers": tube.markers}
        if tube.fmo_minus:
            d["fmo_minus"] = tube.fmo_minus
        return d

    @classmethod
    def deserialize_tube_definition(cls, data: dict[str, Any]) -> TubeDefinition:
        return TubeDefinition(
            markers=data.get("markers", []),
            fmo_minus=data.get("fmo_minus"),
        )

    @classmethod
    def serialize_group_template(cls, gt: GroupTemplate) -> dict[str, Any]:
        return {
            "name": gt.name,
            "role": gt.role.value,
            "tubes": [cls.serialize_tube_definition(t) for t in gt.tubes],
        }

    @classmethod
    def deserialize_group_template(cls, data: dict[str, Any]) -> GroupTemplate:
        return GroupTemplate(
            name=data["name"],
            role=SampleRole(data.get("role", "other")),
            tubes=[cls.deserialize_tube_definition(t) for t in data.get("tubes", [])],
        )

    @classmethod
    def serialize_workflow_template(cls, wt: WorkflowTemplate) -> dict[str, Any]:
        return {
            "name": wt.name,
            "description": wt.description,
            "markers": wt.markers,
            "marker_mappings": [cls.serialize_marker_mapping(m) for m in wt.marker_mappings],
            "groups": [cls.serialize_group_template(g) for g in wt.groups],
            "gate_template": wt.gate_template,
            "protocol_notes": wt.protocol_notes,
            "derived_parameters": wt.derived_parameters,
        }

    @classmethod
    def deserialize_workflow_template(cls, data: dict[str, Any]) -> WorkflowTemplate:
        return WorkflowTemplate(
            name=data["name"],
            description=data.get("description", ""),
            markers=data.get("markers", []),
            marker_mappings=[
                cls.deserialize_marker_mapping(m) for m in data.get("marker_mappings", [])
            ],
            groups=[cls.deserialize_group_template(g) for g in data.get("groups", [])],
            gate_template=data.get("gate_template"),
            protocol_notes=data.get("protocol_notes", ""),
            derived_parameters=data.get("derived_parameters", []),
        )

    @classmethod
    def save_template(cls, template: WorkflowTemplate, path: Path) -> None:
        """Save a workflow template to a JSON file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cls.serialize_workflow_template(template), f, indent=2)
        logger.info("Saved workflow template to %s", path)

    @classmethod
    def load_template(cls, path: Path) -> WorkflowTemplate:
        """Load a workflow template from a JSON file."""
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return cls.deserialize_workflow_template(data)

    @classmethod
    def serialize_sample(cls, sample: Sample) -> dict[str, Any]:
        """Serialize sample metadata (not the raw events)."""
        return {
            "sample_id": sample.sample_id,
            "display_name": sample.display_name,
            "file_path": str(sample.fcs_data.file_path) if sample.fcs_data else None,
            "role": sample.role.value,
            "markers": sample.markers,
            "fmo_minus": sample.fmo_minus,
            "group_ids": sample.group_ids,
            "keywords": sample.keywords,
            "is_compensated": sample.is_compensated,
            "last_viewed_axes": sample.last_viewed_axes,
            "gate_tree": sample.gate_tree.to_dict(),
        }

    @classmethod
    def deserialize_sample(cls, data: dict[str, Any]) -> Sample:
        """Reconstruct a Sample from a serialized dictionary."""
        sample = Sample(
            sample_id=data["sample_id"],
            display_name=data["display_name"],
            role=SampleRole(data.get("role", "other")),
            markers=data.get("markers", []),
            fmo_minus=data.get("fmo_minus"),
            group_ids=data.get("group_ids", []),
            keywords=data.get("keywords", {}),
            is_compensated=data.get("is_compensated", False),
        )
        sample.last_viewed_axes = data.get("last_viewed_axes", {})
        if "gate_tree" in data:
            parsed_tree = GateNode.from_dict(data["gate_tree"])
            if parsed_tree is None:
                raise ValueError("Invalid gate tree format in sample data.")
            sample.gate_tree = parsed_tree
        return sample

    @classmethod
    def serialize_group(cls, group: Group) -> dict[str, Any]:
        return {
            "group_id": group.group_id,
            "name": group.name,
            "role": group.role.value,
            "color": group.color,
            "sample_ids": group.sample_ids,
            "channel_scales": {ch: sc.to_dict() for ch, sc in group.channel_scales.items()},
        }

    @classmethod
    def deserialize_group(cls, data: dict[str, Any]) -> Group:
        group = Group(
            group_id=data["group_id"],
            name=data["name"],
            role=GroupRole(data.get("role", "custom")),
            color=data.get("color", "#4A90D9"),
            sample_ids=data.get("sample_ids", []),
        )
        group.channel_scales = {
            ch: AxisScale.from_dict(sc) for ch, sc in data.get("channel_scales", {}).items()
        }
        return group

    @classmethod
    def serialize_experiment(cls, exp: Experiment) -> dict[str, Any]:
        """Serialize the experiment for workflow save."""
        return {
            "name": exp.name,
            "samples": {sid: cls.serialize_sample(s) for sid, s in exp.samples.items()},
            "groups": {gid: cls.serialize_group(g) for gid, g in exp.groups.items()},
            "marker_mappings": [cls.serialize_marker_mapping(m) for m in exp.marker_mappings],
            "active_template": (
                cls.serialize_workflow_template(exp.active_template)
                if exp.active_template
                else None
            ),
            "derived_parameters": [d.to_dict() for d in exp.derived_parameters],
        }

    @classmethod
    def deserialize_experiment(cls, data: dict[str, Any]) -> Experiment:
        """Reconstruct an Experiment from a serialized dictionary."""
        exp = Experiment(
            name=data.get("name", "Untitled Experiment"),
        )

        logger.info(f"Reconstructing Experiment '{exp.name}' from dict...")

        # Restore samples
        sample_count = 0
        for sid, sdata in data.get("samples", {}).items():
            sample = cls.deserialize_sample(sdata)
            exp.samples[sid] = sample
            sample_count += 1

        logger.info(f"Restored {sample_count} samples.")

        # Restore groups
        for gid, gdata in data.get("groups", {}).items():
            exp.groups[gid] = cls.deserialize_group(gdata)

        # Restore marker mappings
        exp.marker_mappings = [
            cls.deserialize_marker_mapping(m) for m in data.get("marker_mappings", [])
        ]

        # Restore template
        tmpl_data = data.get("active_template")
        if tmpl_data:
            exp.active_template = cls.deserialize_workflow_template(tmpl_data)

        exp.derived_parameters = [
            DerivedParameter.from_dict(d) for d in data.get("derived_parameters", [])
        ]

        return exp
