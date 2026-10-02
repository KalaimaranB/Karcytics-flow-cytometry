"""Two-channel formula templates offered by the derived-parameter editor.

Most derived parameters scientists want are one of a handful of shapes of
two channels (a reporter over a reference, a fraction, a normalized
difference). Picking a template and two channels writes the formula, so
nobody has to type bracket syntax for the common cases.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..transforms import TransformType


@dataclass(frozen=True)
class FormulaTemplate:
    """A two-channel formula shape.

    Attributes:
        key:     Stable identifier (used for widget data / tutorials).
        label:   Menu text.
        pattern: Formula with ``{a}`` / ``{b}`` channel-name placeholders.
        name_pattern: Suggested display name with ``{a}`` / ``{b}`` marker
                 placeholders.
        preferred_transform: Sensible default axis scale for the result.
        hint:    One-line explanation of when to use it.
    """

    key: str
    label: str
    pattern: str
    name_pattern: str
    preferred_transform: str
    hint: str

    def formula(self, channel_a: str, channel_b: str) -> str:
        return self.pattern.format(a=channel_a, b=channel_b)

    def suggested_name(self, label_a: str, label_b: str) -> str:
        return self.name_pattern.format(a=short_label(label_a), b=short_label(label_b))


TEMPLATES: tuple[FormulaTemplate, ...] = (
    FormulaTemplate(
        key="ratio",
        label="Ratio  A ÷ B",
        pattern="[{a}] / [{b}]",
        name_pattern="{a}/{b}",
        preferred_transform=TransformType.LOG.value,
        hint="Signal relative to a reference, e.g. reporter ÷ constitutive marker.",
    ),
    FormulaTemplate(
        key="log_ratio",
        label="Log ratio  log10(A ÷ B)",
        pattern="log10([{a}] / [{b}])",
        name_pattern="log({a}/{b})",
        preferred_transform=TransformType.LINEAR.value,
        hint="Symmetric around 0: +1 means A is 10× B, −1 means B is 10× A.",
    ),
    FormulaTemplate(
        key="fraction",
        label="Fraction  A ÷ (A + B)",
        pattern="[{a}] / ([{a}] + [{b}])",
        name_pattern="{a} fraction",
        preferred_transform=TransformType.LINEAR.value,
        hint="Share of the combined signal coming from A, between 0 and 1.",
    ),
    FormulaTemplate(
        key="norm_diff",
        label="Normalized difference  (A − B) ÷ (A + B)",
        pattern="([{a}] - [{b}]) / ([{a}] + [{b}])",
        name_pattern="({a}-{b})/({a}+{b})",
        preferred_transform=TransformType.LINEAR.value,
        hint="Balance between A and B, from −1 (all B) to +1 (all A).",
    ),
    FormulaTemplate(
        key="sum",
        label="Sum  A + B",
        pattern="[{a}] + [{b}]",
        name_pattern="{a}+{b}",
        preferred_transform=TransformType.LOG.value,
        hint="Combine two channels carrying the same marker (e.g. a dump channel).",
    ),
)


def get_template(key: str) -> FormulaTemplate | None:
    return next((t for t in TEMPLATES if t.key == key), None)


def short_label(label: str) -> str:
    """``"B220 (FITC-A)"`` -> ``"B220"``; a bare channel name is unchanged."""
    if label.endswith(")") and " (" in label:
        return label[: label.rindex(" (")].strip() or label
    return label
