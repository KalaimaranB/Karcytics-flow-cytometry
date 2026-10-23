"""Widgets that register their stylesheets with theme_manager fill in every token.

A misspelt token (``{BG_DRAK}``) is not an error: it stays in the stylesheet
as text and Qt drops the rule, so check none is left.
"""

import re
from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QWidget

from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.ui.graph.graph_manager import GraphManager
from karcytics_plugins.flow_cytometry.ui.widgets.gate_hierarchy.all_samples_popup import (
    AllSamplesPopup,
)
from karcytics_plugins.flow_cytometry.ui.widgets.selection.population_selection_popup import (
    PopulationSelectionPopup,
)
from karcytics_plugins.flow_cytometry.ui.widgets.umap_animator_widget import UmapAnimatorWidget

TOKEN = re.compile(r"\{[A-Z][A-Z_]+\}")


def leftover_tokens(root: QWidget) -> list[str]:
    widgets = [root, *root.findChildren(QWidget)]
    return [
        f"{w.objectName() or type(w).__name__}: {t}"
        for w in widgets
        for t in TOKEN.findall(w.styleSheet())
    ]


@pytest.mark.ui
@pytest.mark.parametrize(
    "build",
    [
        lambda: GraphManager(FlowState(), None, MagicMock(), MagicMock()),
        AllSamplesPopup,
        PopulationSelectionPopup,
        UmapAnimatorWidget,
    ],
)
def test_every_theme_token_is_filled_in(qtbot, build):
    widget = build()
    qtbot.addWidget(widget)
    assert leftover_tokens(widget) == []
