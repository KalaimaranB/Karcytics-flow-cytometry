# Academy & Guided Tutorials

The **Academy** is a built-in, hands-on tutorial system — not a video, not a static walkthrough, but a guided coach that lives inside the workspace itself. It highlights the exact button or panel you need next, watches what you actually do (the shape of the gate you drew, the role you assigned, whether you saved), and only moves on once your work genuinely checks out. If you get something wrong, it tells you what happened and fixes it for you — a poorly drawn gate gets deleted, a correctly-shaped-but-misnamed one gets renamed — so you're never stuck.

Best of all, it provisions its own demo data: **you don't need any FCS files of your own** to try it.

!!! tip "Click the button"
    If you're reading this instead of trying it, stop here and click **🎓 Cyto Academy** in the top-right of the tab bar. It's the single fastest way to actually learn this module.

<!-- SCREENSHOT: docs/images/user/academy/academy-button-highlighted.png — the 🎓 Cyto Academy button in the tab bar, top-right corner -->

## Opening the Academy

Click **🎓 Cyto Academy**, next to the Save Workspace button in the tab bar. This opens the **Academy course catalog** — a set of course cards showing your progress and any badges you've already earned.

<!-- SCREENSHOT: docs/images/user/academy/course-catalog.png — the Academy catalog window showing six course cards (Flow Cytometry Fundamentals, Compensation & Clean-up Gates, Immunophenotyping & the Pipeline, Population Analysis: Run & Validate, Sample Lens: Check Every Gate, Derived Parameters, Statistics & Comparisons) with progress indicators -->

Pick a course and it starts immediately: a floating tutor overlay appears on top of your workspace, with a speech-bubble guide (nicknamed **Cyto**) and a soft spotlight highlighting whichever button, panel, or plot region you need to interact with next.

<!-- SCREENSHOT: docs/images/user/academy/spotlight-overlay.png — the tutorial overlay mid-course, showing Cyto's speech bubble and a glowing highlight around the Add Samples button -->

## How a course actually teaches you

Every course is built from three kinds of steps, and you'll move through all three constantly:

- **Explains a concept.** No action required — read it, then click Next. This is where the "why," not just the "how," gets covered (why FMO controls matter, what compensation is correcting for, what UMAP's axes do and don't mean).
- **Asks you to do something real.** Click the highlighted button, draw a gate, switch a tab, open a sample — the step only advances once you actually perform that interaction in the live workspace.
- **Checks your work automatically.** Karcytics polls your actual workspace state every couple of seconds — did the gate you drew land in roughly the right place? Did you assign the role correctly? Is the right tab active? Did you actually save? — and advances the moment it's satisfied. A wrong gate shape gets silently deleted with an explanation; a right-shaped-but-misnamed gate gets renamed for you automatically so you're never blocked by a typo.

This is what makes the Academy different from a static walkthrough: it's checking the same underlying data your analysis actually depends on, not just whether you clicked "Next."

## Your demo data

Course 1 provisions ten realistic tutorial FCS files (a Blank, a PI viability single stain, five FMO controls, and three "mystery" experimental samples) the first time you need them. If they're already present in your project or a known folder, this is instant; otherwise Karcytics downloads them once (roughly 100&nbsp;MB) from the project's own reference dataset, showing live progress as it goes. You'll never need to hunt for or prepare your own files to complete any of the courses.

<!-- SCREENSHOT: docs/images/user/academy/file-provisioning.png — the provisioning step showing live download progress ("6/10 files done") -->

## The seven courses

The courses build on each other in order: each one after the first opens the workflow you saved at the end of the one before, and checks it is loaded before starting.

### Course 1 — Flow Cytometry Fundamentals

**~50 minutes · no prerequisites · badge: 🔬 Flow Fundamentalist**

The on-ramp. You're handed three unidentified samples — one Spleen, one Thymus, one Bone Marrow — and told you'll have an evidence-based answer for which is which by the end of Course 3. You start by predicting which cells the thymus will barely have; Course 3 tells you if you were right. Along the way you:

- Import all ten tutorial files and learn what a **Group** is and why it controls gate propagation.
- Tag every file with its **Role** (Unstained, Single Stain, FMO Control, Full Panel), one at a time and then in bulk.
- Draw your first gate, **Cells**, from Forward/Side Scatter alone, and learn what a singlet gate is for. It comes before compensation because it uses no dyes.
- Learn *why* spillover happens: explore the **Spectral Viewer**'s real, FPbase-sourced dye curves and work through the interactive **Learning Compensation** masterclass built from your own panel's numbers.
- Open the **Compensation** tab and judge the matrix the cytometer saved in your files: which method produced it, how to read a row and a column, what a well-compensated pair looks like on the before/after scatter and histograms, and why you check it across every sample.
- Save your workspace — required to continue into Course 2.

Short questions check the key ideas as you go: which control marks where CD45-negative ends, what spillover does to an uncompensated cell, where debris sits on a scatter plot, which cell of the matrix answers a given question, how a compensated population should sit, and why one tube isn't enough. It ends on a prediction about the matrix you'll build next.

### Course 2 — Compensation & Clean-up Gates

**~50 minutes · requires Course 1 · badge: ⚖️ Signal Cleaner**

You build a spillover matrix of your own, then draw the gates that depend on it. You:

- Estimate a matrix from your **FMO controls**: see which dye each tube lacks and how Karcytics worked that out, restrict the fit to your **Cells** gate, and watch the fit drawn step by step on one of your own tubes.
- Find the method's blind spot (a detector with no FMO tube gets no estimate) and see whether your Course 1 prediction held.
- **Compare** your matrix with the cytometer's on the Matrices page, pick out the one difference that matters for the next gate, and **fine-tune** that value by hand while watching the plot level out.
- Save your matrix by name, then put the cytometer's matrix back in use, knowing why.
- Gate **Live Cells** on a viability dye with a Biexponential axis, and **Leukocytes** on CD45, anchored to an FMO control's true background and confirmed on a real stained sample.
- Learn the "No-Jump" axis-locking rule and watch Auto-Propagation copy your gates to every sample in the group.
- Save your workspace again — required to continue into Course 3.

Questions along the way: how a tube with an unhelpful name was matched to its missing dye, why the fit uses only your Cells, what the greyed points in the fit are, which matrix difference matters for a viability gate, which PI cluster is dead, and how % Parent becomes % Total.

<!-- SCREENSHOT: docs/images/user/academy/course1-gating-hierarchy.png — the Gating Hierarchy panel showing the completed Cells → Live Cells → Leukocytes tree at the end of Course 2 -->

### Course 3 — Immunophenotyping & the Pipeline

**~40 minutes · requires Course 2 · badge: 🧬 Immunophenotyper**

Picks up exactly where Course 2 left off. You:

- Gate **T-cells** and **B-cells** out of your Leukocytes population two different ways — a two-marker scatter rectangle for one, a histogram-plus-live-FMO-overlay range gate for the other — and learn when each technique is the better call.
- Edit a gate after drawing it with the **Select** tool, watch the edit reach every sample in the group, then **undo** it (Ctrl+Z, or Cmd+Z on a Mac) and learn what Undo does and doesn't cover.
- Split T-cells four ways at once with a single **Quadrant** gate (CD4+, CD8+, double-positive, double-negative), then rename all four resulting leaves.
- Learn to read and reorient the **Pipeline** flowchart view, including the boolean **AND/OR/NOT** logic nodes you'll put to real use in a later course.
- Use the **Quick-Stats** grid to read hard numbers across every sample and decide, from the evidence, which mystery sample is Thymus, Bone Marrow, and Spleen.
- Save your workspace again — required to continue into Course 4.

Questions along the way: where the T cells sit on a B220 vs CD3 plot, what an edit does on the other samples, what Undo won't bring back, why the B220 threshold comes from the FMO (select all that apply), when a histogram beats a scatter plot, and which quadrant holds the helper T cells. To crack the mystery, you name each sample's organ yourself from the Quick-Stats grid, and Course 3 shows how your Course 1 prediction held up.

<!-- SCREENSHOT: docs/images/user/academy/course2-quadrant-gate.png — a CD4 vs CD8 plot with a completed Quadrant gate showing the four renamed subpopulations (CD4+, CD8+, DP, DN) -->

### Course 4 — Population Analysis: Run & Validate

**~65 minutes · requires Course 3 · badge: 🧠 Population Analyst**

No new manual gating anywhere in it — instead, you hand your existing gated data to an algorithm that has never seen your gates, then prove its result out against your own hand-gating. You:

- Validate that your Course 3 gating tree (Leukocytes, T-cells, B-cells) is actually in place before continuing.
- Get a real explanation of what UMAP's axes do and don't mean, with a recommended external video for a deeper dive.
- Select Sample C (the confirmed Spleen) and the Leukocytes gate, and exclude the PI and CD45 channels — each choice explained, not just instructed.
- Read the map settings as one group, then set the ones that matter here — Neighbors, Subsample % and HDBSCAN's Minimum Cluster Size — each with its reason.
- Run the analysis and watch the real, data-driven UMAP animation play out live, built from your own Sample C data.
- Explore the results in the **Plot Gallery** and the **Interactive Map** — hovering over populations to read their marker expression, and switching the map's marker dropdown to watch different lineages light up.
- Let the course itself identify your run's real B-cell cluster from its marker profile (no two runs get the same cluster ID), export it as a genuine gate-tree population, and cross-check it against your own hand-gated B-cells with a Pipeline **AND** node.
- Save your workspace again — required to continue into Course 5.

Questions along the way: what a cell's position on a UMAP axis tells you, why UMAP runs on Leukocytes instead of All Events (select all that apply), why CD45 is left out, which way to turn Neighbors when hunting a rare population, and what data HDBSCAN actually clusters. Before wiring the AND node, you predict how many of UMAP's B cells will fall inside your own B-cells gate; the AND node shows you.

<!-- SCREENSHOT: docs/images/user/academy/course4-umap-plot.png — the Population Analysis tab showing a UMAP projection colored by marker expression, with distinct population "islands" visible -->

### Course 5 — Sample Lens: Check Every Gate

**~44 minutes · requires Course 4 · badge: 🔎 Gate Auditor**

Course 4 checked one population against the clusters. Course 5 checks all of them in the **[Sample Lens](./16_SAMPLE_LENS.md)** tab, before Course 7 reports numbers from them. You predict at the start what the comparison will turn up. You:

- Open the lens on Sample C and pick Course 4's UMAP run, and see exactly which populations it judges (and why UMAP exports and logic nodes are left out).
- **Backgate**: follow B-cells and then CD4+ through every gate on their path, with the population highlighted on each gate's parent.
- Open **Focus** mode for bigger plots, set two plots per row, and show the Live Cells range gate as a dot plot vs SSC-A instead of a histogram.
- Read the run's map twice, coloured by your final populations and by cluster, and learn the three kinds of audit finding.
- Find the cells none of your gates holds (leukocytes that are neither T nor B cells), let **Propose gates** turn the cluster into ordinary rectangle gates, read its precision, recall and F1, and add them to your tree.
- Read **Across samples**: why the thymus is flagged as an outlier on DP (biology, not a gating error), and what **On edge** says about how fragile a gate is.
- Backgate on Sample A, which has no clustering run, to see that the gating path and Across samples don't need one.
- Drag the T-cells gate's top edge into the CD4 T cells on purpose, watch the lens name the gate that cut them, then fix it.
- Save your workspace again — required to continue into Course 6.

Questions along the way: why the run clusters Leukocytes, what grey means on each map, whether a finding proves a gate wrong, what the missed cells are, why gates beat an exported cluster, what precision and recall say, why the lens blames T-cells for cells that would have been CD4+, and what "no findings" does and doesn't prove.

### Course 6 — Second Opinions: FlowSOM & PhenoGraph

**~45 minutes · requires Course 5 · badge: 🩺 Second Opinion**

Course 4 clustered Sample C with UMAP + HDBSCAN. Course 6 asks two methods that work differently, then lets the Sample Lens say which findings they agree on. Each method chooses its grain its own way: HDBSCAN by a minimum cluster size, FlowSOM by *k*, PhenoGraph by a resolution. You predict at the start whether the new methods will agree. You:

- Run **FlowSOM** on the same Leukocytes, with all events. Read its tree: colour it by CD3 and then B220 to find the T and B cell branches, see how many metaclusters split the B cells, re-cut *k* without re-running, and read each metacluster's +/− phenotype in the legend and heatmap.
- Run **[PhenoGraph](./08_POPULATION_ANALYSIS.md)** on the same cells. Read its **Cluster Graph**: circles are clusters, lines link clusters whose cells are neighbours, and a circle with no lines **stands apart**. Colour it by B220, find the small B220+ CD3+ groups standing apart, then lower the resolution and see which clusters merge and which stay apart.
- Open the lens on the FlowSOM run, then on the PhenoGraph run, and read the line under each finding: *Also found by …* or *Only this run finds it*. Learn why both methods report cuts that UMAP didn't (they put nearly every cell in a cluster), why your proposed gates from Course 5 get flagged, what the shared **DN** finding says about the T-cells gate's lower edge, and what to do with a finding only one method reports.
- Change the lens's resolution and watch findings come and go: those are about the method's grain, not your gates.
- Save your workspace again — required to continue into Course 7.

Questions along the way: what FlowSOM does with HDBSCAN's noise cells, what a high *k* does to one population, what an all-negative metacluster is, how many clusters PhenoGraph will find, what a B220+ CD3+ group standing apart could be (doublets are possible, but nothing here can test it), what lowering the resolution does, and how to weigh findings that one or two methods report.

### Course 7 — Derived Parameters, Statistics & Comparisons

**~35 minutes · requires Course 5 · badge: 📊 Insight Reporter**

Course 4 showed that your hand-gated **B-cells** and the unsupervised **UMAP B Cells** are nearly the same cells. Course 7 asks the follow-up: are they also *measured* the same? You make a prediction at the start, and the course answers it. You:

- Confirm your Course 4 export (the UMAP B Cells population and its AND-node cross-check) is actually in place before continuing.
- Build your first **[derived parameter](./15_DERIVED_PARAMETERS.md)** — **B220 ÷ CD45**, the same idea as a GFP ÷ RFP reporter ratio — predict where T cells land in its live preview, then plot it as a histogram of Sample C's Leukocytes, where B and T cells form two peaks roughly 60× apart.
- Learn the rules of thumb for ratios: compensate first, watch the denominator, and treat the result as relative units.
- Choose a fair statistic in the **Statistics** tab (% Parent rather than % Total when samples carry different amounts of debris), read the table, and pick a chart that keeps long population names readable.
- Compare the two methods in **Comparisons** with Violin, Channel Heatmap, Histogram Overlay (on your ratio) and Pseudocolor Overlay, then export a plot and the statistics table.

Along the way, short questions check each idea before you move on: pick the right answer to continue, and after two tries the correct one is outlined. Your answers stay on your computer.

<!-- SCREENSHOT: docs/images/user/academy/course6-statistics-table.png — the Statistics tab showing the computed table comparing hand-gated B-cells against UMAP B Cells -->

## After you finish

Each course awards a badge on completion, tracked on the course catalog card so you can see your progress at a glance. Nothing about the courses is one-shot — you can revisit any of them, or explore a tab on your own, using either the Academy's demo project or your own data.

<!-- SCREENSHOT: docs/images/user/academy/course-completion-badge.png — the course-completion celebration screen showing an earned badge -->

## Where to go next

- **[Getting Started](./01_GETTING_STARTED.md)** — the same core workflow as Courses 1 and 2, written out for readers who'd rather read than click through a tutorial.
- **[Overview](./00_OVERVIEW.md)** — the full map of every tab.
- Once you've completed all seven courses, the individual tab guides (**[Workspace](./02_WORKSPACE.md)** through **[Sample Lens](./16_SAMPLE_LENS.md)**) are the best reference for details a guided course necessarily moves past quickly.
