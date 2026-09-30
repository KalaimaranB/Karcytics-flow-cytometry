"""Derived Parameter Service.

Owns the experiment's derived-parameter definitions: validation, CRUD,
dependency checks against gates, and keeping every sample's computed
columns in sync (via :func:`analysis.derived.sync_fcs_data`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from karcytics_sdk.plugin import CentralEventBus, get_logger

from .. import events
from ..constants import MAX_DERIVED_PARAMETERS
from ..derived import (
    ALLOWED_TRANSFORMS,
    DerivedExpression,
    DerivedParameter,
    FormulaError,
    SyncResult,
    is_derived_key,
    new_param_id,
    parse_formula,
    sync_experiment,
    sync_sample,
)
from ..fcs_io import get_channel_marker_label

if TYPE_CHECKING:
    from ..experiment import Experiment, Sample
    from ..gating import GateNode
    from ..state import FlowState

logger = get_logger(__name__, "flow_cytometry")

MAX_NAME_LENGTH = 60


class DerivedParameterError(ValueError):
    """A derived-parameter definition was rejected (bad name, limit, ...)."""


@dataclass(frozen=True)
class GateDependent:
    """A gate whose axes reference a derived parameter."""

    sample_id: str
    sample_name: str
    node_id: str
    node_name: str


class DerivedParameterInUseError(DerivedParameterError):
    """Deleting a derived parameter that gates still reference."""

    def __init__(self, dependents: list[GateDependent]) -> None:
        names = ", ".join(sorted({d.node_name for d in dependents}))
        super().__init__(f"Used by gate(s): {names}")
        self.dependents = dependents


class DerivedParameterService:
    """CRUD + sync for experiment-wide derived parameters.

    Publishes:
        events.DERIVED_PARAMS_CHANGED({"param_id", "action"}) after any
        definition change, once every sample has been re-synced.
    """

    def __init__(self, state: FlowState) -> None:
        self._state = state

    # ── Queries ───────────────────────────────────────────────────────────

    @property
    def _experiment(self) -> Experiment:
        return self._state.data.experiment

    @property
    def definitions(self) -> list[DerivedParameter]:
        return self._experiment.derived_parameters

    def get(self, param_id: str) -> DerivedParameter | None:
        return next((d for d in self.definitions if d.param_id == param_id), None)

    def available_channels(self) -> dict[str, str]:
        """Real (non-derived) channels across all samples -> display label."""
        channels: dict[str, str] = {}
        for sample in self._experiment.samples.values():
            fcs = sample.fcs_data
            if fcs is None:
                continue
            for ch in fcs.channels:
                if not is_derived_key(ch) and ch not in channels:
                    channels[ch] = get_channel_marker_label(fcs, ch)
        return channels

    def find_dependents(self, param_id: str) -> list[GateDependent]:
        """Every gate, in any sample, drawn on ``param_id``."""
        found: list[GateDependent] = []
        for sid, sample in self._experiment.samples.items():
            for node in _iter_nodes(sample.gate_tree):
                gate = node.gate
                if gate is None:
                    continue
                if param_id in (getattr(gate, "x_param", None), getattr(gate, "y_param", None)):
                    found.append(GateDependent(sid, sample.display_name, node.node_id, node.name))
        return found

    # ── Validation ────────────────────────────────────────────────────────

    def canonicalize(self, formula: str) -> str:
        """Resolve marker-label references to channel names.

        ``[B220] / [CD45]`` becomes ``[FITC-A] / [APC-A]``. References that
        are already channel names are left alone. Raises FormulaError for a
        reference that matches nothing, is ambiguous, or is itself derived.
        """
        expr = parse_formula(formula)
        channels = self.available_channels()
        by_marker = _marker_index(channels)

        mapping: dict[str, str] = {}
        for ref in expr.refs:
            if is_derived_key(ref.name) or ref.name.startswith("ƒ"):
                raise FormulaError(
                    "Derived parameters can't reference other derived parameters", ref.start
                )
            if ref.name in channels:
                continue
            hits = by_marker.get(ref.name.casefold(), [])
            if len(hits) == 1:
                mapping[ref.name] = hits[0]
            elif len(hits) > 1:
                raise FormulaError(
                    f"'{ref.name}' matches several channels ({', '.join(hits)}) — "
                    "use the channel name",
                    ref.start,
                )
            elif channels:
                raise FormulaError(f"Unknown channel [{ref.name}]", ref.start)
        return expr.with_renamed_channels(mapping) if mapping else formula

    def validate(
        self, name: str, formula: str, *, exclude_id: str | None = None
    ) -> tuple[str, DerivedExpression]:
        """Check a proposed definition; return (canonical formula, expression).

        Raises:
            DerivedParameterError: Bad name or too many parameters.
            FormulaError: Bad formula (with character position).
        """
        self._validate_name(name, exclude_id)
        if exclude_id is None and len(self.definitions) >= MAX_DERIVED_PARAMETERS:
            raise DerivedParameterError(
                f"Limit of {MAX_DERIVED_PARAMETERS} derived parameters reached"
            )
        canonical = self.canonicalize(formula)
        return canonical, parse_formula(canonical)

    def _validate_name(self, name: str, exclude_id: str | None) -> None:
        clean = name.strip()
        if not clean:
            raise DerivedParameterError("Name is required")
        if len(clean) > MAX_NAME_LENGTH:
            raise DerivedParameterError(f"Name is too long (max {MAX_NAME_LENGTH} characters)")
        key = clean.casefold()
        for d in self.definitions:
            if d.param_id != exclude_id and d.name.strip().casefold() == key:
                raise DerivedParameterError(f"A derived parameter named '{clean}' already exists")
        for ch, label in self.available_channels().items():
            if key in (ch.casefold(), label.casefold()):
                raise DerivedParameterError(f"'{clean}' is already a channel name")

    # ── Mutations ─────────────────────────────────────────────────────────

    def create(
        self,
        name: str,
        formula: str,
        *,
        preferred_transform: str = "log",
        positive_denominators: bool = True,
    ) -> DerivedParameter:
        canonical, _ = self.validate(name, formula)
        defn = DerivedParameter(
            param_id=new_param_id(),
            name=name.strip(),
            formula=canonical,
            preferred_transform=_check_transform(preferred_transform),
            positive_denominators=positive_denominators,
        )
        self.definitions.append(defn)
        self._after_change(defn.param_id, "created")
        return defn

    def update(  # noqa: PLR0913
        self,
        param_id: str,
        *,
        name: str,
        formula: str,
        preferred_transform: str,
        positive_denominators: bool,
    ) -> DerivedParameter:
        defn = self._require(param_id)
        canonical, _ = self.validate(name, formula, exclude_id=param_id)
        transform = _check_transform(preferred_transform)
        values_changed = (
            canonical != defn.formula or positive_denominators != defn.positive_denominators
        )
        transform_changed = transform != defn.preferred_transform

        defn.name = name.strip()
        defn.formula = canonical
        defn.positive_denominators = positive_denominators
        defn.preferred_transform = transform

        if values_changed or transform_changed:
            # Stored ranges/transforms were fitted to the old values.
            self._forget_scales(param_id)
        self._after_change(param_id, "updated")
        return defn

    def delete(self, param_id: str) -> None:
        """Remove a definition. Refuses while any gate still uses it."""
        self._require(param_id)
        dependents = self.find_dependents(param_id)
        if dependents:
            raise DerivedParameterInUseError(dependents)
        self._experiment.derived_parameters = [
            d for d in self.definitions if d.param_id != param_id
        ]
        self._forget_scales(param_id)
        self._after_change(param_id, "deleted")

    # ── Sync ──────────────────────────────────────────────────────────────

    def ensure_sample(self, sample: Sample) -> SyncResult:
        """Sync one sample's derived columns (idempotent, cheap if current)."""
        return sync_sample(self._experiment, sample)

    def sync_all(self) -> dict[str, SyncResult]:
        return sync_experiment(self._experiment)

    # ── Internals ─────────────────────────────────────────────────────────

    def _require(self, param_id: str) -> DerivedParameter:
        defn = self.get(param_id)
        if defn is None:
            raise DerivedParameterError(f"Unknown derived parameter {param_id}")
        return defn

    def _forget_scales(self, param_id: str) -> None:
        for group in self._experiment.groups.values():
            group.channel_scales.pop(param_id, None)
        fallback = getattr(self._state.view, "fallback_scales", None)
        if isinstance(fallback, dict):
            fallback.pop(param_id, None)

    def _after_change(self, param_id: str, action: str) -> None:
        self.sync_all()
        CentralEventBus.publish(
            events.DERIVED_PARAMS_CHANGED, {"param_id": param_id, "action": action}
        )


def _check_transform(value: str) -> str:
    if value not in ALLOWED_TRANSFORMS:
        raise DerivedParameterError(f"Unsupported scale '{value}' (use linear or log)")
    return value


def _marker_index(channels: dict[str, str]) -> dict[str, list[str]]:
    """Casefolded marker name -> channels whose label is 'Marker (Channel)'."""
    index: dict[str, list[str]] = {}
    for ch, label in channels.items():
        suffix = f" ({ch})"
        if label.endswith(suffix):
            marker = label[: -len(suffix)].strip().casefold()
            if marker:
                index.setdefault(marker, []).append(ch)
    return index


def _iter_nodes(root: GateNode):
    """Yield each node of a gate DAG once."""
    seen: set[str] = set()
    stack = [root]
    while stack:
        node = stack.pop()
        if node.node_id in seen:
            continue
        seen.add(node.node_id)
        yield node
        stack.extend(node.children)
