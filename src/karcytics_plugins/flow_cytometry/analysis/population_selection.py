"""Which (sample, population) pairs a Statistics or Comparisons run includes.

The population picker is a grid: a row per population (matched across samples
by name path), a column per sample, every applicable cell checkable. This is
its state and rules, Qt-free; the popup draws it and forwards clicks.

The rules:

- A pair seen for the first time starts checked, until the user touches the
  picker; after that, pairs that turn up later (tab switches, gates
  propagating late) stay unchecked: nothing checks itself without a click.
- One population per sample (``multi_select`` off, e.g. Violin) keeps at most
  one checked cell per column.
- One sample (``single_sample``, Pseudocolor Overlay, which only ever draws
  one sample's own populations) keeps checked cells in at most one column.
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from .population_matching import (
    ALL_EVENTS_LABEL,
    PopulationGroups,
    PopulationSelectionRow,
    build_row_order,
    compute_population_groups,
)

if TYPE_CHECKING:
    from .experiment import Sample

Cell = tuple[str, str]  # (sample id, population label path)


class PopulationSelection:
    """The picker's checked cells and the rules that change them.

    Every mutator returns whether the checked set (or a mode) changed, so the
    view knows when to redraw and announce it.
    """

    def __init__(self) -> None:
        self.sample_ids: list[str] = []
        self.groups = PopulationGroups()
        self.rows: list[PopulationSelectionRow] = []
        self.checked: set[Cell] = set()
        self._known: set[Cell] = set()
        self.touched = False  # the user has clicked something since the picker was built
        self.multi_select = True
        self.single_sample = False
        self._drag_target = False  # the state a drag paints every cell it crosses
        self._drag_visited: set[Cell] = set()
        self.dragging = False

    # ── what's on the grid ──

    def refresh(self, samples: dict[str, Sample]) -> None:
        """Rebuild the rows for ``samples``, keeping every check already made.

        A pair seen for the first time is checked only while the picker is
        untouched, and then only as the mode allows: every population, All
        Events alone (one per sample), or All Events of the first sample (one
        sample; checking it everywhere would leave several samples active).
        """
        self.sample_ids = list(samples)
        self.groups = compute_population_groups([samples[sid] for sid in self.sample_ids])
        self.rows = build_row_order(self.groups)
        for sid in self.sample_ids:
            for label in self._labels_of(sid):
                cell = (sid, label)
                if cell in self._known:
                    continue
                self._known.add(cell)
                if self.touched:
                    continue
                if self.single_sample:
                    if sid == self.sample_ids[0] and label == ALL_EVENTS_LABEL:
                        self.checked.add(cell)
                elif self.multi_select or label == ALL_EVENTS_LABEL:
                    self.checked.add(cell)

    def applies(self, sid: str, label: str) -> bool:
        """Whether sample ``sid`` has the population at all (else its cell is blank)."""
        return label in self.groups.node_index.get(sid, {})

    def _labels_of(self, sid: str) -> list[str]:
        """The populations ``sid`` has, in row order."""
        return [row.label_path for row in self.rows if self.applies(sid, row.label_path)]

    def checked_populations(self) -> list[tuple[str, str | None, str]]:
        """(sample_id, node_id, label) per checked cell, in grid order: rows, then samples."""
        rows = {row.label_path: i for i, row in enumerate(self.rows)}
        samples = {sid: i for i, sid in enumerate(self.sample_ids)}
        last = len(rows) + len(samples)  # a pair not on the grid sorts after it
        cells = sorted(self.checked, key=lambda c: (rows.get(c[1], last), samples.get(c[0], last)))
        return [
            (sid, self.groups.node_index[sid][label], label)
            for sid, label in cells
            if self.applies(sid, label)
        ]

    def active_sample(self) -> str | None:
        """The sample with checked cells (meaningful in one-sample mode, where there's one)."""
        return next((sid for sid, _label in self.checked), None)

    def shown_sample(self) -> str | None:
        """The active sample, else the first: the one-sample mode's highlighted column."""
        return self.active_sample() or (self.sample_ids[0] if self.sample_ids else None)

    def summary(self, display_names: dict[str, str]) -> str:
        if self.single_sample:
            active = self.active_sample()
            if active is None:
                return "No sample selected."
            name = display_names.get(active, active)
            return f"Comparing within {name} — click another sample's column header to switch."
        picked = sum(1 for sid, _label in self.checked if sid in self.sample_ids)
        available = sum(len(self._labels_of(sid)) for sid in self.sample_ids)
        return f"{picked} of {available} population picks selected"

    # ── modes ──

    def set_multi_select(self, enabled: bool) -> bool:
        """Allow any number of populations per sample, or at most one."""
        if enabled == self.multi_select:
            return False
        self.multi_select = enabled
        if enabled:
            # Every pair checked one-per-sample is still valid. Catch up the
            # "starts checked" default the one-per-sample mode held back, but only
            # while the picker is untouched: after a deliberate choice that would
            # flood it with populations nobody checked (Violin → Channel Heatmap).
            if not self.touched:
                caught_up = self._known
                if self.single_sample:
                    active = self.shown_sample()
                    caught_up = {cell for cell in caught_up if cell[0] == active}
                self.checked |= caught_up
        else:
            # At most one per column: All Events if it was checked, else the first pick.
            kept: set[Cell] = set()
            for sid in self.sample_ids:
                picks = [label for s, label in self.checked if s == sid]
                if ALL_EVENTS_LABEL in picks:
                    kept.add((sid, ALL_EVENTS_LABEL))
                elif picks:
                    kept.add((sid, picks[0]))
            self.checked = kept
        return True

    def set_single_sample(self, enabled: bool) -> bool:
        """Keep checked cells in at most one sample's column, or in any."""
        if enabled == self.single_sample:
            return False
        self.single_sample = enabled
        if not enabled:
            # With no sample checklist to re-check the others from, every sample
            # but the active one gets its fresh "start checked" default back; the
            # active sample's own picks are left alone.
            active = self.active_sample()
            for sid in self.sample_ids:
                if sid != active:
                    self.checked |= self._everything_for(sid)
            return True
        keep = self._sample_to_keep()
        if keep is None:
            self.checked = set()
        elif self.touched:
            # Exactly what the user checked for the surviving sample, nothing added.
            self.checked = {cell for cell in self.checked if cell[0] == keep}
        else:
            self.checked = self._everything_for(keep)
        return True

    def _sample_to_keep(self) -> str | None:
        """Which sample survives entering one-sample mode.

        After the user has picked, the sample they picked the most for (Sample C
        with two populations beats Sample A with one, whichever sorts first);
        before, the first sample in column order with any check, so the outcome
        never depends on set order. With nothing checked, the first sample.
        """
        counts = Counter(sid for sid, _label in self.checked)
        if self.touched:
            picked = [sid for sid in self.sample_ids if sid in counts]
            keep = max(picked, key=lambda sid: counts[sid], default=None)
        else:
            keep = next((sid for sid in self.sample_ids if sid in counts), None)
        return keep if keep is not None else next(iter(self.sample_ids), None)

    def _everything_for(self, sid: str) -> set[Cell]:
        """What "check this sample" means in the current mode."""
        if self.multi_select:
            return {(sid, label) for label in self._labels_of(sid)}
        return {(sid, ALL_EVENTS_LABEL)} if self.applies(sid, ALL_EVENTS_LABEL) else set()

    # ── clicks ──

    def check_all(self, checked: bool) -> bool:
        """All / None: everything the mode allows, or nothing."""
        self.touched = True
        before = set(self.checked)
        if not checked:
            self.checked = set()
        elif self.single_sample:
            sid = self.shown_sample()
            self.checked = self._everything_for(sid) if sid is not None else set()
        else:
            self.checked = set().union(*(self._everything_for(s) for s in self.sample_ids))
        return self.checked != before

    def toggle_cell(self, sid: str, label: str) -> bool:
        self.touched = True
        return self._set(sid, label, (sid, label) not in self.checked)

    def toggle_row(self, label: str) -> bool:
        """A population's name: check it for every sample that has it (or clear it)."""
        self.touched = True
        applicable = [sid for sid in self.sample_ids if self.applies(sid, label)]
        if not applicable:
            return False
        if self.multi_select:
            cells = {(sid, label) for sid in applicable}
            if cells <= self.checked:
                self.checked -= cells
            else:
                self.checked |= cells
        else:
            # This population becomes every applicable sample's one pick.
            self.checked = {cell for cell in self.checked if cell[0] not in applicable}
            self.checked |= {(sid, label) for sid in applicable}
        return True

    def toggle_column(self, sid: str) -> bool:
        """A sample's header: all of its populations (or none); in one-sample
        mode, make it the sample (clicking the current one changes nothing).
        """
        self.touched = True
        if self.single_sample:
            if self.active_sample() == sid:
                return False
            self.checked = self._everything_for(sid)
            return True
        cells = {(sid, label) for label in self._labels_of(sid)}
        if not cells:
            return False
        if cells <= self.checked:
            self.checked -= cells
        else:
            self.checked |= cells
        return True

    def begin_drag(self, sid: str, label: str) -> bool:
        """A press on a cell: it flips, and every cell the drag crosses gets the
        same new state (started on a checked cell, the drag clears its path).
        """
        self.touched = True
        self.dragging = True
        self._drag_target = (sid, label) not in self.checked
        self._drag_visited = set()
        return self.drag_over(sid, label)

    def drag_over(self, sid: str, label: str) -> bool:
        cell = (sid, label)
        if not self.dragging or cell in self._drag_visited:
            return False
        self._drag_visited.add(cell)
        return self._set(sid, label, self._drag_target)

    def end_drag(self) -> bool:
        """Whether a drag was under way (it is over now)."""
        was = self.dragging
        self.dragging = False
        return was

    def is_checked(self, sid: str, label: str) -> bool:
        return (sid, label) in self.checked

    def _set(self, sid: str, label: str, checked: bool) -> bool:
        """Set one cell, within the modes; whether anything changed."""
        cell = (sid, label)
        if not self.applies(sid, label) or checked == (cell in self.checked):
            return False
        if not checked:
            self.checked.discard(cell)
            return True
        if not self.multi_select:
            self.checked = {c for c in self.checked if c[0] != sid}
        if self.single_sample:
            self.checked = {c for c in self.checked if c[0] == sid}
        self.checked.add(cell)
        return True
