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

## A3. Rolling out the rules without crying wolf

- [ ] Write each rule with an SDK unit test of minimal positive and negative fixtures, following
      the existing `tests/unit/evaluator` pattern.
- [ ] **Calibrate on real code before choosing severity.** Run every new rule over flow,
      western-blot, cytometrics and SyntheticBiology. Flow is the golden set: the rule must
      flag the instances listed in A2 (the recall check). Hand-check 20 random hits across the
      other plugins for false positives (the precision check). Ship as a warning only if
      precision is at least about 80%; otherwise ship as info.
- [ ] Commit each repo's initial baseline in the same PR that turns the hook on.
- [ ] Document each rule in the SDK's `docs/Doctor.md`, which `catalog.py` is already checked
      against.

Exit for Part A: an agent editing flow sees new findings in-turn, a commit that grows any
baseline is blocked, and `doctor` flags every A2 row on today's flow code.

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

## B4. One plot-data module, one render contract

The same math exists three times, and the copies have drifted:

- **2-D density:** `analysis/rendering.py`, `ui/graph/renderers/contour.py`,
  `comparisons/kwargs_builders.py`.
- **KDE histogram:** `ui/graph/renderers/histogram.py` and `histogram_overlay_renderer.py`. The
  comparisons copy subsamples to `_KDE_MAX_EVENTS`; the main-graph copy runs `gaussian_kde` on
  every event, which stalls at 1M events.

There are also four render paths: the SDK pipeline with `DisplayStrategy`, `ComparisonsWorker`
with `IPlotRenderer`, inline `with MPL_RASTER_LOCK:` in three widgets, and an ad-hoc task in
`population_analysis_viewer`.

- [ ] Create `analysis/plot_data.py` with `density_2d`, `histogram_1d`, `kde_curve` (one shared
      subsample cap) and `contour_levels`, and delete the copies.
- [ ] Pick one contract: `DisplayStrategy.compute/draw` on the SDK pipeline, which the main
      canvas already uses. Port `IPlotRenderer` to it.
- [ ] Key `PLOT_REGISTRY` by a stable id, not the emoji label (`"🎻  Violin Plot"`).

## B5. Get widgets out of the state object

`ViewState` holds live widget references (`_population_analysis_viewer`, `_graph_manager`,
`_sample_lens`, …, 9 in total), and the 102 Academy validators read them through 53
`getattr(obj, "_private")` calls. Renaming a private attribute silently stalls a course.

- [ ] **SDK:** let tutorial validators receive a plugin-supplied context next to the state.
- [ ] **Flow:** add a typed `AcademyContext`. Each inspected panel exposes a public read-only
      snapshot query that returns a dataclass.
- [ ] Remove the widget fields from `ViewState` (KS332 keeps them out).
- [ ] Split `tutorials/validators.py` (2712 lines) by course. Leave the course content files
      as they are.

## B6. SDK consolidation and theming (merged from the old plan's DRY and SDK-gap items)

- [ ] Migrate the remaining 23 `_apply_theme_styles` to `theme_manager.apply_style()`. These
      need case-by-case work: the hard ones branch on state or drive matplotlib. KS242 stops new
      ones appearing.
- [ ] Fold `FlowComboBox`'s one behaviour change (no text elision) into `BioComboBox` as an
      option, and migrate its 14 users.
- [ ] **SDK:** add a theme-aware matplotlib `style_axes(ax)` to replace the five copies.
      Replace the five `_section_label`s with `BioCaptionLabel`.
- [ ] **SDK:** add a generic canvas zoom-controls overlay. It replaces the two in flow
      (`node_canvas/canvas_view.py`, `gate_hierarchy/widget.py`).
- [ ] **SDK:** add a "confirm destructive action, with a details list" dialog (pattern from
      `node_canvas/canvas_view.py`'s delete preview). It is also usable by B2's delete flow.
- [ ] **SDK:** move `contrib/image_utils.py` (western-blot-specific) out of the generic SDK
      surface.
- [ ] Migrate `axis_control_panel.py` to `repopulate_combo`. This needs its external
      incremental API (`add_channel` / `set_current_x` …) redesigned first.

## B7. Split the god classes

This comes after B2–B6 on purpose, because those phases empty out much of each file.

- [ ] `ui/main_panel.py` (1649 lines, 80 methods). Target ≤ 600 lines.
      - Gate events and delete go to a `GatingController`.
      - Workflow load/save/close goes to the existing `WorkspaceIOHandler`.
      - Async startup goes to a startup sequencer.
      - Academy hooks go to the existing `AcademyWorkflowController`.
- [ ] `population_analysis_viewer.py` (1534).
- [ ] `cluster_results_panel.py` (1406).
      - Start with the ~340-line `_build_unified_statistics_tab`, which becomes its own widget.
      - Move `CopyableCanvas` / `CopyablePixmapLabel` to a shared module.
      - *(old perf plan, deferred item)* Move the Interactive Map tab onto the SDK canvas
        rather than a bespoke `CopyableCanvas`.
- [ ] `statistics_explorer.py` (1396). Use the old plan's targets: a table presenter, a chart
      renderer on the B4 contract, and an export/clipboard service.
- [ ] `spectral_learning_tab.py` (1382).
- [ ] `flow_canvas.py` (1278). Extract `GateHitTester` and move tutorial-guide drawing into an
      overlay, following the existing `gate_drawing_fsm.py` pattern.
- [ ] `graph_window.py` (909), `comparisons_viewer.py` (826).

## B8. Composition root and typing

- [ ] Replace the string-keyed `ServiceFactory.get("…") -> Any` with a frozen dataclass of
      typed services.
- [ ] Build `FlowStore`, `DerivedEditorController` and `AcademyWorkflowController` in the
      composition root (the repo's own documented rule).
- [ ] Hoist the in-function imports that only existed to break cycles. Mark deliberate startup
      ones with `# karcytics: allow KS360 - <reason>`.
- [ ] Initialise the attributes behind the 203 defensive `getattr(self, …)` reads in `__init__`.

## B9. Tests and CI (merged from both old plans)

- [x] Add `tests/contract/test_contract.py` subclassing the SDK's `ContractTestBase` (KS142).
      It runs with `--noconftest` because of the next item.
- [ ] **Stop mocking the SDK in `tests/conftest.py`.** It replaces `karcytics_sdk`, its plugin,
      components and theme modules with `MagicMock`s and dummy widgets, so the suite tests flow
      against a fake SDK: a renamed SDK API still passes, and real SDK widget/theme behaviour
      never runs. Use the real SDK on the offscreen Qt platform and fix what breaks.
- [ ] Close the coverage gaps, all still open:
      - `biology_services.py` (zero tests)
      - nested AND-of-OR-of-NOT in `DagEvaluator`
      - a dedicated `gating/subset.py` test
      - near-singular and underdetermined spillover matrices at the `analysis/compensation.py`
        level (only a UI-level test exists today)
- [ ] Do the deferred rewrites now that the code has settled: drive
      `test_comparisons_plot_types.py` through `ComparisonsWorker.run()` / `_on_render_done()`
      rather than the widget, and make `test_selection_widgets.py` headless.
- [ ] Add a coverage gate `--cov-fail-under` to the `-m "not ui"` CI lane, starting at current
      coverage minus 2 and only ever raised.
- [ ] Docstrings: remove `D100`–`D103` from `ruff.toml`'s ignore list for `analysis/` only (the
      public science API), using per-file ignores for `ui/`.
- [ ] Magic numbers (77 `PLR2004`): lift the domain ones (thresholds, bin counts, defaults) into
      `analysis/constants.py` as B3/B4 touch them; leave pixel sizes inline. The baseline
      covers the rest.
- [ ] CI hardening: pin actions to commit SHAs, add `.github/dependabot.yml` and `CODEOWNERS`.

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
