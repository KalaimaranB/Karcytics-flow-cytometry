"""The module's main tabs, in tab-bar order: the one place that order is defined."""

from __future__ import annotations

import os
from enum import IntEnum


class MainTab(IntEnum):
    """A main tab; its value is its index in the tab bar."""

    WORKSPACE = 0
    GATING = 1
    COMPENSATION = 2
    SPECTRAL = 3
    PIPELINE = 4
    POPULATION_ANALYSIS = 5
    AUTO_GATING = 6
    SAMPLE_LENS = 7
    STATISTICS = 8
    COMPARISONS = 9

    @property
    def available(self) -> bool:
        """False for a tab that is built but not shown yet (still in review).

        Auto Gating stays hidden unless KARCYTICS_FLOW_AUTO_GATING=1.
        """
        if self is MainTab.AUTO_GATING:
            return os.environ.get("KARCYTICS_FLOW_AUTO_GATING") == "1"
        return True

    @property
    def label(self) -> str:
        return self.name.replace("_", " ").title()

    @classmethod
    def restore(cls, saved: object) -> MainTab | None:
        """A tab saved by name, or by index in the order before Sample Lens moved.

        Indices are only ever read in that old order: tabs have been saved by name
        since, so adding a tab (Auto Gating) never changes what an old save restores.
        """
        if isinstance(saved, str):
            tab = cls.__members__.get(saved)
            return tab if tab is not None and tab.available else None
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
