# Auto Gating plan

Transparent auto gating: split a population into **ordinary, editable gates**
and record why each was placed. Asked for by a TA as "PCA-based auto gating"
because clustering (UMAP/FlowSOM/PhenoGraph) doesn't show how a population was
found. Three methods, one engine:

| Method | How the view to split is chosen |
| --- | --- |
| Density valleys | The user picks the axes; cuts go at the low point between peaks |
| Marker-pair search | Every pair of real markers is tried; the clearest wins (EPP-style) |
| PCA | Principal-component planes are ranked; each axis shows its loadings |

Everything after the view (splitting, gate building, naming, provenance, UI)
is shared.

## Where it lives

A full-window **Auto Gating** tab between Population Analysis and Sample Lens.
Sample Lens audits existing gates on one sample; auto gating builds gates for a
group, so it is its own tab. Accepted auto gates are ordinary gates, so Sample
Lens audits them with no extra work. The tab links to it.

## Principles

- **Single source of truth**
  - Accepted gates live only in the group's gate tree; proposals are transient.
  - Copying to the group uses the existing `GatePropagator`.
  - A PC axis is one projection-type derived parameter with frozen loadings.
  - Why a gate is where it is lives on the gate (`gate.provenance`); the Why
    panel and the methods text both read that.
  - Method names and blurbs are defined once, in `models.METHODS`.
  - The logicle-transformed matrix becomes one helper, shared with clustering
    `run_input`.
- **SOLID**
  - Each class has one job: `ViewChooser`, `Splitter`, `GateBuilder`,
    `Namer` (reuses `clustering/describe.py`), `Driver`. The UI only renders a
    `Proposal`.
  - A new method is a new `ViewChooser`.
  - The tab depends only on the `AutoGateEngine` protocol (`analysis/autogate/engine.py`).
- **KISS**
  - No new gate types (Ellipse/Polygon/Range/Quadrant).
  - Step-through first; "run to the end" is a loop over the step.
  - Applying to the group starts fixed; adaptive mode goes through `Gate.adapt()`.
  - Method comparisons are transient dry runs.

The engine is picked in one place, `create_auto_gating_tab()` in
`ui/widgets/auto_gating/__init__.py`, which the workspace builder calls. It is
not in `composition_root` because the engine imports the clustering package
(numba), which must stay out of Phase 1 startup. That is the one line to
change when the real engine replaces `DemoEngine`.

## Phases (one commit each on `main`, pause for review after each)

- [x] **1. UI shell.** The tab with Build / Why this gate / Apply to group /
      Compare methods, driven by `DemoEngine` (example output, demo banner,
      Accept changes nothing).
- [x] **2. Engine core.** `GatingEngine` (one engine, method picked per
      request), `density.py` (smoothed-histogram valleys), `mixture.py` (GMM,
      k by BIC over 1–4, kept only while groups overlap < 0.3), `naming.py`,
      `gating/from_display.py` and serialized `gate.provenance`. The demo
      engine is gone.
- [x] **3. Density valleys live.** Rectangle gates on the chosen axes;
      FSC-A × SSC-A is the default first split (scatter channels are listed
      but start unticked for the marker methods). Accept goes through
      `GateCoordinator.add_gate`, so undo and `GatePropagator` apply.
- [x] **4. PCA.** On arcsinh(x/150), standardized; each PC is written as a
      derived-parameter formula, created on accept and reused when the same
      formula already exists. Loadings and variance shown from real numbers.
- [x] **5. Marker-pair search.**
- [ ] **6. Run to the stopping rules.** Why panel and methods text from real
      provenance are done; the Run button is still disabled ("Coming next").
- [ ] **7. Apply to group.** Review table with a per-sample drift check
      (dashed ghost of each sample's own split, flagged above 5%, controls
      skipped) is done; adaptive per-sample gates via `Gate.adapt()` are not.
- [x] **8. Compare methods.** Dry runs of every method, scored against your
      own gates (F1 by label path).
- [x] **Visual gating tree** in the tab (the Gating tab's tree, read-only,
      proposals dashed; click a population to split it or explain it).
- [x] **Cells and singlets first.** By convention, before any marker: Cells
      (debris cut at the valley below the main FSC peak) from All Events, then
      Singlets (FSC area/height ratio) from the cells gate. Skipped, with the
      reason, when already gated or the file can't show them.
- [x] **From a template.** A fourth method: you write the gating tree and each
      population's markers ("CD4+ CD8−"); the runner splits each parent on
      those markers and keeps the region whose calls match. Steps that aren't
      there say why; Singlets steps aside without FSC-H. Templates save as
      JSON. Apply/Compare don't yet cover template runs.
- [ ] **9. Academy course + user docs** (`docs/user/00_OVERVIEW.md` tab list,
      Sample Lens "sits between" wording, a new `17_AUTO_GATING.md`).
