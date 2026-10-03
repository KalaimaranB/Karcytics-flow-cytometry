# Compensation

Spectral compensation computationally isolates target fluorophore emissions by mathematically eliminating signal bleed-through from overlapping spectral signatures. The **Compensation** tab provides a robust, algorithm-driven environment for generating, reviewing, and applying high-dimensional spillover matrices.

![alt text](../images/03_compensation/compensation_tab.png)

## 1. Getting a Matrix: Choose a Method

Every matrix is obtained in two steps, shown as the two rows at the top of the **Compensation** tab:

1. **Get a matrix** — pick a **Method**, then click the button beside it. The line under the selector says what the method needs and what it found in your loaded samples.
2. **Fine-tune & apply** — adjust any cell by hand (section 2), then apply.

Below the header, a switch chooses what fills the tab:

- **Matrix** — the matrix editor and its before/after preview (section 2).
- **⚙ Method setup** — for the selected method: how it works and its limits, its options, the samples it will use right now, and (for calculated methods) a report of what the last run rested on. With no matrix yet, this page is shown.

The status line always names the method behind the current numbers, for example *method: **Embedded in the FCS files**, then **fine-tuned by hand***. Running a method again replaces the matrix with that method's own numbers and clears the fine-tuned mark.

| Method | Button | Needs |
| --- | --- | --- |
| **Embedded in the FCS files** (default) | **📄 Extract from FCS** | A `$SPILL` / `$SPILLOVER` keyword in a loaded file |
| **Single-stain controls** | **🔬 Calculate Matrix** | At least two samples with role **Single Stain** (an **Unstained Control** is optional) |
| **FMO controls** | **🧮 Estimate from FMOs** | Samples with role **FMO Control** |
| **Import from a file** | **📥 Import CSV** | A `.csv`, `.tsv` or `.txt` matrix, e.g. from FlowJo or R |

### Fitting on a gated population
Single-stain and FMO calculations use every recorded event by default. To calculate on the real cells only, draw a scatter gate (for example **Cells** on FSC/SSC) on the control samples in the Workspace tab, then pick it under **Fit on** in Method setup.

- Only gates drawn on FSC/SSC are offered, including gates nested under other scatter gates (`Cells › Singlets`). A gate on a fluorescence axis depends on the very compensation being calculated, and can cut away the bright events the calculation needs.
- The gate only chooses which events the calculation uses. The finished matrix is applied to every event of every sample.
- A control without the chosen gate is used whole; the **Events used** column says so for each control.

### Embedded in the FCS files (default)
Many acquisition cytometers record the acquisition-time matrix in the FCS metadata. When your files carry one, Karcytics loads and applies it as soon as the samples are loaded, and this method is the one selected when you open the tab. **📄 Extract from FCS** re-reads it, which is also how you go back to the cytometer's numbers after editing.

Method setup lists which samples carry a matrix and whether they agree with the one being read. **Read from** picks the sample; by default it is the first one that has a matrix.

### Single-stain controls
Assign the roles **Single Stain** (and optionally **Unstained Control**) in the Properties Panel first. Each control's primary channel is the one with the highest median of its uncompensated events; spill into every other detector is the ratio of medians, after subtracting the unstained background. Method setup lists the controls and how many events of each are used.

### FMO controls
A fluorescence-minus-one control carries every dye except one, so whatever its missing dye's detector records is spill from the other dyes. Karcytics fits that detector against the others for each FMO and solves for the spillover matrix. Method setup spells out each step.

- Assign the role **FMO Control** to each sample in the Properties Panel.
- **Which dye each tube lacks** is shown in the Method setup table, with how it was worked out: *set by you*, *from its name* (`FMO APC`, `FMO APCCy7`, `FMO CD4` and `FMO minus PE-A` all work), or *from its data* (the channel where the tube is clearly dimmer than the other FMO controls). Change it in the **Missing dye** column of that table, or in the Properties Panel; a manual choice always wins.
- Only one tube is used per dye. A tube that can't be placed, or that duplicates another, is listed as *not used* with the reason.
- A detector without an FMO gets no estimate. Those cells are left at 0 and shown in *grey italic* in the matrix, so you can see what still needs filling in by hand.
- The fit is robust: events with signal in the missing dye's detector that the other dyes don't explain (dead cells, aggregates) are down-weighted rather than read as spill.
- **See it step by step** in Method setup draws the fit on one of your own tubes (pick the tube above the plot; with no FMO controls loaded it uses made-up example data). **Next** and **Play** walk through four steps: what the tube recorded, an ordinary fit, the robust fit with the down-weighted events greyed, and the spill removed, with the cloud sliding flat. It follows the **Fit on** gate, so it shows the same events the calculation uses.
- After a run, the **fit report** in Method setup lists, per detector: the tube used, the events fitted, the share set aside as outliers, how much of the detector's signal the fit attributes to spill (R²; near 0 simply means little spills into it), and the largest spill found.
- Treat the result as a starting point: check each pair on the preview and fine-tune.

### Import from a file
Load a matrix computed elsewhere. Channel names are read from the header row.

## 2. Reviewing and Fine-Tuning the Matrix

Once a matrix is loaded or computed, it is vital to review it for excessive spectral overlap.

1. Open the **Compensation** tab. The matrix editor fills the tab below the two header rows. The status line shows the matrix's size, the method that produced it, and how many samples it is applied to; **Export CSV** and **Toggle Compensation** sit at the top right.
2. Inspect the off-diagonal coefficients. Each **row is a dye** and each **column is a detector**: a cell is the share of the row dye's signal picked up by the column detector. The two cells of a pair (for example FITC → PE and PE → FITC) are separate numbers and are edited independently.
3. Click a cell to plot its pair — its dye on X, its detector on Y. The two cells behind the plotted pair are highlighted, and the note under the matrix says which way each one moves the events.
4. Check the result in the preview on the right, which redraws as you type:
    - **Sample** picks which sample is shown. Judge each cell on the single-stain control for its dye.
    - **Scatter** shows the same events **Before** (raw signal) and **After** (with the matrix as edited), on identical axes. A correctly compensated single-positive population sits level rather than slanting.
    - **Histogram** overlays before (grey) and after (colour) for each of the two channels, which shows whether a negative population has been pushed below zero.
5. Edits are a draft: the status line shows **unapplied edits** and nothing in the workspace changes until you click **✅ Apply to All**, which saves the edits and recompensates every loaded sample. From then on the status line marks the matrix as **fine-tuned by hand**. Cells you edited are shown in **green bold**, cells the method could not estimate in *grey italic*; the marks are saved with the matrix. **↩ Revert Edits** discards them. You can leave the tab and come back without losing a draft.

![alt text](../images/03_compensation/compensation_editor.png)

!!! warning
    High spillover values (typically $>50\%$) indicate severe spectral overlap, which may compromise population resolution. If you observe excessive values, consider redesigning your panel or referencing the **Spectral Ribbon** to analyze the physical overlaps.

## 3. Matrix Application

Matrix computation does not destructively alter the raw `.fcs` event data. 

- **Apply to All**: Click **✅ Apply to All** to project the inverted compensation matrix onto your biological datasets. All active visualizations will synchronously refresh to reflect the compensated geometry.
- **Toggle Compensation**: Use the **🔄 Toggle Compensation** button to quickly flip back and forth between raw and compensated states across all samples. This is highly useful for verifying that your matrix has resolved the spectral overlaps without overcompensating (resulting in "bowing" populations).

## 4. Matrix Export

Once verified, the active compensation matrix can be exported by clicking **📤 Export CSV**. This allows you to standardize the matrix for downstream computational pipelines or documentation in publications.
