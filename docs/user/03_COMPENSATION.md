# Compensation

Spectral compensation computationally isolates target fluorophore emissions by mathematically eliminating signal bleed-through from overlapping spectral signatures. The **Compensation** tab provides a robust, algorithm-driven environment for generating, reviewing, and applying high-dimensional spillover matrices.

![alt text](../images/03_compensation/compensation_tab.png)

## 1. Getting a Matrix: Choose a Method

Every matrix is obtained in two steps, shown as the two rows at the top of the **Compensation** tab:

1. **Get a matrix** — pick a **Method**, then click the button beside it. The line under the selector says what the method needs and what it found in your loaded samples.
2. **Fine-tune & apply** — adjust any cell by hand (section 2), then apply.

The status line always names the method behind the current numbers, for example *method: **Embedded in the FCS files**, then **fine-tuned by hand***. Running a method again replaces the matrix with that method's own numbers and clears the fine-tuned mark.

| Method | Button | Needs |
| --- | --- | --- |
| **Embedded in the FCS files** (default) | **📄 Extract from FCS** | A `$SPILL` / `$SPILLOVER` keyword in a loaded file |
| **Single-stain controls** | **🔬 Calculate Matrix** | At least two samples with role **Single Stain** (an **Unstained Control** is optional) |
| **FMO controls** | **🧮 Estimate from FMOs** | Samples with role **FMO Control** |
| **Import from a file** | **📥 Import CSV** | A `.csv`, `.tsv` or `.txt` matrix, e.g. from FlowJo or R |
| **Advanced algorithms** | — | None available yet |

### Embedded in the FCS files (default)
Many acquisition cytometers record the acquisition-time matrix in the FCS metadata. When your files carry one, Karcytics loads and applies it as soon as the samples are loaded, and this method is the one selected when you open the tab. **📄 Extract from FCS** re-reads it, which is also how you go back to the cytometer's numbers after editing.

### Single-stain controls
Assign the roles **Single Stain** (and optionally **Unstained Control**) in the Properties Panel first. Each control's primary channel is the one with the highest median; spill into every other detector is the ratio of medians, after subtracting the unstained background.

### FMO controls
A fluorescence-minus-one control carries every dye except one, so whatever its missing dye's detector records is spill from the other dyes. Karcytics fits that detector against the others for each FMO and solves for the spillover matrix.

- Assign the role **FMO Control** to each sample. The missing dye is taken from the experiment template, or from the sample's name when it contains exactly one marker or channel name (for example `FMO CD4` or `FMO minus PE-A`).
- A detector without an FMO gets no estimate: spill into it is left at 0. The status note lists those detectors.
- The estimate is only as good as the spread of the other dyes in the tube. Markers that are always expressed together can't be told apart, so check the result on the preview and fine-tune.

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
5. Edits are a draft: the status line shows **unapplied edits** and nothing in the workspace changes until you click **✅ Apply to All**, which saves the edits and recompensates every loaded sample. From then on the status line marks the matrix as **fine-tuned by hand**. **↩ Revert Edits** discards them. You can leave the tab and come back without losing a draft.

![alt text](../images/03_compensation/compensation_editor.png)

!!! warning
    High spillover values (typically $>50\%$) indicate severe spectral overlap, which may compromise population resolution. If you observe excessive values, consider redesigning your panel or referencing the **Spectral Ribbon** to analyze the physical overlaps.

## 3. Matrix Application

Matrix computation does not destructively alter the raw `.fcs` event data. 

- **Apply to All**: Click **✅ Apply to All** to project the inverted compensation matrix onto your biological datasets. All active visualizations will synchronously refresh to reflect the compensated geometry.
- **Toggle Compensation**: Use the **🔄 Toggle Compensation** button to quickly flip back and forth between raw and compensated states across all samples. This is highly useful for verifying that your matrix has resolved the spectral overlaps without overcompensating (resulting in "bowing" populations).

## 4. Matrix Export

Once verified, the active compensation matrix can be exported by clicking **📤 Export CSV**. This allows you to standardize the matrix for downstream computational pipelines or documentation in publications.
