# Derived Parameters

A **derived parameter** is a new per-cell measurement you calculate from the ones every event already has — for example **GFP ÷ RFP**, **log10(PE)**, or **B220 ÷ CD45**. Once you've built one, it behaves exactly like a real detector channel: you can put it on a plot axis, draw gates on it, propagate those gates, and compute statistics on it.

Derived parameters are marked with **ƒ** wherever channels are listed (e.g. **ƒ B220/CD45**).

## When they're useful

| Situation | Example formula | Why |
| --- | --- | --- |
| Reporter normalized to a transfection/expression control | `[GFP-A] / [RFP-A]` | Cancels out how much plasmid each cell happened to receive, leaving promoter activity. |
| Ratiometric dyes and biosensors | `[Indo1-Violet-A] / [Indo1-Blue-A]` | For calcium, pH and FRET sensors the ratio *is* the measurement. |
| A marker relative to a reference marker | `[FITC-A] / [APC-A]` (B220 ÷ CD45) | Normalizes cell-to-cell differences in overall staining; often gives a tighter peak than the marker alone. |
| Share of a combined signal | `[A] / ([A] + [B])` | A bounded 0–1 value that's easy to gate and compare. |
| Two channels carrying the same marker | `[A] + [B]` | E.g. a combined "dump" channel. |

Without a derived parameter, a ratio only appears as a diagonal band on a 2D plot — you can't draw a clean "top 10% by ratio" gate or report a median ratio.

## Building one

Open the editor either way:

- **ƒ Derived** on the **Gating** ribbon, or
- **＋ New derived parameter…** at the bottom of any plot's **X:** or **Y:** dropdown — whatever you create from there is put straight onto that axis.

<!-- SCREENSHOT: docs/images/user/derived/editor.png — the Derived Parameters window building B220/CD45, preview showing the B-cells population -->

1. **Start from** a template — *Ratio A ÷ B*, *Log ratio*, *Fraction A ÷ (A + B)*, *Normalized difference*, or *Sum* — and pick channels **A** and **B**. The formula and a suggested name (e.g. *B220/CD45*) fill in automatically.
2. Or write any formula yourself. Wrap channels in brackets — `[FITC-A]`, or a marker name like `[B220]` — and use `+ - * / ^ ( )` and the functions `log10`, `ln`, `log2`, `exp`, `sqrt`, `abs`, `asinh`, `min(a, b)`, `max(a, b)`. The channel and operator buttons insert at the cursor. Editing a template's formula by hand switches it to *Custom formula*.
3. Choose the **default axis scale** (*Log* suits ratios; *Linear* suits log-ratios, fractions and differences).
4. Check the **preview**: a histogram of the result with its median and the share of invalid events, for any sample and population you pick. When you pick a population, it's drawn in **blue** over the whole sample in **grey**, on an axis that stays put as you switch populations — so you can see where each population sits.
5. Click **Save**.

Errors show as you type, with the position of the problem (for example *"Unknown channel [CD999] (character 12)"*).

Derived parameters belong to the whole workspace: every sample gets the new column, new samples you add later get it too, and it's saved with the workspace and in workflow templates.

## Invalid events

Some events can't produce a sensible value — dividing by zero, or taking the log of a value at or below zero. Those events are **invalid** for that parameter:

- they fall outside every gate drawn on it,
- they're left out of its statistics (median, CV, …) — but still count as cells everywhere else,
- they aren't drawn on its plots.

With **"Treat events with a zero or negative denominator as invalid"** on (the default), any division by a value ≤ 0 is invalid too. Compensated values often dip slightly below zero, and dividing by them produces huge or sign-flipped ratios that would otherwise swamp a plot.

!!! warning "A rising % invalid is a warning sign"
    If the preview shows many invalid events in a population, the denominator is too dim there — the ratio is mostly noise for those cells.

## Rules of thumb

- **Compensate first.** A ratio of uncompensated channels includes spillover. Derived values are recalculated automatically whenever compensation is applied, changed or toggled.
- **Ratios are in relative units.** Fluorophores differ in brightness, so a B220 ÷ CD45 of 0.6 doesn't mean 60% of CD45 is B220. Compare ratios between cells and samples stained and acquired the same way.
- **Log scale hides values ≤ 0.** On a log axis, cells whose ratio is zero or negative can't be shown; switch to linear to see them.

## Editing and deleting

Select a parameter in the list to edit it. If gates are drawn on it, you'll be asked before saving a new formula — the gate boundaries stay where they are, but their populations and statistics are recomputed. Each gate also remembers the formula it was drawn on; the Properties panel shows it and flags when the definition has changed since.

Deleting a parameter that gates use lists those gates and offers to delete them (and everything gated inside them) too. Renaming never affects gates.

Up to 20 derived parameters can be defined per workspace. A derived parameter can't reference another derived parameter.

## Where they appear

| Place | Derived parameters available? |
| --- | --- |
| Plot X/Y axes, gates, gate propagation | Yes |
| Statistics channel (★ stats) | Yes |
| Comparisons: Violin, Histogram Overlay | Yes |
| Comparisons: Channel Heatmap, Radar | No — those compare raw detector intensities side by side |
| UMAP / Population Analysis, compensation | No — they're computed from detectors, not formulas |

!!! tip "Try it in the Academy"
    Course 4 walks through building **B220 ÷ CD45** on the demo data, plotting it, and using it as the Statistics channel.
