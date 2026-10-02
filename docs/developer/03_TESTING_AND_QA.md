# Flow Cytometry Testing Guide

The suite tests **behavior**: what a gate includes, what a population counts,
what the user ends up seeing. It deliberately does not test that a widget has a
given attribute, that a setter stores its argument, or that a mock was called.
Those tests break on every UI tweak and pass even when the feature is broken.

## Layout

```
tests/
├── conftest.py          # sys.path setup + wholesale karcytics_sdk / karcytics mocks
├── fixtures/            # shared fixtures (synthetic events, pre-built gates, FlowState)
├── data/fcs/            # real Specimen_001 FCS files
├── unit/                # fast, headless — run by pre-commit
│   ├── analysis/        # gating, DAG evaluation, transforms, compensation, stats, I/O
│   ├── tutorials/       # Academy step graphs and validators
│   └── ui/              # Qt-free UI logic (layout, workflow reload, autosave)
├── functional/          # real FCS data through the real gating pipeline
├── integration/         # the isolated ui_daemon subprocess, nothing mocked
└── ui/                  # Qt widgets (needs QT_QPA_PLATFORM=offscreen)
```

| Layer | Runs in | What belongs there |
|---|---|---|
| `unit/` | pre-commit + CI | Pure logic with exact expected outputs |
| `functional/` | CI | Real-data pipeline checks (`test_gating_pipeline.py`) |
| `integration/` | CI | Cross-process behavior (`test_ui_daemon.py`) |
| `ui/` | CI (`-m ui`) | User-visible widget behavior: selection rules, gate editing, Generate Plot, warnings |

```bash
uv run pytest tests/unit/ -q                               # what pre-commit runs
QT_QPA_PLATFORM=offscreen uv run pytest tests/ -q          # everything
uv run pytest tests/functional/test_gating_pipeline.py -q  # real-data golden tests
```

Pre-commit only runs `tests/unit/`. Run `functional/`, `integration/` or `ui/`
yourself when you touch those layers.

## The conftest mocks — and the rule that follows

`tests/conftest.py` replaces `karcytics_sdk.plugin` (including
`CentralEventBus`), `karcytics_sdk.plugin.theme_fallback` (`theme_manager`,
`Colors`, `Fonts`) and the Hub's `karcytics.*` modules with `MagicMock`s or
small dummies before any plugin code is imported. `repopulate_combo` and
`PluginDaemon` are the only real SDK pieces.

**So never assert against those mocks.** Publishing to `CentralEventBus` in a
test delivers nothing, and asserting `theme_manager.apply_style` was called
only checks the mock. Test the handler or the resulting state directly instead:
call the subscribed callback yourself (see `test_main_panel_smoke.py::
test_gate_modified_records_one_undo_step_and_dirties`), or check what the widget
shows.

`Colors` resolves every token to `"#000000"`. If code needs a real palette
(for example `Colors.CHART_COLORS`), pin it on the `Colors` object the module
under test imported (see `test_comparisons_plot_types.py`).

## Patterns worth copying

- **Synchronous task scheduler.** `FlowCanvas`, `ClusterResultsPanel` and
  friends take an injectable scheduler. `test_flow_canvas.py::
  _synchronous_scheduler` and `test_cluster_results_panel_gallery.py::
  _FakeGlobalScheduler` run the task inline but emit its result via
  `QTimer.singleShot(0, ...)`, so `.connect()` calls made right after
  `submit()` are registered in time. Wait with `qtbot.waitUntil`. Don't rely
  on the real `QThreadPool`.
- **Exact masks, not lengths.** A gate's `contains()` mask always has the
  input's length, so `assert len(result) == 3` proves nothing. Assert
  `result.tolist() == [False, True, False]`.
- **Golden counts, not ranges.** `functional/test_gating_pipeline.py` pins exact
  per-population counts on real files, cross-checked against an independent
  numpy calculation. If a change intentionally moves them, re-derive and update
  the table. Don't loosen it into `50 < pct < 95`.
- **Drive the real path.** Prefer one test that clicks Generate Plot and checks
  the canvas is visible (`test_generate_button_produces_a_visible_canvas`) over
  several that call internal helpers.
- **Deleted-widget guards.** `sip.delete(widget)` followed by calling the event
  handler is how the stale-callback tests prove a late `CentralEventBus`
  delivery can't raise.

## What not to write

- `hasattr` / "method no longer exists" checks guarding a past refactor.
- Setter round-trips (`set_axes("X")`, then check `_x_param == "X"`).
- The same shared-helper behavior re-tested at every call site. Test
  `repopulate_combo` once in the SDK; test only a call site's own rules.
- `try: ... except AssertionError: pass`, or anything else that can't fail.
- Wall-clock performance assertions. They flake on CI runners.

## FCS test data

`tests/data/fcs/`. Each file has 9 parameters (`FSC-A`, `SSC-A`, `FITC-A`,
`PE-A`, `PerCP-Cy5-5-A`, `Pacific Blue-A`, `APC-Cy7-A`, `APC-A`, `Time`) with
an embedded spill matrix that `load_fcs` auto-applies.

| File | Events |
|---|---|
| `Specimen_001_Sample A.fcs` | 302,017 |
| `Specimen_001_Sample B.fcs` | 316,110 |
| `Specimen_001_Sample C.fcs` | 319,359 |
| `Specimen_001_Blank.fcs` | 306,425 |
| `Specimen_001_PI.fcs` | 308,721 |
| `Specimen_001_FMO APC.fcs` | 309,246 |
| `Specimen_001_FMO APCCy7.fcs` | 309,681 |
| `Specimen_001_FMO FITC.fcs` | 312,237 |
| `Specimen_001_FMO PE.fcs` | 310,847 |
| `Specimen_001_FMO e450.fcs` | 311,384 |

The panel has no CD4/CD8/CD3/B220 channels. The `sample_a_events` /
`sample_c_events` fixtures are **synthetic** (10,000 seeded events with
CD3/CD4/CD8 columns), not these files, and both return the same frame. Load the
real files with `load_fcs` (see `test_gating_pipeline.py`) when a test needs
real distributions.

## Known issues

- **Biexponential gating is non-deterministic near boundaries.**
  `biexponential_transform` adds ±0.5 random dither by default (meant for
  display banding), and `project_to_display`, which every gate's `contains()`
  uses, doesn't disable it. An event within about 0.5 raw units of a
  biexponential gate edge can flip membership between evaluations (up to
  ~0.4% of a gate's count on Sample A). Tests avoid biexponential boundaries
  until this is fixed. Details and measurements:
  [06_TRANSFORMS_AND_SCALING.md](06_TRANSFORMS_AND_SCALING.md#dithering-jitter-and-its-effect-on-gating).
- **Inverted bounds** (`x_min > x_max`, `low > high`) match nothing rather
  than being swapped or rejected. `test_invalid_inputs.py` pins this. Change it
  there if the behavior changes.
