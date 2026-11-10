"""The reference sample's gating tree, drawn like the Gating tab's, with a proposal in it.

The tree is the one source of truth for gates: this only reads it. It lays out
a light mirror of the tree (same node ids, the real gates and statistics) so a
proposal's populations can be drawn under their parent, dashed, without
touching the real tree. Clicking a population picks it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from karcytics_sdk.plugin import ZoomControls
from karcytics_sdk.plugin.components import BioCaptionLabel, BioScrollArea, SecondaryButton
from karcytics_sdk.plugin.theme_fallback import theme_manager
from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import QVBoxLayout, QWidget

from ....analysis.fcs_io import derived_labels_of
from ....analysis.gating.gate_node import GateNode
from ....analysis.population_matching import ALL_EVENTS_LABEL, PATH_SEP, populations
from ....main_tabs import MainTab
from ..gate_hierarchy.node_tree_engine import NodeTreeEngine
from ..gate_hierarchy.sample_view import SampleViewWidget
from ..panel_style import section_header

if TYPE_CHECKING:
    from ....analysis.autogate.models import Region
    from ....analysis.experiment import Sample
    from ....analysis.state import FlowState

PANEL_MIN_WIDTH, PREFERRED_WIDTH, PANEL_MAX_WIDTH = 240, 340, 380
READABLE_SCALE = 0.7  # the tree is fitted to the panel, but never drawn smaller than this
INDENT = " "  # an em space per level
PROPOSED_PREFIX = "proposed:"


def population_items(sample: Sample | None) -> list[tuple[str, str | None]]:
    """(indented name, node id) for every population, All Events first."""
    if sample is None:
        return []
    items: list[tuple[str, str | None]] = [(ALL_EVENTS_LABEL, None)]
    for path, node in populations(sample):
        items.append((INDENT * (path.count(PATH_SEP) + 1) + (node.name or "Unnamed"), node.node_id))
    return items


def _mirror(node: GateNode, copies: dict[str, GateNode]) -> GateNode:
    """A copy of ``node``'s subtree that shares its ids, gates and statistics."""
    if node.node_id in copies:
        return copies[node.node_id]
    copy = GateNode(
        node_id=node.node_id,
        name=node.name,
        gate=node.gate,
        statistics=node.statistics,
        is_logic_node=node.is_logic_node,
        logic_operator=node.logic_operator,
        is_umap_parent=node.is_umap_parent,
    )
    copies[node.node_id] = copy
    for child in node.children:
        if child.is_incomplete:
            continue
        child_copy = _mirror(child, copies)
        child_copy.parents.append(copy)
        copy.children.append(child_copy)
    return copy


class GatingTreePanel(QWidget):
    population_clicked = Signal(object)  # node id (None: All Events)
    open_tab_requested = Signal(object)  # MainTab

    def __init__(self, state: FlowState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = state
        self._engine = NodeTreeEngine()
        self._root_id: str | None = None
        self._focus_id: str | None = None  # the node scrolled into view
        self.setMinimumWidth(PANEL_MIN_WIDTH)
        self.setMaximumWidth(PANEL_MAX_WIDTH)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 16, 16, 16)
        layout.setSpacing(8)
        layout.addWidget(
            section_header(
                "Gating tree",
                "The reference sample's real gating tree. Click a population to split it next, or to "
                "see why an auto gate is where it is. Dashed: proposed, not added yet. Accepted auto "
                "gates are ordinary gates: edit, rename or delete them like any other.",
            )
        )
        self._caption = BioCaptionLabel("")
        layout.addWidget(self._caption)

        self._scroll = BioScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        theme_manager.apply_style(
            self._scroll, "QScrollArea { background: {BG_DARKEST}; border: 1px solid {BORDER}; }"
        )
        self._view = SampleViewWidget(state, editable=False)
        self._view.setObjectName("AutoGateTree")
        self._view.setMinimumSize(120, 120)
        self._view.node_clicked.connect(self._on_node_clicked)
        self._scroll.setWidget(self._view)
        layout.addWidget(self._scroll, 1)
        zoom = ZoomControls(self._view.zoom_in, self._view.zoom_out, self._fit)
        # The panel is narrow: the full labels ("Zoom Out (-)") were clipped to "om Out".
        for button, text, tip in (
            (zoom.zoom_out_button, "−", "Zoom out (-)"),
            (zoom.zoom_in_button, "+", "Zoom in (+)"),
            (zoom.fit_button, "Fit", "Fit the tree to the panel (F)"),
        ):
            button.setText(text)
            button.setToolTip(tip)
        zoom.overlay_on(self._scroll)

        layout.addSpacing(6)
        layout.addWidget(section_header("Elsewhere"))
        lens = SecondaryButton("Check in Sample Lens")
        lens.setToolTip("Audit these gates against a clustering in the Sample Lens tab.")
        lens.clicked.connect(lambda: self.open_tab_requested.emit(MainTab.SAMPLE_LENS))
        gating = SecondaryButton("Open in Gating")
        gating.setToolTip("Show these populations on the Gating tab, where gates can be moved.")
        gating.clicked.connect(lambda: self.open_tab_requested.emit(MainTab.GATING))
        layout.addWidget(lens)
        layout.addWidget(gating)

    def show_tree(
        self,
        sample: Sample | None,
        selected_id: str | None,
        proposed: tuple[Region, ...] = (),
        parent_id: str | None = None,
        parent_events: int = 0,
    ) -> None:
        """``sample``'s tree, ``proposed`` populations dashed under ``parent_id``, ``selected_id`` picked."""
        if sample is None:
            self._caption.setText("No sample loaded")
            self._view.clear()
            return
        self._caption.setText(sample.display_name)
        copies: dict[str, GateNode] = {}
        root = _mirror(sample.gate_tree, copies)
        self._root_id = root.node_id
        parent = copies.get(parent_id) if parent_id else root
        ids = set()
        for i, region in enumerate(proposed):
            node = GateNode(
                node_id=f"{PROPOSED_PREFIX}{i}",
                name=region.name,
                statistics={
                    "pct_parent": 100 * region.fraction,
                    "count": round(region.fraction * parent_events),
                },
                parents=[parent] if parent else [],
            )
            if parent is not None:
                parent.children.append(node)
            ids.add(node.node_id)
        total = sample.fcs_data.num_events if sample.fcs_data is not None else 0
        rects = self._engine.compute(root, total, derived_labels_of(sample.fcs_data))
        for r in rects:
            if r.node_id in ids:
                r.gate_type = "Proposed"
        self._view.set_rects(rects)
        self._view.set_proposed(ids)
        self._view.set_selected(selected_id or root.node_id)
        self._focus_id = selected_id or root.node_id
        QTimer.singleShot(0, self._fit)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt override
        return QSize(PREFERRED_WIDTH, super().sizeHint().height())

    def _fit(self) -> None:
        self._view.fit_view(READABLE_SCALE)
        center = self._view.node_center(self._focus_id) if self._focus_id else None
        if center is not None:  # keep the population being split in view
            self._scroll.ensureVisible(
                center.x(), center.y(), self._scroll.width() // 2, self._scroll.height() // 3
            )

    def _on_node_clicked(self, node_id: str) -> None:
        if node_id.startswith(PROPOSED_PREFIX):
            return
        self.population_clicked.emit(None if node_id == self._root_id else node_id)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        QTimer.singleShot(0, self._fit)
