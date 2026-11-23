"""PopulationSelectionPopup — interactive population×sample picker.

Replaces `PopulationTreeWidget`'s Shared/Sample-Specific tree with a grid:
rows = populations, columns = currently-checked samples, every cell
independently checkable. A population unique to one sample simply has
blank/disabled cells in every other column — that fact alone communicates
"only applies here," so there's no separate "Sample-Specific" section to
explain, and picking population A for sample 1 and population B for sample
2 (impossible in the old tree without a per-row hack) is just two clicks.

Built on `FloatingGridPopup`/`BranchLabel`
(`ui/widgets/gate_hierarchy/floating_grid_popup.py`) — the same shell and
row-label rendering the read-only "Quick Stats" popup
(`ui/widgets/gate_hierarchy/all_samples_popup.py`) uses, so this doesn't
duplicate that popup's chrome. The checked cells and the rules for changing
them are `analysis/population_selection.py`'s `PopulationSelection`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from karcytics_sdk.plugin.components import SecondaryButton
from karcytics_sdk.plugin.theme_fallback import Colors, theme_manager
from PySide6.QtCore import QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLineEdit, QVBoxLayout, QWidget

from karcytics_plugins.flow_cytometry.analysis.population_matching import PopulationRow
from karcytics_plugins.flow_cytometry.analysis.population_selection import PopulationSelection
from karcytics_plugins.flow_cytometry.ui.widgets.gate_hierarchy.floating_grid_popup import (
    FloatingGridPopup,
)

if TYPE_CHECKING:
    from karcytics_plugins.flow_cytometry.analysis.experiment import Sample


class PopulationSelectionPopup(FloatingGridPopup):
    """Floating popup for picking exactly which (sample, population) pairs
    to include — see module docstring. The checked cells and their rules
    are ``selection`` (a Qt-free ``PopulationSelection``); this draws them.

    Signals:
        selectionChanged: emitted whenever the checked set changes (user
            toggle, All/None, refresh(), or a multi/single-select switch).
    """

    selectionChanged = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        self.selection = PopulationSelection()
        self._samples: dict[str, Sample] = {}
        self._search_text = ""
        self._cell_widgets: dict[tuple[str, str], _ToggleCell] = {}
        super().__init__(
            parent,
            object_name="PopulationSelectionPopup",
            title_text="🔲  Select Populations",
            size=(720, 480),
            dismiss_on_outside_click=True,
        )

    # ── Public API ──

    def refresh(self, samples: dict[str, Sample]) -> None:
        """Rebuild the grid for every experiment sample, keeping the checks made.

        Every sample is a column: which samples end up included is just
        which columns have checked cells.
        """
        self._samples = samples
        self.selection.refresh(samples)
        self._changed()

    def get_checked_populations(self) -> list[tuple[str, str | None, str]]:
        """(sample_id, node_id, label) per checked cell, in grid order: rows, then samples."""
        return self.selection.checked_populations()

    def check_all(self, checked: bool) -> None:
        if self.selection.check_all(checked):
            self._changed()

    def set_multi_select(self, enabled: bool) -> None:
        """Switch between unrestricted multi-select and one-per-sample mode."""
        if self.selection.set_multi_select(enabled):
            self._changed()

    def set_single_sample_mode(self, enabled: bool) -> None:
        """Keep checks in at most one sample's column (Pseudocolor Overlay)."""
        if self.selection.set_single_sample(enabled):
            self._changed()

    def summary_text(self) -> str:
        return self.selection.summary(
            {sid: sample.display_name for sid, sample in self._samples.items()}
        )

    # ── UI ───────────────────────────────────────────────────────────

    def _build_toolbar(self) -> QWidget | None:
        container = QWidget()
        self._toolbar = container
        theme_manager.apply_style(
            container, "background: {BG_DARK}; border-bottom: 1px solid {BORDER};"
        )
        outer = QVBoxLayout(container)
        outer.setContentsMargins(14, 8, 14, 8)
        outer.setSpacing(6)

        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText("Search populations...")
        theme_manager.apply_style(
            self._search_box,
            "QLineEdit { background: {BG_MEDIUM}; color: {FG_PRIMARY};"
            " border: 1px solid {BORDER}; border-radius: 4px; padding: 4px 8px; }",
        )
        self._search_box.textChanged.connect(self._on_search_changed)
        outer.addWidget(self._search_box)

        btn_row = QHBoxLayout()
        mini_ss = "QPushButton { padding: 3px 10px; min-height: 26px; }"
        btn_all = SecondaryButton("All")
        btn_all.setStyleSheet(mini_ss)
        btn_all.clicked.connect(lambda: self.check_all(True))
        btn_none = SecondaryButton("None")
        btn_none.setStyleSheet(mini_ss)
        btn_none.clicked.connect(lambda: self.check_all(False))
        btn_row.addWidget(btn_all)
        btn_row.addWidget(btn_none)
        btn_row.addStretch()
        outer.addLayout(btn_row)

        return container

    def _on_search_changed(self, text: str) -> None:
        self._search_text = text.strip().lower()
        self._rebuild_grid()

    def _changed(self) -> None:
        self._rebuild_grid()
        self.selectionChanged.emit()

    def _rebuild_grid(self) -> None:
        selection = self.selection
        needle = self._search_text
        visible = [
            r
            for r in selection.rows
            if not needle or needle in r.row.name.lower() or needle in r.label_path.lower()
        ]
        by_id = {id(r.row): r for r in visible}
        self._cell_widgets = {}

        def cell_factory(prow: PopulationRow, sid: str, col_w: int) -> QWidget:
            label = by_id[id(prow)].label_path
            enabled = selection.applies(sid, label)
            cell = _ToggleCell(
                checked=enabled and selection.is_checked(sid, label),
                enabled=enabled,
                col_width=col_w,
                sample_id=sid,
                label=label,
                controller=self if enabled else None,
            )
            self._cell_widgets[(sid, label)] = cell
            return cell

        def row_click_factory(prow: PopulationRow):
            # One population across several columns makes no sense in one-sample
            # mode: no affordance rather than one that breaks it.
            if selection.single_sample:
                return None
            label = by_id[id(prow)].label_path
            if not any(selection.applies(sid, label) for sid in selection.sample_ids):
                return None
            return lambda: self._row_clicked(label)

        display_names = {
            sid: self._samples[sid].display_name
            for sid in selection.sample_ids
            if sid in self._samples
        }
        highlighted: set[str] | None = None
        if selection.single_sample:
            shown = selection.shown_sample()
            highlighted = {shown} if shown is not None else set()
        header_clicks = selection.multi_select or selection.single_sample
        self._populate_grid(
            [r.row for r in visible],
            selection.sample_ids,
            display_names,
            cell_factory=cell_factory,
            row_click_factory=row_click_factory,
            on_header_clicked=self._header_clicked if header_clicks else None,
            highlighted_sample_ids=highlighted,
            empty_message=(
                "No populations match your search." if needle else "No populations to select."
            ),
        )

    def _row_clicked(self, label: str) -> None:
        self._clicked(self.selection.toggle_row(label))

    def _header_clicked(self, sid: str) -> None:
        self._clicked(self.selection.toggle_column(sid))

    def _clicked(self, changed: bool) -> None:
        if changed:
            self._changed()

    # ── Drag-select (called by `_ToggleCell`) ───────────────────────────

    def _begin_cell_drag(self, sid: str, label: str) -> None:
        self._repaint_dragged(sid, label, self.selection.begin_drag(sid, label))

    def _drag_enter_cell(self, sid: str, label: str) -> None:
        self._repaint_dragged(sid, label, self.selection.drag_over(sid, label))

    def _end_cell_drag(self) -> None:
        # A full rebuild reconciles what a cell repaint can't reach.
        self._clicked(self.selection.end_drag())

    def _repaint_dragged(self, sid: str, label: str, changed: bool) -> None:
        if not changed:
            return
        if (cell := self._cell_widgets.get((sid, label))) is not None:
            cell.set_checked(self.selection.is_checked(sid, label))
        self.selectionChanged.emit()


class _ToggleCell(QWidget):
    """One selectable cell: rounded swatch, click toggles. Visually matches
    `all_samples_popup._HeatCell`'s sizing/shape but shows a checkmark
    instead of a painted percentage.

    A single click and a drag-select are the same gesture at different
    lengths: pressing grabs the mouse and tells `controller` a drag began
    (which also flips this cell); every subsequent move event hit-tests
    whatever `_ToggleCell` is currently under the cursor — possibly a
    sibling, since the grab keeps delivering move events to the pressed
    widget regardless of pointer position — and forwards it to the
    controller so it can paint that cell to the drag's target state.
    """

    def __init__(
        self,
        *,
        checked: bool,
        enabled: bool,
        col_width: int = 64,
        sample_id: str = "",
        label: str = "",
        controller=None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._checked = checked
        self._enabled = enabled
        self._sample_id = sample_id
        self._label = label
        self._controller = controller
        self.setFixedSize(col_width, 30)
        if enabled and controller is not None:
            self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_checked(self, checked: bool) -> None:
        if checked != self._checked:
            self._checked = checked
            self.update()

    def mousePressEvent(self, event: QMouseEvent | None) -> None:
        if (
            self._enabled
            and self._controller is not None
            and event is not None
            and event.button() == Qt.MouseButton.LeftButton
        ):
            self._controller._begin_cell_drag(self._sample_id, self._label)
            self.grabMouse()
        elif event is not None:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent | None) -> None:
        if event is None or self._controller is None:
            return
        widget = QApplication.widgetAt(event.globalPosition().toPoint())
        if isinstance(widget, _ToggleCell) and widget._enabled:
            self._controller._drag_enter_cell(widget._sample_id, widget._label)

    def mouseReleaseEvent(self, event: QMouseEvent | None) -> None:
        if self._controller is not None:
            self.releaseMouse()
            self._controller._end_cell_drag()
        elif event is not None:
            super().mouseReleaseEvent(event)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        path = QPainterPath()
        path.addRoundedRect(QRectF(1, 1, self.width() - 2, self.height() - 2), 4, 4)

        if not self._enabled:
            fill = QColor(Colors.BG_MEDIUM)
            text_color = QColor(Colors.FG_DISABLED)
            label = "—"
        elif self._checked:
            fill = QColor(Colors.ACCENT_PRIMARY)
            text_color = QColor("#ffffff")
            label = "✓"
        else:
            fill = QColor(Colors.BG_DARK)
            text_color = QColor(Colors.FG_DISABLED)
            label = ""

        painter.fillPath(path, fill)
        if self._enabled and not self._checked:
            pen = QPen(QColor(Colors.BORDER))
            pen.setWidth(1)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)

        font = QFont("Inter, sans-serif", 11)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(text_color)
        painter.drawText(
            QRect(0, 0, self.width(), self.height()),
            Qt.AlignmentFlag.AlignCenter,
            label,
        )
        painter.end()
