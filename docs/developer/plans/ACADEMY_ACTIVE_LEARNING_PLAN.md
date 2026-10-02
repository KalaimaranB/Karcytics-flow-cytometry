# Plan: active, question-based learning in the Flow Academy

**Status:** Phases 1–2 merged (SDK 2.4.0, flow #4); Phases 3–6 done on `feature/academy-course-plumbing` (2026-10-01); Phase 7 next. Resume from the first unchecked checkpoint in [Phases and checkpoints](#phases-and-checkpoints).

**Released so far:** SDK 2.3.0 (`QuestionStep`, SDK #14); flow 0.10.0 (flow #2), plus the first Course 4 questions merged to `main` (flow #3).

**Branches:** one per phase in each repo, each merged before the next starts. Phase 2: SDK and flow `feature/academy-popup-highlights` (SDK 2.4.0).

**Why:** the professors asked for more active learning. Today the courses explain and the learner clicks; they rarely have to *think*. We want:

- **Questions the learner must answer correctly to move on.** Single-choice or select-all-that-apply, about what's on screen or what was just covered.
- **Question now, answer later.** Ask a prediction ("which hump will the T cells be in?"), let the learner find out, and pay it off, sometimes a whole course later. Course 1's spleen/thymus/bone-marrow mystery, solved in Course 2, is the model.
- **No longer courses.** Steps get more concise, with the learning built into them. Course 4 (80 steps) should get *shorter*.

It also covers two points from the course review: Course 4's feature-tour feel, and highlights drawn on the wrong window for targets inside popups.

---

## 1. Principles

1. **Every question earns its place.** It tests something the learner needs later or checks a misconception that is common in real analysis. No trivia about where a button is.
2. **Replace explanations with questions, don't add to them.** A step that explains "dead cells take up PI, so they're bright" becomes "Which peak are the dead cells?" The explanation moves into the answer feedback.
3. **Wrong answers teach.** Every wrong option has its own feedback explaining *why* it's wrong. The learner retries until correct. After 2 wrong attempts, the correct option is highlighted, but they still have to pick it, so there's no dead end.
4. **Short.** Question ≤ 50 words, each option ≤ 15 words, feedback ≤ 40 words (enforced by a test).
5. **On-screen questions spotlight what to look at**, and leave the UI usable (`allow_interaction=True`) so the learner can hover, zoom or switch a dropdown before answering.
6. **Numbers in questions come from the tutorial data**, checked by a test (see §6). Never "about 60%" from memory.

## 2. SDK: a `QuestionStep` (Karcytics-SDK)

`BranchingStep` is not enough. It renders options as footer buttons, title-cases their labels, and has no notion of a correct answer. So we add a new step type in `karcytics_sdk/plugin/tutorial_models.py`:

```python
@dataclass
class AnswerOption:
    text: str
    correct: bool = False
    feedback: str = ""          # shown when this option is chosen (why right / why wrong)

@dataclass
class QuestionStep(BaseStep):   # text = the question
    options: list[AnswerOption] = field(default_factory=list)
    multi_select: bool = False  # "select all that apply"
    kind: str = "check"         # "check" (must be correct) | "predict" (any answer, revealed later)
    question_id: str = ""       # stable key for recording the answer (predictions, analytics)
    explanation: str = ""       # shown once answered correctly, before Continue
    reveal_after_attempts: int = 2
```

**Behaviour:**
- Options render as radio buttons (or checkboxes) *in the bubble body*, with a **Check** button in the footer. Next stays hidden until the answer is correct.
- **Wrong:** show that option's feedback, then retry. Multi-select wrong answers say "one or more are wrong" plus the feedback for the first wrong pick, so the learner isn't told the whole answer.
- **After `reveal_after_attempts` wrong tries:** the correct option(s) are outlined, and the learner must still select them.
- **Correct:** show `explanation`, then Continue → `next_step_id`.
- **`kind="predict"`:** any answer is accepted, and the Continue label says "Let's find out". The answer is recorded for a later reveal.
- **Keyboard:** 1–9 toggles an option, Enter checks.

**Recorded answers:** `AcademyManager.answers[course_id][question_id] = {choice, attempts, correct}`, persisted in `progress.json`. This powers two things:
- **Reveals:** a later step's text can reference the learner's answer, e.g. `{answer:c1_q_mystery}` in text. Because answers are persisted, this works across courses.
- **Future reporting:** optional per-question attempt counts for the professors. Not built now, but stored so it's possible later.

**Validation (in `__post_init__`):**
- At least 2 options.
- Single-select: exactly one correct.
- Multi-select: at least one correct.
- `check` questions: every wrong option has feedback.
- `predict` questions: no correct flags needed.

**Tests:** model validation, overlay rendering (radio vs. checkbox, Check/Continue, wrong-answer feedback, reveal after N attempts), manager recording and persistence, and `{answer:…}` substitution.

**Release:** needs an SDK minor bump (2.1.9 → 2.2.0) and the plugin's `karcytics-sdk>=2.2.0` pin.

## 3. SDK: highlight targets inside popups (review point 4)

The Academy overlay lives in the main window, so a target inside a separate window is spotlit on the main window underneath it. We fixed this for the Derived Parameters dialog with a plugin-side hook (`ui/widgets/tutorial_highlight.py`, `metadata["in_window_targets"]`).

Other popups are parented the same way and likely have the same bug:

| Popup | Steps affected |
| --- | --- |
| Population picker | `c4_s05`, `c4_s17b`, `c4_s20a` |
| Transform dialog | `c1_s27d`, `c1_s30d` |
| Compensation matrix dialog | `c1_s15` |
| Quick-Stats grid | `c2_s50b`–`c2_s53b` |

**Plan:**
1. Audit those steps in the app.
2. Move `TutorialHighlight` into the SDK, and make `AcademyStepDriver._update_targets` split targets by window: the main window gets overlay rects, other windows get in-window frames plus their frame rect so Cyto stays clear.
3. Then drop the plugin's `in_window_targets` special case; ordinary `target_widget_names` just works.

## 4. Making room: conciseness levers

These free about 30 steps across the four courses, so questions fit without growing any course.

| Lever | Today | After | Steps saved |
| --- | --- | --- | --- |
| Tab switches | Click tab + "Checking tab…" + wrong-tab retry (3 steps) | One `VerificationStep` with `TabActiveValidator`, spotlighting the tab (already used by `c4_d05`) | ~25 |
| Generate + wait | "Click Generate" + "Rendering…" (2 steps) | One `VerificationStep` whose validator waits for the plot | ~7 (mostly Course 4) |
| Explanation → question | InfoStep explaining X | QuestionStep about X, with the explanation in the feedback | 0 (swap) |
| Course 4 exports | 4 separate export clicks | One step: "export this table and this plot" (`ForcedInteractionStep` checklist) | ~6 |

**Step budget:**

| Course | Now | Target | Questions (≈) |
| --- | --- | --- | --- |
| 1 | 75 | ≤ 75 | 6 |
| 2 | 75 | ≤ 72 | 6 |
| 3 | 69 | ≤ 68 | 6 |
| 4 | 80 | ≤ 65 | 7 |

## 5. Question map (drafts)

These are drafts: wording and numbers get checked against the app and data while writing. **(P)** = prediction, answered later.

### Course 1: Fundamentals
| # | After / replaces | Question | Answer (feedback carries the why) |
| --- | --- | --- | --- |
| 1 (P) | `c1_s1_intro` | "One sample is thymus, where T cells mature. What will it have *very few* of?" | Recorded; revealed in Course 2 (`c2_s51`). |
| 2 | `c1_s4_roles_intro` | "Which file shows where 'CD45-negative' ends?" | FMO APC (not the Blank: it lacks the other dyes' spillover). |
| 3 | replaces `c1_s12e_spectral_theory_2` | "FITC spills into the PE detector. Uncompensated, a FITC-bright PE-negative cell looks…" | Falsely PE-positive. |
| 4 | replaces `c1_s22d_scatter_physics` (on-screen) | "Where does debris sit on FSC vs SSC?" | Low FSC, low SSC: small, simple. |
| 5 | replaces `c1_s27c_biexp_explain` (on-screen) | "Which peak are the dead cells?" | Right/bright: damaged membranes let PI in. |
| 6 | after `c1_s28_stats_intro` | "Live is 90% of Cells; Cells is 70% of all events. Live's % Total?" | 63%. |

### Course 2: Immunophenotyping
| # | After / replaces | Question | Answer |
| --- | --- | --- | --- |
| 1 | replaces `c2_s06_tcell_plot_read` (on-screen) | "X = B220, Y = CD3. Where are the T cells?" | Upper-left. |
| 2 | `c2_s17_threshold_info` (multi) | "Why set the B220 threshold from the FITC FMO? (select all)" | Includes other dyes' spillover into FITC ✓, same staining as the sample ✓; "It has no cells" ✗. |
| 3 | `c2_s19_bcell_done` | Scenario: "One marker, positive vs. negative — scatter or histogram?" | Histogram + FMO. |
| 4 | replaces most of `c2_s38_quadrant_naming_info` | "X = CD4, Y = CD8. Which quadrant is CD4⁺CD8⁻ (helpers)?" | Lower-right. |
| 5–7 | replace `c2_s51`–`c2_s53` (on-screen, Quick-Stats) | "Sample A: many T cells, almost no B cells. Which organ?" (then B, then C) | Thymus / bone marrow / spleen; `c2_s54` becomes a short recap that pays off Course 1's prediction. |

### Course 3: Population analysis
| # | After / replaces | Question | Answer |
| --- | --- | --- | --- |
| 1 | replaces `c3_s05_umap_theory_2` | "On a UMAP, what does a cell's x = 5 tell you?" | Nothing on its own; only neighbours matter. |
| 2 | replaces `c3_s10_gate_why` (multi) | "Why run UMAP on Leukocytes, not All Events? (select all)" | Debris/dead cells form fake islands ✓, faster ✓; "UMAP can't read scatter" ✗. |
| 3 | replaces `c3_s12_exclude_why` | "Inside Leukocytes, why exclude CD45?" | Every cell is CD45⁺, so it can't separate anything. |
| 4 | `c3_s14_neighbors` | "You're hunting a rare 200-cell population. Neighbours: raise or lower?" | Lower. |
| 5 | replaces `c3_s21_hdbscan_why` | "HDBSCAN clusters which data?" | The original 6-D data, not the 2-D picture. |
| 6 (P) | before `c3_s54_wire_and` | "What % of UMAP B cells will fall inside your hand-gated B cells?" | Revealed at `c3_s56` against the real AND-node number. |

### Course 4: restructured around one question
Driving question, asked at `c4_s00_intro` as **(P)**: *"Are UMAP's B cells and your hand-gated B cells the same cells, measured the same way?"* Every section answers part of it, and graduation shows the learner their prediction next to the evidence.

| Section | Change |
| --- | --- |
| Derived parameter | `c4_d08b` becomes **(P)** "Before you switch: which hump will T cells be in?". `c4_d13_pitfalls` becomes a question: "One population shows 40% invalid — what's wrong?" → dim denominator. |
| Statistics | `c4_s04_stats_theory` becomes a question: "Comparing B cells across organs with different debris — % Parent or % Total?". `c4_s07` becomes an on-screen question: "Which sample has almost no B cells?". The three chart-type steps (`c4_s09`–`c4_s14`) collapse to one step plus a question: "Long population names — which chart?". |
| Comparisons | Drop the radar chart (4 steps). The histogram overlay uses **ƒ B220/CD45** instead of B220, with a question: "Do both B-cell definitions peak at the same ratio?". Generate/wait pairs are merged. |
| Export | 7 steps become 1 checklist step. |
| Graduation | Reveal: prediction vs. the AND node, heatmap and ratio evidence. |

## 6. Quality gates

- `tests/unit/tutorials/test_course_step_graph.py` follows the new link fields (`QuestionStep` next ids) and checks that every **(P)** question has a later reveal step referencing its `question_id`.
- A new `test_question_steps.py` covers: SDK validation passes, length limits (§1.4), the `question_id` is unique across all courses, and there's at least one on-screen question per course.
- A new `test_tutorial_numbers.py` recomputes the numbers quoted in questions and steps from the tutorial FCS files (e.g. B220/CD45 medians, % Total by sample, AND-node overlap) and fails if the text drifts from the data. It needs a small `NUMBERS` table that course text formats from.
- Per phase, the user plays the changed course end to end (the only way to catch overlay/visual issues; see the step 15 spotlight bug).

## Phases and checkpoints

Each phase is one commit on a single branch per repo (see the memory note on phase commits), then a play-through checkpoint by the user before the next phase starts.

- [x] **Phase 0: land the current work.** SDK 2.2.0 (including the spotlight repaint fix) merged as SDK PR #13. Flow work on `feature/undo-redo-integration`, bumped to 0.10.0, is in flow PR #2.
- [x] **Phase 1: SDK `QuestionStep`** (§2) plus tests. Merged: SDK #14 (2.3.0), flow #3. In place of a sandbox course, two real Course 4 questions were added for trying it in the app: `c4_d14_invalid_question` and `c4_s04b_median_question`. *Checkpoint: user plays Course 4 up to the Statistics tab and settles the look.* Done 2026-10-01 as an automated offscreen walk-through (below).
- [x] **Phase 2: SDK cross-window highlights** (§3), then remove the plugin's `in_window_targets` special case. `feature/academy-popup-highlights` (SDK 2.4.0). *Checkpoint: popup steps in Courses 1, 2 and 4 highlight correctly.* Done 2026-10-01: the real panel, loaded from a saved Courses 1–3 workspace, was driven offscreen through every Course 4 step (all but the final Save, which needs the Hub) plus the Course 1 Transforms and Course 2 Quick-Stats popups, with a screenshot per step. It found and fixed: a scrolled-out target framed over the dialog's buttons, and sidebar targets spotlit off-screen (targets are now scrolled into view once per step); question feedback clipped after a wrong-then-right answer; Course 1's unnamed Outliers dropdown (now guarded by `test_target_names.py`); and Course 2/4 text claiming gates propagate only to Samples A–C (they reach every sample in the group, so the B-cells row checks all 10).
- [x] **Phase 3: course plumbing.** Tab-switch and generate/wait collapses (§4) across all four courses; step-graph test updates. *Checkpoint: quick run of each course's first half.* Done: all 13 tab switches are one interactive `VerificationStep` on the tab bar (no "Checking tab…" or "Oops!" steps), and Course 4's Compute and five Generate steps wait on their own validator (no "Rendering…" step). Steps (total / main path): Course 1 75→73 / 60, Course 2 75→70 / 61, Course 3 69→65 / 63→61, Course 4 84→70 / 78→68. Tabs saved fewer main-path steps than the ~25 estimated: in Courses 1–2 the click step was already off the main path. Checked with a full Course 4 walk-through and a Course 2 tab step on the real panel.
- [x] **Phase 4: Course 4** restructure plus questions (§5). *Checkpoint: full play-through.* Done: 56 main-path steps (from 68), 7 questions. Changes from the §5 draft, after checking the data:
    - The opening prediction (`c4_same_measure`) asks whether the two B-cell methods **measure** the same on B220, since Course 3 already shows they're the same cells. It's revealed at the histogram overlay and at graduation.
    - `c4_d08q` is a check question, not a prediction: learners can reason it out from what B220 marks.
    - `c4_d13_pitfalls` stays an InfoStep; making it a question put three questions in four steps.
    - The % Parent question (`c4_s06q`) replaces the old stats theory step, and the table now uses **% Parent and CV** instead of % Total and CV. That also drops the subsample star: UMAP B Cells' % Parent is a share of the Leukocytes UMAP ran on, so it compares directly with B-cells' % of Leukocytes (64% vs 68%).
    - The chart-type question ("which charts keep long names readable?") felt awkward in play-through, so it was replaced with an on-screen CV question: Sample B's B-cells have the lowest CV on the ratio, so what does that mean? It's followed by one Heatmap step.
    - Exports are one `ForcedInteractionStep` with two checked subtasks (Comparisons plot, Statistics CSV); the tabs record successful exports in `completed_exports`.
    - Verified with a full offscreen walk-through to completion, including graduation.
- [x] **Phase 5: Course 1 questions.** *Checkpoint: play-through.* Done: six questions, as drafted. The thymus prediction (`c1_thymus_few`) is revealed in Course 2's `c2_s54_mystery_reveal` alongside Sample A's 0.3% B-cells; Phase 6 may move it when `c2_s51`–`c2_s53` become questions. The spillover, debris, PI and % Total questions replace their InfoSteps and keep the content that mattered in the explanation (single stains drive the matrix; the Cells gate and Biexponential notes; Event Count and Group Preview). The FMO question sits after the roles intro. Steps: 73→75 total (the budget), 60→62 main path. Choices, feedback and explanations render as plain text, so `test_answer_text_is_plain` rejects markdown there. Checked offscreen: every question answered wrong then right on the real panel (debris on the Blank's FSC/SSC plot, PI on the PI sample at Cells), plus the Course 2 reveal showing the recorded answer.
- [x] **Phase 6: Course 2 questions,** including the Course 1 → 2 prediction reveal. *Checkpoint: play-through.* Done: seven questions, all replacing InfoSteps, so Course 2 stays at 70 steps (61 main path). T-cell location (`c2_s06`), why the FMO sets the B220 threshold (`c2_s17`, select all), histogram vs scatter (`c2_s19`), the CD4+ quadrant (`c2_s38`, with the Q1–Q4 map in the explanation), and one organ question per sample in the open Quick-Stats grid (`c2_s51`–`c2_s53`). The questions make learners read the grid rather than stating the numbers. The play-through also caught the grid's old description: samples are its **columns** and every cell is **% Parent**, not rows and % Total, so all four Quick-Stats steps and the reveal (Sample A's B-cells: 0.4% of Leukocytes) now say so. The Course 1 prediction stays revealed in `c2_s54`. Before this phase, two changes after the Course 1 play-through:
    - **Gate checks loosened** (user request): polygon overlap 80% (was 90%); range and rectangle edges within 10% of the axis or 35% of the edge's own value, whichever is larger, so high edges on log axes have room; quadrant crosshairs get a quarter of the target window's width as margin on each side. Low edges keep the axis-wide band only, so a B-cells threshold can't creep into the B cells.
    - **Correct answers no longer always come first.** The SDK shows choices in source order, and every check question in Courses 1 and 4 had the answer first. Positions now vary, and `test_correct_answer_position_varies` keeps it that way.
  Checked offscreen on the real panel: every Course 2 question answered wrong then right, with the plot or Quick-Stats grid it refers to on screen.
- [ ] **Phase 7: Course 3 questions.** *Checkpoint: play-through.*
- [ ] **Phase 8: numbers test** (§6), user docs (`docs/user/10_ACADEMY_TUTORIALS.md`), and the flow plugin version bump that releases it (the SDK side shipped as 2.4.0 in Phase 1–2).

## Decisions (2026-10-01)

1. **Wrong answers:** the learner must select the correct answer to continue. It's outlined after 2 wrong tries, but they still have to pick it.
2. **Recording:** attempts per question are saved locally only (`progress.json`); no export.
3. **Radar chart:** drop its steps from Course 4, but explain what it's for in one sentence: comparing populations' whole marker profiles at once (shape = profile). Point learners to it for many-marker panels.
