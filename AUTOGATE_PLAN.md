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
- [ ] **2. Engine core.** Data types already exist in `models.py`. Still to
      build: the shared transform helper, the `Splitter` (GMM by BIC plus
      density valley, with a check for two clear peaks and no GPL `diptest`),
      the `Namer`, the `GateBuilder` and `gate.provenance` (serialized). Unit
      tests on synthetic blobs, including a one-blob control.
- [ ] **3. Density valleys live.** The real engine replaces the demo for this
      method. Accept writes gates via the gate coordinator; `GatePropagator`
      copies them to the group.
- [ ] **4. PCA.** The projection derived parameter (frozen loadings, centre,
      scale and logicle settings), the PC-plane view chooser, and the loadings
      and scree panels fed by real numbers.
- [ ] **5. Marker-pair search.**
- [ ] **6. Run to the stopping rules + Why panel from real provenance +
      methods text.**
- [ ] **7. Apply to group.** Real review table; adaptive mode through
      `Gate.adapt()`; flag big moves.
- [ ] **8. Compare methods.** Dry runs; agreement with manual gates via
      `sample_lens/agreement.py`.
- [ ] **9. Academy course + user docs** (`docs/user/00_OVERVIEW.md` tab list,
      Sample Lens "sits between" wording, a new `17_AUTO_GATING.md`).
