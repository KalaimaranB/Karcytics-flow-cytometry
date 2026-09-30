from __future__ import annotations

from typing import TYPE_CHECKING

from karcytics_sdk.plugin import CentralEventBus

from karcytics_plugins.flow_cytometry.analysis import events

if TYPE_CHECKING:
    from ...ui.main_panel import FlowCytometryPanel


class MainPanelController:
    """Manages the signal routing and event bus subscriptions for the Flow Cytometry workspace."""

    @staticmethod
    def wire(panel: FlowCytometryPanel) -> None:  # noqa: PLR0915
        """Connect internal widget signals and CentralEventBus subscriptions."""
        panel._subscriptions = []  # type: ignore[attr-defined]

        def _subscribe(topic, cb):
            CentralEventBus.subscribe(topic, cb)
            panel._subscriptions.append((topic, cb))  # type: ignore[attr-defined]

        # ── Undo history & unsaved changes ────────────────────────────
        # HistoryRecorder (analysis/history_recorder.py) is the one table of
        # which events are undo steps; the store behind it decides dirtiness.
        from PyQt6.QtCore import QTimer

        from karcytics_plugins.flow_cytometry.analysis.history_recorder import HistoryRecorder

        panel._history_recorder = HistoryRecorder(  # type: ignore[attr-defined]
            panel._store,
            CentralEventBus.subscribe,
            CentralEventBus.unsubscribe,
            defer=lambda fn: QTimer.singleShot(0, fn),
        )
        panel._history_recorder.start()  # type: ignore[attr-defined]
        _subscribe(events.STATE_RESTORED, panel._on_state_restored)

        # ── Structural change → Node Canvas ───────────────────────────
        def _on_structural_change(_payload):
            panel._refresh_node_canvas()

        _subscribe(events.GATE_CREATED, _on_structural_change)
        _subscribe(events.LOGIC_NODE_CREATED, _on_structural_change)
        _subscribe(events.GATES_CREATED, _on_structural_change)
        _subscribe(events.GATE_DELETED, _on_structural_change)
        _subscribe(events.GATE_RENAMED, _on_structural_change)
        # GATE_MODIFIED only ever fires once per completed drag gesture (see
        # FlowCanvas._commit_gate_edit / GateDrawingFSM._finish_edit — the
        # live-drag preview mutates the Gate object directly and never
        # publishes this event), so one edit = one undo step.
        _subscribe(events.GATE_MODIFIED, _on_structural_change)

        def _on_gate_renamed_ui(payload):
            # Renaming changes no stats/geometry — only refresh the properties
            # panel, and only if it's currently showing the renamed node.
            node_id = payload.get("node_id")
            if node_id == panel.state.view.current_gate_id:
                panel._properties_panel.refresh()

        _subscribe(events.GATE_RENAMED, _on_gate_renamed_ui)

        # A connection that doesn't (yet) satisfy a logic node's wiring
        # requirements must NOT trigger the full canvas rebuild above —
        # CanvasManager handles its own cheap, targeted redraw for these (see
        # CanvasManager._on_connection_pending); the HistoryRecorder still
        # records them as steps.

        _subscribe(events.DERIVED_PARAMS_CHANGED, panel._on_derived_params_changed)

        # ── Workspace ribbon: samples loaded → refresh tree + groups ──
        # Note: Event subscription for UI refresh is handled in the components themselves

        panel._workspace_ribbon.samples_loaded.connect(panel._on_samples_loaded)
        panel._workspace_ribbon.group_requested.connect(panel._on_group_requested)

        # ── Pipeline Ribbon & Node Canvas ─────────────────────────────
        panel._pipeline_ribbon.sample_selected.connect(panel._node_canvas.set_sample)
        panel._pipeline_ribbon.logic_node_requested.connect(panel._gate_coordinator.add_logic_node)
        panel._pipeline_ribbon.orientation_changed.connect(panel._node_canvas.set_orientation)
        panel._node_canvas.node_double_clicked.connect(panel._on_gate_double_clicked)
        panel._node_canvas.node_removed.connect(
            lambda node_id: (
                panel._gate_coordinator.remove_population(
                    panel._node_canvas.current_sample_id, node_id
                )
                if panel._node_canvas.current_sample_id
                else None
            )
        )
        panel._node_canvas.connection_requested.connect(panel._gate_coordinator.add_connection)
        panel._node_canvas.connection_removed.connect(panel._gate_coordinator.remove_connection)
        panel._node_canvas.rename_requested.connect(
            lambda node_id, new_name, target_ids: (
                panel._gate_coordinator.rename_population(
                    panel._node_canvas.current_sample_id, node_id, new_name, target_ids
                )
                if panel._node_canvas.current_sample_id
                else None
            )
        )
        panel._node_canvas.link_delete_requested.connect(
            lambda src, tgt, target_ids: panel._gate_coordinator.remove_connection_for_samples(
                src, tgt, target_ids
            )
        )

        # ── Workspace ribbon: template loaded → refresh everything ────
        panel._workspace_ribbon.template_load_requested.connect(panel._refresh_all)

        # ── Compensation ribbon: matrix changed → refresh ─────────────
        panel._compensation_ribbon.compensation_changed.connect(panel._on_compensation_changed)

        # ── Gating ribbon → drawing tool selection ────────────────────
        panel._gating_ribbon.tool_selected.connect(panel._graph_manager.set_drawing_mode)
        panel._gating_ribbon.delete_gate_requested.connect(panel._on_delete_selected_gate)
        panel._gating_ribbon.copy_gates_requested.connect(panel._on_copy_gates_from_active)
        panel._gating_ribbon.derived_params_requested.connect(lambda: panel._derived_editor.open())
        panel._graph_manager.derived_editor_requested.connect(panel._derived_editor.open_for_axis)

        # ── Graph manager → gate controller ───────────────────────────
        panel._graph_manager.gate_drawn.connect(panel._on_gate_drawn)
        panel._graph_manager.gate_selection_changed.connect(panel._on_gate_selected_on_canvas)
        panel._graph_manager.active_graph_changed.connect(panel._on_active_graph_changed)
        panel._graph_manager.tool_change_requested.connect(panel._gating_ribbon.select_tool)

        # ── Gate controller → UI updates ──────────────────────────────
        def _show_flash_message(text: str, *, is_error: bool = True) -> None:
            """Transient on-canvas banner, auto-dismissed after 2.5s.

            Shared by the tutorial invalid-gate-shape case and partial gate
            propagation failures — both want something louder than the
            routine status bar for something the user should notice.
            """
            from PyQt6.QtCore import Qt, QTimer
            from PyQt6.QtWidgets import QLabel

            bg = "rgba(220, 50, 50, 0.9)" if is_error else "rgba(40, 40, 40, 0.9)"
            label = QLabel(text, panel._graph_manager)
            label.setStyleSheet(
                f"background: {bg}; color: white; padding: 12px; border-radius: 6px; "
                "font-weight: bold; font-size: 14px;"
            )
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.resize(label.sizeHint())
            # Center it near the top of the graph manager
            label.move((panel._graph_manager.width() - label.width()) // 2, 40)
            label.show()
            QTimer.singleShot(2500, label.deleteLater)

        def _show_invalid_gate_flash():
            _show_flash_message("Gate inaccurate. Please try again.")

        def _tutorial_shape_validator():
            """Returns the active GateShapeValidator, or None if not applicable."""
            try:
                from karcytics_sdk.plugin.runtime_services import (
                    tutorial_manager as global_tutorial_manager,
                )

                step = global_tutorial_manager.current_step
                if step and hasattr(step, "validator"):
                    from ...tutorials.validators import GateShapeValidator

                    if isinstance(step.validator, GateShapeValidator):
                        return global_tutorial_manager, step.validator
            except Exception:
                import traceback

                traceback.print_exc()
            return None, None

        def _handle_gate_created(payload):
            sample_id = payload.get("sample_id")
            node_id = payload.get("node_id")

            tutorial_manager, validator = _tutorial_shape_validator()
            if validator and not validator.validate_shape(
                tutorial_manager.app_state, node_id, sample_id
            ):
                if hasattr(validator, "set_explicit_failure"):
                    validator.set_explicit_failure(node_id)
                # Validation failed! Auto-delete the gate.
                panel._gate_coordinator.remove_population(sample_id, node_id)
                _show_invalid_gate_flash()
                return

            panel._on_gate_added(sample_id, node_id)
            panel.gate_added_to_tree.emit()

        def _handle_gates_created(payload):
            """Batched counterpart of _handle_gate_created for gates that create
            several nodes at once (e.g. quadrant gates) — validates each node as
            before, but triggers only one refresh/selection for the whole batch
            instead of one per node.
            """
            sample_id = payload.get("sample_id")
            nodes = payload.get("nodes", [])
            if not nodes:
                return

            tutorial_manager, validator = _tutorial_shape_validator()

            valid_node_ids = []
            any_invalid = False
            for entry in nodes:
                node_id = entry.get("node_id")
                if validator and not validator.validate_shape(
                    tutorial_manager.app_state, node_id, sample_id
                ):
                    panel._gate_coordinator.remove_population(sample_id, node_id)
                    any_invalid = True
                    continue
                valid_node_ids.append(node_id)

            if any_invalid:
                _show_invalid_gate_flash()

            if valid_node_ids:
                panel._on_gates_added(sample_id, valid_node_ids)
                # _handle_gate_created (the single-node path) emits this after
                # _on_gate_added — a quadrant gate always creates 4 nodes at
                # once via this batched path instead, so without emitting it
                # here too, any InteractionStep wired to event_trigger=
                # "gate_added_to_tree" (e.g. course2.py's c2_s37_draw_quadrant)
                # never advances: the tutorial waits forever even after a
                # correctly-drawn quadrant.
                panel.gate_added_to_tree.emit()

        _subscribe(events.GATE_CREATED, _handle_gate_created)
        _subscribe(events.GATES_CREATED, _handle_gates_created)
        _subscribe(
            events.GATE_DELETED,
            lambda p: panel._on_gate_removed(p.get("sample_id"), p.get("node_id")),
        )
        _subscribe(
            events.GATE_SELECTED,
            lambda p: panel._on_gate_selected_from_controller(p.get("sample_id"), p.get("node_id")),
        )

        def _on_stats_updated(payload):
            sid = payload.get("sample_id")
            nid = payload.get("node_id")
            panel._on_gate_stats_updated(sid, nid)
            panel._refresh_node_canvas()

        _subscribe("flow.gate.stats_updated", _on_stats_updated)

        def _on_all_stats(payload):
            sid = payload.get("sample_id")
            panel._on_all_stats_updated(sid)
            panel._refresh_node_canvas()

        _subscribe("flow.gate.all_stats_updated", _on_all_stats)

        # ── Propagator → live UI updates ──────────────────────────────
        _subscribe(
            events.SAMPLE_UPDATED,
            lambda p: panel._on_propagated_sample_updated(
                p.get("sample_id"), p.get("stats"), p.get("new_tree")
            ),
        )

        # Refresh GroupsPanel when sample memberships might have changed
        _subscribe(events.SAMPLE_UPDATED, lambda p: panel._groups_panel.refresh())

        def _on_prop_complete(payload):
            payload = payload or {}
            if payload.get("failed"):
                names = []
                errors = payload.get("errors", {})
                for sid in errors:
                    sample = panel.state.data.experiment.samples.get(sid)
                    names.append(sample.display_name if sample else sid)
                max_names_shown = 3
                shown = ", ".join(names[:max_names_shown]) + (
                    "…" if len(names) > max_names_shown else ""
                )
                _show_flash_message(
                    f"Gate propagation failed for {payload['failed']} sample"
                    f"{'s' if payload['failed'] != 1 else ''}: {shown}"
                )
            panel._on_propagation_complete(payload)
            panel._refresh_node_canvas()

        _subscribe(events.PROPAGATION_COMPLETE, _on_prop_complete)

        # ── Sample list → graph + properties ──────────────────────────
        panel._sample_list.sample_double_clicked.connect(
            panel._graph_manager.open_graph_with_context
        )
        panel._sample_list.population_open_requested.connect(
            panel._graph_manager.open_graph_for_sample
        )
        panel._sample_list.selection_changed.connect(
            lambda sid: panel._properties_panel.show_sample_properties(sid, None)
        )
        panel._sample_list.selection_changed.connect(panel._on_sample_selection_changed)

        # ── Gate Hierarchy → graph + properties ───────────────────────
        panel._gate_hierarchy.gate_double_clicked.connect(panel._on_gate_double_clicked)
        panel._gate_hierarchy.selection_changed.connect(panel._on_gate_selection_changed)
        panel._gate_hierarchy.gate_rename_requested.connect(
            panel._gate_coordinator.rename_population
        )
        panel._gate_hierarchy.gate_delete_requested.connect(panel.delete_gate_with_dialog)
        panel._gate_hierarchy.copy_gates_requested.connect(panel._on_copy_gates)
        panel._gate_hierarchy.propagation_mode_changed.connect(panel._on_propagation_mode_changed)
        panel._gate_hierarchy.propagate_requested.connect(
            panel._gate_coordinator.propagate_to_all_groups
        )

        # ── Groups panel selection → filter sample list ───────────────
        panel._groups_panel.group_selected.connect(panel._sample_list.filter_by_group)

    @staticmethod
    def unwire(panel: FlowCytometryPanel) -> None:
        """Unsubscribe from CentralEventBus to prevent memory leaks or calling dead UI."""
        if hasattr(panel, "_subscriptions"):
            for topic, cb in panel._subscriptions:
                CentralEventBus.unsubscribe(topic, cb)
            panel._subscriptions.clear()
        recorder = getattr(panel, "_history_recorder", None)
        if recorder is not None:
            recorder.stop()
