# Flow Cytometry: SDK Abstraction, Performance & Test-Focus Plan

## Goal

This is a companion to `Code_quality_improve_plan.md` (which covers lint/docstring/CodeRabbit
hygiene). That plan is about **noise reduction**. This one is about **substance**: is the
40k-line flow module using the SDK's abstractions well, is the computational core efficient at
real sample sizes (tens of thousands to millions of events), does the architecture hold up to
SOLID/DRY, and does the test suite protect the parts of the codebase that are actually stable
(the science) instead of the parts still being redesigned (the UI).

Produced by a 4-way parallel review: SDK abstraction audit, analysis-layer review (~9.1k lines),
UI-layer review (~30.8k lines), and test-suite composition review. Findings are cited with
file:line so they're directly actionable.

**Overall verdict up front:** the architecture is sound where it matters most — background work
genuinely goes through the SDK's `AnalysisBase`/`task_scheduler`/`worker_thread`/`managed_task`
infra (no raw `QThread` subclasses exist anywhere in the plugin), the gate hierarchy uses real
polymorphism, and the composition-root/builder/controller layer is well-engineered. The problems
concentrate in three places: (1) a handful of hot-path performance bugs in gate-mask evaluation,
(2) widget-layer God classes that mix rendering/data-fetching/state, each reimplementing SDK
theming/combo/canvas primitives instead of using them, and (3) a test suite where ~2,563 lines in
`tests/ui/` (and a smaller slice of `tests/unit/ui/`) test widget mechanics rather than logic,
diluting signal exactly where the owner doesn't want investment right now.

---

## Priority 0 — Do these first (mechanical, low-risk, high or immediate payoff)

| # | Fix | File:line | Why first |
|---|---|---|---|
| 1 | Drop the redundant `.copy()` after boolean-indexed DataFrame slices | `gating/base.py:71`, `gating/gate_node.py:178`, `statistics_analysis.py:91`, `compute/dag_evaluator.py:80` | Boolean indexing already allocates a new frame; the second copy is pure waste on every gate/render/stats call, over potentially millions of rows |
| 2 | Drop unconditional `gc.collect()` after every render task | `graph/render_task.py:312-314` | Runs on every pan/zoom/thumbnail redraw; forces a full GC pass and can stall the worker pool that's supposed to keep the UI responsive |
| 3 | Fix CI to stop gating merges on `tests/ui/` | `.github/workflows/release.yml:231` | `pytest.mark.ui` exists and is applied but CI runs `pytest tests/` with no `-m` filter, so UI-mechanics tests already block PRs today despite the marker existing to prevent that |
| 4 | Delete the dead test file | `tests/unit/analysis/test_stats.py` | Entire file is one comment, no test — currently reads as coverage that doesn't exist |
| 5 | Rewrite the assertion-free "test" | `tests/unit/ui/test_layout.py::test_layout_computation` | Calls `NodeTreeEngine().compute(root)` and only `print()`s the result — zero assertions, false confidence on gate-hierarchy layout |
| 6 | Fix duplicate `@dataclass` decorator | `analysis/config.py:220-221` | Harmless but a lint-blind-spot marker; two-line fix |
| 7 | Promote `LockedFigureCanvas` into the SDK as a standalone class next to `LayeredMatplotlibCanvas` | SDK: `plugin/rendering/mpl_canvas.py`; plugin: `ui/graph/_mpl_compat.py:9-53` | Already a clean, self-contained ~50-line class; flow independently re-derived a sip-deleted race-condition fix the SDK doesn't have yet. Highest payoff-to-effort ratio in the whole review |
| 8 | Replace the ~35 raw `QMessageBox.*` calls with `dialogs.show_info/show_warning/show_error/ask_yes_no` | Heaviest: `ui/ribbons/workspace_ribbon.py` (10), `ui/ribbons/compensation_ribbon.py` (12); also `main_panel.py`, `sample_list.py`, `groups_panel.py`, `bulk_role_dialog.py`, `node_canvas/canvas_view.py`, `graph/render_window.py` | Mechanical find/replace; `dialogs.py` already handles parent stay-on-top propagation these call sites reimplement inconsistently |
| 9 | Delete `ui/dialogs/save_workflow_dialog.py`, import the SDK's `SaveWorkflowDialog` instead | `ui/dialogs/save_workflow_dialog.py` is byte-identical (diff shows only whitespace) to `karcytics_sdk/plugin/dialogs.py:289-337` | Zero-risk deletion of a confirmed exact duplicate |

---

## Priority 1 — Performance (analysis layer hot paths)

The offload architecture itself is sound (heavy work already goes through `AnalysisBase` +
`task_scheduler`), so these are about wasted work *inside* the background paths, not missing
threading.

1. **No memoization of ancestor gate masks.** `GateNode._get_mask`/`apply_hierarchy`
   (`gating/gate_node.py:149-178`) recompute the full ancestor chain from raw events on every
   call, with call sites in nearly every UI refresh path (`render_window.py:74`,
   `graph_window.py:467,519`, `statistics_explorer.py:669,689,696`,
   `comparisons/data_extractor.py:42,68,137`, `population_analysis_viewer.py:842,1075`,
   `umap_analysis.py:109`). The codebase already has the right pattern —
   `compute/dag_evaluator.py`'s `DagEvaluator.evaluate` does topologically-ordered BFS with a
   memoized `evaluated_masks` dict — it's just not used by these call sites.
   **Fix:** route these callers through `DagEvaluator`-style memoized evaluation, or cache masks
   per node keyed on a data-version token.

2. **Three independent tree-walk implementations that will drift.** `GateNode._get_mask` (naive,
   no memo), `DagEvaluator.evaluate` (BFS + memo), and `StatisticsAnalysis._walk_and_compute`
   (`statistics_analysis.py:69-143`, its own recursive walker) all compute conceptually the same
   thing at different speeds. **Fix:** make `StatisticsAnalysis` delegate to `DagEvaluator`.

3. **Every gate edit triggers a full-tree stats recompute.** `services/gate_mutation_service.py`
   (lines 64, 188, 231, 260, 284, 369) unconditionally calls
   `self._coordinator.recompute_all_stats(sample_id)`, walking every node even when only one
   leaf's subtree changed. **Fix:** scope recompute to the mutated node's descendants and any
   logic nodes referencing it.

4. **Double in-memory copy of every loaded sample.** `fcs_io.py:281` and `fcs_io.py:751` both
   unconditionally copy the full event DataFrame to preserve pre-compensation values — every
   loaded sample permanently holds two full float64 copies. **Fix:** materialize `raw_events`
   lazily on first compensation, or store as a diff.

5. **UMAP computed twice for the animation flow** (`animation/animation_prep.py:131-157` runs a
   second full UMAP fit purely for the educational animation, independent of the real
   `UmapAnalysis` computation on the same data). It's backgrounded, so not UI-blocking, but is a
   real duplicated-compute cost worth consolidating if animation and analysis can share one fit.

6. **O(n) linear tree search on every mutation.** `GateNode.find_node_by_id`/`find_nodes_by_gate`
   (`gating/gate_node.py:92-123`) are called repeatedly per operation (e.g. `add_connection`
   calls `find_node_by_id` three times plus a separate cycle-check search). Fine today; an
   id→node index on `Experiment`/`Sample` makes this O(1) and matters as hierarchies grow.

7. Un-vectorized per-channel loop in compensation setup (`compensation.py:118-136`) — minor,
   easy vectorization with `np.median(df[cols].values, axis=0)`.

## Priority 1 — Performance (UI layer)

1. **`ClusterResultsPanel` builds matplotlib figures synchronously on the UI thread over the full
   UMAP embedding** (`widgets/cluster_results_panel.py:269-331`, `_build_plot_gallery`) — one
   `Figure` + `scatter()` + colorbar per channel, potentially 100k+ points each, none of it
   through the SDK's `RenderComputeStage`/rasterize-lock split that exists for exactly this.
   **This is the single clearest UI-thread-blocking risk found in the review.**
   `CopyableCanvas` in the same file also bypasses `LayeredMatplotlibCanvas` entirely — the same
   SDK class `flow_canvas.py` correctly builds on, and whose docstring says it was extracted
   *from* this plugin's own earlier pattern.

2. **`paintEvent` rebuilds a lookup dict from scratch every call**
   (`widgets/gate_hierarchy/sample_view.py:147`) — cache `node_map` as an instance attribute,
   invalidate only when `self._rects` changes.

3. **Theme changes double-apply.** The root panel already does a recursive `findChildren` +
   `_apply_theme_styles()` cascade (`main_panel.py:573-622`), but ≥6 leaf widgets *also* connect
   directly to `theme_manager.theme_changed`, rebuilding their QSS twice per toggle. Pick one
   propagation mechanism (the cascade already works).

4. **Combo repopulation is O(n) full-rebuild on every refresh, ~14 call sites**, even when the
   item set hasn't changed (e.g. a tab switch re-triggering `refresh_samples()`). Extract one
   `repopulate_combo(combo, items, restore_key)` helper that no-ops when unchanged.

---

## Priority 2 — SOLID/DRY: God classes and dispatch logic

### God classes (widget layer — this is where responsibilities pile up)

Known list from the lint-focused plan (`statistics_explorer.py` 1528, `population_analysis_viewer.py`
1348, `main_panel.py` 1176, `cluster_results_panel.py` 1163, `spectral_learning_tab.py` 1011,
`comparisons_viewer.py` 1065) is confirmed as also architecturally overloaded, not just long.
**One addition to that list: `graph/flow_canvas.py` (1186 lines)** — combines matplotlib
rendering, mouse hit-testing, a gate-drawing-mode state machine bridge, coordinate transforms, and
tutorial-guide drawing in ~60 methods on one class.

Concrete extraction targets:
- `StatisticsExplorer`: extract `StatisticsTablePresenter`, `StatisticsChartRenderer`, an
  export/clipboard service. Also stop reaching directly into `sample.gate_tree`/`sample.fcs_data`
  (`statistics_explorer.py:657-699`) — `render_task.py:112` already shows the right pattern,
  going through `PopulationService.get_gated_events`.
- `flow_canvas.py`: extract a `GateHitTester` collaborator and move tutorial-guide drawing into a
  separate overlay strategy, following the existing `graph/gate_drawing_fsm.py` extraction
  pattern already used elsewhere in the same file.
- `cluster_results_panel.py`: split plotting into a presenter returning `RenderData`-shaped
  results (reusing the SDK's compute/rasterize contract — see Priority 1 UI #1), keep only tab
  wiring in the panel class.

### Dispatch logic (OCP)

- `statistics.py:83-133` and `transforms.py:288-402` branch on `StatType`/`TransformType` via
  if/elif chains — duplicated once forward and once for the inverse in `transforms.py`. The
  codebase already has the right pattern: `gating/gate_factory.py:13-46` uses a
  `_GATE_REGISTRY` dispatch table. **Fix:** mirror that registry approach for both.

### DRY

- **Scale-resolution boilerplate copy-pasted in every gate's `contains()`** — identical ~8-line
  block in `rectangle.py`, `range.py`, `quadrant.py`, `ellipse.py`, `polygon.py` (5 copies).
  Extract one `project_to_display(raw_values, scale)` helper.
- **Biexponential/Logicle defaults hardcoded in 3 places** (`constants.py:52-55`,
  `_utils.py:113-119`, `transforms.py:236-239,345-348`) that must be kept in sync by hand — a
  comment in `_utils.py` already notes a past drift incident ("increased from 0.5"). Consolidate
  to the named constants in `constants.py` and reference them everywhere.
- **Fluorescence-channel detection duplicated**: `compensation.py:367-380` vs
  `fcs_io.py:772-784` — two independent heuristics that can silently diverge.
- **35 hand-rolled `_apply_theme_styles` methods** across ribbons/widgets/graph components,
  each manually f-string-interpolating `Colors.*`/`Fonts.*` into QSS, where the SDK's `Bio*`
  component family (`BioButton`, `BioComboBox`, `BioLabel`, `BioTableWidget`, `BioSplitter`,
  `BioScrollArea`) already self-themes. Migrating widgets built on raw `QWidget`/`QComboBox`/
  `QLabel` to the `Bio*` equivalents removes most of these at the source.
- **`FlowComboBox` (`ui/widgets/styled_combo.py:17-67`) duplicates `BioComboBox`
  (`components.py:575-616`) at ~90% code overlap**, used in 10 files, while sibling files doing
  the same job (`statistics_explorer.py`, `population_analysis_viewer.py`, `comparisons_viewer.py`,
  `cluster_results_panel.py`) import the real `BioComboBox` instead — two parallel components for
  one job. Fold `FlowComboBox`'s one real behavioral delta (no text elision) into `BioComboBox`
  as an option/subclass, standardize call sites.
- **6 ribbon classes duplicate an identical container stylesheet string verbatim**
  (`gating_ribbon.py:121`, `compensation_ribbon.py:114`, `pipeline_ribbon.py:118`,
  `spectral_ribbon.py:39`, `workspace_ribbon.py:89`, `statistics_ribbon.py:34`) instead of using
  `plugin/ribbon.py`'s `BioRibbon` — but this is partly an SDK gap, see below.
- **Two independent zoom-control overlay widgets**
  (`node_canvas/canvas_view.py:216-236` and `gate_hierarchy/widget.py:136-147`) built over
  different `QGraphicsView` canvases, doing the same three-button zoom-in/zoom-out/fit strip.

---

## Priority 3 — SDK gaps (worth adding to the SDK, not just the plugin)

These are cases where flow_cytometry *had* to build something from scratch because no SDK
equivalent exists at all — genuine SDK-abstraction gaps, not underuse:

1. **A lightweight standalone lock-guarded matplotlib canvas** (Priority 0 #7 above) —
   `LayeredMatplotlibCanvas` is currently the *only* canvas base offered, and it forces the full
   async compute/rasterize machinery even for a plugin that just wants "draw this figure safely."
2. **No themed toolbar/ribbon container shape narrower than `BioRibbon`.** `BioRibbon` is really
   "an action bar with a Run/Cancel state machine built in," not a general toolbar container —
   that mismatch is the root cause of the 6x duplicated ribbon stylesheet, not just a missed
   import. A `ThemedToolbarContainer` base (with `BioRibbon` becoming one specialization) fixes
   this for flow and gives other plugins a starting point.
3. **No generic canvas zoom-controls overlay widget** — natural companion to
   `rendering/graphics_scene.py`'s existing view/scene base classes.
4. **No generic "confirm destructive action with a details list" dialog** — `dialogs.py`'s
   `ask_yes_no` only takes a flat message string; `node_canvas/canvas_view.py:300-347` hand-built
   a "delete this and N affected children" preview that's a reasonable, reusable UX pattern.
5. `contrib/image_utils.py` (682 lines) is western-blot-specific domain logic (band detection,
   contrast LUTs) sitting under a generically-named SDK package with zero flow_cytometry usage —
   worth relocating so the SDK's public surface doesn't overstate its generality.

---

## Priority 4 — Test suite: refocus on functionality, not UI mechanics

**This directly addresses the "tests target the UI, which is still being designed" concern.**

### What's already good (don't touch)
`tests/functional/` (1,037 lines, zero Qt imports, 100% functional) and `tests/unit/analysis/`
(~3,810 lines) are the strongest subtrees and the model to emulate going forward.

### The actual problem: CI doesn't use the marker that already exists
`pyproject.toml` already defines a `ui` pytest marker and it's applied consistently across
`tests/ui/`, but `.github/workflows/release.yml:231` runs plain `pytest tests/` with no `-m`
filter — so these UI-mechanics tests already gate every PR today. **This is Priority 0 #3 above
and is the single highest-leverage change for the stated concern**: split CI into a fast/PR-gating
lane (`-m "not ui"`) and a full nightly lane that still runs everything.

### Concrete deletions (pure mechanics, no unique signal, will churn on redesign)
- `tests/ui/test_flow_canvas.py::TestFlowCanvasInitialization` (all 6 tests — hasattr/isinstance
  checks only; collapse to one "constructs without raising" smoke test)
- `tests/ui/test_gate_hierarchy.py::test_gate_hierarchy_init`
- `tests/ui/test_main_panel_smoke.py::test_main_panel_initialization` (existence/hasattr only)
- `tests/ui/test_group_preview.py::test_group_preview_panel_init`, `test_preview_thumbnail_init`
- `tests/unit/ui/test_logic_nodes_and_deletion.py::test_node_item_context_menu_emits_delete`
  (logic already covered by sibling tests in the same file that test headlessly)
- `tests/ui/test_comparisons_viewer_selector_wiring.py::test_comparisons_viewer_constructs_and_refreshes`,
  `tests/ui/test_statistics_explorer_selector_wiring.py::test_statistics_explorer_constructs_and_refreshes`

**Caveat worth keeping in mind:** don't reflexively delete every test that happens to drive a
widget. `tests/ui/test_comparisons_plot_types.py::test_generate_button_produces_a_visible_canvas`
looks like a "click button, check visible" test but its docstring shows it caught two real bugs
(a `QLayout` truthiness bug that silently dropped rendered output, and a BLAS/threadpool SIGBUS
under nested parallelism). Rewrite it to hit the underlying `ComparisonsWorker.run()` and
`_on_render_done()` directly instead of deleting the coverage.

### Rewrites (same logic, headless entry point instead of driving the widget)
- `test_comparisons_plot_types.py` (above) — split into a direct `ComparisonsWorker.run()` test
  and a direct `_on_render_done()` test against a stub layout.
- `tests/ui/test_selection_widgets.py` — extract the real logic ("shared vs sample-specific
  population resolution") into a pure function and test that directly; keep one thin wiring smoke
  test.
- `tests/ui/test_main_panel_smoke.py::test_graph_manager_initialization` — currently asserts on
  `QTabWidget` internals (`_tabs.count()`); test a `GraphManager`-level accessor instead if one
  can be exposed.

### Coverage gaps (higher priority than the deletions above — this is where correctness lives)
1. **`fcs_io.py` (807 lines, the core FCS parser) has only 3 trivial tests, 37 lines total** — no
   coverage for malformed/truncated files, FCS 2.0/3.0/3.1 TEXT-segment differences, missing
   required keywords (`$PAR`, `$TOT`, `$BYTEORD`), or mixed int/float DATA segments. **Given the
   plugin's core value is scientific correctness on real (often messy) instrument output, this is
   the single biggest gap in the whole test suite.**
2. `biology_services.py` (269 lines, FPBase GraphQL client + cache) — zero tests.
3. `compute/dag_evaluator.py` boolean-logic gating — only 3 single-level tests; no nested
   AND-of-OR-of-NOT or empty-parent edge cases.
4. `gating/subset.py` — no dedicated unit test file, only indirect coverage.
5. Compensation math has no test for near-singular/ill-conditioned spillover matrices or
   underdetermined cases (more channels than stains).
6. `tests/unit/analysis/test_stats.py` — dead file, see Priority 0 #4.

### Process
- Add a `tests/test_plugin_contract.py` subclassing the SDK's `ContractTestBase`
  (`karcytics_sdk/testing/contract.py`) — currently unused anywhere in flow_cytometry despite
  being cheap and catching manifest/entry-point/headless-init regressions that the hand-rolled
  `DummyPluginBase` smoke test doesn't.
- Hold `tests/ui/` to the bar the SDK's own tests already set (`Karcytics-SDK/tests/unit/plugin/test_toast.py`,
  `.../rendering/test_mpl_canvas.py`): touching a real QWidget is fine, asserting only that it
  exists is not — assert debounce/ordering/stale-result-dropped *behavior* instead.

---

## Suggested execution order

1. **Priority 0 table** — one sprint, mechanical, immediately de-risks CI and kills confirmed
   duplicates. Start with the CI marker fix (#3) since it's the direct answer to "tests target the
   UI which isn't ready."
2. **FCS I/O test coverage** (Priority 4, gap #1) — before any refactor of `fcs_io.py`'s double-copy
   issue (Priority 1, analysis #4), since that refactor needs a safety net first.
3. **Gate-mask memoization + DagEvaluator consolidation** (Priority 1, analysis #1-#3) — highest
   performance payoff, moderate effort, no user-facing behavior change.
4. **God-class extractions** (Priority 2) — do incrementally, one class per PR, in the order:
   `flow_canvas.py` → `statistics_explorer.py` → `cluster_results_panel.py`. These are large diffs;
   land them separately from the performance work above so review stays tractable.
5. **SDK promotions** (Priority 3) — small, standalone SDK PRs (`LockedFigureCanvas` first, it's
   nearly free) that unblock the plugin-side DRY cleanups in Priority 2.
6. **Remaining DRY/theming consolidation** (35 `_apply_theme_styles`, `FlowComboBox`/`BioComboBox`,
   ribbon stylesheets) — lowest urgency, highest total line-count reduction; good ongoing/backlog
   work rather than a blocking sprint item.
