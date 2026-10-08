"""The population grids paint their cells and row labels in the theme's colours."""

from __future__ import annotations

import pytest
from PySide6.QtGui import QColor

from karcytics_plugins.flow_cytometry.ui.widgets.gate_hierarchy import all_samples_popup
from karcytics_plugins.flow_cytometry.ui.widgets.gate_hierarchy.all_samples_popup import _HeatCell
from karcytics_plugins.flow_cytometry.ui.widgets.selection import population_selection_popup
from karcytics_plugins.flow_cytometry.ui.widgets.selection.population_selection_popup import (
    _ToggleCell,
)

pytestmark = pytest.mark.ui

LIGHT = {"BG_DARK": "#ffffff", "BG_MEDIUM": "#f0f6fc"}


def _fill(widget) -> str:
    """The colour a cell is filled with, sampled clear of its centred text."""
    return QColor(widget.grab().toImage().pixel(8, widget.height() // 2)).name()


@pytest.fixture
def light_theme(monkeypatch):
    # Both modules share the suite's stand-in Colors, which is all black.
    for token, value in LIGHT.items():
        monkeypatch.setattr(population_selection_popup.Colors, token, value, raising=False)


def test_selector_cells_follow_the_theme(qtbot, light_theme):
    unchecked = _ToggleCell(checked=False, enabled=True)
    unavailable = _ToggleCell(checked=False, enabled=False)
    for cell in (unchecked, unavailable):
        qtbot.addWidget(cell)

    assert _fill(unchecked) == LIGHT["BG_DARK"]
    assert _fill(unavailable) == LIGHT["BG_MEDIUM"]


def test_quick_stats_empty_cells_follow_the_theme(qtbot, light_theme):
    assert all_samples_popup.Colors is population_selection_popup.Colors
    zero = _HeatCell(0, 0.0)
    not_applied = _HeatCell(0, None)
    for cell in (zero, not_applied):
        qtbot.addWidget(cell)

    assert _fill(zero) == LIGHT["BG_DARK"]
    assert _fill(not_applied) == LIGHT["BG_MEDIUM"]
