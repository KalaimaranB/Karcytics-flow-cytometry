"""Grouped population tree shared by the Statistics and Comparisons tabs.

Replaces the old per-sample-duplicated tree (one full nested gate hierarchy
repeated under every checked sample) with two sections:

* "Shared Populations" — populations present under the same name in *every*
  checked sample (the normal result of group gate propagation). Checking one
  applies it to every sample that has it.
* "Sample-Specific" — a collapsed sub-tree per sample for anything that
  doesn't match across all checked samples.

A search box filters both sections by label text, which is what actually
solves the "massive set of populations" scaling problem the grouping alone
doesn't: even within "Shared" or one sample's "Specific" list there can be
many rows.

One-population-per-sample "radio" mode (used by plot types that take exactly
one population per sample, e.g. Violin/FMO in Comparisons) reuses this same
grouped tree rather than a separate flat-per-sample layout, so it gets the
"check one shared row to apply it everywhere" convenience too. The rule that
makes this unambiguous: a "shared" label is by definition present in *every*
currently checked sample, so at most one shared label can ever be checked at
once — it acts as the default pick for every sample. A checked
sample-specific label is a per-sample *override* that takes precedence over
the shared default for that one sample only, leaving every other sample's
pick (shared or otherwise) untouched. See ``get_checked_populations()`` and
``_on_item_changed()`` for where that precedence is applied and enforced.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QTreeWidgetItemIterator,
    QVBoxLayout,
    QWidget,
)

from karcytics_plugins.flow_cytometry.analysis.population_matching import (
    ALL_EVENTS_LABEL,
    PATH_SEP,
    PopulationGroups,
    compute_population_groups,
)
from karcytics_plugins.flow_cytometry.ui.widgets.checkbox_style import checkbox_qss

if TYPE_CHECKING:
    from karcytics_plugins.flow_cytometry.analysis.experiment import Sample

# Sentinel stored in Qt.ItemDataRole.UserRole for non-checkable header/sample
# rows, matching the `False` sentinel already used by the legacy per-sample
# trees this widget replaces.
_HEADER = False
_SHARED_ROLE = "__shared__"


def _get_theme_tokens():
    from karcytics_sdk.plugin.theme_fallback import Colors, theme_manager

    return Colors, theme_manager


def _filter_item(item: QTreeWidgetItem, needle: str) -> bool:
    """Hide rows that don't match `needle` unless a descendant matches. Returns visibility."""
    self_match = (not needle) or (needle in item.text(0).lower())
    child_visible = False
    for c in range(item.childCount()):
        child = item.child(c)
        if child is not None and _filter_item(child, needle):
            child_visible = True
    visible = self_match or child_visible
    item.setHidden(not visible)
    return visible


class PopulationTreeWidget(QWidget):
    """Population checklist: grouped Shared/Sample-Specific tree, with a
    search filter. In multi-select mode any number of populations may be
    checked per sample; in one-per-sample ("radio") mode, checking a shared
    label picks it for every sample and checking a sample-specific label
    overrides just that one sample (see module docstring).

    Signals:
        selectionChanged: emitted whenever the checked-population set changes.
    """

    selectionChanged = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._multi_select = True
        self._samples: dict[str, Sample] = {}
        self._checked_sample_ids: list[str] = []
        self._groups: PopulationGroups = PopulationGroups()

        # Multi-select persistent check state, keyed by label-path.
        self._checked_shared: set[str] = set()
        self._known_shared: set[str] = set()
        self._checked_per_sample: dict[str, set[str]] = {}
        self._known_per_sample: dict[str, set[str]] = {}

        self._search_text = ""

        self._build_ui()
        _, theme_manager = _get_theme_tokens()
        theme_manager.theme_changed.connect(self._apply_theme_styles)
        self.destroyed.connect(self._cleanup)

    def _cleanup(self) -> None:
        _, theme_manager = _get_theme_tokens()
        try:
            theme_manager.theme_changed.disconnect(self._apply_theme_styles)
        except (TypeError, RuntimeError):
            pass

    # ── UI construction ─────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        from karcytics_sdk.plugin.components import SecondaryButton

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText("Search populations...")
        self._search_box.textChanged.connect(self._on_search_changed)
        layout.addWidget(self._search_box)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setMinimumHeight(200)
        layout.addWidget(self.tree)

        btn_row = QHBoxLayout()
        mini_ss = "QPushButton { padding: 3px 10px; min-height: 26px; }"
        self._btn_all = SecondaryButton("All")
        self._btn_all.setStyleSheet(mini_ss)
        self._btn_all.clicked.connect(lambda: self.check_all(True))
        self._btn_none = SecondaryButton("None")
        self._btn_none.setStyleSheet(mini_ss)
        self._btn_none.clicked.connect(lambda: self.check_all(False))
        btn_row.addWidget(self._btn_all)
        btn_row.addWidget(self._btn_none)
        btn_row.addStretch()
        layout.addLayout(btn_row)
        self._update_all_none_visibility()

        self._apply_theme_styles()

    # ── Public API ───────────────────────────────────────────────────────────

    def set_multi_select(self, enabled: bool) -> None:
        """Switch between unrestricted multi-select and one-per-sample mode."""
        if enabled == self._multi_select:
            return
        self._multi_select = enabled
        if enabled:
            self._expand_to_multi_select()
        else:
            self._coerce_to_one_per_sample()
        self._rebuild()
        self._update_all_none_visibility()

    def _coerce_to_one_per_sample(self) -> None:
        """Entering one-per-sample mode: collapse down to at most one shared
        label (preferring "All Events" — the one-per-sample default — over
        an arbitrary carried-over multi-select pick) and clear every
        per-sample override, so every sample falls back to that shared
        default instead of an arbitrary leftover population. Without this, a
        plot type switch (e.g. Heatmap -> Violin) could leave several
        populations checked per sample, violating the very constraint this
        mode exists to enforce.
        """
        if ALL_EVENTS_LABEL in self._checked_shared:
            self._checked_shared = {ALL_EVENTS_LABEL}
        elif len(self._checked_shared) > 1:
            self._checked_shared = {next(iter(self._checked_shared))}
        self._checked_per_sample = {sid: set() for sid in self._checked_per_sample}

    def _expand_to_multi_select(self) -> None:
        """Entering multi-select mode: catch up every label that became
        "known" while one-per-sample mode was active. refresh() only
        defaults a label to checked the first time it's ever seen — while in
        one-per-sample mode that default is deliberately suppressed (see
        refresh()), so a label first discovered during that mode would
        otherwise never get multi-select's "default to checked" treatment
        at all, even after switching modes.
        """
        self._checked_shared |= self._known_shared
        for sid, known in self._known_per_sample.items():
            self._checked_per_sample.setdefault(sid, set()).update(known)

    def _update_all_none_visibility(self) -> None:
        """The "All"/"None" buttons only make sense in multi-select mode — in single-select
        (radio, one population per sample) mode there is no "select all"
        option to offer, since exactly one population per sample is required.
        """
        self._btn_all.setVisible(self._multi_select)
        self._btn_none.setVisible(self._multi_select)

    def refresh(self, samples: dict[str, Sample], checked_sample_ids: list[str]) -> None:
        """Recompute population groups for the checked samples and redraw."""
        self._samples = samples
        self._checked_sample_ids = [sid for sid in checked_sample_ids if sid in samples]
        self._groups = compute_population_groups([samples[sid] for sid in self._checked_sample_ids])

        # New populations default to checked the first time they're seen;
        # afterwards the user's own check state is preserved across refreshes.
        # In one-per-sample mode, only "All Events" (always shared — see
        # ALL_EVENTS_LABEL in population_matching.py) gets this default, since
        # defaulting every newly-seen label to checked would check multiple
        # populations at once, violating the one-per-sample constraint.
        for label in self._groups.shared:
            if label not in self._known_shared:
                self._known_shared.add(label)
                if self._multi_select or label == ALL_EVENTS_LABEL:
                    self._checked_shared.add(label)
        for sid, labels in self._groups.per_sample.items():
            known = self._known_per_sample.setdefault(sid, set())
            checked = self._checked_per_sample.setdefault(sid, set())
            for label in labels:
                if label not in known:
                    known.add(label)
                    if self._multi_select:
                        checked.add(label)

        self._rebuild()

    def check_all(self, checked: bool) -> None:
        """The "Select all" / "clear all" options are only offered (see the All/None
        buttons) in multi-select mode; one-per-sample mode has no "select
        all populations" concept to offer, since only one may be checked.
        """
        if checked:
            self._checked_shared = set(self._groups.shared)
            self._checked_per_sample = {
                sid: set(labels) for sid, labels in self._groups.per_sample.items()
            }
        else:
            self._checked_shared = set()
            self._checked_per_sample = {sid: set() for sid in self._groups.per_sample}
        self._rebuild()
        self.selectionChanged.emit()

    def get_checked_populations(self) -> list[tuple[str, str | None, str]]:
        """Return (sample_id, node_id, label) triples for every checked population.

        Multi-select mode: every checked shared label (fanned out to each
        sample that has it) plus every checked sample-specific label — any
        number of populations per sample.

        One-per-sample mode: exactly one entry per checked sample — that
        sample's own override if it has one, else the single checked shared
        label (which, being "shared", is always present for every currently
        checked sample), else nothing if neither is set.
        """
        result: list[tuple[str, str | None, str]] = []
        if self._multi_select:
            for sid in self._checked_sample_ids:
                node_idx = self._groups.node_index.get(sid, {})
                for label in self._checked_shared:
                    if label in node_idx:
                        result.append((sid, node_idx[label], label))
                for label in self._checked_per_sample.get(sid, set()):
                    if label in node_idx:
                        result.append((sid, node_idx[label], label))
            return result

        shared_label = next(iter(self._checked_shared), None)
        for sid in self._checked_sample_ids:
            node_idx = self._groups.node_index.get(sid, {})
            override = next(iter(self._checked_per_sample.get(sid, set())), None)
            active_label = override if override is not None else shared_label
            if active_label is not None and active_label in node_idx:
                result.append((sid, node_idx[active_label], active_label))
        return result

    def set_search_text(self, text: str) -> None:
        self._search_box.setText(text)

    # ── Rebuild ──────────────────────────────────────────────────────────────

    def _on_search_changed(self, text: str) -> None:
        self._search_text = text.strip().lower()
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            if top is not None:
                _filter_item(top, self._search_text)

    def _rebuild(self) -> None:
        try:
            self.tree.itemChanged.disconnect()
        except TypeError:
            pass

        self.tree.blockSignals(True)
        self.tree.clear()

        self._rebuild_tree()
        self.tree.itemChanged.connect(self._on_item_changed)

        self.tree.blockSignals(False)
        self._apply_theme_styles()

        if self._search_text:
            for i in range(self.tree.topLevelItemCount()):
                top = self.tree.topLevelItem(i)
                if top is not None:
                    _filter_item(top, self._search_text)

    def _rebuild_tree(self) -> None:
        shared_header = QTreeWidgetItem([f"▾ Shared Populations ({len(self._groups.shared)})"])
        shared_header.setData(0, Qt.ItemDataRole.UserRole, _HEADER)
        shared_header.setData(0, Qt.ItemDataRole.UserRole + 1, _HEADER)
        shared_header.setFlags(Qt.ItemFlag.ItemIsEnabled)
        self.tree.addTopLevelItem(shared_header)
        self._build_nested_rows(
            shared_header,
            self._groups.shared,
            role_data=_SHARED_ROLE,
            negated_lookup=self._negated_for_shared,
            checked_lookup=lambda label: label in self._checked_shared,
        )
        shared_header.setExpanded(True)

        specific_samples = [
            sid for sid in self._checked_sample_ids if self._groups.per_sample.get(sid)
        ]
        specific_header = QTreeWidgetItem(
            [f"▾ Sample-Specific ({len(specific_samples)} sample(s))"]
        )
        specific_header.setData(0, Qt.ItemDataRole.UserRole, _HEADER)
        specific_header.setData(0, Qt.ItemDataRole.UserRole + 1, _HEADER)
        specific_header.setFlags(Qt.ItemFlag.ItemIsEnabled)
        self.tree.addTopLevelItem(specific_header)

        for sid in specific_samples:
            sample = self._samples.get(sid)
            labels = self._groups.per_sample.get(sid, [])
            sample_header = QTreeWidgetItem(
                [f"{sample.display_name if sample else sid} ({len(labels)})"]
            )
            sample_header.setData(0, Qt.ItemDataRole.UserRole, _HEADER)
            sample_header.setData(0, Qt.ItemDataRole.UserRole + 1, _HEADER)
            sample_header.setFlags(Qt.ItemFlag.ItemIsEnabled)
            specific_header.addChild(sample_header)
            self._build_nested_rows(
                sample_header,
                labels,
                role_data=sid,
                negated_lookup=lambda label, _sid=sid: self._negated_for_sample(_sid, label),
                checked_lookup=lambda label, _sid=sid: (
                    label in self._checked_per_sample.get(_sid, set())
                ),
            )

    def _build_nested_rows(
        self,
        header_item: QTreeWidgetItem,
        labels: list[str],
        role_data: str,
        negated_lookup,
        checked_lookup,
    ) -> None:
        built: dict[str, QTreeWidgetItem] = {}
        for label in sorted(labels, key=lambda label: label.count(PATH_SEP)):
            if label == ALL_EVENTS_LABEL:
                parent_item, icon, leaf = header_item, "⬡  ", ALL_EVENTS_LABEL
            else:
                parent_path = label.rsplit(PATH_SEP, 1)[0] if PATH_SEP in label else None
                parent_item = header_item
                if parent_path is not None:
                    found = built.get(parent_path)
                    if found is not None:
                        parent_item = found
                leaf = label.rsplit(PATH_SEP, 1)[-1]
                icon = "⊘ " if negated_lookup(label) else "◆ "
            item = QTreeWidgetItem([f"{icon}{leaf}"])
            item.setData(0, Qt.ItemDataRole.UserRole, role_data)
            item.setData(0, Qt.ItemDataRole.UserRole + 1, label)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                0, Qt.CheckState.Checked if checked_lookup(label) else Qt.CheckState.Unchecked
            )
            parent_item.addChild(item)
            built[label] = item

    def _negated_for_shared(self, label: str) -> bool:
        for sid in self._checked_sample_ids:
            node_id = self._groups.node_index.get(sid, {}).get(label)
            if node_id:
                return self._negated_for_sample(sid, label)
        return False

    def _negated_for_sample(self, sid: str, label: str) -> bool:
        node_id = self._groups.node_index.get(sid, {}).get(label)
        sample = self._samples.get(sid)
        if not node_id or not sample or not sample.gate_tree:
            return False
        node = sample.gate_tree.find_node_by_id(node_id)
        return bool(node and node.negated)

    def _on_item_changed(self, item: QTreeWidgetItem, _column: int) -> None:
        role = item.data(0, Qt.ItemDataRole.UserRole)
        label = item.data(0, Qt.ItemDataRole.UserRole + 1)
        if role is _HEADER or label is _HEADER:
            return
        checked = item.checkState(0) == Qt.CheckState.Checked

        if not self._multi_select and checked:
            self._enforce_one_per_sample(item, role)

        if role == _SHARED_ROLE:
            bucket = self._checked_shared
        else:
            bucket = self._checked_per_sample.setdefault(role, set())
        if checked:
            bucket.add(label)
        else:
            bucket.discard(label)
        self.selectionChanged.emit()

    def _enforce_one_per_sample(self, item: QTreeWidgetItem, role: str) -> None:
        """One-per-sample mode: uncheck every other item in the same `role`
        bucket — every other "Shared Populations" row if `item` is shared
        (since a shared label always spans every checked sample, at most one
        can be the active default at a time), or every other row under the
        same sample if `item` is a sample-specific override. Deliberately
        does NOT touch the other bucket: checking a per-sample override
        leaves the shared default (and every other sample's pick) alone —
        that's what lets one sample be overridden without disturbing the
        rest.
        """
        self.tree.blockSignals(True)
        it = QTreeWidgetItemIterator(self.tree)
        while it.value():
            other = it.value()
            if other and other is not item:
                other_role = other.data(0, Qt.ItemDataRole.UserRole)
                other_label = other.data(0, Qt.ItemDataRole.UserRole + 1)
                if other_role == role and other_label is not _HEADER:
                    other.setCheckState(0, Qt.CheckState.Unchecked)
            it += 1
        self.tree.blockSignals(False)
        if role == _SHARED_ROLE:
            self._checked_shared.clear()
        else:
            self._checked_per_sample[role] = set()

    # ── Theme ────────────────────────────────────────────────────────────────

    def _apply_theme_styles(self) -> None:
        Colors, _ = _get_theme_tokens()
        self.tree.setStyleSheet(
            f"QTreeWidget {{ background: {Colors.BG_DARKEST}; border: 1px solid {Colors.BORDER};"
            f" border-radius: 4px; color: {Colors.FG_PRIMARY}; }}"
            f"QTreeWidget::item {{ color: {Colors.FG_PRIMARY}; padding: 2px 4px; }}"
            f"QTreeWidget::item:hover {{ background: {Colors.BG_DARK}; color: {Colors.FG_PRIMARY}; }}"
            f"QTreeWidget::item:selected {{ background: {Colors.BG_MEDIUM}; color: {Colors.FG_PRIMARY}; }}"
            + checkbox_qss()
        )
        self._search_box.setStyleSheet(
            f"QLineEdit {{ background: {Colors.BG_MEDIUM}; color: {Colors.FG_PRIMARY};"
            f" border: 1px solid {Colors.BORDER}; border-radius: 4px; padding: 4px 8px; }}"
        )

        fg_color = QColor(Colors.FG_PRIMARY)

        def _recolor(item: QTreeWidgetItem) -> None:
            item.setForeground(0, fg_color)
            for c in range(item.childCount()):
                child = item.child(c)
                if child is not None:
                    _recolor(child)

        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            if top is not None:
                _recolor(top)
