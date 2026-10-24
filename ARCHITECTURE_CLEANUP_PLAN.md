# Flow Cytometry: Architecture Cleanup Plan

Audit date: 2026-10-18, at `5b79a93`. This plan **replaces** `Code_quality_improve_plan.md`
and `SDK_Abstraction_Performance_Plan.md`. Every item still open in them is merged below, or
explicitly dropped with a reason; Appendix A accounts for each one. Delete both files once this
plan is accepted.

Resume at the first unchecked box. Every phase leaves the plugin runnable.

The plan has two parts:

- **Part A: static guardrails (SDK evaluator).** This codebase was written almost entirely by
  agents. Agents repeat whatever pattern is nearby and ignore warnings nobody enforces, so the
  durable fix is checks that run automatically, at edit time, before a flaw spreads. Part A
  comes first because without it Part B will regress.
- **Part B: the flow refactor itself.**

---

## Why: the numbers

| | When the old plans were written | Now |
| --- | --- | --- |
| Plugin source | ~40k lines | **67.8k lines / 242 files** |
| `ui/` vs `analysis/` | — | **31k vs 8k** (plus tutorials 11.5k) |
| `main_panel.py` | 1176 (flagged "split this") | **1649**, 80 methods |
| `cluster_results_panel.py` | 1163 (flagged) | **1406** |
| `spectral_learning_tab.py` | 1011 (flagged) | **1382** |
| `population_analysis_viewer.py` | 1348 (flagged) | **1534** |
| Hand-written `_apply_theme_styles` | ~18 left to migrate | **23** |
| `FlowComboBox` (duplicate of `BioComboBox`) users | 10 | **14** |

Each of these was identified, planned, and then got worse. The cause isn't missing rules:
`karcytics-sdk doctor` already flags `FlowComboBox` (KS211) and the raw QSS (KS241). The
evaluator just never reaches the agent:

- **`doctor` runs nowhere in this repo.** It is not in pre-commit. CI runs
  `karcytics-sdk evaluate`, which is a different command.
- Even when run by hand, warnings never fail anything. Today that is 324 warnings, ignored.
- It has no per-file mode, so it can't give feedback in the edit loop. Its only mode is a scan
  of the whole repo.
- It has no rules at all for size, layering, duplication, dead code, or test quality.

Other baselines used below:

- 331 in-function imports
- 203 defensive `getattr(self, …)` / `hasattr(self, …)`
- 249 `noqa` (105 of them complexity, 77 `PLR2004`)
- 125 `type: ignore`
- 52 private reach-throughs (`self._a._b`)
- 48 debug traces at WARNING level
- 8 classes with only static methods
- 8 tests with no assertion

### What is already right (keep it)

- `analysis/` has no direct PySide6 imports and never imports `ui/` or `tutorials/`.
- Serialization is consolidated in `analysis/workspace_document.py`, a model for Phases B3–B4.
- The gate hierarchy is real polymorphism, and the stats and transform registries are good OCP.
- The SDK's `catalog.py` approach ("the SDK provides this, use it") is right. It only needs more
  rows and enforcement.

---

# Part A — Static guardrails for agentic development

## A1. Get the evaluator into the loop (the real gap)

Feedback should arrive at three points: edit time, so the agent fixes it right away; commit
time, as the gate; and CI, as the backstop.

- [x] **SDK: `doctor --files <paths>`.** Runs the per-file rules on just the given files.
- [x] **SDK: `--baseline` / `--update-baseline` / `--reset-baseline`.** `.karcytics-baseline.json`
      records counts per file and rule (and measurements for the size rules). A count may go
      down but never up; `--update-baseline` only ever tightens it.
- [x] **SDK: suppressions need a reason** (`# noqa: X - why`, `# type: ignore[x]  # why`,
      `# karcytics: allow KSxxx - why`); one without a reason is KS310.
- [x] **Flow: Claude Code `PostToolUse` hook** running `uv run karcytics-sdk doctor --claude-hook`
      in `.claude/settings.json`, now tracked in git (the rest of `.claude/` stays ignored).
- [x] **Flow: pre-commit** `karcytics-doctor` (`karcytics-sdk doctor . --baseline`) plus a
      `contract-test` hook.
- [x] **Flow: CI** runs the same doctor command and the contract test in the lint job.
- [x] **Flow `CLAUDE.md`:** fix findings rather than suppress them; `--update-baseline` only
      after a count went down.

## A2. New rules, one per flaw found in this audit

Each row is a flaw this audit found, with its evidence in flow. Prefer off-the-shelf tools where
they exist, and write custom AST rules only for Karcytics-specific conventions. All new rules
start as warnings under the baseline ratchet.

| # | Agentic failure mode | Evidence in flow | Rule | Implementation |
| --- | --- | --- | --- | --- |
| 1 | Files and classes grow without limit | god classes +20–40% after being flagged | **KS300** file > 600 lines; **KS301** class > 30 methods; **KS302** function > 80 lines | custom AST, ratcheted |
| 2 | Suppress instead of fix | 249 `noqa`, 125 `type: ignore` | **KS310** a suppression without a reason (counts ratcheted by the baseline) | custom |
| 3 | Reinvent a helper that already exists | `_style_axes` ×5, `_section_label` ×5, KDE ×2, stats via if/elif in `data_extractor` | **KS320** the same private helper with a similar body in ≥ 2 modules; **KS321** clone function bodies (local names normalised, ≥ 8 statements) | custom AST |
| 4 | Ignore an SDK equivalent | 23 hand-written `_apply_theme_styles`, `FlowComboBox` | **KS242** an f-string stylesheet interpolating `Colors.`/`Fonts.` → `theme_manager.apply_style`; **KS243** a `clear()` + `addItem` loop on a combo → `repopulate_combo` (KS241 stayed info) | catalog rows + custom |
| 5 | Leaks across the UI/analysis layer | `Debouncer` (Qt `QTimer`) in `analysis/gate_propagator.py`; 12 direct `apply_hierarchy` calls and 33 raw `fcs_data.events` reads in `ui/`; widgets stored on `FlowState` | **KS205** a Qt-backed SDK export in `analysis/` (`QT_BACKED_SDK_EXPORTS` in `catalog.py`); **KS330** a `ui/` module with no Qt use (info: "belongs in analysis/"); **KS331** calls reserved to `analysis/`, per plugin, from `[tool.karcytics.evaluator] analysis_only`; **KS332** a `QWidget`-typed or `Any` widget field on a `PluginState` subclass | custom |
| 6 | Pass-through layers and "service" classes | `GateCoordinator` (mostly one-line forwards); 8 classes with only static methods | **KS340** class where ≥ 60% (and ≥ 5) of methods only forward to a `self` attribute; **KS341** class with only `@staticmethod`s → module functions | custom AST |
| 7 | Reaching into private attributes | 52 `self._a._b`; 53 `getattr(obj, "_private")` in `tutorials/validators.py` | **KS342** a `x._a._b` chain or `getattr(non-self, "_name")` | custom AST |
| 8 | Defensive attribute probing | 203 `getattr(self, "x", default)` / `hasattr(self, …)`, some on attributes never set in `__init__` | **KS343** `getattr`/`hasattr` on `self` → initialise in `__init__` | custom AST |
| 9 | Branching on type names instead of polymorphism | `type(gate).__name__ == "QuadrantGate"` | **KS344** comparing `type(x).__name__` or `__class__.__name__` | custom AST |
| 10 | Dead code left behind | `GATE_STATS_UPDATED` published 6×, 0 subscribers; 6 unused topics; unused Protocol; unused widget; empty package | **KS350** a topic published but never mentioned elsewhere; **KS351** a topic constant never used | custom (bus topics) |
| 11 | Import-cycle workarounds | 331 in-function imports | **KS360** an in-function import (ratcheted; a deliberate one carries `# karcytics: allow KS360 - why`) | custom |
| 12 | Debug noise | 48 `logger.warning("[tag] …")` | **KS361** a WARNING/ERROR log whose message starts with a `[TAG]` | custom |
| 13 | Changelog written into code | comments citing "Priority 1 analysis #3", paragraphs of history inside handlers | **KS362** (info) a comment referencing plan items (`Priority N`, `#N analysis`, `(Done)`) | custom regex, info only |
| 14 | Tests that test nothing | 8 tests with no assertion; old plan's hasattr/isinstance-only tests; `patch.object(Cls, "signal")` intercepts nothing under PySide6 | **KS370** a test with no assert or `raises`; **KS371** a test whose only asserts are `isinstance` / `hasattr` / `is not None`; **KS372** `patch.object` on a Signal attribute | `test_rules.py` |
| 15 | Missing contract test | KS142 has fired for months | promote **KS142** to an error for plugins | registry change |

Explicitly **not** rules: comment density, line-length-style taste, naming. These are too noisy,
and an agent will game them.

## A3. Rolling out the rules — done

- [x] Each rule has SDK unit tests with positive and negative fixtures (`tests/unit/evaluator`).
- [x] Calibration was replaced by the baseline ratchet: every rule ships as a warning, existing
      hits are recorded in each repo's `.karcytics-baseline.json`, and only growth blocks a
      commit. False positives found on flow were fixed in the SDK (5de18e1, 559ee55).
- [x] Flow's baseline was committed with the hook (f5bf3ca).
- [x] All 71 rules are documented in the SDK's `docs/Doctor.md`.

Exit for Part A is met: findings show in-turn through the Claude hook, pre-commit and CI block
growth, and the doctor flags the A2 rows on flow.

---

# Part B — Flow refactor

Each phase also ratchets the baseline down once it lands.

## B1. Delete what's dead — done

- [x] ~~Remove the 6 `GATE_STATS_UPDATED` publishes~~ — **kept**: `MainPanelController`
      subscribed to it by raw string, so it was live. Every topic is now a constant in
      `analysis/events.py` (raw-string uses replaced), and the SDK's KS350/KS351 now resolve
      string literals to their topic.
- [x] Remove the 6 unused topics, plus `AXIS_UPDATED` (published, never handled) and
      `set_scale`'s `notify` flag.
- [x] Delete `IWorkflowPersistence`, `ui/widgets/marker_panel.py`, the empty `ui/onboarding/`.
- [x] Drop the `_gate_controller` alias; the `[phaseN]`/diagnostic traces log at `debug`.
- [x] Fix the structure section of `CLAUDE.md`.
- [x] Give the 8 hollow tests real assertions (2 of the doctor's hits were false positives,
      fixed in the SDK: a `test_*` fixture, and `qtbot.waitSignal` as an assertion).
- [x] Delete the two superseded plan files.

## B2. Collapse the gating service stack — done

- [x] `GateCoordinator` absorbed `GateMutationService`, `GateSelectionService`,
      `GateEventPublisher` and `StatsService`; no sub-service holds a reference back to it.
- [x] The static classes (`GateModifier`, `PopulationSplitter`, `NamingService`,
      `GatingService`) became module functions in `analysis/gating/tree_edits.py`, plus
      `remove_subtree` (the single removal; `PopulationService` is now read-only).
- [x] `GatePropagator.find_targets` is public; its unused `_parent` argument is gone.
- [x] `GateNode.iter_dag()` already was the shared walker; the hand-written walkers in
      `main_panel`, `population_service`, naming, `find_nodes_by_gate` and the quadrant
      validators now use it.
- [x] `dag_evaluator` is module functions; `evaluate`/`evaluate_scoped` share one walk and
      `GateNode.combine_parent_masks` (one AND/OR/NOT implementation). It deliberately does
      **not** write masks into `GateNode`'s cache: it runs on a worker thread, and a gate edit
      during the run would get its fresh cache overwritten with a stale mask.
- [x] Multi-sample delete moved to `GateCoordinator.delete_gate` (+ `populations_under_gate`
      for the pre-delete graph switch); `remove_subtree` reports only nodes actually gone, so a
      logic node that survives through another parent keeps its graph open.
- [x] `type(gate).__name__ == "QuadrantGate"` → `Gate.takes_population_name`; the
      validators' `QuadrantSubGate` name checks → `isinstance`.
- [x] `add_population`'s `node | list` return is gone with `add_population` itself.
- [x] `IGateCoordinator` / `IPopulationService` deleted (one implementation each, no test
      seam); the UI type-hints the concrete classes.

## B3. Make `analysis/` the only route to event data — done

- [x] One gateway in `analysis/population_service.py`: `population_events(experiment, sample,
      node)`, `channel_values(...)` and `uncompensated_events(sample)`, all with the
      derived-column sync. All 12 `apply_hierarchy` calls and 33 raw `fcs_data.events` /
      `raw_events` reads outside `analysis/` (13 files) go through it.
- [x] `data_extractor` moved to `analysis/comparison_data.py`; its statistics use
      `statistics.value_statistic` (the shared registry) instead of an if/elif chain. Its class
      API stays until B4 reworks the comparisons render contract.
- [x] `ui/widgets/matrix_sources.py` → `analysis/compensation_sources.py`, Qt-free: `obtain()`
      takes an `ask_path(title, filter)` callable the view supplies.
- [x] `attachment_manager.py` and `scope_resolution.py` moved into `analysis/`.
- [x] KS331 on for flow: `analysis_only = ["apply_hierarchy", "fcs_data.events",
      "fcs_data.raw_events"]`.
- [ ] **Moved out of B3:** the 7 KS205 hits (Qt-backed SDK objects in `analysis/`: the
      propagator's `Debouncer`, the FCS/UMAP/PhenoGraph `PluginDaemon` use, `UmapService`'s
      `AnalysisWorker`). Fixing them means moving scheduling out of `analysis/`; do it with B8's
      composition-root work.

Not moved: `GateEditor` / `GateFactory` / `CoordinateMapper`. They are interaction geometry,
not science.

## B4. One plot-data module, one render contract — done

The same math exists three times, and the copies have drifted:

- **2-D density:** `analysis/rendering.py`, `ui/graph/renderers/contour.py`,
  `comparisons/kwargs_builders.py`.
- **KDE histogram:** `ui/graph/renderers/histogram.py` and `histogram_overlay_renderer.py`. The
  comparisons copy subsamples to `_KDE_MAX_EVENTS`; the main-graph copy runs `gaussian_kde` on
  every event, which stalls at 1M events.

There are also four render paths: the SDK pipeline with `DisplayStrategy`, `ComparisonsWorker`
with `IPlotRenderer`, inline `with MPL_RASTER_LOCK:` in three widgets, and an ad-hoc task in
`population_analysis_viewer`.

- [x] The plot math lives in `analysis/rendering.py` (kept its name: seven importers and the
      baseline already point at it): `kde_curve` (one `KDE_MAX_EVENTS` cap, fitted on a
      `stable_subsample_mask` subsample), `histogram_curve`, `density_grid`, `contour_levels`.
      The main-graph KDE is capped now (1M events: 0.98 s → 0.03 s per redraw); the comparisons
      copies and the dead `compute_1d_histogram` are gone. The 2-D pseudocolor density was
      already shared — the comparisons overlay uses `compute_pseudocolor_base_density`.
- [x] ~~Port `IPlotRenderer` to `DisplayStrategy`~~ — **not done, on purpose.** Both already
      split heavy compute (off `MPL_RASTER_LOCK`) from drawing (under it), which was the point.
      They differ in scope: `DisplayStrategy` draws one dataset onto an axes the canvas pipeline
      owns; an `IPlotRenderer` builds a whole figure (ridge subplots, polar radar, heatmap with
      colorbar), which "draw onto this axes" cannot express. The real stragglers are the widgets
      that build charts inline on the GUI thread (`statistics_explorer`, the cluster panels,
      `compensation_preview`); each moves onto `IPlotRenderer` when B7 splits it.
- [x] `PLOT_REGISTRY` is keyed by `PlotType` (a `StrEnum`); the emoji text is `PlotTypeSpec.label`.
      The combo carries the id as item data, `ComparisonsViewer.current_plot_type()` returns it,
      and the Course 6 validators compare ids instead of substrings of the label.

> **Re-baselined 2026-10-21** (flow `5f31335`, SDK `9f47022`) after B1–B4 and the SDK's
> 2026-10-18 additions. Numbers below are re-measured; the SDK half of B5 and B6 already exists.
> Recommended order: **B9a → B5 → B6 → B8 → B7 → B9b**, pausing for review after each chunk.

## B9a. Run the tests against the real SDK — done

`tests/conftest.py` used to replace `karcytics_sdk`, `.plugin`, `.components`, `.tasks`,
`.events` and `.workflow` with `MagicMock`s and dummy widgets (362 lines). Now it sets the
offscreen platform and a test-only plugin id, and keeps the frames the SDK would send the Hub.

- [x] The real SDK runs under every test. Only 7 tests and 3 setup errors broke out of 1,489:
      five asserted on calls to the fake bus/signals (now: real slots, or a `wraps=` spy),
      two leaned on the fake theme or the deleted dummy `PluginBase`.
- [x] The setup errors were a real SDK bug the mocks hid: `LayeredMatplotlibCanvas` connected
      its render worker to lambdas, so a render finishing after the canvas was deleted emitted
      on a dead object. Fixed in the SDK with a regression test.
- [x] A second hidden bug surfaced when the whole suite ran in one process: the SDK's task
      scheduler kept Qt's default 512 KB thread stack (macOS), and `numpy.linalg.inv` inside the
      compensation-preview render task overflowed it (SIGBUS). The SDK scheduler now gives pool
      threads 16 MB. (The Hub's in-process scheduler is not changed: in-process plugins are
      being retired.)
- [x] The fake `karcytics` (Hub) module is gone.
- [x] The contract test runs with the unit tests (pre-commit) and the main CI test step.
- [x] `test_ui_daemon.py` uses the SDK's `spawn_ui_daemon`; the SDK harness gained
      `PYTHONFAULTHANDLER` and `DaemonIO.finished_stderr()` for it.

## B5. Get widgets out of the state object

The SDK half is done (9e0fe91): `PluginBase.academy_context()`, and `IValidator.check()` /
`describe()` receive it. Flow does not use it yet.

`ViewState` holds 9 widget references (KS332: `_graph_manager`, `_pipeline_ribbon`,
`_spectral_viewer`, `_statistics_explorer`, `_comparisons_viewer`, `_compensation_view`,
`_population_analysis_viewer`, `_sample_lens`, `_derived_editor`). `tutorials/validators.py`
is 2,733 lines with 102 validator classes, and reaches widgets' private attributes throughout.

- [x] B5.1: a typed `AcademyContext` (`ui/academy_context.py`) returned by the panel's
      `academy_context()`; the workspace builder fills it as Phase 2 builds each tab. Widget
      validators derive from `FlowUIValidator` and implement `validate_ui(state, ui)`; `AllOf`
      forwards the context. The 9 widget fields are gone from `ViewState`.
- [x] B5.2: validators and course text callbacks read only public widget state. Widgets with
      several things to check return an `academy_snapshot()` (frozen dataclasses in
      `ui/academy_context.py`); the rest gained a property (`SampleLensTab.model`,
      `GraphWindow.axis_panel`, `PipelineRibbon.orientation_label`, ...). Academy corrections
      act through `AcademyContext.gate_coordinator` and the panel's public delete. KS342 under
      `tutorials/` went from 133 to 0; three widgets each gained one method (accepted in the
      baseline). The rewritten checks gained tests against real widgets.
- [x] Split `tutorials/validators.py` into a `tutorials/validators/` package by topic, not by
      course file: most checks are shared (`TabActiveValidator` by 7 courses, `GateShapeValidator`
      by 4). Modules: base, setup, gating, checkpoints (composite prerequisite checks; they sit
      above setup and gating, which broke the only import cycle), compensation, clustering,
      reports, derived, lens. Largest is gating (~710 lines). Importers name the module directly;
      no re-exporting `__init__`. Dropped the write-only `_TUTORIAL_STATE` global.

## B6. Adopt the SDK's shared pieces

The SDK side is done (332a609, 45a925f): `rendering.style_axes` / `AxesColors`,
`ZoomControls`, `dialogs.confirm_destructive`, `BioComboBox(fit_contents=True)`, and
`image_utils` deprecated. What is left is flow's migration:

- [x] Five local axes stylers → `style_axes` (`spectral_learning_tab`, `spectral_viewer`, and the
      violin, heatmap and pseudocolor-overlay renderers).
- [x] Five `_section_label`s → the SDK's new `BioSectionLabel` (SDK 556c172), not
      `BioCaptionLabel`, which is a word-wrapped hint, not a heading.
- [x] `FlowComboBox` (13 users) → `BioComboBox(fit_contents=True)`; delete `styled_combo.py`.
- [x] Zoom overlays in `node_canvas/canvas_view.py` and `gate_hierarchy/` → `ZoomControls` (the
      Pan toggle rides along as a `BioToggleButton` extra).
- [x] Deletes that affect other items → `confirm_destructive`: the Pipeline canvas's three
      hand-built list dialogs (delete with children, rename in several samples, delete a
      connection). The gating panel's gate delete already asks through its scope dialog, so it
      keeps that rather than a second prompt.
- [x] The 7 hand-rebuilt combos (KS243) → `repopulate_combo`. `AxisControlPanel` swaps its
      `clear_combos` / `add_channel` / `add_new_derived_entry` sequence for one
      `set_channels(channels, derived_entry=)`. Needed SDK 1a69e0a: `restore_data=None` used to
      mean "leave it", so an "All events" (None) item could not be reselected.
- [x] `_apply_theme_styles` → `theme_manager.apply_style()` where the stylesheet is static:
      `GraphManager`, `FloatingGridPopup` and both subclasses (whose overrides are gone), and the
      UMAP caption. What is left re-renders plots or repaints, or belongs to a B7 god class
      (`main_panel`, `population_analysis_viewer`, `statistics_explorer`, `comparisons_viewer`,
      `spectral_viewer`, `cluster_results_panel`); those go with their split.

Not in scope here: the bulk theming debt (216 hard-coded colours KS240, 173 hand-built
stylesheets KS242, 76 raw Qt widgets KS210, 18 raw dialogs KS220). The ratchet stops growth;
each file pays its share when B7 splits it.

## B7. Split the god classes

Comes after B5/B6, which empty out much of each file. Sizes today:

- [ ] `ui/main_panel.py` (1,623). Target ≤ 600: gate events and delete → a `GatingController`;
      workflow load/save/close → `WorkspaceIOHandler`; async startup → a startup sequencer;
      Academy hooks → `AcademyWorkflowController`, which then takes that workflow-document
      interface instead of the whole panel and is built in the composition root (from B8).
      Done so far: `GatingController` owns gate events, selection and delete (8664dd5);
      `WorkflowDocument` (in `FlowServices`) owns the open workflow's name, metadata and
      save/load state and the unsaved-changes prompts, so `WorkspaceIOHandler` and
      `AcademyWorkflowController` take it instead of panel privates. The dead
      `handle_load` / `load_from_pm` / `load_standalone` paths went with it. SDK gap: no
      three-way Save/Discard/Cancel dialog, so that prompt keeps a raw `QMessageBox` (KS220 allow).
      `StartupSequencer` runs Phase 2 and the Ready Gate handshake (334f599). The panel's
      Hub-bus Academy hooks (`ACADEMY_COURSE_PREPARE_PROJECT` / `_COMPLETED`) were dead (the
      Hub never emits them) and are gone; `AcademyWorkflowController` takes the document and
      IO handler and uses the panel's public `current_tab` / `show_tab`. It stays built by the
      panel, not `build_services()`, to keep it off the Phase 1 import path.
- [ ] `population_analysis_viewer.py` (1,527).
- [ ] `cluster_results_panel.py` (1,406): the ~340-line `_build_unified_statistics_tab` becomes
      its own widget; `CopyableCanvas` / `CopyablePixmapLabel` to a shared module; the
      Interactive Map tab onto the SDK canvas.
- [ ] `spectral_learning_tab.py` (1,382).
- [ ] `statistics_explorer.py` (1,378): table presenter, chart on `IPlotRenderer` (see B4),
      export/clipboard service.
- [ ] `flow_canvas.py` (1,278): extract `GateHitTester`; tutorial-guide drawing into an overlay
      (the `gate_drawing_fsm.py` pattern).
- [ ] `analysis/compensation_sources.py` (995, moved in B3): one module per matrix source.
- [ ] `graph_window.py` (901), `comparisons_viewer.py` (825).
- [ ] Charts built inline on the GUI thread move onto `IPlotRenderer` as their widget is split:
      `statistics_explorer`, `cluster_results_panel`, `cluster_map_view`,
      `compensation_preview`.

## B8. Composition root and typing — done

- [x] Replace the string-keyed `ServiceFactory.get("…") -> Any` (20 call sites) with a frozen
      dataclass of typed services. `build_services()` returns `FlowServices`; the panel keeps it
      as `panel.services`, and its eight per-service aliases are gone.
- [x] Build `FlowStore` and `DerivedEditorController` in the composition root.
      `AcademyWorkflowController` moved to B7: it reads seven of the panel's private fields
      (workflow filename/metadata, `_close_after_save`, tab bar…), so it needs the narrow
      workflow-document interface that B7's main_panel split creates.
- [x] Move scheduling out of `analysis/` (KS205, 7: the propagator's `Debouncer`, the
      FCS/UMAP/PhenoGraph `PluginDaemon` use, `UmapService`'s `AnalysisWorker`) and replace the
      hand-rolled FCS warm-up thread (KS231).
  - [x] The worker process: `analysis/daemon_port.py` holds a Qt-free `DaemonCall` protocol
        (and the array wire format); fcs_io, UMAP and PhenoGraph take one. The real one is
        `ui/services/flow_daemon.py`, which also starts the worker through `task_scheduler`
        instead of a hand-rolled thread. fcs_io's `_daemon_lock` went: `PluginDaemon` already
        takes one call at a time. Tests pass `tests.fixtures.daemon.in_process_daemon`, which
        runs the worker's handlers in-process, instead of monkeypatching `compute`.
  - [x] The schedulers: `GatePropagator` (its `Debouncer`), `UmapService` and
        `DataLoaderService` moved to `ui/services/`. The composition root builds the propagator
        and hands it to `GateCoordinator`, which knows it only as `analysis.propagation.Propagation`;
        which samples a change reaches is the pure `propagation_targets()` there. Re-compensating
        a reloaded sample (written twice in the loader, flagged KS331 once it left `analysis/`)
        is now `Sample.adopt_reloaded_data()`. KS205 and KS231 are at 0.
  - Not moved: the tutorial download thread (`tutorial_assets.py`) keeps its daemon thread,
    with a stated reason. It is minutes of downloads with retry sleeps; on the task pool it
    would hold a pool thread, and Qt waits for the pool at quit. `GateCoordinator` still
    submits its statistics jobs to `task_scheduler` itself (the rule does not count that); it
    goes when B7 splits the coordinator's callers.
- [x] Hoist the in-function imports that only broke cycles (KS360: 406). Mark deliberate
      startup ones `# karcytics: allow KS360 - <reason>`. KS360 went 370 → 60. About 330 were
      hoisted. Each hoist had to pass two checks: every module still imports when it is the
      first one loaded, and importing the panel (the Phase 1 path) pulls in no new modules;
      main_panel's imports were tried one at a time. The deliberate ones carry a reason: the plugin's
      phased startup (one file-level allow each in `__init__.py` and `ui_daemon.py`), Phase 2 modules kept off Phase 1 (main_panel,
      the derived-editor dialog) and heavy libraries loaded on first use (matplotlib, scipy,
      numba…). The 60 left are real cycles, so they stay counted, not hidden: gates ↔
      `GateNode` (`analysis/gating`), `analysis/state` ↔ `workspace_document`, and the graph
      window / canvas layers ↔ the workspace builder. They go with B7's splits.
- [x] Initialise in `__init__` the attributes behind the 142 `getattr`/`hasattr(self, …)` reads
      (KS343: 136). KS343 went 121 → 12. Each attribute got a real default (or `None` where it
      is built later) and a direct read. Some probes guarded nothing and went with their dead
      code: widgets never assigned (`_seed_spin`, `_cluster_panel`, `_detector_list`,
      `_run_name_edit`, `_startup_stats_cb`), `FlowCanvas._dirty`, which nothing sets, and
      re-theme calls on SDK widgets that theme themselves. The FSM's seven copies of a
      busy-retry throttle became one `_RetryWhenFree`. The 12 left are main_panel's Phase 2
      widgets (`_graph_manager`, `_sample_list`…), which the builder attaches later; making
      them Optional would put a `None` check before 50+ uses, so they go with B7's main_panel
      split.

## B9b. Tests and CI, the rest

- [x] `tests/contract/test_contract.py` subclasses the SDK's `ContractTestBase` (KS142).
- [ ] Coverage gaps, all still open: `biology_services.py` (zero tests); nested AND-of-OR-of-NOT
      in the DAG evaluator; a dedicated `gating/subset.py` test; near-singular and
      underdetermined spillover matrices at the `analysis/compensation.py` level.
- [ ] Deferred rewrites: drive `test_comparisons_plot_types.py` through
      `ComparisonsWorker.run()` / `_on_render_done()`, and make `test_selection_widgets.py`
      headless.
- [ ] Coverage gate `--cov-fail-under` on the `-m "not ui"` CI lane (current minus 2, raise only).
- [ ] Docstrings required in `analysis/` only (drop D100–D103 there; per-file ignores for `ui/`).
- [ ] Domain magic numbers (77 `PLR2004`) into `analysis/constants.py`; pixel sizes stay inline.
- [ ] Reasons on suppressions (KS310: 335), file by file as each is touched.
- [ ] CI hardening: pin `deploy-docs.yml`'s actions to SHAs (`release.yml` is partly pinned),
      add `.github/dependabot.yml` and `CODEOWNERS`.

---

## Things to avoid (guardrails for this plan itself)

- No Protocol or ABC for anything with one implementation.
- Split along real responsibilities, not to get under a number. The ratchet stops growth; it
  doesn't demand splits.
- Don't abstract the course content.
- Don't move interaction geometry into `analysis/` for purity's sake.

---

## Appendix A — Where every open item from the old plans went

**From `SDK_Abstraction_Performance_Plan.md`**

| Old item | Status |
| --- | --- |
| P0 (all 9 items), P1 analysis #1/#3/#4/#7, P1 UI #1 gallery/#2/#3/#4 | Done; nothing to carry |
| P1 analysis #5 (UMAP twice), #6 (id→node index) | Closed as intentional / not worth it; not carried |
| P1 analysis #2 remainder: two mask walkers | **B2** |
| P1 UI #1 remainder: Interactive Map tab | **B7** (`cluster_results_panel`) |
| P1 UI #4 remainder: `axis_control_panel` | **B6** |
| P2 god classes: `StatisticsExplorer`, `flow_canvas`, `cluster_results_panel` targets | **B7**, extraction targets kept |
| P2 remaining `_apply_theme_styles` (now 23) | **B6** + rule KS242 |
| P2 `FlowComboBox` duplicate (now 14 users) | **B6** + rule KS211 enforced |
| P2 duplicate zoom-controls overlays | **B6** |
| P2 `marker_panel.py` dead code | **B1** |
| P3 SDK gaps #3 zoom overlay, #4 destructive-confirm dialog, #5 `image_utils` | **B6** |
| P4 deferred test rewrites | **B9** |
| P4 coverage gaps 2–5 | **B9** |
| P4 contract test | **B9** + KS142 promoted to error |
| P4 "assert behaviour, not existence" for UI tests | rules KS370/KS371 |

**From `Code_quality_improve_plan.md`**

| Old item | Status |
| --- | --- |
| Ph 1 ruff/mypy zero, no `print()` | Done |
| Ph 2 suppression targets (noqa ≤ 40, type: ignore ≤ 20) | Replaced by the KS310 rule and the baseline ratchet plus root-cause fixes in B2–B8. The ratchet only goes down, so the old absolute targets remain the direction. |
| Ph 5 god classes | **B7** |
| Ph 6 magic numbers | **B9**, domain constants only |
| Ph 8: `ruff format` in pre-commit | Already done (`ruff-formatter` hook) |
| Ph 8: coverage gate, SHA pinning, `CODEOWNERS`, Dependabot | **B9** |
| Ph 3: docstrings everywhere | **Changed:** enforced for `analysis/` only (B9). Docstrings generated in bulk for 290 UI methods would be noise. |
| Ph 0 / Ph 7: CodeRabbit full-repo review (empty-root-commit PR, `.coderabbit.yaml` tuning) | **Dropped.** Plugin repos commit straight to `main` with no PRs, and Part A gives deterministic, repeatable coverage of the same smells on every edit, not one review pass. Revisit after Part B if a one-off architectural second opinion is wanted. |
| Ph 4: CodeRabbit-generated unit-test stubs | **Dropped.** Generated stubs are the main source of assertion-free and existence-only tests (KS370/KS371). Real coverage gaps are listed in B9 instead. |
