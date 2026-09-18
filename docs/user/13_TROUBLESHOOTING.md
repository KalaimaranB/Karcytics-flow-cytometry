# Troubleshooting Guide

Common issues, error messages, and solutions for Karcytics Flow Cytometry analysis.

---

## Data Loading Issues

### Issue: "FCS File Not Found" or "Permission Denied"

**Symptoms:** Error when trying to open FCS file.

**Solutions:**

1. Verify file path is correct (no typos or moved files).
2. Check the file isn't locked by another application (e.g. open in FlowJo).
3. Try copying the file into your project's own `assets` folder and re-adding it from there — Karcytics offers to do this automatically the first time you add a file from outside the project (see [Workspace](./02_WORKSPACE.md#1-importing-data)).
4. On network drives, verify the connection is active before retrying.

---

### Issue: "Unrecognized FCS Format"

**Symptoms:** An error parsing the file header when loading.

**Solutions:**

1. Verify the file is actually FCS format (not a renamed `.txt`/`.csv`).
2. Check the FCS version — Karcytics supports **FCS 2.0, 3.0, and 3.1**. Very old (1.0) or newer, less common variants may not parse correctly.
3. Try opening the file in another tool (e.g. FlowJo) to confirm it isn't corrupted.
4. If it still fails, contact your instrument core — the export may be non-standard.

---

### Issue: Slowness or instability with very large datasets

**Symptoms:** Sluggish plotting or high memory use with samples in the millions of events.

**Solutions:**

1. Open the sample's plot and click **⚙ Settings** — every render mode has a **Max Events** cap with quick-set buttons (e.g. 10k/50k/100k/All in Dot Plot) that limits how many events are actually drawn.
2. Switch to the **Fast Preview** quick preset in the same dialog while you're actively exploring, then switch back to **Standard** or **Publication** once you've settled on a view. See [Global Rendering Settings](./02_WORKSPACE.md#4-global-rendering-settings).
3. Close other applications to free RAM.
4. If problems persist on very large panels, consider gating out unneeded populations early so downstream plots and statistics run against fewer events.

---

## Visualization Issues

### Issue: "Empty Plot" or "No Events Displayed"

**Symptoms:** Canvas shows a blank plot despite data being loaded.

**Possible Causes & Solutions:**

| Cause | Solution |
|-------|----------|
| Wrong axis selected | Check the **X:** / **Y:** dropdowns above the plot |
| Data out of display range | Press **F** with the mouse over the plot to fit the view to your data |
| Gate too restrictive | Double-click a less-restrictive population (e.g. the root) in the **Gating Hierarchy** panel |
| Transform mismatch | Open **⚙ Transforms** and try a different scale (Linear, Log, Biexponential) |
| Compensation not applied | If you expect compensated data, check for the **[Comp]** tag on the sample in the Sample List |

---

### Issue: "Plot Rendering is Slow"

**Symptoms:** The plot takes a noticeable amount of time to update after a change.

**Solutions:**

1. Open **⚙ Settings** on the plot and switch to the **Fast Preview** quick preset, or lower **Max Events** and **Population Detail** manually.
2. If the sample has millions of events, consider gating down to a smaller population before fine-tuning a plot.
3. Close other applications to free CPU.
4. Restart Karcytics if a session has been open a very long time and performance has visibly degraded.

---

### Issue: "Gates Not Visible on Plot"

**Symptoms:** You drew a gate but can't see it overlaid on the canvas.

**Solutions:**

1. Confirm you're looking at the same population the gate was drawn on — double-click the gate's node in the **Gating Hierarchy** panel to navigate to it directly.
2. Press **F** with the mouse over the plot to fit the view — the gate may simply be outside the current zoom/pan.
3. Make sure you're on the sample the gate was actually drawn on (or a group member it propagated to), not an unrelated sample.

---

## Gating Issues

### Issue: "Gates Not Propagating to Other Samples"

**Symptoms:** You drew a gate on one sample, but it doesn't appear on other samples you expected.

**Solutions:**

1. Verify the samples are actually in the same **Group** — check the **Groups** panel, or drag the samples together into one group (see [Workspace](./02_WORKSPACE.md#dataset-grouping)).
2. Manually push the gate to every sample in the group with **📋 Copy Gates** on the **[Gating](./04_GATING.md)** ribbon — this works regardless of the automatic propagation state.
3. Remember propagation only copies a gate to samples that share the same parent population by name; a sample missing that parent population won't receive the child gate.

---

### Issue: "Cannot Draw Gate"

**Symptoms:** Clicking a gate tool does nothing, or drawing doesn't register.

**Solutions:**

1. Confirm the tool is actually selected on the **[Gating](./04_GATING.md)** ribbon (Rect, Polygon, Ellipse, Quad, or Range) — the currently active tool is highlighted.
2. Make sure you're drawing on the plot canvas itself, not on the axis labels or outside the plot area.
3. For Polygon gates: click to place each vertex, then double-click or press **Enter** to close the shape — a single click-and-drag won't work the way it does for Rectangle or Ellipse.
4. Press **Esc** at any time to cancel a gate you started by mistake and try again.

---

## Compensation Issues

### Issue: "Spillover Matrix Computation Failed"

**Symptoms:** An error, or an obviously wrong matrix, when calculating from controls.

**Solutions:**

1. Confirm your control samples have the correct **Role** assigned in the Workspace **Properties Panel** — each single-stain control needs **Single Stain**, and you need one **Unstained** sample as the baseline (see [Workspace](./02_WORKSPACE.md#assigning-sample-roles)).
2. Check that each single-stain control actually shows a clear positive population in its primary detector — a weak or absent stain will produce an unreliable spillover coefficient.
3. If a specific control looks wrong, reassign its role to **Other** temporarily and recompute without it to isolate the problem control.
4. See [Scientific Logic](./11_SCIENTIFIC_LOGIC.md) for the underlying linear algebra.

---

### Issue: "Compensation Looks Wrong"

**Symptoms:** After applying compensation, populations look over- or under-corrected (e.g. a diagonal "smear" that should be resolved, or a population bowing the other way).

**Possible Causes:**

| Cause | Solution |
|-------|----------|
| Spillover matrix computed from a weak/noisy control | Recompute using a cleaner single-stain control |
| A control is mislabeled | Verify each Single Stain sample actually contains only that one dye |
| Comparing against already-compensated data | Check the sample's **[Comp]** tag — applying a second matrix on top of an already-compensated file will distort it |
| Overcompensation ("bowing") | Use **🔄 Toggle Compensation** on the [Compensation](./03_COMPENSATION.md) ribbon to compare raw vs. corrected and confirm the correction direction |

---

## Statistics Issues

### Issue: Statistics show 0, NaN, or blank values

**Symptoms:** The Statistics results table shows unexpected values.

**Solutions:**

1. Check the population actually has events — select it in the **Gating Hierarchy** and confirm **Event Count** in the Properties Panel is greater than 0. A count of 0 means the gate was too restrictive (or drawn on the wrong parent).
2. Some statistics need variance to be meaningful — **CV** on a population with a single repeated value, or on a very small population, can legitimately read 0 or be unstable.
3. Make sure you clicked **Compute Statistics** again after changing your sample/population/statistic selection — see [Statistics](./06_STATISTICS.md).

---

## Performance & Crashes

### Issue: Karcytics crashes or reports an unexpected error

When the core application or a plugin hits a fatal error, Karcytics shows a **"System Alert — Karcytics Diagnostic"** dialog automatically, with a summary of what happened, the recent log lines, and an optional field for describing what you were doing. Click **Send to Sentry** to send that report directly — this is the primary way to report a bug, no separate bug tracker step needed.

If you'd rather not send a report automatically, or want to gather details to share yourself:

- Open **Preferences** (Edit menu, or **Ctrl+,** / **Cmd+,**) → **Privacy & Diagnostics**, which has **Open Logs Folder** and **Copy Diagnostic Report** buttons.
- Logs are written to `~/.karcytics/logs/` on every OS (Windows, macOS, and Linux all use the same home-directory-relative path) — `core.log` for the main application, and a per-plugin log under `plugin_workers/` for the Flow Cytometry module specifically.
- You can also reach out to the developer directly, or file an issue at [Karcytics-flow-cytometry/issues](https://github.com/KalaimaranB/Karcytics-flow-cytometry/issues) for the Flow Cytometry plugin specifically.

### System requirements

Karcytics is primarily supported on modern **Windows** and **macOS**. Linux is not currently a first-class packaged target — it can be run from source, but isn't part of the main packaged release. It requires **Python 3.11 or 3.12**. For more detail see the main Karcytics installation guide.

---

## Related Documentation

- **[Getting Started](./01_GETTING_STARTED.md)**: Basic workflow tutorial
- **[Keyboard Shortcuts](./12_KEYBOARD_SHORTCUTS.md)**: The real, current set of key bindings
- **[Scientific Logic](./11_SCIENTIFIC_LOGIC.md)**: Mathematical principles behind compensation and transforms
