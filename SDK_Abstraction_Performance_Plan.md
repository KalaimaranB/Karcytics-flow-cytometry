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

> [!NOTE]
> **Done.** All 9 items (redundant `.copy()`, `gc.collect()` removal, CI `-m "not ui"` split, dead/assertion-free test fixes, duplicate `@dataclass`, `LockedFigureCanvas` promoted to the SDK, raw `QMessageBox` calls replaced, duplicate `save_workflow_dialog.py` deleted) verified complete.

---

## Priority 1 — Performance (analysis layer hot paths)

The offload architecture itself is sound (heavy work already goes through `AnalysisBase` +
`task_scheduler`), so these are about wasted work *inside* the background paths, not missing
threading.

1. ~~No memoization of ancestor gate masks~~ — **Done.** `GateNode._get_mask` now caches
   `(events, mask)` per node, keyed on the *identity* of the `events` DataFrame (a reload or
   compensation change always produces a new DataFrame object — see `fcs_io.py`/
   `data_loader_service.py` — so a changed dataset is a natural cache miss with no separate
   version token needed). Gate edits/rewires don't change that object at all, so those invalidate
   explicitly via the new `GateNode.invalidate_mask_cache()`, wired into the two places the tree
   can actually change: `GateCoordinator.recompute_all_stats` (the single choke point every
   mutation already funnels through) and `PopulationService.remove_population` (the one path that
   doesn't call `recompute_all_stats`, since it rewrites a surviving logic node's `parents` list
   directly). Every UI refresh call site (`render_window.py`, `graph_window.py`,
   `statistics_explorer.py`, `comparisons/data_extractor.py`, `population_analysis_viewer.py`,
   `umap_analysis.py`) benefits for free since they all call the existing `apply_hierarchy`
   entry point — no call-site changes needed. Regression-tested in
   `tests/unit/analysis/gating/test_gate_node_mask_cache.py` (cache reuse, cache-miss on a new
   DataFrame, invalidation, descendant propagation, and a diamond-DAG shared-ancestor case) and
   two new tests in `test_gate_coordinator.py` covering the two invalidation call sites end to end.
   284 analysis/functional tests plus the affected UI suites all still green.

2. ~~Three independent tree-walk implementations that will drift~~ — **Done.**
   `StatisticsAnalysis` no longer has its own `_walk_and_compute`; it now calls the same
   `DagEvaluator.evaluate` that `propagation_worker.py` already used, closing the drift risk
   between "stats after a direct edit" and "stats after group propagation." Porting it wasn't a
   clean swap — the old walker did two things `DagEvaluator` didn't: computed logic-node
   `per_parent_pcts` overlap percentages (ported over, needs only already-computed counts, not
   masks), and — the one we deliberately chose not to drop — emitted a Qt `analysis_error` signal
   and **dropped the entire failed subtree** from results when a gate's `.contains()` raised,
   rather than silently reporting zero counts for it. `DagEvaluator.evaluate` gained an optional
   `on_gate_error` callback for this: when given, a failing gate's descendants are pruned from the
   result entirely (matching the old behavior exactly); when omitted (`propagation_worker.py`'s
   case, unchanged), it keeps its original zero-mask-and-continue behavior. Two independent walkers
   still remain (`GateNode._get_mask`'s own AND/OR/NOT combination logic, now cached per Priority 1
   analysis #1, and `DagEvaluator`'s separate reimplementation of the same combination) — reducing
   that further to one wasn't in scope here and would need `DagEvaluator` to reuse `GateNode`'s
   cache instead of its own `evaluated_masks` dict. Regression-tested in
   `tests/unit/analysis/test_dag_evaluator.py` (per-parent overlap math, default vs. callback
   failure handling, sibling-unaffected-by-pruning) and `test_statistics_analysis.py`. 311
   analysis/functional/gating tests green, ruff/mypy clean repo-wide.

3. ~~Every gate edit triggers a full-tree stats recompute~~ — **Done.**
   `GateCoordinator.recompute_all_stats`/`StatsService.recompute_all_stats`/`StatisticsAnalysis`
   all gained an optional `node_ids` parameter; when given, only that subtree gets invalidated and
   recomputed via the new `DagEvaluator.evaluate_scoped`, which reads unaffected ancestors' masks
   straight from `GateNode`'s cache (Priority 1 analysis #1) instead of walking the whole tree.
   `gate_mutation_service.py`'s call sites now pass the actual node(s) that changed —
   `add_gate`/`split_population`: the new node; `add_connection`/`remove_connection`: the rewired
   target; `modify_gate`: every node sharing that gate (`find_nodes_by_gate`, already computed for
   its event-publishing loop, just reordered to run first). `copy_gates_to_group` deliberately keeps
   the full-tree path — it replaces the whole target tree, so "everything changed" is accurate
   there. Logic-node `per_parent_pcts` for an out-of-scope parent now falls back to that parent's
   last-persisted count instead of 0 (only the *pruned-by-gate-failure* case still uses 0, since
   that data is genuinely untrustworthy). Verified end-to-end in
   `test_gate_coordinator.py::test_modify_gate_does_not_recompute_an_unrelated_siblings_gate` —
   monkeypatches a sibling gate's `.contains()` and asserts it's never even called — plus 5 new
   `evaluate_scoped` unit tests (scope boundary, cache reuse, parity with a full `evaluate()`,
   persisted-count fallback, failure pruning within a subtree). 317 analysis/functional/gating
   tests green, ruff/mypy clean repo-wide.

4. ~~Double in-memory copy of every loaded sample~~ — **Done.** Both call sites
   (`_build_fcs_data_from_daemon_response` and `_load_with_fcsparser`'s tolerant-reader path) only
   call `events_df.copy()` when the FCS file actually has an embedded spillover matrix
   (`_has_embedded_spill`, a cheap dict-key check reusing the same key list `_auto_apply_spill`
   already scans) — that's the only thing that ever mutates `events_df` in place. When there's no
   embedded spill (confirmed the common case), `raw_events` just shares the same DataFrame object
   as `events` instead of duplicating it — provably safe since every other consumer
   (`compensation_ribbon.py`'s reset-to-raw, `compensation.py`'s `apply_compensation`) already
   makes its own `.copy()` before mutating rather than assuming independence. Regression-tested in
   `tests/unit/analysis/test_fcs_io.py` (6 new tests: the key-check helper, identity-sharing for
   both loader paths when there's no spill key, and correct independent-copy + compensated-vs-raw
   values when there is one). 304 analysis/functional tests green, ruff/mypy clean.

5. ~~UMAP computed twice for the animation flow~~ — **Not a bug, intentional.** Re-checked
   `animation/animation_prep.py:131-157`'s own docstring: it's a much smaller "mini-UMAP" computed
   synchronously on a reduced subset purely for the animation's visuals, deliberately sequential
   with (not duplicating) the real background `UmapAnalysis` fit over the full dataset. Removed
   from the backlog.

6. ~~O(n) linear tree search on every mutation~~ — **Assessed, intentionally skipped.**
   Investigated adding an id→node index on `Sample`. Real hierarchies are typically dozens of
   nodes, so the O(n) walk itself is microseconds — the "three times" in `add_connection` turned
   out to be three *different* lookups (source, target, subtree-scoped cycle-check), not a
   redundant repeated one, so there's no free win from caching within a single operation either.
   Building a real index means wiring invalidation into 7+ structural-mutation call sites across
   `population_service.py`/`gate_mutation_service.py`/`splitter.py`, plus the 3 places
   `sample.gate_tree` gets *reassigned* outright (gate propagation, experiment load, tree reset),
   and migrating ~50 call sites — one of which (`add_connection`'s cycle-check) is deliberately
   subtree-scoped and must stay on the recursive method or cycle detection breaks. A stale index
   would fail safe (lookup miss, not wrong data) rather than silently corrupt anything, but the
   invalidation-surface risk isn't justified by a payoff this small. Left as a linear scan.

7. ~~Un-vectorized per-channel loop in compensation setup~~ — **Done.**

## Priority 1 — Performance (UI layer)

1. ~~`ClusterResultsPanel` builds matplotlib figures synchronously on the UI thread over the full
   UMAP embedding~~ — **Plot Gallery done; Interactive Map tab deliberately deferred.**
   `_build_plot_gallery` (one `Figure` + `scatter()` + colorbar per channel, potentially 100k+
   points each — **the single clearest UI-thread-blocking risk found in the review**) now shows a
   lightweight placeholder tile immediately and renders each tile off the UI thread via a new
   `ClusterPlotRenderTask` (self-contained `AnalysisBase`, mirrors `render_task.py::RenderTask`'s
   shape exactly: builds a headless `Figure` under `MPL_RASTER_LOCK`, returns an RGBA byte buffer)
   dispatched through `task_scheduler.submit()`. `ClusterResultsPanel` listens to the global
   `task_scheduler.task_finished`/`task_error` signals the same way `group_preview.py` already
   does, matches each completed tile back to its grid position, and swaps the placeholder for a
   `CopyablePixmapLabel` (a `QPixmap`-backed tile with the same right-click-to-copy behavior
   `CopyableCanvas` had). The actual scatter/colorbar drawing code was extracted verbatim into a
   shared pure function (`cluster_scatter_draw.draw_cluster_scatter`) so the headless render task
   and the still-synchronous Interactive Map tab's live `Figure` never drift.

   A real thread-safety bug surfaced during this work, independent of the tile-sizing issue below:
   the Interactive Map/Statistics tabs' synchronous `Figure` construction (`_create_plot`, the
   Expression Profiles bar chart) wasn't behind any lock, so it could race a background
   `ClusterPlotRenderTask` touching matplotlib's (thread-unsafe) Agg backend at the same
   moment — `fig.tight_layout()` calls into the Agg renderer to measure text extents, not just
   `canvas.draw()`. This is the same class of bug `render_task.py`'s own comment warns about
   (SIGBUS on macOS ARM from concurrent unlocked Agg calls); it was only caught because a
   real-thread diagnostic script crashed with no Python traceback. Both call sites now wrap their
   `Figure`-through-`CopyableCanvas` construction in the same `MPL_RASTER_LOCK` the render task
   already uses.

   Getting the *tile sizing* right (unrelated to the crash above) took three iterations, each
   introducing a new bug in turn — worth recording so nobody repeats them: (1) `setScaledContents`
   stretched a tile's fixed-aspect-ratio pixmap independently in X/Y to fill its grid cell, visibly
   distorting it (squashed/elongated UMAP blobs); (2) replacing that with a `setFixedSize` clamp
   killed the distortion but also shrank every tile well below what the old *expanding*
   `CopyableCanvas` used to occupy, making the same marker count look artificially denser than the
   Interactive Map's equivalent plot; (3) restoring `Expanding` + resize-driven
   `Qt.AspectRatioMode.KeepAspectRatio` rescaling fixed both of those, but `QGridLayout` doesn't
   reliably give equal-`Expanding` widgets equal row height without explicit row stretch factors —
   rows ended up wildly different heights (verified directly: 120px/258px/315px for otherwise
   identical tiles), which the earlier column-only `setColumnStretch` fix didn't address. The
   settled design abandons dynamic expand-and-fill entirely: `CopyablePixmapLabel` is one fixed,
   deterministic display size (`_GALLERY_TILE_WIDTH_PX`/`_HEIGHT_PX` = 467x373 — 2/3 of an initial
   700x560, tuned down after that read as too large in practice — vs. the original synchronous
   canvas's 500x400 figsize-at-100dpi footprint, so tiles don't look artificially dense, without
   any `QGridLayout` stretch/expand behavior involved in sizing them at all), with the source
   rendered at `_GALLERY_SUPERSAMPLE` (2x) that size and downscaled once with `KeepAspectRatio` for
   crispness (group_preview.py's supersample-then-downscale trick). Verified directly with a real,
   shown widget hierarchy (not just unit-level property assertions, which had masked the row-height
   bug before): every tile measures exactly its configured fixed size, deterministically, regardless
   of window size. The real cost: tiles no longer grow to fill extra window width the way the old
   live canvas did — an explicit, accepted tradeoff for a design that can't drift.

   The Interactive Map tab was deliberately left synchronous: its hover tooltip and
   `PolygonSelector` freehand-draw both need a live Qt-thread `Axes` with real event wiring, which
   a background-rendered flat image can't provide — `CopyableCanvas`/`LockedFigureCanvas` still
   bypass `LayeredMatplotlibCanvas` there, left as documented backlog rather than force-fit into
   this change. Regression-tested in `tests/ui/test_cluster_plot_render_task.py` (3 tests: headless
   render correctness, discrete cluster-ID colorbar, not-configured error path) and
   `tests/ui/test_cluster_results_panel_gallery.py` (7 tests: placeholders shown before any render
   completes, one task dispatched per tile, 2x-supersample render config, a tile becomes a
   fixed-size `CopyablePixmapLabel` on completion, a standalone construction test locking in
   fixed-size + non-distorted display, a raising render task leaves its placeholder in place rather
   than crashing, `_cluster_plot_params()`'s discrete-colorbar math).
   135 UI tests + 492 non-UI tests green, ruff/mypy clean repo-wide.

2. ~~`paintEvent` rebuilds a lookup dict from scratch every call~~ — **Done.**

3. ~~Theme changes double-apply~~ — **Done.** Removed the redundant direct
   `theme_manager.theme_changed` subscriptions in the 6 leaf widgets (`sample_view.py`,
   `gate_hierarchy/widget.py`, `population_tree.py`, `sample_checklist.py`,
   `comparisons_viewer.py`) — all now theme solely via `MainPanel`'s cascade.
   `statistics_explorer.py` keeps its subscription (it does real cascade-unreachable work —
   repainting an already-computed table/chart with new colors) but no longer also calls
   `_apply_theme_styles()` itself. Regression-tested in `tests/ui/test_theme_single_propagation.py`.

4. ~~Combo repopulation is O(n) full-rebuild on every refresh, ~14 call sites~~ — **Done**
   (except `axis_control_panel.py`, deliberately deferred — see below).
   `repopulate_combo(combo, items, restore_data)` was promoted into the SDK itself
   (`karcytics_sdk.plugin.components`, next to `BioComboBox` which it operates on) rather than kept
   as a flow-cytometry-local helper — it's pure `QComboBox` logic with no flow-cytometry-specific
   code in it, so any plugin gets the same "true no-op when both the item set and resolved
   selection are unchanged" fix, not just this one. Unit-tested in the SDK's own
   `tests/unit/plugin/test_components.py`; the flow-cytometry test conftest mock now points at the
   real implementation (not a second copy) so plugin-side tests exercise the actual logic.
   Migrated: `pipeline_ribbon.py` (also fixed a latent bug where restoring the selection happened
   *after* `blockSignals(False)`, so `sample_selected` could fire twice per refresh),
   `pseudocolor_overlay_options.py`'s X/Y channel combos, `compensation_editor_dialog.py`'s X/Y
   combos (also fixed a latent bug there — no `blockSignals` at all around the old rebuild, so
   `_update_plots` fired 2-3 times per matrix-size change instead of once),
   `statistics_explorer.py`'s channel and chart-stat combos, and
   `population_analysis_viewer.py`'s sample/gate/history combos. Every migration got its own
   characterization tests written *against the pre-migration code first* to lock in exact
   restore/default/no-signal-during-rebuild behavior before touching it — new test files:
   `test_pseudocolor_overlay_options_channels.py`, `test_compensation_editor_dialog_channels.py`,
   `test_statistics_explorer_combos.py`, `test_population_analysis_viewer_combos.py` (24 tests
   total). `axis_control_panel.py` remains unmigrated: it builds its combo incrementally across
   several methods (`clear_combos`/`add_channel`/`set_current_x`/`set_current_y`/etc.) called
   externally by `graph_window.py`, so migrating it means redesigning that external API first, not
   a drop-in swap — left as explicit backlog, not silently dropped. 117 UI tests + 478 non-UI tests
   green, ruff/mypy clean repo-wide.

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

- ~~`statistics.py`/`transforms.py` branch on `StatType`/`TransformType` via if/elif chains~~ —
  **Done.** Both now use registry dicts mirroring `gate_factory.py`'s `_GATE_REGISTRY`
  (`transforms.py`'s registries stay string-`.value`-keyed, preserving the existing IPC-safety
  comment about enum identity not surviving a process boundary).

### DRY

- ~~Scale-resolution boilerplate copy-pasted in every gate's `contains()`~~ — **Done**
  (`project_to_display()` extracted to `_utils.py`).
- ~~Biexponential/Logicle defaults hardcoded in 3 places~~ — **Done** (consolidated to
  `constants.py`).
- ~~Fluorescence-channel detection duplicated~~ — **Done** (`compensation.py` now delegates to
  `fcs_io.get_fluorescence_channels`).
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
- ~~6 ribbon classes duplicate an identical container stylesheet string verbatim~~ — **Done.**
  All 6 (`compensation_ribbon.py`, `gating_ribbon.py`, `pipeline_ribbon.py`, `spectral_ribbon.py`,
  `statistics_ribbon.py`, `workspace_ribbon.py`) now subclass the SDK's new
  `ThemedToolbarContainer` (see Priority 3 gap #2) instead of hand-rolling `_apply_theme_styles()`;
  the method is deleted entirely from each, not shrunk.
- **Two independent zoom-control overlay widgets**
  (`node_canvas/canvas_view.py:216-236` and `gate_hierarchy/widget.py:136-147`) built over
  different `QGraphicsView` canvases, doing the same three-button zoom-in/zoom-out/fit strip.

---

## Priority 3 — SDK gaps (worth adding to the SDK, not just the plugin)

These are cases where flow_cytometry *had* to build something from scratch because no SDK
equivalent exists at all — genuine SDK-abstraction gaps, not underuse:

1. ~~A lightweight standalone lock-guarded matplotlib canvas~~ — **Done** (same item as the
   `LockedFigureCanvas` promotion in Priority 0).
2. ~~No themed toolbar/ribbon container shape narrower than `BioRibbon`~~ — **Done.** Added
   `ThemedToolbarContainer` to `karcytics_sdk/plugin/ribbon.py` — a minimal `QWidget` subclass
   providing only objectName-scoped background/border theming via `theme_manager.apply_style()`,
   with no layout or Run/Cancel state machine. `BioRibbon` is now a specialization of it
   (`BioRibbon(ThemedToolbarContainer)`); all 6 flow_cytometry ribbons migrated to inherit it
   directly (see the DRY item above).
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
**Done** — all of the below collapsed/removed, all suites still green:
- ~~`tests/ui/test_flow_canvas.py::TestFlowCanvasInitialization`~~ collapsed 6 hasattr/isinstance
  tests into one `test_constructs_with_expected_defaults`.
- ~~`tests/ui/test_gate_hierarchy.py`~~ deleted (its one test's construction is already exercised
  by `test_gate_hierarchy_stale_callbacks.py`).
- ~~`tests/ui/test_main_panel_smoke.py::test_main_panel_initialization`~~ deleted.
- ~~`tests/ui/test_group_preview.py::test_group_preview_panel_init`, `test_preview_thumbnail_init`~~
  deleted (real rebuild behavior already covered by `test_main_panel_smoke.py`).
- ~~`tests/unit/ui/test_logic_nodes_and_deletion.py::test_node_item_context_menu_emits_delete`~~
  deleted.
- ~~selector-wiring `..._constructs_and_refreshes` tests~~ deleted from both
  `test_comparisons_viewer_selector_wiring.py` and `test_statistics_explorer_selector_wiring.py`.

**Caveat worth keeping in mind:** don't reflexively delete every test that happens to drive a
widget. `tests/ui/test_comparisons_plot_types.py::test_generate_button_produces_a_visible_canvas`
looks like a "click button, check visible" test but its docstring shows it caught two real bugs
(a `QLayout` truthiness bug that silently dropped rendered output, and a BLAS/threadpool SIGBUS
under nested parallelism). Rewrite it to hit the underlying `ComparisonsWorker.run()` and
`_on_render_done()` directly instead of deleting the coverage.

### Rewrites (same logic, headless entry point instead of driving the widget)
- ~~`test_main_panel_smoke.py::test_graph_manager_initialization`~~ — **Done.** Added
  `GraphManager.get_open_graph(sample_id, node_id)`; test now asserts through that instead of
  `_tabs.count()`/`_tabs.widget(0)`.
- `test_comparisons_plot_types.py` and `tests/ui/test_selection_widgets.py` — **deferred**, not
  because they're wrong, but `comparisons_viewer.py`/`population_tree.py` are both under active
  unrelated development in this working tree right now; revisit once that work lands to avoid
  rewriting tests against code that's still moving.

### Coverage gaps (higher priority than the deletions above — this is where correctness lives)
1. ~~`fcs_io.py` has only 3 trivial tests~~ — **Done.** `tests/unit/analysis/test_fcs_io.py` now
   covers truncated files, integer/float/mixed-`$PnB` DATA segments, big-endian byte order,
   `$PAR`/malformed-header edge cases, and the strip-ratio diagnostics path, via synthetic
   FCS3.1 files built by a `_write_minimal_fcs` test helper (17 tests total).
2. `biology_services.py` (269 lines, FPBase GraphQL client + cache) — zero tests.
3. `compute/dag_evaluator.py` boolean-logic gating — **substantially improved, not fully closed.**
   The Priority 1 analysis #1-#2 work added `tests/unit/analysis/test_dag_evaluator.py` (11 tests:
   root/regular/logic-node stats, per-parent overlap math, failure-with-and-without-pruning, scoped
   recompute) on top of the original 3 single-level AND/OR/NOT tests in `test_dag_gating.py` — but
   still no explicit *nested* AND-of-OR-of-NOT compound-tree test.
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

1. ~~Priority 0 table~~ — **Done.**
2. ~~FCS I/O test coverage~~ (Priority 4, gap #1) — **Done.**
3. ~~Gate-mask memoization + DagEvaluator consolidation + scoped recompute + fcs_io double-copy~~
   (Priority 1, analysis #1-#4) — **Done.** Item #6 (id→node index) was assessed and intentionally
   skipped — negligible payoff at realistic hierarchy sizes vs. a real invalidation-surface risk.
   Item #5 (UMAP-twice) turned out to be intentional, not a bug — removed from the plan.
4. ~~Combo repopulation dedup~~ (Priority 1, UI #4) — **Done** (except `axis_control_panel.py`,
   deliberately deferred pending an external-API redesign).
5. ~~`ClusterResultsPanel` Plot Gallery off-thread rendering~~ (Priority 1, UI #1) — **Done** for
   the Plot Gallery (the flagged single clearest risk); the Interactive Map tab's live canvas is
   deliberately deferred — see the item above for why.
6. **God-class extractions** (Priority 2) — do incrementally, one class per PR, in the order:
   `flow_canvas.py` → `statistics_explorer.py` → `cluster_results_panel.py`. These are large diffs;
   land them separately from the performance work above so review stays tractable. Not started.
7. **SDK promotions** (Priority 3) — small, standalone SDK PRs. `LockedFigureCanvas`,
   `repopulate_combo`, and `ThemedToolbarContainer` are all already done this way; the remaining
   gaps (generic zoom-controls overlay, generic destructive-confirm dialog, relocating
   `contrib/image_utils.py`) are still open.
8. **Remaining DRY/theming consolidation** (35 `_apply_theme_styles`, `FlowComboBox`/`BioComboBox`)
   — lowest urgency, highest total line-count reduction; good ongoing/backlog work rather than a
   blocking sprint item. Not started. (Ribbon stylesheets are done, see item 7 above.)
