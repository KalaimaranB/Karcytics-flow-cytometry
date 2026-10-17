# Sample Lens — implementation plan

Replaces the "Sample Lens (Demo)" tab with the real feature: one sample, every
population, checked against an unsupervised clustering of the same events. Our
answer to CytoFLEX's single-sample analysis page.

**Status record:** the phase checklist below. Resume at the first unchecked
phase. One branch (`feature/sample-lens-demo`), one commit per phase.

## What the user gets

1. **Gating path with backgating.** Pick a population: every gate on its path is
   shown as a live plot of its parent population, with the picked population's
   events highlighted. Gates on these plots are the real gates — dragging one
   edits it and propagates it like anywhere else.
2. **Gate audit.** Using a UMAP + HDBSCAN run of the sample, each cluster is
   compared with the final populations. Findings, in plain language:
   *missed population* (a cluster no final gate holds), *gate merges clusters*,
   *gate cuts a cluster*.
3. **Across samples.** For the picked population: its % parent in every sample
   that has it, flagged when the gate edge sits in a dense part of that sample's
   data, or when its % parent is an outlier.
4. **Fix a missed population.** Propose ordinary rectangle gates on real
   channels that recover the cluster; add them to the tree through the gate
   coordinator (so undo, propagation and stats all work).

## Reuse (do not rebuild)

| Need | Reuse |
|---|---|
| Population tree / selection | `ui/widgets/gate_hierarchy.GateHierarchy` |
| Gating-path plots, gate editing | `ui/graph/flow_canvas.FlowCanvas` (+ coordinator) |
| UMAP scatter | `ui/widgets/cluster_scatter_draw.draw_cluster_scatter` |
| Population masks | `GateNode` DAG evaluation (mask cache) |
| Same population across samples | `analysis/population_matching.label_path_index` |
| Display transforms | `analysis/transforms.apply_transform` / `invert_transform`, gate `x_scale`/`y_scale` |
| Running UMAP, storing runs | `UmapService` + `experiment_edits.add_umap_run` |
| Adding gates | `IGateCoordinator.add_gate` |
| Widgets, theming | SDK `components` + `theme_manager.apply_style` |

## Design notes

- **Scope of an audit = the UMAP run.** A run covers a subsample (`indices`) of
  one population (`node_id`). Only the leaf populations *under that node* are
  judged, and only on the run's events. The UI says so.
- **Final population = leaf** of the gate DAG, excluding UMAP-exported cluster
  nodes (`is_umap_parent` subtrees) — those come from the clustering itself.
- **Edge density, any gate shape:** an event is "on the edge" if nudging it by
  a small step in display space (±x, ±y) flips its membership. Works for every
  gate type through `Gate.contains`, no per-shape geometry.
- **Gate synthesis** works in display space (the gate's own channel scales),
  then converts the box back to raw values for a `RectangleGate`.
- Analysis lives in `analysis/sample_lens/` and stays Qt-free.

## Phases

- [x] **1. Analysis core** — `analysis/sample_lens/`: run scope (align a UMAP
  run with a sample's events and populations), audit, edge density +
  cross-sample check, gate synthesis. Public `GateNode.mask()`. Unit tests.
- [x] **2. Backgating overlay on FlowCanvas** — `set_backgate(mask, color)`;
  2-D scatter overlay and 1-D highlight through the existing data layer.
- [x] **3. Sample Lens tab** — replaces the demo: sample + run pickers ("Run
  UMAP + clustering" when none), population list, findings, gating-path strip,
  UMAP gates-vs-clusters, across-samples table. Live refresh on gate events.
- [x] **4. Fix a missed population** — propose gates for a cluster, preview,
  add through the coordinator.
- [x] **5. Docs** — user docs page, plan checked off. (The demo tab, never
  committed, was deleted in phase 3.)
- [x] **6. Academy Course 5** — `tutorials/course5.py` (56 steps) between Population
  Analysis and reporting (now Course 6). Found on the tutorial data first: Course 3's
  T-cells guide cut the CD4 T cells (guide fixed), logic nodes hid their gates from
  the final populations, and controls skewed Across samples (both fixed). The
  sidebar's icicle became an indented `PopulationList`: a wide tree doesn't fit
  340 px. Lens validators in `tutorials/validators.py`; dry run on the tutorial
  data passes every check in order.

## Later (not in this plan)

- Persisting dismissed findings in the workspace.
- Fixes for "merges" / "cuts" (today: Show only, the user edits the gate).
