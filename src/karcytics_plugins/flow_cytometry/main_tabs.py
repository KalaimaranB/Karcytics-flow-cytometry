"""The module's main tabs, in tab-bar order: the one place that order is defined."""

from __future__ import annotations

from enum import IntEnum


class MainTab(IntEnum):
    """A main tab; its value is its index in the tab bar."""

    WORKSPACE = 0
    GATING = 1
    COMPENSATION = 2
    SPECTRAL = 3
    PIPELINE = 4
    POPULATION_ANALYSIS = 5
    SAMPLE_LENS = 6
    STATISTICS = 7
    COMPARISONS = 8

    @property
    def label(self) -> str:
        return self.name.replace("_", " ").title()

    @classmethod
    def restore(cls, saved: object) -> MainTab | None:
        """A tab saved by name, or by index in the order before Sample Lens moved."""
        if isinstance(saved, str):
            return cls.__members__.get(saved)
        if isinstance(saved, int) and 0 <= saved < len(_LEGACY_ORDER):
            return _LEGACY_ORDER[saved]
        return None


# Tab order until Sample Lens, Statistics and Comparisons became the last three.
_LEGACY_ORDER = (
    MainTab.WORKSPACE,
    MainTab.GATING,
    MainTab.COMPENSATION,
    MainTab.PIPELINE,
    MainTab.STATISTICS,
    MainTab.SPECTRAL,
    MainTab.POPULATION_ANALYSIS,
    MainTab.COMPARISONS,
    MainTab.SAMPLE_LENS,
)
