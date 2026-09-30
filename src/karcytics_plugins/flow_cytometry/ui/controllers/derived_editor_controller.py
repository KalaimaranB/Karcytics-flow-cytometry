"""Opens the Derived Parameters dialog and follows up on what it saves.

Owns the single (lazily created, non-modal) dialog instance and the one
bit of cross-widget behaviour: a parameter created from a graph's
"＋ New derived parameter…" axis entry is put straight onto that axis.
"""

from __future__ import annotations

import weakref
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from PyQt6.QtWidgets import QWidget

    from karcytics_plugins.flow_cytometry.analysis.services.derived_parameter_service import (
        DerivedParameterService,
    )
    from karcytics_plugins.flow_cytometry.analysis.state import FlowState
    from karcytics_plugins.flow_cytometry.ui.dialogs.derived_parameter_dialog import (
        DerivedParameterDialog,
    )


class DerivedEditorController:
    def __init__(
        self,
        state: FlowState,
        service: DerivedParameterService,
        remove_population: Callable[[str, str], bool],
        parent: QWidget,
    ) -> None:
        self._state = state
        self._service = service
        self._remove_population = remove_population
        self._parent = parent
        self._dialog: DerivedParameterDialog | None = None
        self._axis_target: tuple[weakref.ref, str] | None = None

    @property
    def dialog(self) -> DerivedParameterDialog:
        if self._dialog is None:
            from karcytics_plugins.flow_cytometry.ui.dialogs.derived_parameter_dialog import (
                DerivedParameterDialog,
            )

            self._dialog = DerivedParameterDialog(
                self._state,
                self._service,
                remove_population=self._remove_population,
                parent=self._parent,
            )
            self._dialog.parameter_saved.connect(self._on_saved)
        return self._dialog

    def open(self, param_id: str | None = None) -> None:
        """Ribbon button / general entry: show the manager."""
        self._axis_target = None
        self.dialog.open_existing(param_id)

    def open_for_axis(self, graph: Any, axis: str) -> None:
        """'＋ New derived parameter…' picked in ``graph``'s X or Y dropdown."""
        self._axis_target = (weakref.ref(graph), axis)
        self.dialog.open_new()

    def _on_saved(self, param_id: str, created: bool) -> None:
        target, self._axis_target = self._axis_target, None
        if not created or target is None:
            return
        graph_ref, axis = target
        graph = graph_ref()
        if graph is None:
            return
        try:
            graph.select_axis_param(axis, param_id)
        except RuntimeError:  # tab closed while the dialog was open
            pass
