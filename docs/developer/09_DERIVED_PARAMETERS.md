# Derived Parameters

Derived parameters are user-defined per-event formulas (e.g. `[FITC-A] / [APC-A]`) exposed as extra channels. This page covers how they're modelled, the one rule every data-loading path must follow, and where the pieces live. For the user-facing behaviour see [Derived Parameters](../user/15_DERIVED_PARAMETERS.md).

## Design in one paragraph

A derived parameter is appended to each sample as an extra **column in `fcs_data.events`** and an extra **key in `fcs_data.channels`**. Almost everything downstream — axis dropdowns, gates (`Gate.contains` looks columns up by name), propagation, `DagEvaluator`, statistics, comparisons — already works by channel name, so it works with derived parameters unchanged. The column is **never persisted and never written to `raw_events`**; it's recomputed from the current event table whenever that table changes.

## Module map

| Module | Responsibility |
| --- | --- |
| `analysis/derived/expression.py` | Formula language: `parse_formula()` → `DerivedExpression` (`channels`, `evaluate(df)`), `FormulaError(message, position)`. |
| `analysis/derived/models.py` | `DerivedParameter` (stored definition), `DerivedParameterDraft` (editor input), `is_derived_key()`, `new_param_id()`. |
| `analysis/derived/sync.py` | `sync_fcs_data()`, `sync_sample()`, `sync_experiment()`, `strip_derived_columns()`. |
| `analysis/derived/state.py` | `DerivedColumnsState` — per-`FCSData` bookkeeping owned by sync. |
| `analysis/derived/templates.py`, `preview.py` | Editor helpers (Qt-free). Not exported from the package `__init__`, so the light import chain through `fcs_io` doesn't pull in scipy. |
| `analysis/services/derived_parameter_service.py` | Validation, create/update/delete, `find_dependents()`, publishes `DERIVED_PARAMS_CHANGED`. |
| `analysis/channel_inference.py` | `DerivedAwareChannelInference` — derived axes default to their preferred linear/log scale. |
| `ui/widgets/derived_formula_editor.py`, `ui/dialogs/derived_parameter_dialog.py`, `ui/widgets/mini_histogram.py` | Editor, non-modal manager dialog, preview histogram. |
| `ui/controllers/derived_editor_controller.py` | Owns the dialog; puts a parameter created from a graph's axis dropdown onto that axis. |

## Keys, persistence and gates

- **Column key**: `derived:<8 hex>` (`constants.DERIVED_PREFIX`). Gates, axis memory and channel scales reference the key, so renaming a parameter never breaks them. Display labels (`ƒ <name>`) come from `get_channel_marker_label()` / `derived_labels_of()`.
- **Definitions** live on `Experiment.derived_parameters` and are serialized by `ExperimentSerializer` under `"derived_parameters"` (absent → `[]`). `WorkflowTemplate.derived_parameters` carries them in templates; `apply_template()` merges without duplicates.
- **Gate record**: `Gate.derived_formulas` snapshots the formula of any derived axis when the gate is created (`GateMutationService`). It's display/audit only — evaluation always uses the current definition — and is serialized only when non-empty, so ordinary gates serialize exactly as before. `gate_from_dict()` restores it centrally.
- Derived parameters can't reference other derived parameters (rejected by `DerivedParameterService.canonicalize`).

## The sync contract

!!! warning "Rule"
    Any code that **replaces** `sample.fcs_data`, or assigns `sample.fcs_data.events`, must call `sync_sample(experiment, sample)` (or `sync_experiment(experiment)`) before anything evaluates gates.

Current call sites:

| Path | Where |
| --- | --- |
| New sample added | `Experiment.add_sample()` |
| Compensation apply / toggle | `CompensationRibbon._on_apply_all`, `_on_toggle_compensation` |
| Workspace reload | `WorkflowService.reload_fcs_data` — before `on_complete` evaluates gates |
| State restore (undo/redo, workflow load) | `FlowStore.restore`, `WorkflowService.reload_fcs_data` |
| Definition created / edited / deleted | `DerivedParameterService._after_change` |
| **Safety nets** | `PopulationService.get_gated_events`, `GateCoordinator.recompute_all_stats` |

How sync stays correct and cheap:

- **Idempotent, zero-cost when unused.** `sync_sample()` returns immediately when the experiment has no definitions and the frame has no derived columns — workspaces that never use the feature never touch this code.
- **Swap, don't mutate.** Sync builds a new DataFrame and assigns it to `fcs_data.events`. Concurrent readers never see a half-written column, and `GateNode` mask caches (keyed on frame identity) miss naturally.
- **Replaced frames are detected, not trusted.** `DerivedColumnsState.frame_ref` is a weak reference to the frame sync last produced. Any other frame is treated as fresh base data and fully recomputed — even if it carries copies of old derived columns (e.g. `apply_compensation` copying `events` when there's no raw backup; it also strips them itself).
- **Signatures** (`formula | positive_denominators`) detect definition edits on an unchanged frame, so only edited columns are recomputed.
- **Missing inputs → NaN column**, never a missing column, so gates on the parameter can't raise `KeyError` on a sample that lacks a channel.

## Numeric semantics

- Evaluation is vectorized float64 under `np.errstate(all="ignore")`; ±inf becomes NaN.
- `positive_denominators=True` turns any division by a value ≤ 0 into NaN.
- NaN fails every gate comparison and is dropped by `compute_statistic` (`dropna`), auto-range (`isfinite`) and pseudocolor rendering.
- `apply_transform()` preserves NaN (Logicle would otherwise map it to ≈ −1 display units, which would plot — and gate — invalid events at the axis floor).
- Only `linear` and `log` scales are offered: Logicle's parameter estimation assumes a ~262k fluorescence range.
- **Log floor.** `log_transform` clamps values below `min_value` (1.0 for detectors), which would put every ratio < 1 on one point. `AxisScale.log_floor` carries the floor; `AxisManager` gives derived keys `DERIVED_LOG_FLOOR` (1e-6), and every transform call site gets it via `get_transform_kwargs()` / `log_transform_kwargs()` (`CoordinateMapper`, `project_to_display` for gates, `RenderTask`). Log-axis ticks are the decades within the visible range (`log_decade_tick_values`), not the fixed 10³–10⁵. The Comparisons histogram overlay has no `AxisScale`; it lowers the floor only when the pooled data's median is below 1.

## Formula language

`[channel]` references (channel name or unambiguous marker label — the service canonicalizes to channel names), numbers, `+ - * / ^ **`, unary minus, parentheses, and the whitelisted functions in `expression._FUNCTIONS`. It's parsed with `ast` and compiled to closures; user text never reaches `eval`/`pd.eval`. Limits: 500 characters, 50 channel references, nesting depth 32. To add a function, add it to `_FUNCTIONS` (name → numpy callable, arity) and a case to `tests/unit/analysis/derived/test_expression.py`.

## Events and UI

`events.DERIVED_PARAMS_CHANGED` (`{"param_id", "action"}` with `action` ∈ created/updated/deleted) is published after every sample has been re-synced:

- `HistoryRecorder` records an undo step (created/updated/deleted — not `synced`), and `MainPanelController` calls `_on_derived_params_changed` (refreshes Statistics/Comparisons pickers, hierarchy, node canvas; recomputes stats for samples with gates on an *edited* parameter).
- Each `GraphWindow` rebuilds its own axis lists — falling back to FSC-A/SSC-A if its axis was deleted, re-rendering if its axis was edited.
- The dialog refreshes its list (e.g. after undo).

The "＋ New derived parameter…" entry is a sentinel item (`NEW_DERIVED_SENTINEL`) appended by `AxisControlPanel.add_new_derived_entry()`; picking it snaps the combo back and emits `new_derived_requested(axis)` → `GraphWindow.derived_editor_requested` → `GraphManager.derived_editor_requested` → `DerivedEditorController.open_for_axis`.

Channel consumers intentionally differ: `get_fluorescence_channels()` excludes derived keys (so UMAP, compensation and the multi-channel Comparisons plots never see them); direct `fcs_data.channels` listings (axes, Statistics, single-channel Comparisons) include them.

## Academy

Course 4's derived-parameter block (`c4_d01`–`c4_d13`, plus `c4_s06a_ratio_channel`) uses `DerivedRatioExistsValidator`, `DerivedEditorClosedValidator`, `ActiveGraphDerivedAxisValidator` and `StatsDerivedChannelValidator`. They match on the saved canonical formula, not the name the learner chose. Steps inside the dialog use plain `target_widget_names`: the dialog is its own window, and since SDK 2.4.0 the Academy driver frames targets in other windows inside that window. `tests/unit/tutorials/test_course_step_graph.py` checks every course for dangling or unreachable steps.

## Tests

- `tests/unit/analysis/derived/` — expression, sync, service, integration hooks (compensation, reload, gates, templates), templates/preview, inference strategy; shared `make_fcs`/`make_sample` fixtures in its `conftest.py`.
- `tests/ui/test_derived_parameter_ui.py` — editor, dialog flows, axis-dropdown entry, controller, ribbon button, `GraphWindow`.
