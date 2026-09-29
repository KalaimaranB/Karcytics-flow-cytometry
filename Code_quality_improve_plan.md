# Google-Grade Quality Sprint: Implementation Plan

## Goal

Achieve code quality that **exceeds Google's Python standards** and enable CodeRabbit to perform a full, meaningful first review of the entire codebase — not just diffs.

---

## Current State (Audit Results)

| Metric | Current | Target |
| --- | --- | --- |
| Ruff errors | 0 (done) | 0 |
| Mypy errors | 0 (done) | 0 |
| `# type: ignore` suppressions | 107 | < 20 (unavoidable 3rd-party only) |
| `# noqa` suppressions | 274 | < 40 (architectural exceptions only) |
| Public functions missing docstrings | 290 | 0 (via CodeRabbit automation) |
| Classes missing docstrings | 4 | 0 |
| Test/source line ratio | 0.23x | ≥ 0.5x (via CodeRabbit automation) |
| Files > 500 lines ("God Classes") | 17 | Decomposed or justified |
| `print()` statements in src | 0 (done) | 0 |

---

## How CodeRabbit Reviews Work

> [!IMPORTANT]
> By default, CodeRabbit **only reviews changed files in a PR diff**. To get a full first review of the entire codebase, we must use a specific branch strategy explained in Phase 0.

### CodeRabbit Automation to Leverage

- **Docstrings**: CodeRabbit can auto-generate Google-style docstrings for functions/classes when triggered with `@coderabbitai generate docstrings`.
- **Unit tests**: CodeRabbit can suggest and generate unit test stubs via `@coderabbitai generate unit tests`.
- **Nitpick comments**: CodeRabbit will comment on every remaining smell in a reviewed file.

---

## Phase 0 — Branch Strategy for Full Codebase Review

The trick to force CodeRabbit to review **every file** is to create a PR where the diff is the entire codebase. We do this by creating a fresh branch from an **empty root commit**, so all files appear as new additions.

### Steps

1. Create `quality/full-review-baseline` branch containing only an empty commit
2. Push current `main` state as a squashed commit on top of that empty base
3. Open a PR: `quality/full-review-baseline → main` (do NOT merge — this PR is for review only)
4. Comment `@coderabbitai review` to trigger a full-file-by-file sweep
5. Let CodeRabbit generate docstrings and unit tests on this PR
6. After all CodeRabbit comments are resolved/addressed, separately open the real PRs with actual changes

> [!NOTE]  
> This is a standard pattern called a "review-only PR". It is used specifically to bootstrap CodeRabbit on an existing codebase.

---

## Phase 1 — Fix Ruff & Mypy CI Blockers (Automated)

> [!NOTE]
> **Done.** Verified `ruff check src/` and `mypy src/` both report zero errors across all 181
> source files, and `print()` statements in `src/` are gone.

---

## Phase 2 — Eliminate Suppressions (Root-Cause Fixes)

> [!IMPORTANT]
> **107 `# type: ignore` and 274 `# noqa` suppressions are the biggest signal to CodeRabbit that code quality is poor.** These are the primary focus for root-cause fixes.

### 2.1 `# type: ignore` Audit and Triage

Categorize all 107 suppressions:

- **Legitimate** (3rd-party stubs missing: PyQt6, matplotlib, scipy): Move to `pyproject.toml` mypy overrides → delete the inline `# type: ignore`.
- **Structural** (e.g. `Optional` not narrowed): Fix with `assert`, guard, or proper type narrowing — the approach we started in Phase 4.
- **Workarounds** (wrong return type, bad assignment): Fix the code, not the suppression.

**Target**: ≤ 20 remaining, all in UI layer for PyQt6 signal typing (which has no stubs).

### 2.2 `# noqa` Audit and Triage

Categorize all 274:

- **`# noqa: D...`** (missing docstrings): Delete these — CodeRabbit will generate them.
- **`# noqa: PLR0913/0917`** (too many args): Refactor functions to use dataclass config objects or keyword-only args.
- **`# noqa: PLR2004`** (magic numbers): Extract named constants.
- **`# noqa: S110/BLE001`** (broad exception): These are the pre-approved architectural ones — keep, but verify all others.

**Target**: ≤ 40 remaining (only `S110`/`BLE001` architectural guards and Qt event handler patterns).

---

## Phase 3 — Docstrings (CodeRabbit Automated)

**Do NOT write these manually.** This is CodeRabbit's job.

### Strategy

1. In the Phase 0 review PR, after CI passes, comment: `@coderabbitai generate docstrings`
2. CodeRabbit will open a sub-PR with Google-style docstrings for all 290 public functions.
3. Review, approve, merge.

### What to enable in `ruff.toml`

Currently `D100`–`D107` (all docstring rules) are **ignored**. After CodeRabbit generates docstrings:

- **Remove** `D100`, `D101`, `D102`, `D103`, `D104`, `D105`, `D107` from the ignore list.
- **Keep** `D106` (nested classes) and `D205` (blank line in summary).
- This enforces docstrings in CI from that point forward.

---

## Phase 4 — Unit Tests (CodeRabbit Automated)

**Do NOT write these manually either.** CodeRabbit generates unit test stubs.

### Strategy

1. After docstrings are merged, comment: `@coderabbitai generate unit tests` on the review PR.
2. CodeRabbit targets the analysis layer first (framework-agnostic, easy to test headlessly).
3. Review generated tests — they will need fixtures and integration with the existing `conftest.py`.

### What to enforce after

- Add `--cov-fail-under=60` to `pytest` in CI (current ratio is 0.23x, targeting ≥0.5x).
- Add `pytest-cov` badge to README.

---

## Phase 5 — Structural Refactors (God Classes)

These are the 17 files over 500 lines that CodeRabbit will flag as "God Classes". We address them **before** the full review so CodeRabbit's comments are about logic, not structure.

### High-Priority Decompositions

| File | Lines | Strategy |
| --- | --- | --- |
| `statistics_explorer.py` | 1528 | Extract: `StatisticsTableModel`, `StatisticsExportService`, `StatisticsFilterPanel` |
| `population_analysis_viewer.py` | 1348 | Extract: `PopulationPlotController`, `PopulationDataService` |
| `main_panel.py` | 1176 | Extract: `MainPanelEventBus`, `MainPanelLayoutManager` |
| `cluster_results_panel.py` | 1163 | Extract: `ClusterPlotRenderer`, `ClusterExportService` |
| `course1.py` | 1001 | Extract tutorial steps into a `steps/` package |
| `spectral_learning_tab.py` | 1011 | Extract: `SpectralPlotRenderer`, `SpectralDataController` |
| `comparisons_viewer.py` | 1065 | Extract: `ComparisonRenderer`, `ComparisonDataSelector` |

> [!NOTE]
> These are **not renamed or deleted** — they become thin orchestrators that delegate to the extracted components. This preserves all existing signal/slot connections.

---

## Phase 6 — Named Constants (Magic Numbers)

CodeRabbit's `# noqa: PLR2004` audit will catch these. Pre-emptively:

1. Create `src/karcytics_plugins/flow_cytometry/analysis/constants.py` (likely already exists — verify).
2. Extract all numeric literals used in comparisons into this module:
   - Gate thresholds, bin counts, color channel limits, timeout values.
3. Create `src/karcytics_plugins/flow_cytometry/ui/constants.py` for UI-specific values:
   - Pixel sizes, animation durations, font sizes.

---

## Phase 7 — CodeRabbit Configuration Tuning

Update `.coderabbit.yaml` to maximize the quality of the first review:

### Enable full-repo scan

```yaml
reviews:
  finishing_touches:
    docstrings:
      enabled: true    # Let CR generate docstrings
  tools:
    ast-grep:
      enabled: true    # Structural pattern matching
    ruff:
      enabled: true    # CR runs its own ruff check
    mypy:
      enabled: true
```

### Add review scope to cover unchanged files

```yaml
reviews:
  auto_review:
    enabled: true
    base_branches:
      - "quality/full-review-baseline"  # Forces full file coverage
```

---

## Phase 8 — CI/CD Hardening

Minor gaps to close before the full review so the pipeline is bulletproof:

1. **Add coverage gate**: `--cov-fail-under=40` (start achievable, raise later).
2. **Add `ruff format --check`** as a pre-commit gate (currently only in CI).
3. **Pin `actions/checkout@v4`** with SHA for supply chain security.
4. **Add `CODEOWNERS`** file: `* @KalaimaranB` so all PRs route to you.
5. **Add `dependabot.yml`** for automated dependency updates in `.github/`.

---

## Execution Order

> [!IMPORTANT]
> **Phase 0 (CodeRabbit review PR) comes LAST.** The goal is to eliminate all known debt first so CodeRabbit's review is high-signal — focused on logic, architecture, and content (docs/tests) — not on noqa and type: ignore noise you already know about.

### The Rule

**Everything you CAN control → fix yourself first. Everything left → let CodeRabbit review and automate.**

```text
YOU FIX                              WHAT
────────────────────────────────────────────────────────────────
Phase 1  Fix CI blockers             ruff=0 errors, mypy=0 errors
Phase 2  Kill suppressions           noqa ≤40, type:ignore ≤20
Phase 5  Decompose God Classes       structural clarity before review
Phase 6  Named constants             eliminate PLR2004 magic numbers
Phase 8  CI hardening                coverage gate, CODEOWNERS, Dependabot
Phase 7  Tune .coderabbit.yaml       configure before opening the PR
────────────────────────────────────────────────────────────────
CODERABBIT AUTOMATES                 WHAT
────────────────────────────────────────────────────────────────
Phase 0  Open full-repo review PR    force CR to see every file
Phase 3  @coderabbitai generate      290 Google-style docstrings
         docstrings
Phase 4  @coderabbitai generate      unit test stubs for analysis layer
         unit tests
```

### Why this order?

Opening the CodeRabbit PR before cleaning up would flood it with ~300+ comments about noqa and type: ignore suppressions you already know about — pure noise. After cleanup, CodeRabbit's comments will be about **architecture, logic, and correctness** — the high-value feedback you actually want.

---

## Open Questions

> [!IMPORTANT]
> **God class decomposition (Phase 5)** — Do you want to tackle this in the same sprint, or defer the structural refactors and let CodeRabbit flag them as review comments first? The former is cleaner but riskier; the latter is safer but means CodeRabbit's first review will be full of structural noise.

> [!IMPORTANT]
> **CodeRabbit PR strategy** — Are you comfortable with the "empty base commit" approach for Phase 0? The alternative is to manually open a PR with a trivial change and use `@coderabbitai review` on a per-file basis, which is slower but less confusing in git history.
