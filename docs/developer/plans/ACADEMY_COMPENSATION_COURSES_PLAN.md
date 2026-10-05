# Plan: teach the new Compensation tab (Courses 1–2 become 1–3)

**Status:** plan only, nothing built. Resume from the first unchecked box in [Phases and checkpoints](#phases-and-checkpoints).

**Why:** the Compensation tab now has selectable methods, a Method setup page, the FMO method with its step-by-step illustration, before/after previews across samples, fine-tuning, and a matrix library. Course 1 still teaches the old tab in 8 steps, and its Apply step points at a button on a page that isn't open. The gating order also changes: **Cells gate → compensation → Live Cells**, because the FMO fit runs on the Cells gate and Live Cells is gated on a compensated channel.

**Constraints (from the user):**
- Every course stays at **55–70 steps** (total, side branches included).
- Order in the first course: setup, Cells gate, singlets explained, then compensation, before any Live Cells gate.
- Five courses in total: today's 1 and 2 become 1, 2 and 3; today's 3 and 4 become 4 and 5 unchanged.
- The rules of [ACADEMY_ACTIVE_LEARNING_PLAN.md](ACADEMY_ACTIVE_LEARNING_PLAN.md) still apply: questions replace explanations, quoted numbers come from the data, wrong answers carry feedback.

---

## 1. The split

Compensation is cut in two by skill: **judging a matrix you already have** (Course 1) and **building and refining your own** (Course 2).

| # | Course | Content | Steps (approx.) |
| --- | --- | --- | --- |
| 1 | Setup, first gate & compensation basics | Intro 3 · import and roles 14 · Cells gate and singlets 17 · Spectral viewer and masterclass 7 · compensation part A 18 · save and graduation 2 | 61 |
| 2 | Building a matrix & clean-up gates | Checkpoint and intro 3 · compensation part B 22 · Live Cells 15 · Leukocytes 20 · propagation, save, graduation 3 | 63 |
| 3 | Immunophenotyping | Today's Course 2 minus its Spectral section (8 steps), plus a reworded recap | 62 |
| 4 | Population analysis | Today's Course 3 | 62 |
| 5 | Derived parameters & statistics | Today's Course 4 | 56 main path |

Step counts for existing sections were counted from the source; new sections are budgets. Each phase re-counts.

Why the Spectral viewer moves to Course 1: it explains *why* spillover exists, which belongs before the learner reads a matrix, not a whole course after. Its masterclass slideshow ends on "which control tubes would you need to build a matrix?", which sets up Course 2.

## 2. What the tutorial data offers

Measured on `tests/data/fcs/` (FMO fit on all events; re-measure on the Cells gate in Phase 0).

| Pair (dye → detector) | File's matrix | FMO method | Use in the course |
| --- | --- | --- | --- |
| PE → PerCP-Cy5.5 | 0.300 | not estimated (0, greyed) | The key hook. There is no PerCP-Cy5.5 FMO, so the FMO method leaves that column empty. PerCP-Cy5.5 is the **PI** channel, so this cell decides whether PE-bright cells look dead. |
| Pacific Blue → APC-Cy7 | 0.000 | 0.051 (earlier runs: about 0.02 on Cells) | Shows that "Fit on: Cells" changes the answer. |
| APC → APC-Cy7 | 0.170 | 0.194 | Two methods, close agreement: what "roughly agree" looks like. |
| PE → FITC | 0.030 | 0.047 | Same. |

Other facts the course text must respect:
- The file's matrix is **applied automatically on import** (samples show ✦). "Apply to all samples" in Course 1 therefore reports that samples were skipped.
- All five FMO tubes are placed **from their data**; the e450 tube's name does not identify its dye, so it is the natural example for "How we know".
- The PE tube clears the detection threshold narrowly (0.48 against 0.5). If the threshold rule changes, re-check that all five still place.

## 3. Course 1 — compensation part A (judge the matrix you have)

Placed after the Cells gate and singlets. Replaces `c1_s12_comp_intro` … `c1_s16_apply_matrix`.

| # | Step | Type |
| --- | --- | --- |
| 1 | Why compensate now: scatter gates don't need it, every fluorescence gate does | Info |
| 2 | The file's matrix was applied on import (✦ in the sample list) | Info |
| 3–9 | Spectral tab: viewer, your six markers, EX/EM, overlap, Learning Compensation masterclass. Moved from `c2_s43`–`c2_s49`; `c2_s47` loses its reference to the DP population, which isn't gated yet. `c1_spillover_effect` (existing question) sits here. | Mixed |
| 10 | Open the Compensation tab | Verification |
| 11 | Method setup: the Method dropdown, and why *Embedded in the FCS files* is the default | Info |
| 12 | The setup table: which files carry a matrix and whether they agree | Info |
| 13 | Click **Extract from FCS**; the tab switches to Matrix | Interaction |
| 14 | "Which cell says how much PE leaks into the PerCP-Cy5.5 detector?" (on screen; answer 0.30, row = dye, column = detector) | Question |
| 15 | The status line names the method the numbers came from | Info |
| 16 | Set the preview to X = PE, Y = PerCP-Cy5.5 | Interaction |
| 17 | "After compensation, how should a PE-only population sit?" (level, not tilted up) | Question |
| 18 | View → Scatter + histograms; what the histograms add | Interaction + Info |
| 19 | Sample → All samples | Interaction |
| 20 | "Why check every sample, not one?" (a matrix that fits one tube can over- or under-correct another) | Question |
| 21 | Matrices page: the result was saved with a name, "✓ in use" | Info |
| 22 | **Prediction:** "The FMO method has no PerCP-Cy5.5 tube. What will it say about spill into that detector?" Revealed in Course 2. | Question (P) |

Then save and graduation. The course ends with the data compensated by the file's matrix, so stopping here leaves nothing broken.

## 4. Course 2 — compensation part B (build your own), then the clean-up gates

| # | Step | Type |
| --- | --- | --- |
| 1 | Checkpoint: 10 samples, roles, Cells gate, compensated | Verification |
| 2 | Why build your own: a file may carry no matrix, and a cytometer's matrix deserves a check | Info |
| 3 | Compensation tab → Method: **FMO controls** | Interaction |
| 4 | How it works (the explanation on the page, in one bubble) | Info |
| 5 | The tube table: Missing dye, How we know | Info |
| 6 | "The e450 tube's name doesn't say Pacific Blue. How was it placed?" (dim in that channel compared with the other FMOs) | Question |
| 7 | Fit on → **Cells** | Interaction |
| 8 | "Why fit on Cells rather than all events?" (debris and aggregates aren't dye signal) | Question |
| 9 | See it step by step: pick a tube, press Play | Verification |
| 10 | "What are the greyed points in step 3?" (events the robust fit set aside) | Question |
| 11 | Click **Estimate from FMOs** | Interaction |
| 12 | The fit report: events fitted, set aside, R² | Info |
| 13 | Matrix page: the grey italic PerCP-Cy5.5 column. Reveal of Course 1's prediction. | Info (reveal) |
| 14 | Matrices → Compare with the file's matrix | Interaction |
| 15 | "Which difference matters most for a PI viability gate?" (PE → PerCP-Cy5.5: 0.30 against 0) | Question |
| 16 | Open the FMO matrix in the editor; preview PE against PerCP-Cy5.5 | Interaction |
| 17 | Type 0.30 into PE → PerCP-Cy5.5; the cell turns green and the status says fine-tuned | Verification |
| 18 | Watch the preview level out | Info |
| 19 | Save current as… (name it) | Interaction |
| 20 | Other methods in one bubble: single stains, CSV import, manual | Info |
| 21 | Decide: the file's matrix came from full single-stain controls, so it stays in use. Select it and **Apply to all samples**. | Verification |
| 22 | Recap: compare, understand the differences, then choose | Info |

Then Live Cells, Leukocytes and propagation, moved from Course 1 with their step ids unchanged.

**Step 21 is a hard requirement, not a teaching choice.** Every number quoted in Courses 3–5 and every gate guide was measured with the file's matrix (`tests/functional/test_tutorial_numbers.py`). The checkpoint before Live Cells must confirm the matrix in use equals the embedded one.

## 5. Engineering

**Course identity**
- Keep `flow_course_1_fundamentals`, `flow_course_2_gating`, `flow_course_3_analysis`, `flow_course_4_reporting` so saved progress, badges and recorded answers survive. Add `flow_course_compensation` between 1 and 2; `flow_course_2_gating` now requires it.
- Displayed numbers come from registration order (`__init__.py::register_courses`, `tutorials/courses.py`). Rename the modules to match what the learner sees (`course2.py` → `course3.py`, and so on) with `git mv`, ids untouched.
- Moved steps keep their ids (`c1_s26…`, `c2_s43…`). New steps in the new course use the prefix `cc_`.
- Check how `{answer:c1_thymus_few}` resolves across courses before moving any question: answers are stored per course id.
- A learner who finished today's Course 1 will see Course 1 complete and the new Course 2 not started, though they already drew its gates. Accept this; the new Course 2's gate steps pass immediately when the gate exists.

**Existing code that names a course**
- `tutorials/validators.py:880–883` records prerequisites by id on save. Add the new id. The second call uses `flow_course_3_pipeline`, which is not a registered id (the course is `flow_course_3_analysis`); check whether Course 3 unlocking relies on it.
- `ui/widgets/spectral_viewer.py:307` shows the Learning Compensation tab only while `flow_course_2_gating` is active. It must follow the masterclass to Course 1.
- `Course1StateValidator` (used by `c2_s00_verify`) expects Cells → Live Cells → Leukocytes. It stays for Course 3. Course 2 needs a new checkpoint: samples, roles, Cells gate, compensated.
- Tab indices: Gating 1, Compensation 2, Spectral 5.

**New validators** (`tutorials/validators.py`)
- Method selected; page shown (setup / matrix / matrices).
- Matrix in the editor came from a given source; matrix library holds a named entry.
- Fit-on gate equals "Cells". Method options live on the view, not in state, so this validator reads the view.
- A given cell was edited to a value within tolerance (`origin == CELL_EDITED`).
- Preview shows a given channel pair, view or "All samples".
- The matrix in use equals the embedded one (the Step 21 gate).

**Widget names to add** for spotlights. Present today: `CompensationMethodCombo`, `CompensationPageToggle`, `ExtractFCSButton`, `MethodSetupPanel`, `MethodSampleCombo`, `MethodGateCombo`, `MethodIllustrationCombo`, `EditorMatrixCombo`, `PreviewPopulationCombo`, `CompensationGuideButton`, `MatrixLibraryPanel`, `MatrixLibraryList`, `MatrixCompareCombo`, `ApplyAllButton`. Missing: the setup inputs table and fit report, the illustration's Play/Next buttons, the matrix table, the preview's Sample, X, Y and View selectors, the status line, and the library's Save, Open in editor and comparison table.

**Tests**
- `tests/unit/tutorials/` (`test_course_step_graph`, `test_question_steps`, `test_target_names`, `test_properties_view_steps`) each list the four courses; add the fifth.
- `test_tutorial_numbers.py`: add the quoted matrix values (0.30, the FMO values on Cells) to `QUOTES`, and import the new course.
- A test that the Step 21 validator rejects the FMO matrix and accepts the embedded one.

**Docs:** `docs/user/10_ACADEMY_TUTORIALS.md`; the old tab order in `00_OVERVIEW.md`, `01_GETTING_STARTED.md`, `02_WORKSPACE.md`; compensation screenshots.

## Phases and checkpoints

Work continues on `main`, one commit per phase, unpushed until the user says otherwise. Each checkpoint is a play-through of the changed course (by the user, or the offscreen walk-through used for the active-learning plan).

- [ ] **Phase 0: settle the facts.** In the app, with the tutorial files: (a) FMO fit on Cells — record the values that the course will quote; (b) apply the FMO matrix without the PE → PerCP-Cy5.5 cell and confirm the PE vs PerCP-Cy5.5 preview visibly tilts, and that typing 0.30 levels it; (c) confirm re-applying the file's matrix after applying another restores the original events exactly; (d) answer the two open checks in §5 (answer lookup across courses, the `flow_course_3_pipeline` id). If (b) is not visible on screen, part B needs a different hook before any step is written.
- [ ] **Phase 1: restructure with no new teaching.** New course registered, modules renamed, Live Cells / Leukocytes / propagation moved to Course 2, Spectral block moved to Course 1, checkpoints and prerequisites rewired, test lists updated. The compensation sections are the old 8 steps, repaired for the new tab. *Checkpoint: all five courses complete end to end.*
- [ ] **Phase 2: plumbing for the new steps.** Widget names and validators from §5, with tests. No course text.
- [ ] **Phase 3: Course 1 part A** (§3). *Checkpoint: play Course 1.*
- [ ] **Phase 4: Course 2 part B** (§4), including the prediction reveal and the Step 21 gate. *Checkpoint: play Course 2, then the first gate of Course 3 on the saved workspace.*
- [ ] **Phase 5: wording pass on Courses 3–5.** Course numbers in text, Course 3's intro, objectives and recap now that Spectral has left it. *Checkpoint: skim each course's first and last five steps.*
- [ ] **Phase 6: numbers test, user docs, version bump and release.**

## Open decisions

1. **Spectral viewer in Course 1 or Course 2?** Planned: Course 1 (61 / 63 / 62). In Course 2 instead the totals are about 54 / 70 / 62, which puts Course 1 just under the range.
2. **New course id and module renames** as in §5, or leave module names alone and accept that `course2.py` holds what learners call Course 3.
3. **Detection threshold.** Whether to make missing-dye detection judge by how far the dimmest channel stands out, before the course quotes "how we know" on a tube that passes narrowly.
