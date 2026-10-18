# Sample Lens

!!! tip "Learn it hands-on"
    Academy **Course 5 — Sample Lens: Check Every Gate** walks through every part of this tab on the tutorial data.

The **Sample Lens** tab is a single-sample check of your gating strategy. It answers the question manual gating never answers on its own: *is this strategy actually right?* It shows every gate on a population's path with that population highlighted (backgating), compares your gates with an unsupervised clustering of the same cells, and shows how a population behaves across every sample.

It sits between Population Analysis and Statistics: check your gates first, then report on them. Like Statistics and Population Analysis, it takes over the whole window: a sidebar on the left, results on the right.

## 1. Before you start: a clustering run

!!! tip "Just backgating? No run needed"
    The gating path (section 3) and **Across samples** (section 4) work on any sample, with or without a clustering run. Only the audit findings and the map need one.

The lens judges your gates against a clustering run of the sample (see [Population Analysis](./08_POPULATION_ANALYSIS.md)): a **UMAP + HDBSCAN** run made with **Run HDBSCAN Auto-Clustering** checked, a **FlowSOM** run, or a **PhenoGraph** run. Runs made in Population Analysis appear in the **Clustering run** list.

If the sample has none:

1. In **Populations**, click the population to cluster. Use your last clean-up gate (for example *Live singlets*), not All Events: debris and dead cells form clusters of their own that you excluded on purpose.
2. Press **Run UMAP + clustering on …**. It runs in the background with the default settings (10,000 events) and selects the new run when it finishes. For FlowSOM or PhenoGraph, make the run in Population Analysis.

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

### With a FlowSOM run

Findings speak of **metaclusters** (M0, M1, …) and give each one's phenotype, as in the FlowSOM Tree (for example *Metacluster M8 (B220− CD4− CD3− CD8−) isn't in any population*). FlowSOM always makes *k* metaclusters, so at a high *k* one population is split into several, and at a low *k* two are lumped together. The lens allows for both:

- **Merges** are only flagged when the metaclusters' phenotypes clearly differ (a marker is + in one and − in the other). Two metaclusters with the same phenotype are one population split by a high *k*, not a gate mistake.
- **Cuts** are only flagged when the cells the gate keeps and the cells it drops have the same phenotype. If they differ, the gate is rightly separating two populations the metacluster lumped together.
- Findings with the same phenotype on the same population are shown once, naming all their metaclusters.

A **Metaclusters (k)** control appears under the run: change it and the lens re-audits at once. A finding that only appears at one *k* deserves less weight than one that holds across several.

### With a PhenoGraph run

Findings name clusters as C0, C1, … with their phenotypes, and follow the same rules as FlowSOM: PhenoGraph also splits large populations into several clusters, so a merge needs clearly different phenotypes and a cut needs the same phenotype on both sides. A **Resolution** control appears under the run; changing it re-clusters in the background (a few seconds, with a status line) and then re-audits. The map draws each cell around its cluster, with the cluster links behind.

### Do other runs agree?

When the sample has more than one clustering run of the same population (say a UMAP, a FlowSOM and a PhenoGraph run of *Leukocytes*), each finding ends with a line saying which other runs report it too (*Also found by FlowSOM k=5, PhenoGraph res=1.0*) or that *only this run finds it*. A cut or a merge counts as the same when it's on the same gate; a missed cluster, when the other run also misses a cluster made of mostly the same cells.

A finding several methods report is about your gates. One that only a single method reports, and that changes with *k* or the resolution, is more likely about the method.

## 3. Gating path (backgating)

**Populations** lists the sample's populations as an indented tree. **Bold** ones are the final populations the lens judges; *italic* ones (UMAP exports and logic nodes) it leaves out.

Click a population in **Populations**. The strip at the top shows one plot per gate on its path: each plot shows that gate's **parent** population on the gate's own axes, in grey, with the selected population drawn on top in colour. This shows at a glance where the population sits at every step.

These are live plots of the real gates. Each plot starts with its own path gate selected; click another gate drawn on the same plot (a sibling, such as B-cells next to T-cells) to select it there. The selection stays on that plot and doesn't change the Gating tab's. Drag a selected gate and it is edited exactly as on the Gating tab: statistics are recounted, the change propagates to the other samples in the group, and it can be undone. The lens refreshes on its own after any gate change anywhere in the app.

**Focus mode and plot views.** Above the path, **Focus** gives the plots the whole tab: the sidebar, the maps and Across samples are hidden until you click **Exit focus** or press Esc. **Plots per row** sets how many plots share a row (*All* keeps the path on one row). In focus mode plots grow to fill the width, and the path scrolls both ways when it doesn't fit. Both settings work outside focus mode too.

Each plot has its own view menu, remembered per gate while you move between populations:

| Gate | Views |
| --- | --- |
| 1-D (range, e.g. Live Cells on PI) | **Histogram**, or **Dot plot vs SSC-A / FSC-A**: the range is drawn as a band, still editable |
| 2-D (rectangle, polygon, ellipse, quadrant) | **Pseudocolor**, **Dot plot**, **Contour**. **Histogram** is greyed out: on one axis the gate would drop half of what it selects |


## 4. The map, twice, and Across samples

- **Coloured by your final populations**: each cell in the colour of the final population it ended up in; grey if none. A grey slice through a coloured island is a gate edge cutting a population.
- **Coloured by cluster** (HDBSCAN or PhenoGraph) or **by metacluster** (FlowSOM): the same cells, coloured by cluster. Where the two pictures disagree, the findings circle the spot. Click a cluster to circle it.

For a FlowSOM run, the map is the FlowSOM tree: each cell is drawn around its node, with the tree's lines behind, and a finding rings each node of its metaclusters.

**Across samples** lists the selected population in every sample that has it (matched by its full path, e.g. *Lymphocytes / T cells / CD4+*). Controls (unstained, single-stain, FMO and isotype samples) are left out, because their stains differ from the panel:

- **% parent** and **Events**, as in Statistics.
- **On edge**: the share of the parent's cells sitting right at the gate's edge. Above 5%, the edge runs through a dense part of the data and a small shift (of the gate, or of staining) changes the result a lot.
- **Flags**: *edge in a dense region*, and *outlier* when a sample's % parent is far from the other samples' median (more than three robust deviations, and at least 5 points).

## 5. Fixing a missed population

On a *Cluster N isn't in any population* finding, press **Propose gates**. The lens searches your run's channels (and forward/side scatter) for a short chain of ordinary rectangle gates that recovers the cluster, and previews each step with the cluster highlighted. The bar above shows the number of gates and how well they match the cluster (F1, precision, recall).

Every step has a tick box. Untick a step you don't want, for example a third gate that barely raises F1: the steps after it are redrawn on the cells the remaining gates keep, and the scores update. A search step is only added when it raises F1, so leaving one out usually costs a little precision; the bar shows how much.

- **Add gates to tree** creates the ticked steps as a chain under the run's population, named *Cluster N* (FlowSOM: *Metacluster MN*; PhenoGraph: *Cluster CN*). They are ordinary gates: rename them, edit them, and they propagate to the rest of the group like any gate you draw.
- **Cancel** discards the proposal; nothing is changed until you add it.

Unlike a population exported from UMAP (a list of specific cells), these gates are geometry on real markers, so they mean the same thing on every sample.
