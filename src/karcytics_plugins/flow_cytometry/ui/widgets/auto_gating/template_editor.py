"""The gating template, written as a tree: each population's name and markers.

Double-click to edit. Markers are written as you would say them ("CD3+",
"CD4+ CD8−", "CD45lo"); "scatter" and "singlets" are the conventional Cells and
Singlets steps. The template itself (``analysis.autogate.template``) is the
single source; this only edits it, and saves it as a file to reuse.
"""

from __future__ import annotations

import json
from itertools import count
from pathlib import Path

from karcytics_sdk.plugin.components import BioCaptionLabel, SecondaryButton
from karcytics_sdk.plugin.dialogs import get_save_path
from karcytics_sdk.plugin.theme_fallback import theme_manager
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QHeaderView,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ....analysis.autogate.template import (
    STARTER,
    GatingTemplate,
    TemplateStep,
    parse_calls,
)

TREE_HEIGHT = 230
BUTTONS_PER_ROW = 2  # the sidebar is narrow
ID_ROLE = Qt.ItemDataRole.UserRole
NEW_NAME = "New population"
FILE_FILTER = "Gating template (*.json)"


class TemplateEditor(QWidget):
    changed = Signal()
    problem = Signal(str)  # a template that couldn't be opened or saved

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ids = count(1)
        self._name = STARTER.name
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self._tree = QTreeWidget()
        self._tree.setObjectName("AutoGateTemplateTree")
        self._tree.setColumnCount(2)
        self._tree.setHeaderLabels(["Population", "Markers"])
        self._tree.setFixedHeight(TREE_HEIGHT)
        self._tree.setIndentation(12)
        self._tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._tree.setEditTriggers(
            QTreeWidget.EditTrigger.DoubleClicked | QTreeWidget.EditTrigger.EditKeyPressed
        )
        theme_manager.apply_style(
            self._tree,
            "QTreeWidget { background: {BG_DARKEST}; color: {FG_PRIMARY};"
            " border: 1px solid {BORDER}; border-radius: 4px; }"
            " QHeaderView::section { background: {BG_DARK}; color: {FG_SECONDARY};"
            " border: none; padding: 4px; }",
        )
        self._tree.itemChanged.connect(lambda _item, _col: self.changed.emit())
        layout.addWidget(self._tree)
        layout.addWidget(
            BioCaptionLabel(
                "Double-click to edit. Markers: “CD3+”, “CD4+ CD8−”, “CD45lo” (two at most); "
                "“scatter” and “singlets” are the usual Cells and Singlets gates."
            )
        )
        layout.addLayout(self._buttons())
        self.set_template(STARTER)

    def _buttons(self) -> QGridLayout:
        grid = QGridLayout()
        grid.setSpacing(6)
        for i, (text, tip, slot) in enumerate(
            (
                ("+ Beside", "Add a population beside the selected one.", self._add_sibling),
                ("+ Inside", "Add a population inside the selected one.", self._add_child),
                ("Remove", "Remove the selected population and those inside it.", self._remove),
                ("Load…", "Open a saved template.", self._load),
                ("Save…", "Save this template to reuse it.", self._save),
            )
        ):
            button = SecondaryButton(text)
            button.setToolTip(tip)
            button.clicked.connect(slot)
            grid.addWidget(button, i // BUTTONS_PER_ROW, i % BUTTONS_PER_ROW)
        return grid

    # ── The template ──────────────────────────────────────────────────

    def template(self) -> GatingTemplate | str:
        """The template as written, or what needs fixing first."""
        steps: list[TemplateStep] = []

        def walk(item: QTreeWidgetItem | None, parent_id: str | None) -> str | None:
            if item is None:
                return None
            name = item.text(0).strip() or NEW_NAME
            parsed = parse_calls(item.text(1))
            if isinstance(parsed, str):
                return f"{name}: {parsed}"
            step_id = str(item.data(0, ID_ROLE))
            steps.append(TemplateStep(step_id, name, parent_id, *parsed))
            for i in range(item.childCount()):
                problem = walk(item.child(i), step_id)
                if problem:
                    return problem
            return None

        for i in range(self._tree.topLevelItemCount()):
            problem = walk(self._tree.topLevelItem(i), None)
            if problem:
                return problem
        return GatingTemplate(self._name, tuple(steps))

    def set_template(self, template: GatingTemplate) -> None:
        self._name = template.name
        self._tree.blockSignals(True)
        self._tree.clear()
        items: dict[str, QTreeWidgetItem] = {}
        for step in template.ordered():
            parent = items.get(step.parent_id) if step.parent_id else None
            items[step.step_id] = self._item(step.name, step.calls_text, parent, step.step_id)
        self._tree.expandAll()
        self._tree.blockSignals(False)
        self.changed.emit()

    def _item(
        self, name: str, markers: str, parent: QTreeWidgetItem | None, step_id: str = ""
    ) -> QTreeWidgetItem:
        item = QTreeWidgetItem([name, markers])
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        item.setData(0, ID_ROLE, step_id or f"step{next(self._ids)}")
        if parent is None:
            self._tree.addTopLevelItem(item)
        else:
            parent.addChild(item)
            parent.setExpanded(True)
        return item

    # ── Buttons ───────────────────────────────────────────────────────

    def _add_sibling(self) -> None:
        current = self._tree.currentItem()
        self._add(current.parent() if current is not None else None)

    def _add_child(self) -> None:
        self._add(self._tree.currentItem())

    def _add(self, parent: QTreeWidgetItem | None) -> None:
        item = self._item(NEW_NAME, "", parent)
        self._tree.setCurrentItem(item)
        self._tree.editItem(item, 0)
        self.changed.emit()

    def _remove(self) -> None:
        item = self._tree.currentItem()
        if item is None:
            return
        parent = item.parent()
        if parent is None:
            self._tree.takeTopLevelItem(self._tree.indexOfTopLevelItem(item))
        else:
            parent.removeChild(item)
        self.changed.emit()

    def _load(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open gating template", "", FILE_FILTER)
        if not path:
            return
        try:
            template = GatingTemplate.from_dict(json.loads(Path(path).read_text()))
        except (OSError, ValueError, KeyError) as exc:
            self.problem.emit(f"Couldn't open {Path(path).name}: {exc}")
            return
        self.set_template(template)

    def _save(self) -> None:
        template = self.template()
        if isinstance(template, str):
            self.problem.emit(f"Fix the template before saving it. {template}")
            return
        path = get_save_path(self, "Save gating template", f"{template.name}.json", FILE_FILTER)
        if path:
            Path(path).write_text(json.dumps(template.to_dict(), indent=2))
