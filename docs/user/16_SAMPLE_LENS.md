# Sample Lens

The **Sample Lens** tab is a single-sample check of your gating strategy. It answers the question manual gating never answers on its own: *is this strategy actually right?* It shows every gate on a population's path with that population highlighted (backgating), compares your gates with an unsupervised clustering of the same cells, and shows how a population behaves across every sample.

It is the last tab of the module. Like Statistics and Population Analysis, it takes over the whole window: a sidebar on the left, results on the right.

## 1. Before you start: a clustering run

The lens judges your gates against a **UMAP + HDBSCAN** run of the sample (see [Population Analysis](./08_POPULATION_ANALYSIS.md)). Any run made with **Run HDBSCAN Auto-Clustering** checked works, including ones you made in Population Analysis.

If the sample has none:

1. In **Populations**, click the population to cluster. Use your last clean-up gate (for example *Live singlets*), not All Events: debris and dead cells form clusters of their own that you excluded on purpose.
2. Press **Run UMAP + clustering on …**. It runs in the background with the default settings (10,000 events) and selects the new run when it finishes.

!!! note "What the lens judges"
    Only the events of the selected run, and only the **final populations** under the run's population, the ones with no gates below them. Populations exported from a UMAP run are left out, because they come from the clustering itself. The line under the title always says what is being judged, for example *"Judging 6 final populations on 10,000 events of Live singlets"*.

## 2. Audit findings

Each finding is a place where your final populations and the clusters disagree:

| Finding | What it means | What to do |
|---|---|---|
| ◯ **Cluster N isn't in any population** | A distinct group of cells that none of your final gates holds. | A population you haven't gated, or one you dropped on purpose. Press **Propose gates** (section 5). |
| ⊕ **'Gate' holds N different clusters** | One gate catches two or more distinct groups of cells. | Check whether they really are one population (split the gate if not). |
| ✂ **'Gate' cuts cluster N in two** | The gate holds part of a cluster; the rest falls just outside. | The edge probably runs through the population rather than around it: look at it in the gating path and move it. |

Click a finding to select its population and circle its clusters on the UMAP.

!!! warning "A second opinion, not ground truth"
    Clustering can split one population in two or merge two similar ones, depending on its settings. Treat a finding as a prompt to look, not as a verdict.

## 3. Gating path (backgating)

Click a population in **Populations**. The strip at the top shows one plot per gate on its path: each plot shows that gate's **parent** population on the gate's own axes, in grey, with the selected population drawn on top in colour. This shows at a glance where the population sits at every step.

These are live plots of the real gates. Drag a gate here and it is edited exactly as on the Gating tab: statistics are recounted, the change propagates to the other samples in the group, and it can be undone. The lens refreshes on its own after any gate change anywhere in the app.

## 4. The UMAP, twice, and Across samples

- **Coloured by your final populations**: each cell in the colour of the final population it ended up in; grey if none. A grey slice through a coloured island is a gate edge cutting a population.
- **Coloured by cluster (HDBSCAN)**: the same cells, coloured by cluster. Where the two pictures disagree, the findings circle the spot. Click a cluster to circle it.

**Across samples** lists the selected population in every sample that has it (matched by its full path, e.g. *Lymphocytes / T cells / CD4+*). Controls (unstained, single-stain, FMO and isotype samples) are left out, because their stains differ from the panel:

- **% parent** and **Events**, as in Statistics.
- **On edge**: the share of the parent's cells sitting right at the gate's edge. Above 5%, the edge runs through a dense part of the data and a small shift (of the gate, or of staining) changes the result a lot.
- **Flags**: *edge in a dense region*, and *outlier* when a sample's % parent is far from the other samples' median (more than three robust deviations, and at least 5 points).

## 5. Fixing a missed population

On a *Cluster N isn't in any population* finding, press **Propose gates**. The lens searches your run's channels (and forward/side scatter) for a short chain of ordinary rectangle gates that recovers the cluster, and previews each step with the cluster highlighted. The bar above shows the number of gates and how well they match the cluster (F1, precision, recall).

- **Add gates to tree** creates the chain under the run's population, named *Cluster N*. They are ordinary gates: rename them, edit them, and they propagate to the rest of the group like any gate you draw.
- **Cancel** discards the proposal; nothing is changed until you add it.

Unlike a population exported from UMAP (a list of specific cells), these gates are geometry on real markers, so they mean the same thing on every sample.
