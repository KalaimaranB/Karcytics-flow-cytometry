"""Derived-parameter definition model."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from ..constants import DERIVED_PREFIX
from ..transforms import TransformType
from .expression import DerivedExpression, parse_formula

SCHEMA_VERSION = 1

# Derived parameters are ratios/combinations, not detector intensities —
# biexponential's shape estimation assumes a ~262k fluorescence range and
# would crush them, so only linear and log are offered.
ALLOWED_TRANSFORMS = (TransformType.LINEAR.value, TransformType.LOG.value)


def is_derived_key(channel: str | None) -> bool:
    """True if ``channel`` is a derived-parameter column key."""
    return bool(channel) and str(channel).startswith(DERIVED_PREFIX)


def new_param_id() -> str:
    """Return a fresh, stable column key for a new derived parameter."""
    return f"{DERIVED_PREFIX}{uuid.uuid4().hex[:8]}"


@dataclass
class DerivedParameter:
    """A per-event formula exposed as an extra channel.

    Attributes:
        param_id: Stable column key (``derived:<hex>``). Gates, axis memory
                  and channel scales reference this, so renaming the
                  parameter never breaks them.
        name:     Display name (``B220/CD45``).
        formula:  Canonical formula text using channel names, e.g.
                  ``[FITC-A] / [APC-A]``.
        preferred_transform: Default axis scale (``linear`` or ``log``).
        positive_denominators: Treat events whose denominator is ≤ 0 as
                  invalid (NaN) instead of producing a sign-flipped or
                  exploding value.
    """

    param_id: str
    name: str
    formula: str
    preferred_transform: str = TransformType.LOG.value
    positive_denominators: bool = True

    def __post_init__(self) -> None:
        if self.preferred_transform not in ALLOWED_TRANSFORMS:
            self.preferred_transform = TransformType.LINEAR.value
        self._expr: DerivedExpression | None = None
        self._expr_text: str | None = None

    @property
    def expression(self) -> DerivedExpression:
        """Parsed formula (cached; raises FormulaError if invalid)."""
        if self._expr is None or self._expr_text != self.formula:
            self._expr = parse_formula(self.formula)
            self._expr_text = self.formula
        return self._expr

    @property
    def signature(self) -> str:
        """Fingerprint of everything that affects the computed values."""
        return f"{self.formula}|{int(self.positive_denominators)}"

    @property
    def label(self) -> str:
        """Channel-list display label."""
        return f"ƒ {self.name}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "param_id": self.param_id,
            "name": self.name,
            "formula": self.formula,
            "preferred_transform": self.preferred_transform,
            "positive_denominators": self.positive_denominators,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DerivedParameter:
        return cls(
            param_id=data["param_id"],
            name=data.get("name", data["param_id"]),
            formula=data["formula"],
            preferred_transform=data.get("preferred_transform", TransformType.LOG.value),
            positive_denominators=bool(data.get("positive_denominators", True)),
        )
