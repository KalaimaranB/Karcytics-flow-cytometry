# FlowSOM — implementation plan

Adds FlowSOM to the Population Analysis tab as a second clustering method next to
UMAP + HDBSCAN, and teaches the Sample Lens to audit gates against either one.
First, the main tabs are reordered so the last three follow the workflow:
Sample Lens → Statistics → Comparisons.

**Status record:** the phase checklist below. Resume at the first unchecked
phase. Commit on `main`, one commit per phase. Each phase leaves the plugin
runnable.

## What FlowSOM produces

UMAP + HDBSCAN gives every event a 2-D map position and a cluster label, with
some events labelled noise (-1). FlowSOM gives something different:

1. **A grid of nodes.** A self-organizing map (SOM), by default 10 × 10 = 100
   nodes. Each node is a small group of very similar cells, described by its
   median marker values (its *code*). Every event is assigned to exactly one
   node. No event is noise.
2. **A tree of the nodes.** A minimum spanning tree (MST) links each node to
   the nodes most like it. FlowSOM's standard picture is this tree: one circle
   per node, sized by event count and coloured by a marker or by metacluster.
   Branches of the tree usually follow lineages.
3. **Metaclusters.** The 100 node codes are clustered hierarchically into *k*
   metaclusters, which are the populations. Each event's label is its node's
   metacluster. Because the hierarchy is kept, *k* can be changed after the
   run without retraining (re-cutting 100 nodes is instant).

What it does not produce: a 2-D position for each event. To show events on a
map, use one of these:
- the tree layout, with each event drawn near its node (jittered), as FlowSOM's
  own plots do; or
- an optional UMAP of the same events, computed only for display.

How it compares with HDBSCAN, as a second opinion:
- HDBSCAN finds clusters by density and can drop rare or diffuse cells as
  noise. FlowSOM assigns every cell, so a small population tends to get its
  own node.
- FlowSOM splits the data into as many metaclusters as *k* asks for. A *k*
  that is too high splits one real population in two; a *k* that is too low
  merges two. HDBSCAN chooses the number of clusters itself.
- FlowSOM is fast: a million events takes seconds, and it needs no UMAP
  first. It can therefore run on the whole population instead of a
  subsample.

## Parameters (Population Analysis, FlowSOM selected)

| Parameter | Default | Meaning |
|---|---|---|
| Sample, Population, Channels, Run name | as UMAP | shared with UMAP |
| Events | 100% (cap 1,000,000) | FlowSOM is fast enough for the whole population |
| Grid size | 10 × 10 | number of nodes; more nodes gives finer detail |
| Metaclusters (*k*) | 10 | expected number of populations; can be changed after the run |
| Training passes | 10 | passes over the data while the SOM learns |
| Learning rate | 0.05 → 0.01 | how far nodes move per update, shrinking during training |
| Random seed | 42 | makes a run reproducible |
| Also compute UMAP for display | off | adds a per-event map (slower) |

Every parameter but the seed gets a help button in plain language, like the
UMAP ones.

## Reuse (do not rebuild)

| Need | Reuse |
|---|---|
| Gate filter, subsample, logicle transform | the preprocessing in `UmapAnalysis.run`, pulled out into one shared function |
| Background run, cancel, progress | `AnalysisBase` + `task_scheduler`, the `UmapService` pattern |
| Heavy compute off the GUI process | `daemon_worker` (new `run_flowsom` handler beside `run_umap`) |
| Storing and saving runs | `experiment_edits.add_umap_run`, `store._umap_runs`, `attachment_manager` |
| Cluster stats and marker heatmap | the stats block at the end of `UmapAnalysis.run` |
| Exporting clusters as populations | `ClusterResultsPanel._create_populations` (labels plus indices, method-agnostic already) |
| MST, hierarchical metaclustering | `scipy.sparse.csgraph.minimum_spanning_tree`, `scipy.cluster.hierarchy` (scipy is already a dependency) |
| Lens audit, gate synthesis, across samples | `analysis/sample_lens/` unchanged; it works on labels |

No new dependency. The SOM is written in NumPy (batch SOM, vectorized). The
`flowsom` Python package is not used: it pulls in anndata and other heavy
dependencies, and its licence has to be checked against PolyForm Noncommercial
(the same problem PyQt6 had).

## Design notes

- **One run format.** A run stays a dict in `umap_runs`. The storage keys keep
  their names so old workspaces open unchanged. New field `method`:
  `"umap_hdbscan"` (default when missing) or `"flowsom"`. A FlowSOM run adds:
  - `nodes` (per event)
  - `codes` (nodes × channels)
  - `grid`
  - `mst_edges`
  - `layout` (2-D node positions)
  - `linkage`
  - `k`

  `clusters` holds the per-event metacluster, so every existing consumer of
  `clusters` keeps working. `embedding` is the jittered tree layout, or the
  display UMAP when that option is on (`embedding_kind`: `"tree"` or `"umap"`).
- **A method descriptor, not if-chains.** A small `ClusteringMethod` record per
  method holds:
  - display name
  - cluster noun ("cluster" or "metacluster")
  - map caption
  - whether it has noise
  - whether *k* can be re-cut

  The lens and the results panel read wording from it. This lets the next
  method (PhenoGraph, hierarchical) slot in as a new descriptor.
- **Re-cutting *k*.** It changes `clusters` from `linkage` in the GUI process.
  The new labels and `k` are stored on the run. Clusters already exported are
  not changed; they are populations now.
- **Merge findings must allow for over-splitting.** With FlowSOM, "this gate
  holds 2 metaclusters" may just mean *k* is too high. The lens flags a merge
  only when the two metaclusters stay separate at a coarser cut (they join
  high in the hierarchy). Otherwise it stays quiet. The finding text names *k*.
- **The UMAP animation is UMAP-only.** A FlowSOM run shows the progress bar,
  then the results.
- **Tab order is one source of truth.** A `MainTab` enum (in tab order) plus a
  table from tab to center-stack page and chrome (sidebars, ribbon). It
  replaces:
  - the literal indices in `main_panel._on_tab_changed_locked` and its other
    `setCurrentIndex(6)`-style calls;
  - the `TabActiveValidator(n)` literals in courses 1–6.

  The validator takes a `MainTab`. Academy pause/resume saves the tab **name**,
  and an old saved integer is mapped through the old order.

## Phases

- [ ] **0. Tab reorder.**
  - New order: Workspace, Gating, Compensation, Pipeline, Spectral,
    Population Analysis, **Sample Lens, Statistics, Comparisons**.
  - Add the `MainTab` enum and route table, and replace every literal index
    (`main_panel`, `TabActiveValidator` in all courses, `SAMPLE_LENS_TAB`).
  - Academy saved state stores the tab name, with a legacy-int migration.
  - Docs: `00_OVERVIEW.md` tab list; `16_SAMPLE_LENS.md` ("It is the last tab"
    becomes "between Population Analysis and Statistics").
  - Tests:
    - every `MainTab` routes to the right page;
    - a saved int from the old order restores the right tab;
    - the course tests still pass.
- [ ] **1. FlowSOM core (Qt-free).** New `analysis/clustering/`:
  - `flowsom.py` builds the SOM (batch, seeded), assigns nodes, builds the
    MST, lays the tree out in 2-D, metaclusters with Ward linkage, and
    provides `recut(linkage, k)`.
  - `methods.py` holds the `ClusteringMethod` descriptors.
  - Unit tests on the lens fixture's planted populations: FlowSOM recovers
    them (adjusted Rand index above a threshold); a seeded run is
    reproducible; re-cutting gives exactly *k* labels; 1M events stays under
    a time budget.
- [ ] **2. Run plumbing.**
  - Pull UMAP's preprocessing out into a shared function (gate filter,
    subsample, transform, channel labels, stats and heatmap).
  - Add `FlowsomAnalysis`, the `run_flowsom` daemon handler, and a
    `FlowsomService` (or one generalized service).
  - Persist the new arrays in `attachment_manager`; runs without `method` load
    as UMAP.
  - Tests: run → save → load round trip; old UMAP workspaces still load.
- [ ] **3. Population Analysis UI.**
  - Algorithm combo: "UMAP + HDBSCAN" / "FlowSOM", with a stacked parameter
    panel per method.
  - Results:
    - a new **FlowSOM Tree** tab (node circles sized by count, coloured by
      metacluster or a chosen marker);
    - the gallery and map use `embedding`, whatever produced it;
    - a *k* control re-cuts, and Population Statistics and the export list
      refresh.
  - The run history shows the method. Export as populations is unchanged.
  - Tests: run FlowSOM from the tab with a fake service; re-cut updates the
    stats.
- [ ] **4. Sample Lens.**
  - The run picker shows the method.
  - The map caption and finding wording come from the descriptor.
  - For a tree-layout run the map draws the tree (nodes coloured by majority
    final population, and by metacluster).
  - Merge findings are hierarchy-aware for re-cuttable methods.
  - The scope line names *k*, and a small *k* control in the lens re-cuts and
    re-audits.
  - Tests:
    - the planted mistakes are found with a FlowSOM run;
    - a deliberately high *k* does not create merge findings;
    - a UMAP run behaves exactly as before.
- [ ] **5. Docs.**
  - `08_POPULATION_ANALYSIS.md`: a FlowSOM section (what the results mean,
    choosing *k*, when to prefer it).
  - `16_SAMPLE_LENS.md`: auditing with FlowSOM, *k* and merges.
  - Plan checked off.
- [ ] **6. Academy.** Run FlowSOM on the tutorial data first, as was done for
  the lens. Then add a short "second opinion" section to Course 5: run FlowSOM
  on Sample C and check that the lens names the same missed population; change
  *k* and see which findings depend on it. Course 4 gets one step pointing at
  the algorithm picker. Dry run, then the step and word-limit tests.

## Open questions (decide when the phase starts)

- **Spectral's position.** This plan keeps it after Pipeline. Moving it next
  to Compensation would also follow the workflow, but it shifts more indices.
- **Default event count.** Is the whole population (capped) right, or should
  FlowSOM match UMAP's subsample so the two runs compare on the same events?
  Matching makes the lens comparison cleaner; the whole population is
  FlowSOM's strength.
- **Large exports.** Exporting metaclusters from a 1M-event run writes very
  large `SubsetGate` index lists into the workspace. This may need a compact
  encoding before it is the default.

## Later (not in this plan)

- PhenoGraph or other methods as further descriptors.
- Showing where a UMAP run and a FlowSOM run of the same population agree, in
  the lens.
- Automatic choice of *k* (elbow or consensus).
