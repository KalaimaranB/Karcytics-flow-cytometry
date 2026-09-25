# Academy & Guided Tutorials

The **Academy** is a built-in, hands-on tutorial system — not a video, not a static walkthrough, but a guided coach that lives inside the workspace itself. It highlights the exact button or panel you need next, watches what you actually do (the shape of the gate you drew, the role you assigned, whether you saved), and only moves on once your work genuinely checks out. If you get something wrong, it tells you what happened and fixes it for you — a poorly drawn gate gets deleted, a correctly-shaped-but-misnamed one gets renamed — so you're never stuck.

Best of all, it provisions its own demo data: **you don't need any FCS files of your own** to try it.

!!! tip "Click the button"
    If you're reading this instead of trying it, stop here and click **🎓 Cyto Academy** in the top-right of the tab bar. It's the single fastest way to actually learn this module.

<!-- SCREENSHOT: docs/images/user/academy/academy-button-highlighted.png — the 🎓 Cyto Academy button in the tab bar, top-right corner -->

## Opening the Academy

Click **🎓 Cyto Academy**, next to the Save Workspace button in the tab bar. This opens the **Academy course catalog** — a set of course cards showing your progress and any badges you've already earned.

<!-- SCREENSHOT: docs/images/user/academy/course-catalog.png — the Academy catalog window showing three course cards (Flow Cytometry Fundamentals, Immunophenotyping/Pipeline/Spectral Mastery, Population Analysis & Advanced Comparisons) with progress indicators -->

Pick a course and it starts immediately: a floating tutor overlay appears on top of your workspace, with a speech-bubble guide (nicknamed **Cyto**) and a soft spotlight highlighting whichever button, panel, or plot region you need to interact with next.

<!-- SCREENSHOT: docs/images/user/academy/spotlight-overlay.png — the tutorial overlay mid-course, showing Cyto's speech bubble and a glowing highlight around the Add Samples button -->

## How a course actually teaches you

Every course is built from three kinds of steps, and you'll move through all three constantly:

- **Explains a concept.** No action required — read it, then click Next. This is where the "why," not just the "how," gets covered (why FMO controls matter, what compensation is correcting for, what UMAP's axes do and don't mean).
- **Asks you to do something real.** Click the highlighted button, draw a gate, switch a tab, open a sample — the step only advances once you actually perform that interaction in the live workspace.
- **Checks your work automatically.** Karcytics polls your actual workspace state every couple of seconds — did the gate you drew land in roughly the right place? Did you assign the role correctly? Is the right tab active? Did you actually save? — and advances the moment it's satisfied. A wrong gate shape gets silently deleted with an explanation; a right-shaped-but-misnamed gate gets renamed for you automatically so you're never blocked by a typo.

This is what makes the Academy different from a static walkthrough: it's checking the same underlying data your analysis actually depends on, not just whether you clicked "Next."

## Your demo data

Course 1 provisions ten realistic tutorial FCS files (a Blank, a PI viability single stain, five FMO controls, and three "mystery" experimental samples) the first time you need them. If they're already present in your project or a known folder, this is instant; otherwise Karcytics downloads them once (roughly 100&nbsp;MB) from the project's own reference dataset, showing live progress as it goes. You'll never need to hunt for or prepare your own files to complete any of the three courses.

<!-- SCREENSHOT: docs/images/user/academy/file-provisioning.png — the provisioning step showing live download progress ("6/10 files done") -->

## The three courses

The courses build on each other in order — Course 2 requires Course 1's saved workflow, and Course 3 requires Course 2's.

### Course 1 — Flow Cytometry Fundamentals

**~50 minutes · no prerequisites · badge: 🔬 Flow Fundamentalist**

The on-ramp. You're handed three unidentified samples — one Spleen, one Thymus, one Bone Marrow — and told you'll have an evidence-based answer for which is which by the end of Course 2. Along the way you:

- Import all ten tutorial files and learn what a **Group** is and why it controls gate propagation.
- Tag every file with its **Role** (Unstained, Single Stain, FMO Control, Full Panel), one at a time and then in bulk.
- Learn *why* spillover happens — dyes emit across broad, overlapping wavelength ranges, not single clean peaks — then watch Karcytics auto-detect and apply an embedded compensation matrix, and manually extract and apply one yourself so you know exactly what happened under the hood.
- Build a real three-level gating hierarchy — **Cells → Live Cells → Leukocytes** — reading Forward/Side Scatter physics, using a viability control with a Biexponential axis, and anchoring a CD45 gate to an FMO control's true background before confirming it against a real stained sample.
- Learn the "No-Jump" axis-locking rule and watch Auto-Propagation copy your gates to every sample in the group in real time via the **Group Preview** panel.
- Save your workspace — required to continue into Course 2.

<!-- SCREENSHOT: docs/images/user/academy/course1-gating-hierarchy.png — the Gating Hierarchy panel showing the completed Cells → Live Cells → Leukocytes tree at the end of Course 1 -->

### Course 2 — Immunophenotyping, Pipeline & Spectral Mastery

**~45 minutes · requires Course 1 · badge: 🧬 Immunophenotyper**

Picks up exactly where Course 1 left off (it checks that your saved workflow is actually loaded before starting). You:

- Gate **T-cells** and **B-cells** out of your Leukocytes population two different ways — a two-marker scatter rectangle for one, a histogram-plus-live-FMO-overlay range gate for the other — and learn when each technique is the better call.
- Split T-cells four ways at once with a single **Quadrant** gate (CD4+, CD8+, double-positive, double-negative), then rename all four resulting leaves.
- Learn to read and reorient the **Pipeline** flowchart view, including the boolean **AND/OR/NOT** logic nodes you'll put to real use in a later course.
- Explore the **Spectral Viewer**'s real, FPbase-sourced dye curves, work through an interactive **Learning Compensation** masterclass slideshow built from your own panel's real numbers, and learn when overlapping spectra actually matter biologically versus when they don't.
- Use the **Quick-Stats** grid to read hard numbers across every sample and build a genuine, evidence-based hypothesis for which mystery sample is Thymus, Bone Marrow, and Spleen.
- Save your workspace again — required to continue into Course 3.

<!-- SCREENSHOT: docs/images/user/academy/course2-quadrant-gate.png — a CD4 vs CD8 plot with a completed Quadrant gate showing the four renamed subpopulations (CD4+, CD8+, DP, DN) -->

### Course 3 — Population Analysis

**~50 minutes · requires Course 2 · badge: 🧠 Population Analyst (awarded once Course 3 is complete)**

Course 3 is being released in parts — it doesn't yet end in a graduation screen; a "Course 3 will be complete soon!" step marks where the released content currently stops, and you can safely resume from there once more ships. No new manual gating anywhere in it. You:

- Validate that your Course 2 gating tree (Leukocytes, T-cells, B-cells) is actually in place before continuing.
- Get a real explanation of what UMAP's axes do and don't mean, with a recommended external video for a deeper dive.
- Select Sample C (the confirmed Spleen) and the Leukocytes gate, and exclude the PI and CD45 channels — each choice explained, not just instructed.
- Walk every run parameter — Neighbors, Min Distance, Subsample %, Distance Metric, Seed, and HDBSCAN's Minimum Cluster Size — with a real justification for each.
- Run the analysis and watch the real, data-driven UMAP animation play out live, built from your own Sample C data.
- Explore the results in the **Plot Gallery** and the **Interactive Map** — hovering over populations to read their marker expression, and switching the map's marker dropdown to watch different lineages light up.
- Let the course itself identify your run's real B-cell cluster from its marker profile (no two runs get the same cluster ID), export it as a genuine gate-tree population, and cross-check it against your own hand-gated B-cells with a Pipeline **AND** node.
- Read the real agreement between the two independent methods in the **Statistics** tab (table and all three chart types) and every chart type in **Comparisons**, including the new Pseudocolor Overlay.

<!-- SCREENSHOT: docs/images/user/academy/course3-umap-plot.png — the Population Analysis tab showing a UMAP projection colored by marker expression, with distinct population "islands" visible -->

## After you finish

Each course awards a badge on completion, tracked on the course catalog card so you can see your progress at a glance. Nothing about the courses is one-shot — you can revisit any of them, or explore a tab on your own, using either the Academy's demo project or your own data.

<!-- SCREENSHOT: docs/images/user/academy/course-completion-badge.png — the course-completion celebration screen showing an earned badge -->

## Where to go next

- **[Getting Started](./01_GETTING_STARTED.md)** — the same core workflow as Course 1, written out for readers who'd rather read than click through a tutorial.
- **[Overview](./00_OVERVIEW.md)** — the full map of all eight tabs.
- Once you've completed all three courses, the individual tab guides (**[Workspace](./02_WORKSPACE.md)** through **[Comparisons](./09_COMPARISONS.md)**) are the best reference for details a guided course necessarily moves past quickly.
