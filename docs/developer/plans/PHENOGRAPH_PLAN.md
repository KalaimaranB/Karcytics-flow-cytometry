# PhenoGraph — implementation plan

Adds PhenoGraph to the Population Analysis tab as a third clustering method,
next to UMAP + HDBSCAN and FlowSOM. The Sample Lens audits against it, and the
lens learns to say when several methods agree. The Academy is reorganised so
the three methods fit across two courses.

**Status record:** the phase checklist below. Resume at the first unchecked
phase. Commit on `main`, one commit per phase. Each phase leaves the plugin
runnable.

## What PhenoGraph does

PhenoGraph (Levine et al., *Cell* 2015) is graph-based clustering:

1. **Neighbours.** For every event, find its *k* nearest events in marker space
   (default *k* = 30).
2. **Shared-neighbour graph.** Link two events by how many neighbours they
   share (Jaccard: shared ÷ combined). Two events in the same population share
   most neighbours; two events either side of a gap share almost none.
3. **Communities.** Leiden finds groups of events that link more to each other
   than to the rest. The **resolution** sets how fine the groups are: higher
   gives more, smaller clusters.

Like FlowSOM, nearly every event gets a cluster. Events that end up in a
cluster smaller than a minimum size (default 10) are labelled outliers (-1).
Unlike FlowSOM you don't choose the number of clusters, and unlike HDBSCAN
nothing is dropped for being sparse.

What it does not produce: a 2-D map position per event, or a tree. What it adds
instead is the graph, from which we can say **how strongly each pair of
clusters is connected** (the PAGA idea, Wolf et al. 2019).

### Measured on the tutorial data

Sample C, Leukocytes, 208,961 events, 4 markers, scratch benchmark:

| Step | Time |
|---|---|
| Neighbours (pynndescent, *k* = 30) | 8 s |
| Jaccard weights (SciPy) | 2.4 s |
| Leiden, per resolution | 3 s |

| Resolution | Clusters |
|---|---|
| 0.5 | 15 |
| 1.0 | 32 |
| 2.0 | 57 |

At 1.0 the B cells are split into many clusters along gradients (a known
PhenoGraph trait). A 0.5% B220+ CD3+ CD8+ cluster appears, likely B–T
doublets, but not confirmed. The tutorial files have only area channels
(FSC-A, SSC-A; no FSC-H/W), so no singlet plot can check it: the Academy
presents it as an open question.

## Licences

| Package | Role | Licence | Status |
|---|---|---|---|
| `pynndescent` | nearest neighbours | BSD-2 | already installed (via umap-learn) |
| `scipy` | Jaccard weights, sparse graph | BSD-3 | already a dependency |
| `scikit-network` 0.33.5 | `sknetwork.clustering.Leiden` | BSD-3 | **new**; needs only numpy + scipy; wheels for cp310–313 on macOS, Windows, Linux; works with our numpy 1.26.4 |
| `phenograph` | — | MIT, but requires the two below | **not used** |
| `leidenalg` | — | GPL-3 | **not allowed** |
| `python-igraph` | — | GPL-2 | **not allowed** |

The PhenoGraph steps (neighbours → Jaccard → Leiden → small clusters to -1)
are ours, a few dozen lines. Only Leiden comes from scikit-network.
`scripts/check_license_compliance.py` must pass with it added.

## Parameters (Population Analysis, PhenoGraph selected)

| Parameter | Default | Meaning |
|---|---|---|
| Sample, Population, Channels, Run name | shared | as the other methods |
| Events | 100% (cap 1,000,000) | full population; ~15 s at 200k |
| Neighbours (*k*) | 30 | how many neighbours each event links to; higher merges small groups into larger ones |
| Resolution | 1.0 | how fine the clusters are; can be changed after the run |
| Minimum cluster size | 10 | smaller clusters become outliers |
| Random seed | 42 | reproducible neighbour search and Leiden |

Each gets a plain-language help button, like the other methods.

## Results

A **Cluster Graph** tab, first for PhenoGraph runs (like FlowSOM Tree):

- One circle per cluster, sized by events, coloured by cluster or by a marker
  (scaled to the clusters' range, like the tree).
- Edges between clusters, thickness = connectivity (edges between the two
  clusters in the shared-neighbour graph ÷ what their sizes would predict).
  Weak edges hidden below a threshold (a slider).
- Layout: classical MDS + SMACOF on connectivity distances, reusing the FlowSOM
  layout code.
- Reading guide, three steps:
  1. Thick edges join clusters that are one population cut along a gradient.
  2. A cluster with no strong edges is a distinct group, often rare and
     worth a look.
  3. Colour by a marker to name the groups.
- **Resolution** control: debounced re-cluster in the background (~3 s), with
  a progress line. Not instant like FlowSOM's *k*.
- The legend and phenotype heatmap reused from FlowSOM (generalised to any
  clusters), with +/lo/− calls.

Gallery, interactive map, statistics and export work as for the other methods.
The map's `embedding` is the cluster-graph layout with events jittered round
their cluster (`embedding_kind` = `"graph"`), like FlowSOM's tree. A UMAP map for
PhenoGraph runs is left for later (see Decisions).

## Design notes

- **Run format.** Same dict in `umap_results`; `method` = `"phenograph"`.
  Added keys:
  - `resolution`
  - `n_neighbors`
  - `min_cluster_size`
  - `cluster_edges` (pairs + connectivity)
  - `layout` (per cluster)

  `clusters` holds per-event labels, so every consumer keeps working.
- **The graph is not saved.** At 209k × 30 neighbours it is about 25 MB. On
  load, changing the resolution rebuilds it once (~10 s, background, with a
  progress line), then keeps it for the session.
- **Memory at 1M events.** The benchmark's one-shot Jaccard (`A[rows]`) would
  build ~900M entries. Compute it in chunks of rows (or in numba), and test
  1M events under a time and memory budget.
- **Where it runs.** pynndescent is numba, like UMAP, which runs in the daemon
  process. Phase 2 confirms whether the task worker thread is safe (as
  FlowSOM's is) or the daemon is needed.
- **Method descriptor.** Add a `ClusteringMethod` for PhenoGraph. Generalise
  "re-cut":
  - descriptor field `recut_param`: name, label, range, step and whether
    re-cutting is instant (*k*) or a background job (resolution);
  - the lens's *k* row becomes a generic row driven by it.

  Replace the lens's `recuttable` checks for "may over-split" with a descriptor
  flag `over_splits` (FlowSOM, PhenoGraph), so the phenotype-aware merge/cut
  rules apply to both.
- **Determinism.** pynndescent with a seed can still vary across thread
  counts. Test that a seeded run gives the same clusters (adjusted Rand index
  ≈ 1); if not, document it and seed Leiden at least.

## Phases

- [x] **0. Dependency.** Add `scikit-network==0.33.5` to `pyproject.toml`
  and lock it. Licence check, SBOM and pip-audit pass. A smoke test imports
  `sknetwork.clustering.Leiden` and clusters a toy graph.
- [x] **1. PhenoGraph core (Qt-free).** Found while building: scikit-network's
  Leiden uses the C library's `rand()` (unseeded by `random_state`), so the
  module seeds it under a lock; the Jaccard count is a numba merge (numba now a
  direct dependency); the graph holds at most 250k events, the rest take the
  majority cluster of their 5 nearest graph events (1M events: 25 s, 1.9 GB
  peak, against 4.3 GB uncapped). Layout helpers moved to `layout.py`, shared
  with FlowSOM. `analysis/clustering/phenograph.py`:
  - `knn_graph(x, k, seed)`: pynndescent, then chunked Jaccard, giving a
    symmetric CSR graph;
  - `leiden(graph, resolution, seed, min_size)`: labels numbered largest
    first, small clusters to -1;
  - `cluster_connectivity(graph, labels)`: PAGA-style edges;
  - the cluster layout, reusing the MDS + SMACOF from `flowsom.py` (moved to a
    shared helper).

  Unit tests on the lens fixture's planted populations:
  - ARI above a threshold;
  - more clusters at a higher resolution;
  - seeded reproducibility;
  - connectivity is high inside a split population and low between distinct
    ones;
  - 1M events within budget.
- [x] **2. Run plumbing.** Runs in the daemon: in a worker thread the
  neighbour search and Leiden stalled the GUI thread for up to 1.8 s. The
  daemon loads the Qt-free `clustering` package by path and caches the last
  three runs' graphs by `run_uid`; after a reload the graph is rebuilt from the
  run's intensities (equal to rounding, so clusters match to ARI > 0.95). The
  method descriptor gained `RecutSetting` (k or resolution), `over_splits` and
  `tag_prefix`. `PhenographAnalysis` and `PhenographParams`.
  `run_phenograph()` in the service (thread or daemon, per the note above).
  - `recluster_run(run, resolution)`, as `recut_run`: exported clusters
    unchanged, names cleared, tables recomputed.
  - Persistence in `attachment_manager`; the graph is rebuilt on demand.
  - Tests: run → save → load round trip; reclustering after load rebuilds the
    graph.
- [x] **3. Population Analysis UI.** The FlowSOM tree's frame (guide, colour by,
  re-cut control, legend, heatmap, hover) became `ClusterMapView`; the FlowSOM
  tree and the PhenoGraph `Cluster Graph` are subclasses. A cluster with no
  links is marked "stands apart" in the legend and title. The results panel asks
  the viewer to re-cluster (`recluster_requested`) and shows the result
  (`apply_recluster`); the spin waits with "Re-clustering…" meanwhile.
  - "PhenoGraph" in the method combo, with its own parameter panel.
  - Events slider at 100% for PhenoGraph.
  - The **Cluster Graph** tab: guide, colour by, resolution control, edge
    threshold, legend and heatmap (generalised from the FlowSOM widgets, not
    copied).
  - History label: `"{i}. {name} · PhenoGraph res=1.0"`.
  - Tests: run from the tab with a fake service; changing the resolution
    refreshes the statistics, the history and the export list.
  - User checks it live here (first runnable slice).
- [ ] **4. Sample Lens.**
  - PhenoGraph runs in the run picker.
  - The resolution row (generic re-cut row).
  - Findings name clusters with phenotypes and use the over-split rules.
  - The map draws the cluster graph with finding clusters ringed.
  - Tests mirror the FlowSOM lens tests.
- [ ] **5. Agreement across methods.** When the open sample has more than one
  clustering run on the same population, each finding says which other runs
  report the same kind of finding on the same gate ("Also found by: FlowSOM,
  PhenoGraph"). Findings found by only one method are marked as such.
  - A finding is the same if it has the same kind and the same population
    path; clusters are not compared.
  - Tests: two runs agreeing, and one disagreeing.
- [ ] **6. Docs.**
  - `08_POPULATION_ANALYSIS.md`: a PhenoGraph section (graph, resolution,
    reading connectivity, when to prefer it).
  - A three-method comparison table: noise, cluster count, speed, what each
    view shows.
  - `16_SAMPLE_LENS.md`: PhenoGraph and the agreement line.
- [ ] **7. Academy.** See below. Dry runs on the tutorial data offscreen, then
  step and word-limit tests. User plays it live.

## Academy: three methods across two courses

Course 4 already runs ~65 minutes with UMAP + HDBSCAN and FlowSOM. Adding
PhenoGraph there would make it ~85. **Recommended:**

| # | Course | Change |
|---|---|---|
| 4 | Population Analysis: UMAP + HDBSCAN | FlowSOM section moved out; back to ~50 min |
| 5 | Sample Lens | FlowSOM add-on moved out; unchanged otherwise |
| **6** | **Second Opinions: FlowSOM & PhenoGraph** (new) | see below; ~45 min |
| 7 | Reporting (old Course 6) | renumbered only |

New Course 6, after the lens so the lens is already known:

1. **Why a second opinion.** Every method makes you choose how fine to cut:
   minimum cluster size, *k*, resolution.
2. **FlowSOM.** The Course 4 FlowSOM section, moved as is: prediction on noise,
   run, read the tree by CD3 and B220, *k* high and to 5, phenotypes.
3. **PhenoGraph.**
   - Prediction: will it find more or fewer clusters than FlowSOM's 10?
   - Run it on the same Leukocytes, then read the cluster graph: thick edges
     join split B cells; colour by B220.
   - Find the isolated small cluster and read its phenotype (B220+ CD3+).
     Ask what it could be; doublets are one possibility, not the answer.
     Explain the FSC-H/W check these files can't do.
   - Change the resolution and watch the B-cell clusters merge.
4. **Three opinions in the lens.** Switch runs and read "Also found by". Which
   finding do all three report? Which only one? Then the existing "Which
   findings to trust" step.
5. Prediction reveal and graduation; badge e.g. 🩺 "Second Opinion".

Mechanics:

- **Course ids stay.** `flow_course_6_reporting` keeps its id and becomes
  Course 7 by order and title. The new course gets
  `flow_course_clustering_methods`, so saved progress and badges still match.
- **Prerequisites.**
  - The new course requires the lens course.
  - Reporting keeps requiring the lens, not the new course, so anyone part-way
    through reporting isn't locked out.
  - Order in `COURSES` sets the numbering.
- **Text.** Every "Course N" in texts, course docstrings and
  `10_ACADEMY_TUTORIALS.md` is renumbered. The Course 4 / 5 FlowSOM references
  move with the steps.
- **Paused progress in removed steps.** `_resume_point` returns a block
  unchanged when its step no longer exists. Fall back to the latest step in
  its history that still exists, or the course start. Test it with a saved
  block pointing at a removed FlowSOM step.

## Decisions (2026-10-18)

- **Academy layout:** the table above. FlowSOM moves to the new Course 6
  with PhenoGraph; Reporting becomes Course 7.
- **The B220+ CD3+ cluster:** the Academy may say it *could* be doublets, but
  must not present it as fact. Treat it as a question for the learner, not an
  answer.
- **No UMAP map for PhenoGraph** in this plan. The cluster graph is the
  method's own view, the gallery and lens use the jittered graph layout (as
  FlowSOM does), and Course 4's UMAP run is already there to compare with.
  The optional UMAP stays under *Later*.
- **Neighbours default 30, not 15.** UMAP's 15 sets the map's local detail;
  HDBSCAN then clusters the map, not that graph, so matching the number
  doesn't make the methods comparable. In PhenoGraph *k* sets the grain:
  on the tutorial data, k = 15 gave 46 clusters at resolution 1.0 against 32
  at k = 30, splitting populations further, and saved only ~1.5 s. 30 is
  PhenoGraph's published default; keep it, with help text saying lower means
  finer.

## Later (not in this plan)

- An optional UMAP map for PhenoGraph runs, reusing the neighbour graph.

- t-SNE (openTSNE, BSD) as an alternative map for any method.
- MILK (Yachie lab, bioRxiv Aug 2026) once peer-reviewed and packaged; check
  its licence.
- Consensus clusters across methods (events every method groups together).
