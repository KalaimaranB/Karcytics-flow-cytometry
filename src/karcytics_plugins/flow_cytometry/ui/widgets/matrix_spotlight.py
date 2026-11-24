"""Spotlighting part of a matrix table for the Academy: a row, a column, or one cell.

Table cells aren't widgets, so the Academy driver's name lookup can't find
them; a widget exposes ``get_tutorial_target_rects(step)`` instead and builds
the rects here. A step asks under ``MATRIX_HIGHLIGHT_KEY`` in its metadata:
``{"row": "PE-A"}``, ``{"column": "PerCP-Cy5-5-A"}``, or both for one cell.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QRect
from PySide6.QtWidgets import QTableWidget

from karcytics_plugins.flow_cytometry.ui.academy_context import MATRIX_HIGHLIGHT_KEY


def matrix_target_rects(table: QTableWidget, step: Any) -> list[QRect]:
    """Global rects of the row, column or cell ``step`` asks for; [] if none."""
    wanted = (getattr(step, "metadata", None) or {}).get(MATRIX_HIGHLIGHT_KEY)
    if not wanted or not table.isVisible():
        return []
    headers = (table.horizontalHeaderItem(c) for c in range(table.columnCount()))
    labels = [h.text() if h is not None else "" for h in headers]
    every = range(len(labels))
    rows = [labels.index(wanted["row"])] if wanted.get("row") in labels else every
    columns = [labels.index(wanted["column"])] if wanted.get("column") in labels else every
    area = QRect()
    for r in rows:
        for c in columns:
            if (item := table.item(r, c)) is not None:
                area = area.united(table.visualItemRect(item))
    if area.isEmpty():
        return []
    return [QRect(table.viewport().mapToGlobal(area.topLeft()), area.size())]
