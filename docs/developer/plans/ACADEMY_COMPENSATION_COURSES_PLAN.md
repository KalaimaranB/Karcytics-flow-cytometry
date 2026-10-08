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
- Detection asks that one channel stand clear of the tube's others. The PE tube is the least clear-cut (0.48 as bright as the other FMOs, its next-lowest channel at 1.01) and still places with room to spare.

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
- Saved progress is not a concern (user, 2026-10-04: too few users so far), so ids, modules and step prefixes are renumbered to match what the learner sees: `flow_course_1_fundamentals`, `flow_course_2_compensation` (new), `flow_course_3_gating`, `flow_course_4_analysis`, `flow_course_5_reporting`, in `course1.py` … `course5.py` (`git mv`).
- Step ids follow their course: moved and renumbered steps get the new `c2_` / `c3_` / `c4_` / `c5_` prefix in one mechanical pass, with `question_id`s, `test_tutorial_numbers.py::QUOTES` and the other tests updated in the same commit.
- Check how `{answer:c1_thymus_few}` resolves across courses before moving any question: answers are stored per course id.

**Existing code that names a course**
- `tutorials/validators.py:880–883` records prerequisites by id on save. Update it for the new ids. The second call uses `flow_course_3_pipeline`, which is not a registered id (the course is `flow_course_3_analysis`); check whether Course 3 unlocking relies on it.
- `ui/widgets/spectral_viewer.py:307` shows the Learning Compensation tab only while `flow_course_2_gating` is active. It must follow the masterclass to Course 1 (`flow_course_1_fundamentals`).
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

- [x] **Phase 0: settle the facts.** Done 2026-10-04 on the tutorial files, with the Cells gate drawn along `c1_s24_cells_gate`'s guide and the real Compensation view rendered offscreen.
    - **(a) FMO fit on Cells** (about 100,000 events sampled from about 302,000 in Cells per tube; 1.3–4.7% set aside): PE → FITC 0.043, FITC → PE 0.029, PerCP-Cy5.5 → PE 0.045, Pacific Blue → FITC 0.016, Pacific Blue → APC-Cy7 0.032 (0.051 on all events), APC-Cy7 → APC 0.036, APC → APC-Cy7 0.194. The PerCP-Cy5.5 column is not estimated.
    - **(b) The hook is visible.** On Sample A, PE against PerCP-Cy5.5: with the FMO matrix the main population stays a diagonal streak, the same as the raw plot; with the file's matrix, or with 0.30 typed into PE → PerCP-Cy5.5, it sits level. PE-bright cells' median PI reading is about 3,300 with the FMO matrix, 1,250 with the cell filled in, 930 with the file's matrix.
    - **(c) Re-applying the file's matrix** brings events back to within float rounding of the imported values (largest difference 0.19 on values up to about 260,000), not bit for bit. The Step 21 gate therefore compares matrices, not events.
    - **(d)** `{answer:…}` looks through every course's answers, so questions can move freely. Nothing in the SDK or Hub reads the prerequisites recorded on save (`has_prerequisite` has no callers), so the `flow_course_3_pipeline` id is dead but harmless; tidy it in Phase 1.
- [x] **Phase 1: restructure with no new teaching.** Done 2026-10-04. Five courses registered (`flow_course_1_fundamentals`, `flow_course_2_compensation`, `flow_course_3_gating`, `flow_course_4_analysis`, `flow_course_5_reporting`) in `course1.py` … `course5.py`, with step ids, question ids and in-text course numbers renumbered to match.
    - **Course 1 (55 steps):** setup → Cells and singlets → compensation. The Spectral block (`c1_sp43`–`c1_sp49`) sits before the Compensation tab switch. The old compensation steps are repaired for the three-page tab, with one added step to open Matrices before Apply (`c1_s15b_open_matrices`).
    - **Course 2 (37 steps):** new checkpoint (`SetupAndCellsStateValidator`: samples, roles, Cells gate, every sample compensated), intro, then Live Cells, Leukocytes and propagation as `c2_…`.
    - **Course 3 (63 steps):** loses the Spectral block; its recap now leads straight to the mystery. Courses 4 and 5: 62 and 58.
    - Checkpoint validators are named for what they check, not a course number (`BaseGatesStateValidator`, `LineageGatingCompleteValidator`, `PopulationAnalysisCompleteValidator`). The unused prerequisite recording on save is gone. The page buttons got object names.
    - **Budget check with the real counts:** Course 1 with part A is about 64 (55 − 9 old compensation steps + 18), Course 2 with part B about 59.
    - *Checkpoint status:* the tutorial tests pass (step graph, target names, gate guides, quoted numbers), and Course 1's compensation clicks were driven on the real Compensation view (Extract switches to Matrix; Apply reports 10 skipped and changes nothing). **No course has been played end to end since the restructure.**
- [x] **Phase 2: plumbing for the new steps.** Done 2026-10-04, no course text changed.
    - **Validators** (`tutorials/validators.py`, tested in `tests/ui/test_compensation_tab_validators.py`): `CompensationMethodValidator`, `CompensationPageValidator`, `CompensationFitGateValidator`, `IllustrationPlayedValidator`, `EditorMatrixValidator` (source, and optionally one hand-edited cell near a value), `PreviewShowsValidator` (x, y, view, sample), `SavedMatrixValidator`, and `EmbeddedMatrixInUseValidator` (the Step 21 gate).
    - They read the tab through new read-only properties on `CompensationView` (`method_key`, `page`, `fit_gate`, `editor`, `illustration_step`, `samples_match_matrix`) and `CompensationEditor.preview_selection`, reached as `state.view._compensation_view`.
    - **Widget names added:** `CompensationSetupPageButton`, `CompensationMatrixPageButton`, `CompensationMatricesPageButton`, `CompensationStatusLine`, `MethodInputsTable`, `MethodReportTable`, `IllustrationNextButton`, `IllustrationPlayButton`, `CompensationMatrixTable`, `CompensationPreviewArea`, `PreviewSampleCombo`, `PreviewXCombo`, `PreviewYCombo`, `PreviewViewCombo`, `MatrixSaveButton`, `MatrixOpenInEditorButton`, `MatrixCompareTable`.
- [x] **Phase 3: Course 1 part A** (§3). Done 2026-10-04: Course 1 is 65 steps. Fourteen steps (`c1_m01`–`c1_m13` plus the Extract click) replace the old compensation steps: Method setup and its table, reading the 0.30 cell, the status line, plotting PE against PerCP-Cy5.5 on Sample A, scatter then histograms, All samples, the Matrices page, and the prediction `c1_fmo_blind_spot`. Four are questions.
    - Changes from the §3 draft: the pair is set by **clicking the 0.3000 cell** (which the editor already supports) rather than two dropdowns, and there is no Apply click, since nothing needs applying; Course 2 applies a matrix for real.
    - The preview opens on whichever sample is open in the workspace (the Blank, after the Cells gate), so the step also asks for Sample A and checks it by name.
    - Course 2's intro shows the prediction back for now; Phase 4 adds the real reveal.
    - *Checkpoint status:* each new step's validator was driven false-then-true on the real tab with the tutorial files, and the scatter and histogram claims were checked against the rendered plots. **Not yet played through with the overlay.**
- [x] **Phase 4: Course 2 part B** (§4). Done 2026-10-04: Course 2 is 60 steps (23 new, `c2_b01`–`c2_b23`, five of them questions). All five courses are within 55–70: 65, 60, 63, 62, 58.
    - Changes from the §4 draft, after checking the app: running a method already puts its matrix in the editor and marks it "in use, changed since it was applied", so there is no "Open in editor" step, and the handover step (re-apply the file's matrix) is genuinely needed. The prediction is revealed at the setup table's last row (`c2_b06_reveal`), before the run, because the table already says "not estimated — left at 0". The fit-report step was dropped to stay in budget.
    - `MatricesComparedValidator` and `CompensationView.library_comparison` were added for the comparison step.
    - `test_tutorial_numbers.py` now checks the matrix values the steps quote (0.30, 0.04, "the largest value", the empty PerCP-Cy5.5 column, agreement "within a few hundredths" elsewhere).
    - *Checkpoint status:* every validator step was driven false-then-true, in order, on the real Compensation view with the tutorial files and a Cells gate; the handover leaves the samples within float rounding of their imported values. **Not yet played through with the overlay**, so spotlight placement (especially targets inside the scrolling Method setup page and the Save-name dialog) is unchecked.
- [x] **Phase 5: wording pass on Courses 3–5.** Done 2026-10-04. Course numbers in step text were shifted in Phase 1. Course 3 is now "Immunophenotyping & the Pipeline": its title, description, objectives and mystery intro no longer promise spectral theory.
- [ ] **Phase 6: numbers test, user docs, version bump and release.** Numbers test and docs done 2026-10-04 (`10_ACADEMY_TUTORIALS.md` describes five courses; tab order and course numbers fixed in `00_OVERVIEW.md`, `01_GETTING_STARTED.md`, `15_DERIVED_PARAMETERS.md`, developer `09_DERIVED_PARAMETERS.md`). The user played Courses 1 and 2 end to end on 2026-10-04 and approved them. **Still open:** a play-through of Course 3 (it lost its Spectral section and now opens from Course 2's workspace), new screenshots, and the version bump and release, which wait for the user.

- [x] **Follow-up: gate editing and undo** (user request, 2026-10-07). Course 3 gains five steps after the T-cells gate (`c3_e01`–`c3_e05`, 68 steps in all): the Select tool, resizing the T-cells gate, a question on the edit reaching every sample, undoing it with the keyboard shortcut, and a question on what Undo doesn't cover. Course 1 mentions Ctrl/Cmd+Z at the Cells gate. Course 2's "which one do we keep?" step now says when you would keep your own matrix.
    - `GateEditTracker` pairs the two steps: the edit step remembers the gate's shape and passes when it differs; the undo step passes when it is back.
    - Checked on the real store, coordinator and Compensation view with the tutorial files: a gate edit is one undo step ("Edit Gate") and Undo restores it on every sample in the group; undoing a matrix change restores the matrix **and** the samples' values; "Apply to all samples" is not an undo step of its own (the matrix change is); cell edits in the matrix editor, axis-scale changes and switching sample make no undo step.
    - *Not yet played with the overlay.* Undo is taught by keyboard shortcut only, as the user asked.

## Decisions (2026-10-04)

1. **Spectral viewer and masterclass go in Course 1.**
2. **Saved progress is not preserved.** Ids, modules and step prefixes are renumbered cleanly (§5).
3. **Missing-dye detection** now requires one channel to stand clear of the tube's others, instead of a fixed half-brightness cut-off. Done ahead of the course work.
