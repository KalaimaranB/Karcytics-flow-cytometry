"""The sample's populations as an indented list: a gating tree that fits a sidebar.

Final populations (the ones the lens judges) are bold; UMAP exports and
logic nodes, which it leaves out, are italic (a font, because the SDK list's
stylesheet sets every row's colour).
"""

from __future__ import annotations

from karcytics_sdk.plugin.components import BioListWidget
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QListWidgetItem

from ....analysis.experiment import Sample
from ....analysis.population_matching import PATH_SEP, populations
from ....analysis.sample_lens.scope import is_cluster_population

INDENT = "\u2003"  # an em space per level


class PopulationList(BioListWidget):
    population_clicked = Signal(object)  # node_id

    def __init__(self) -> None:
        super().__init__()
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.setSpacing(2)
        self.itemClicked.connect(
            lambda item: self.population_clicked.emit(item.data(Qt.ItemDataRole.UserRole))
        )

    def show_populations(
        self, sample: Sample | None, final_paths: set[str], selected_id: str | None
    ) -> None:
        self.clear()
        if sample is None:
            return
        for path, node in populations(sample):
            item = QListWidgetItem(INDENT * path.count(PATH_SEP) + (node.name or "Unnamed"))
            item.setData(Qt.ItemDataRole.UserRole, node.node_id)
            item.setToolTip(path)
            font = QFont(item.font())
            font.setBold(path in final_paths)
            font.setItalic(node.is_logic_node or is_cluster_population(node))
            item.setFont(font)
            self.addItem(item)
            if node.node_id == selected_id:
                self.setCurrentItem(item)
