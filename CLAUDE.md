# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A Karcytics plugin (`flow_cytometry`) — flow cytometry analysis (FCS I/O, Logicle transforms, compensation, hierarchical gating, UMAP, statistics) built on FlowKit. Runs as a **separate process** (`process_model = "isolated"` in `pyproject.toml`'s `[tool.karcytics.plugin]`), not in-process inside the Hub — this is different from an in-process plugin, so it must never import `karcytics.*` (the Hub package); it only depends on `karcytics_sdk` (from the sibling `Karcytics-SDK` repo, resolved via `[tool.uv.sources]` as an editable local path).

Entry point: `[tool.karcytics.plugin] entry_point = "karcytics_plugins.flow_cytometry:initialize"`. Plugin id/version/signing metadata all live in that same `pyproject.toml` table — `tests/` is deliberately excluded from the release ZIP and from the signed `security.json` ledger (`custom_exclusions = ["tests"]`); don't add production code under `tests/` expecting it to ship.

The package version has one source of truth: `pyproject.toml`'s `[project].version`, read at runtime via `importlib.metadata` with a source-tree fallback (see `src/karcytics_plugins/flow_cytometry/__init__.py::_read_version`) — never hardcode the version elsewhere.

See `../Karcytics/ECOSYSTEM.md` for the full map of all 7 Karcytics repos and their relationships.

## Qt binding

PySide6 only (LGPL; PyQt6 is GPL and incompatible with our license). Never import PyQt6 — `karcytics-sdk doctor .` flags it (KS203). PySide6 differs from PyQt6 in ways tests don't always catch; see "Qt binding" in `../Karcytics-SDK/CLAUDE.md` for the full list. The ones that bit this repo: `Signal(dict)` silently drops non-string keys (use `Signal(object)`), `layout.removeWidget(None)` raises, a failed `disconnect()` warns instead of raising (use `safe_disconnect` from the SDK), and `patch("PySide6.QtWidgets.QMenu.exec")` does not reach an SDK subclass — patch the class actually instantiated (`BioMenu`).

## Commands

```bash
uv run pytest tests/unit/ --tb=short -q          # what pre-commit runs — unit only
uv run pytest tests/ -q                          # full suite incl. functional/integration/ui
uv run pytest tests/unit/analysis/test_x.py -q   # single test file
uv run ruff check src/ tests/ --fix
uv run ruff format src/ tests/
uv run mypy --explicit-package-bases src/
```

Pre-commit already runs ruff, mypy, pip-audit, license compliance, `tests/unit/` (not the full suite), a plugin re-signing step, and security-ledger verification. Don't pre-run the full suite before committing — the hook only runs `tests/unit/`; run `tests/functional`, `tests/integration`, or `tests/ui` yourself only for changes that touch those layers.

The SDK contract test lives in `tests/contract/` and runs on its own (`uv run pytest tests/contract --noconftest`), because `tests/conftest.py` mocks the SDK.

### Karcytics doctor

`karcytics-sdk doctor . --baseline` runs in pre-commit and CI, and a Claude Code hook (`.claude/settings.json`) runs it on every file you edit. It fails only on findings over `.karcytics-baseline.json`. When it reports something:

- Fix the cause. Don't add a `noqa`, `type: ignore` or `# karcytics: allow` to silence it; if a suppression is genuinely right, it must say why (`# karcytics: allow KS360 - <reason>`).
- After a change that lowers a count, run `uv run karcytics-sdk doctor . --update-baseline` and commit the baseline with it. That command never raises a count; don't use `--reset-baseline` to absorb new debt.
- Rules and fixes: `../Karcytics-SDK/docs/Doctor.md`.

Test markers: `unit`, `functional`, `integration`, `ui` (needs Qt/display), `slow`, `edge_case`.

## Structure

`src/karcytics_plugins/flow_cytometry/`:
- `analysis/` — pure compute, no Qt. Top-level modules hold the science (`transforms.py`, `compensation.py`, `statistics.py`, `fcs_io.py`, the clustering analyses); `gating/` (gate types and the gate tree), `compute/` (`dag_evaluator.py`, boolean logic nodes), `services/` (gate mutation helpers), `clustering/`, `derived/` (derived parameters), `sample_lens/`, `animation/` (UMAP step animations).
- `ui/` — `builders/`, `controllers/`, `dialogs/`, `graph/` (canvas/plotting), `ribbons/`, `services/`, `widgets/`.
- `workflows/` — JSON-serializable experiment templates.
- `tutorials/` — Academy/guided-tutorial content and assets.

This mirrors the SDK's `PluginBase`/`AnalysisBase` split ([Karcytics-SDK](../Karcytics-SDK)'s `CLAUDE.md`): UI code in `ui/` should call into `analysis/` for computation rather than embedding it, since `analysis/` needs to stay independently testable and Qt-free.

`tests/` mirrors `src/` plus `tests/data/fcs` (sample FCS fixtures) and `tests/fixtures/`.

## Docs

`docs/developer/` — read before touching the corresponding area, these are current and detailed:
- `00_ARCHITECTURE_OVERVIEW.md`, `04_SERVICES_AND_DEPENDENCY_INJECTION.md` — the `ServiceFactory` composition root (`ui/composition_root.py`) that wires domain/infrastructure services; construct new services there, not ad hoc in panel code.
- `02_UI_ENGINE.md`, `07_RENDERING_AND_VISUALIZATION.md`, `08_DATA_FLOW_AND_SIGNAL_CONNECTIONS.md` — before working in `ui/`.
- `05_GATING_AND_COMPENSATION_DEEP_DIVE.md`, `06_TRANSFORMS_AND_SCALING.md` — before working in `analysis/`.
- `09_DERIVED_PARAMETERS.md` — before adding any code path that loads, reloads or replaces a sample's `fcs_data`/`events` (it must re-sync derived columns — see "The sync contract").
- `03_TESTING_AND_QA.md` — testing conventions beyond the marker list above.

`docs/user/` covers user-facing workflows (gating, compensation, spectral unmixing) if you need the scientist-facing behavior spec rather than the implementation.
