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
duplicate that popup's chrome. Row order/branch-connector computation comes
from `analysis/population_matching.py`'s `build_row_order()`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from karcytics_sdk.plugin.theme_fallback import Colors
from PyQt6.QtCore import QRect, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QApplication, QHBoxLayout, QLineEdit, QVBoxLayout, QWidget

from karcytics_plugins.flow_cytometry.analysis.population_matching import (
    ALL_EVENTS_LABEL,
    PopulationGroups,
    PopulationRow,
    PopulationSelectionRow,
    build_row_order,
    compute_population_groups,
)
from karcytics_plugins.flow_cytometry.ui.widgets.gate_hierarchy.floating_grid_popup import (
    FloatingGridPopup,
)

if TYPE_CHECKING:
    from karcytics_plugins.flow_cytometry.analysis.experiment import Sample


class PopulationSelectionPopup(FloatingGridPopup):
    """Floating popup for picking exactly which (sample, population) pairs
    to include — see module docstring.

    Signals:
        selectionChanged: emitted whenever the checked set changes (user
            toggle, All/None, refresh(), or a multi/single-select switch).
    """

    selectionChanged = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        self._samples: dict[str, Sample] = {}
        self._sample_ids: list[str] = []
        self._groups = PopulationGroups()
        self._rows: list[PopulationSelectionRow] = []

        # Flat (sample_id, label_path) pairs — replaces the old tree's
        # shared/per-sample-override/exclusion buckets entirely.
        self._checked: set[tuple[str, str]] = set()
        self._known: set[tuple[str, str]] = set()

        # Sample checklist toggles, tab switches, and a gate that finishes
        # propagating late all trigger another refresh() long after the
        # popup first opened — before this flag existed, any (sample,
        # population) pair that simply hadn't been *seen* yet at that point
        # (e.g. a gate that propagated onto a sample after the user had
        # already clicked None and hand-picked a couple of populations) got
        # silently auto-checked on that later refresh, with no click behind
        # it. Once the user has touched the picker at all, later refreshes
        # must leave newly-discovered pairs unchecked instead.
        self._user_has_interacted = False

        self._multi_select = True
        # Mirror image of `_multi_select`: that governs how many populations
        # per sample *column* can be checked; this governs how many sample
        # *columns* can have any checked population at all. Only "🌈
        # Pseudocolor Overlay" (Comparisons) needs it — that renderer only
        # ever draws one sample's own populations.
        self._single_sample_mode = False
        self._search_text = ""

        # Drag-select state: press-and-drag across cells paints them all to
        # the same target state (the opposite of whatever the press-started
        # cell's state was), so a vertical or horizontal drag selects — or,
        # started on a checked cell, deselects — every cell it crosses.
        self._cell_widgets: dict[tuple[str, str], _ToggleCell] = {}
        self._drag_active = False
        self._drag_target_checked = False
        self._drag_visited: set[tuple[str, str]] = set()

        super().__init__(
            parent,
            object_name="PopulationSelectionPopup",
            title_text="🔲  Select Populations",
            size=(720, 480),
            dismiss_on_outside_click=True,
        )

    # ── Public API (mirrors the old PopulationTreeWidget's surface) ────

    def refresh(self, samples: dict[str, Sample]) -> None:
        """Recompute rows for every experiment sample and redraw.

        Every sample is always shown as a column — there's no separate
        sample checklist gating this anymore; which samples end up
        "included" is purely a function of which columns have checked
        cells (see `get_checked_sample_ids()`).
        """
        self._samples = samples
        self._sample_ids = list(samples.keys())
        self._groups = compute_population_groups([samples[sid] for sid in self._sample_ids])
        self._rows = build_row_order(self._groups)

        # New (sample, population) pairs default to checked the first time
        # they're seen; afterwards the user's own check state is preserved
        # across refreshes. In one-per-sample-column mode, only All Events
        # gets this default; in single-sample mode, only the first sample
        # column gets it (checking All Events for every sample would leave
        # more than one sample "active" before the user's touched anything).
        for sid in self._sample_ids:
            node_idx = self._groups.node_index.get(sid, {})
            for row in self._rows:
                if row.label_path not in node_idx:
                    continue
                key = (sid, row.label_path)
                if key in self._known:
                    continue
                self._known.add(key)
                if self._user_has_interacted:
                    continue
                if self._single_sample_mode:
                    if sid == self._sample_ids[0] and row.label_path == ALL_EVENTS_LABEL:
                        self._checked.add(key)
                elif self._multi_select or row.label_path == ALL_EVENTS_LABEL:
                    self._checked.add(key)

        self._rebuild_grid()
        self.selectionChanged.emit()

    def _active_sample_id(self) -> str | None:
        """The one sample with any checked cell — meaningful only while
        `_single_sample_mode` is on, where at most one ever has checks.
        """
        for sid, _label in self._checked:
            return sid
        return None

    def get_checked_populations(self) -> list[tuple[str, str | None, str]]:
        """Return (sample_id, node_id, label) triples for every checked cell."""
        result: list[tuple[str, str | None, str]] = []
        for sid, label in self._checked:
            node_idx = self._groups.node_index.get(sid, {})
            if label in node_idx:
                result.append((sid, node_idx[label], label))
        return result

    def check_all(self, checked: bool) -> None:
        self._user_has_interacted = True
        if not checked:
            self._checked = set()
        elif self._single_sample_mode:
            sid = self._active_sample_id() or (self._sample_ids[0] if self._sample_ids else None)
            self._checked = self._all_populations_for_sample(sid) if sid is not None else set()
        elif self._multi_select:
            self._checked = {
                (sid, row.label_path)
                for sid in self._sample_ids
                for row in self._rows
                if row.label_path in self._groups.node_index.get(sid, {})
            }
        else:
            self._checked = {
                (sid, ALL_EVENTS_LABEL)
                for sid in self._sample_ids
                if ALL_EVENTS_LABEL in self._groups.node_index.get(sid, {})
            }
        self._rebuild_grid()
        self.selectionChanged.emit()

    def _all_populations_for_sample(self, sid: str) -> set[tuple[str, str]]:
        if self._multi_select:
            return {
                (sid, row.label_path)
                for row in self._rows
                if row.label_path in self._groups.node_index.get(sid, {})
            }
        if ALL_EVENTS_LABEL in self._groups.node_index.get(sid, {}):
            return {(sid, ALL_EVENTS_LABEL)}
        return set()

    def set_multi_select(self, enabled: bool) -> None:
        """Switch between unrestricted multi-select and one-per-sample mode."""
        if enabled == self._multi_select:
            return
        self._multi_select = enabled
        if enabled:
            # Every pair checked in one-per-sample mode is still valid
            # once multi-select opens up, so it never needs to change here.
            # Only auto-fill the "every population defaults to checked"
            # pairs (catching up ones discovered while radio mode
            # suppressed that default) while the user hasn't made a
            # deliberate choice yet — once they have, unioning in every
            # known population would silently flood a hand-picked
            # selection with populations they never checked (e.g.
            # switching a plot type from Violin to Channel Heatmap).
            if not self._user_has_interacted:
                new_known = self._known
                if self._single_sample_mode:
                    active = self._active_sample_id() or (
                        self._sample_ids[0] if self._sample_ids else None
                    )
                    new_known = {(s, lbl) for (s, lbl) in new_known if s == active}
                self._checked |= new_known
        else:
            # Collapse to at most one checked cell per column: prefer All
            # Events if it was checked, else keep the first checked pick.
            new_checked: set[tuple[str, str]] = set()
            for sid in self._sample_ids:
                picks = [label for (s, label) in self._checked if s == sid]
                if ALL_EVENTS_LABEL in picks:
                    new_checked.add((sid, ALL_EVENTS_LABEL))
                elif picks:
                    new_checked.add((sid, picks[0]))
            self._checked = new_checked
        self._rebuild_grid()
        self.selectionChanged.emit()

    def set_single_sample_mode(self, enabled: bool) -> None:
        """Restrict to at most one sample column having any checked
        population — the sole mechanism enforcing "exactly one sample" for
        plot types like Pseudocolor Overlay, which only ever renders one
        sample's own populations.
        """
        if enabled == self._single_sample_mode:
            return
        self._single_sample_mode = enabled
        if enabled:
            if self._user_has_interacted:
                # Keep whichever sample the user's own picks were actually
                # richest for — e.g. Sample C with both B-cells and UMAP B
                # Cells checked should survive over Sample A with only
                # B-cells, not just "whichever sample sorts first."
                counts: dict[str, int] = {}
                for s, _l in self._checked:
                    counts[s] = counts.get(s, 0) + 1
                keep = max(
                    (sid for sid in self._sample_ids if sid in counts),
                    key=lambda sid: counts[sid],
                    default=None,
                )
            else:
                # `_active_sample_id()` isn't reliable here: multiple
                # samples can still have checks at this exact moment
                # (single-sample mode isn't enforced yet), and picking
                # arbitrarily among them would make the "which sample
                # survives" outcome depend on set iteration order.
                # Deterministically prefer the first sample (in
                # `_sample_ids` order) that currently has any checks.
                checked_sids = {s for s, _l in self._checked}
                keep = next((sid for sid in self._sample_ids if sid in checked_sids), None)
            if keep is None and self._sample_ids:
                keep = self._sample_ids[0]
            if keep is None:
                self._checked = set()
            elif self._user_has_interacted:
                # Keep exactly what the user already checked for the
                # surviving sample — don't flood in every population for
                # it just because the mode switch needs to drop every
                # other sample.
                self._checked = {(s, lbl) for (s, lbl) in self._checked if s == keep}
            else:
                self._checked = self._all_populations_for_sample(keep)
        else:
            # There's no separate sample checklist to re-check other
            # samples with once a single-sample plot type freed them back
            # up — bring every sample but the one that was active back to
            # the same "start checked" default a fresh refresh() gives it,
            # so switching to a multi-sample plot type doesn't silently
            # strand every sample except whichever one Pseudocolor picked.
            # Unlike entering single-sample mode above, this always
            # restores every other sample regardless of interaction — with
            # no separate sample checklist, "leave the freed-up samples
            # stranded unchecked forever" isn't a reasonable alternative,
            # and the surviving sample's own population picks (the part
            # that matters for `_user_has_interacted`) are untouched here.
            active = self._active_sample_id()
            for sid in self._sample_ids:
                if sid != active:
                    self._checked |= self._all_populations_for_sample(sid)
        self._rebuild_grid()
        self.selectionChanged.emit()

    def summary_text(self) -> str:
        if self._single_sample_mode:
            active = self._active_sample_id()
            if active is None:
                return "No sample selected."
            name = self._samples[active].display_name if active in self._samples else active
            return f"Comparing within {name} — click another sample's column header to switch."
        n_checked = len({(sid, label) for sid, label in self._checked if sid in self._sample_ids})
        n_available = sum(
            1
            for sid in self._sample_ids
            for row in self._rows
            if row.label_path in self._groups.node_index.get(sid, {})
        )
        return f"{n_checked} of {n_available} population picks selected"

    # ── UI ───────────────────────────────────────────────────────────

    def _build_toolbar(self) -> QWidget | None:
        from karcytics_sdk.plugin.components import SecondaryButton

        container = QWidget()
        self._toolbar = container
        outer = QVBoxLayout(container)
        outer.setContentsMargins(14, 8, 14, 8)
        outer.setSpacing(6)

        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText("Search populations...")
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

    def _apply_theme_styles(self) -> None:
        super()._apply_theme_styles()
        if hasattr(self, "_toolbar"):
            self._toolbar.setStyleSheet(
                f"background: {Colors.BG_DARK}; border-bottom: 1px solid {Colors.BORDER};"
            )
        if hasattr(self, "_search_box"):
            self._search_box.setStyleSheet(
                f"QLineEdit {{ background: {Colors.BG_MEDIUM}; color: {Colors.FG_PRIMARY};"
                f" border: 1px solid {Colors.BORDER}; border-radius: 4px; padding: 4px 8px; }}"
            )

    def _on_search_changed(self, text: str) -> None:
        self._search_text = text.strip().lower()
        self._rebuild_grid()

    def _rebuild_grid(self) -> None:
        needle = self._search_text
        visible = [
            r
            for r in self._rows
            if not needle or needle in r.row.name.lower() or needle in r.label_path.lower()
        ]
        by_id = {id(r.row): r for r in visible}
        self._cell_widgets = {}

        def cell_factory(prow: PopulationRow, sid: str, col_w: int) -> QWidget:
            sel_row = by_id[id(prow)]
            label = sel_row.label_path
            enabled = label in self._groups.node_index.get(sid, {})
            checked = enabled and (sid, label) in self._checked
            cell = _ToggleCell(
                checked=checked,
                enabled=enabled,
                col_width=col_w,
                sample_id=sid,
                label=label,
                controller=self if enabled else None,
            )
            self._cell_widgets[(sid, label)] = cell
            return cell

        def row_click_factory(prow: PopulationRow):
            if self._single_sample_mode:
                # Checking one population across multiple sample columns is
                # incoherent in this mode — hide the affordance rather than
                # leave a control that would immediately violate it.
                return None
            sel_row = by_id[id(prow)]
            applicable = any(
                sel_row.label_path in self._groups.node_index.get(sid, {})
                for sid in self._sample_ids
            )
            if not applicable:
                return None
            return lambda sr=sel_row: self._toggle_row(sr)

        display_names = {
            sid: self._samples[sid].display_name for sid in self._sample_ids if sid in self._samples
        }
        highlighted: set[str] | None = None
        if self._single_sample_mode:
            active = self._active_sample_id() or (self._sample_ids[0] if self._sample_ids else None)
            highlighted = {active} if active is not None else set()
        self._populate_grid(
            [r.row for r in visible],
            self._sample_ids,
            display_names,
            cell_factory=cell_factory,
            row_click_factory=row_click_factory,
            on_header_clicked=(
                self._toggle_column if (self._multi_select or self._single_sample_mode) else None
            ),
            highlighted_sample_ids=highlighted,
            empty_message=(
                "No populations match your search." if needle else "No populations to select."
            ),
        )

    # ── Toggle handlers ──────────────────────────────────────────────

    def _set_cell_checked(self, sid: str, label: str, checked: bool) -> bool:
        """Set one cell's checked state, respecting single-select-per-column
        mode and single-sample mode. Returns True if the checked set
        actually changed.
        """
        key = (sid, label)
        if label not in self._groups.node_index.get(sid, {}):
            return False
        if checked == (key in self._checked):
            return False
        if checked:
            if not self._multi_select:
                self._checked = {(s, lbl) for (s, lbl) in self._checked if s != sid}
            if self._single_sample_mode:
                self._checked = {(s, lbl) for (s, lbl) in self._checked if s == sid}
            self._checked.add(key)
        else:
            self._checked.discard(key)
        return True

    def _toggle_cell(self, sid: str, label: str) -> None:
        self._user_has_interacted = True
        target = (sid, label) not in self._checked
        if self._set_cell_checked(sid, label, target):
            self._rebuild_grid()
            self.selectionChanged.emit()

    def _toggle_row(self, sel_row: PopulationSelectionRow) -> None:
        self._user_has_interacted = True
        label = sel_row.label_path
        applicable = [
            sid for sid in self._sample_ids if label in self._groups.node_index.get(sid, {})
        ]
        if not applicable:
            return
        if self._multi_select:
            all_checked = all((sid, label) in self._checked for sid in applicable)
            for sid in applicable:
                if all_checked:
                    self._checked.discard((sid, label))
                else:
                    self._checked.add((sid, label))
        else:
            # Sets this row as the pick for every applicable sample,
            # clearing whatever each of those samples had picked before.
            self._checked = {(s, lbl) for (s, lbl) in self._checked if s not in applicable}
            for sid in applicable:
                self._checked.add((sid, label))
        self._rebuild_grid()
        self.selectionChanged.emit()

    def _toggle_column(self, sid: str) -> None:
        self._user_has_interacted = True
        if self._single_sample_mode:
            # The header click is "make this the active sample," not a
            # toggle — there's always exactly one active sample once this
            # mode is on, so clicking the already-active one is a no-op.
            if self._active_sample_id() == sid:
                return
            self._checked = self._all_populations_for_sample(sid)
            self._rebuild_grid()
            self.selectionChanged.emit()
            return

        applicable = [
            row.label_path
            for row in self._rows
            if row.label_path in self._groups.node_index.get(sid, {})
        ]
        if not applicable:
            return
        all_checked = all((sid, label) in self._checked for label in applicable)
        for label in applicable:
            if all_checked:
                self._checked.discard((sid, label))
            else:
                self._checked.add((sid, label))
        self._rebuild_grid()
        self.selectionChanged.emit()

    # ── Drag-select (called by `_ToggleCell`) ───────────────────────────

    def _begin_cell_drag(self, sid: str, label: str) -> None:
        """A press on a cell starts a drag: every further cell the mouse
        crosses while the button stays down gets painted to the same target
        state as this first cell would flip to (checked→unchecked cells
        deselect the whole path; unchecked→checked cells select it).
        """
        self._user_has_interacted = True
        self._drag_active = True
        self._drag_target_checked = (sid, label) not in self._checked
        self._drag_visited = set()
        self._apply_drag_cell(sid, label)

    def _drag_enter_cell(self, sid: str, label: str) -> None:
        if self._drag_active:
            self._apply_drag_cell(sid, label)

    def _end_cell_drag(self) -> None:
        if not self._drag_active:
            return
        self._drag_active = False
        # Full rebuild reconciles anything a direct cell repaint can't
        # reach (e.g. row/column click-to-toggle-all state).
        self._rebuild_grid()
        self.selectionChanged.emit()

    def _apply_drag_cell(self, sid: str, label: str) -> None:
        key = (sid, label)
        if key in self._drag_visited:
            return
        self._drag_visited.add(key)
        if self._set_cell_checked(sid, label, self._drag_target_checked):
            cell = self._cell_widgets.get(key)
            if cell is not None:
                cell.set_checked(self._drag_target_checked)
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

    def mousePressEvent(self, event: QMouseEvent | None) -> None:  # noqa: N802
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

    def mouseMoveEvent(self, event: QMouseEvent | None) -> None:  # noqa: N802
        if event is None or self._controller is None:
            return
        widget = QApplication.widgetAt(event.globalPosition().toPoint())
        if isinstance(widget, _ToggleCell) and widget._enabled:
            self._controller._drag_enter_cell(widget._sample_id, widget._label)

    def mouseReleaseEvent(self, event: QMouseEvent | None) -> None:  # noqa: N802
        if self._controller is not None:
            self.releaseMouse()
            self._controller._end_cell_drag()
        elif event is not None:
            super().mouseReleaseEvent(event)

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        path = QPainterPath()
        path.addRoundedRect(QRectF(1, 1, self.width() - 2, self.height() - 2), 4, 4)

        if not self._enabled:
            fill = QColor("#21262d")
            text_color = QColor("#484f58")
            label = "—"
        elif self._checked:
            fill = QColor(Colors.ACCENT_PRIMARY)
            text_color = QColor("#ffffff")
            label = "✓"
        else:
            fill = QColor("#1a2030")
            text_color = QColor("#484f58")
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
