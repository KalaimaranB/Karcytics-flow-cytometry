"""The reference sample's real gating tree, with a proposal's populations shown under their parent.

The tree is the one source of truth for gates: this only reads it. Proposed
populations are not in it until accepted, so they are drawn italic and
marked "proposed".
"""

from __future__ import annotations

from karcytics_sdk.plugin.components import BioCaptionLabel, BioListWidget, SecondaryButton
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QListWidgetItem, QVBoxLayout, QWidget

from ....analysis.experiment import Sample
from ....analysis.population_matching import ALL_EVENTS_LABEL, PATH_SEP, populations
from ....main_tabs import MainTab
from ..panel_style import section_header

PANEL_MIN_WIDTH, PANEL_MAX_WIDTH = 220, 290
INDENT = " "  # an em space per level
_PROPOSED = "proposed"
_NAME_ROLE = Qt.ItemDataRole.UserRole
_PARENT_ROLE = Qt.ItemDataRole.UserRole + 1


def population_items(sample: Sample | None) -> list[tuple[str, str | None]]:
    """(indented name, node id) for every population, All Events first."""
    if sample is None:
        return []
    items: list[tuple[str, str | None]] = [(ALL_EVENTS_LABEL, None)]
    for path, node in populations(sample):
        items.append((INDENT * (path.count(PATH_SEP) + 1) + (node.name or "Unnamed"), node.node_id))
    return items


class GatingTreePanel(QWidget):
    population_clicked = Signal(str, str)  # population name, its parent's name
    open_tab_requested = Signal(object)  # MainTab

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(PANEL_MIN_WIDTH)
        self.setMaximumWidth(PANEL_MAX_WIDTH)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 16, 16, 16)
        layout.setSpacing(8)
        layout.addWidget(
            section_header(
                "Gating tree",
                "The group's real gating tree. Accepted auto gates are ordinary gates: edit, "
                "rename or delete them like any other. Click a population to see why it was gated.",
            )
        )
        self._caption = BioCaptionLabel("")
        layout.addWidget(self._caption)
        self._list = BioListWidget()
        self._list.setObjectName("AutoGateTree")
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self._list.setSpacing(2)
        self._list.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self._list, 1)

        layout.addSpacing(6)
        layout.addWidget(section_header("Elsewhere"))
        lens = SecondaryButton("Check in Sample Lens")
        lens.setToolTip("Audit these gates against a clustering in the Sample Lens tab.")
        lens.clicked.connect(lambda: self.open_tab_requested.emit(MainTab.SAMPLE_LENS))
        gating = SecondaryButton("Open in Gating")
        gating.setToolTip("Show these populations on the Gating tab.")
        gating.clicked.connect(lambda: self.open_tab_requested.emit(MainTab.GATING))
        layout.addWidget(lens)
        layout.addWidget(gating)

    def show_tree(
        self, sample: Sample | None, parent_id: str | None, proposed: tuple[str, ...]
    ) -> None:
        """``sample``'s tree, with ``proposed`` populations under the node ``parent_id``."""
        self._list.clear()
        self._caption.setText(sample.display_name if sample is not None else "No sample loaded")
        ancestors: list[str] = []  # the names on the path to the current row
        for label, node_id in population_items(sample):
            name = label.strip()
            depth = len(label) - len(label.lstrip(INDENT))
            del ancestors[depth:]
            self._add(label, name, ancestors[-1] if ancestors else "")
            ancestors.append(name)
            if node_id == parent_id and proposed:
                for child in proposed:
                    item = self._add(f"{INDENT * (depth + 1)}{child}  · {_PROPOSED}", child, name)
                    font = QFont(item.font())
                    font.setItalic(True)
                    item.setFont(font)

    def _add(self, label: str, name: str, parent: str) -> QListWidgetItem:
        item = QListWidgetItem(label)
        item.setData(_NAME_ROLE, name)
        item.setData(_PARENT_ROLE, parent)
        item.setToolTip(f"{parent} / {name}" if parent else name)
        self._list.addItem(item)
        return item

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        self.population_clicked.emit(item.data(_NAME_ROLE), item.data(_PARENT_ROLE))
