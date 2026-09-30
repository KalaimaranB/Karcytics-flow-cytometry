"""Event topic constants for the flow cytometry module.

These are used with the Karcytics SDK's CentralEventBus to ensure
decoupled communication between components.
"""

# Gate events
GATE_CREATED = "flow.gate.created"
LOGIC_NODE_CREATED = "flow.gate.logic_node_created"
# Fired once for gates that create several nodes in one action (e.g. quadrant
# gates create 4 GateNodes). Consumers that would otherwise redo a full
# refresh per node should subscribe here instead of to GATE_CREATED so the
# refresh happens once per user action instead of once per node.
GATES_CREATED = "flow.gate.batch_created"
GATE_RENAMED = "flow.gate.renamed"
GATE_DELETED = "flow.gate.deleted"
GATE_MODIFIED = "flow.gate.modified"
GATE_PROPAGATED = "flow.gate.propagated"
GATE_SELECTED = "flow.gate.selected"
GATE_PREVIEW = "flow.gate.preview"

# Sample events
SAMPLE_SELECTED = "flow.sample.selected"
SAMPLE_DESELECTED = "flow.sample.deselected"
SAMPLE_LOADED = "flow.sample.loaded"

# Canvas/Rendering events
RENDER_MODE_CHANGED = "flow.render.mode_changed"
RENDER_CONFIG_CHANGED = "flow.render.config_changed"
AXIS_PARAMS_CHANGED = "flow.axis.params_changed"
AXIS_RANGE_CHANGED = "flow.axis.range_changed"
AXIS_RANGE_AUTO_UPDATED = "flow.axis.range_auto_updated"
TRANSFORM_CHANGED = "flow.transform.changed"
DISPLAY_MODE_CHANGED = "flow.display.mode_changed"
FMO_CHANGED = "flow.fmo.changed"

# Statistics events
STATS_COMPUTED = "flow.stats.computed"
STATS_INVALIDATED = "flow.stats.invalidated"

# Compensation events
COMPENSATION_APPLIED = "flow.compensation.applied"

# UMAP events
UMAP_COMPLETED = "flow.umap.completed"

# Analysis layer internal replacement topics
AXIS_UPDATED = "flow.axis.updated"
GATE_STATS_UPDATED = "flow.gate.stats_updated"
ALL_STATS_UPDATED = "flow.gate.all_stats_updated"
PROPAGATION_REQUESTED = "flow.gate.propagation_requested"
PROPAGATION_COMPLETE = "flow.gate.propagation_complete"
SAMPLE_UPDATED = "flow.gate.sample_updated"

# Experiment-level change (e.g. compensation applied across all samples)
EXPERIMENT_DATA_CHANGED = "flow.experiment.data_changed"

# Derived-parameter definitions created/edited/deleted. Payload:
# {"param_id": str, "action": "created" | "updated" | "deleted" | "synced"}
DERIVED_PARAMS_CHANGED = "flow.derived.changed"

# ── Undo/redo & unsaved changes (see store.FlowStore, history_recorder) ──
# A user edit to the analysis model that has no more specific event above.
# Payload: {"label": str} — the step's name in Edit → Undo "<label>".
MODEL_EDITED = "flow.model.edited"
# A saved-but-not-undoable setting changed (axis scales, render settings):
# marks the workspace unsaved without adding an undo step. Payload: {}.
DISPLAY_SETTINGS_CHANGED = "flow.display.settings_changed"
# Undo/redo just rebuilt state.data.experiment from a snapshot. Every
# Sample/Group/GateNode object is new — views must re-resolve by id.
STATE_RESTORED = "flow.state.restored"
