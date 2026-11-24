# Plan: a more scaffolded Course 1, especially compensation

**Status:** built in one pass on flow `main` (2026-11-23). After a first look (2026-11-24): the deck is self-guided rather than narrated per slide, and the compensation phase was trimmed (merged tab steps; method setup, status line, histograms and the Matrices tour left to Course 2). Awaiting a live play-through. The professor deploys to the whole class within days, so everything here ships together.

**Why:** a professor ran Courses 1–3 and found everything working. Their one suggestion was to scaffold Course 1 more: "I have a feeling they will struggle with the compensation part of the module and all the math they have to do."

**Decisions (from review):**
- **Nothing optional.** All theory stays in Course 1 and is required, placed where it is needed.
- **A real compensation on/off switch** that changes the actual data (the Before/After preview is not enough).
- **A small calculator** on the maths steps.
- **No pilot or migration work.** No students have started, so step ids can change freely.

---

## 1. What makes it hard today

1. **The answer comes before the problem.** Students are told compensation was "auto-applied" (`c1_s12c`) before seeing anything that needs fixing.
2. **Theory arrives as one long wall.** Spillover, spectra, FPbase, AB/EX/EM, overlap integrals and callouts come back to back, mostly as text steps, and before students know what they're for.
3. **Maths with no worked example.** Slide 3 asks for "Rise ÷ Run × 100"; the three-cells slide asks for `y − 20.0% × 750`. Neither has been shown first, and neither number is explained in plain words.
4. **Unclear examples.** The three-cells slide calls its points "Cell 1, 2, 3", so the reader can't tell what each one stands for.
5. **Alone in the deck.** Cyto says "I'll step back" for all seven slides.
6. **Wording drift and typos.** "Spillover / leak / overlap / cross-talk" are used loosely, and "Detector 1/2" sits beside named dyes. Strings run together in 5 steps ("forother", "theshoulders", "tissues:spleen", "background,defining", "signal.Try").

## 2. Principles

1. **Problem first:** see wrong-looking data, wonder why, then learn the cause.
2. **Theory in the order you need it:** emission explains the problem; excitation and lasers explain why only some overlaps matter. Each is taught right before it is used.
3. **Feel it, then measure it, then compute it:** a slider before a ruler, a ruler before a formula.
4. **Worked example, then half-done, then alone** for every calculation, with round numbers first.
5. **Words before formulas:** "20% spillover = for every 100 units of PI light, the PE detector reads 20 extra."
6. **Name things by what they are:** "a PI-only cell", not "Cell 1"; dye names, not "Detector 1/2".
7. **One word per idea:** *spillover* (glossed once as "light landing in the wrong detector"), *detector*, *dye*.

## 3. The new compensation arc

Course 1's Setup and First-gate phases keep their steps (typos fixed, plus a recap card each). The compensation phase is rebuilt as below. The numbers come from the tutorial data and the deck's laser-aware estimate.

### Beat 1: The mystery (Compensation tab, compensation OFF)
1. Cyto turns compensation **off** with the new switch, and the ✦ tags disappear. A one-line explanation says what the switch does.
2. The student opens Sample A on **PE (CD4) vs PerCP-Cy5.5 (PI)**. The bright CD4 cloud climbs diagonally into PI-positive territory.
3. **Prediction:** "These CD4-bright cells look PI-positive, so dead. Are they?" (no wrong answer, paid off in Beat 5).

### Beat 2: Theory, part 1: why light ends up in the wrong detector (Spectral tab)
4. Where the curves come from: FPbase, real measured spectra (short).
5. The panel's dyes load from the files; markers vs dyes; PI is its own dye read in PerCP-Cy5.5.
6. **Emission curves are broad hills** (the current `c1_s12d` text, now shown while the student looks at the curves): PE's hill reaches into the detector where PI is read.
7. **Question:** with PE bright and no PI, what does the PI detector read? (the current `c1_s12e`, now asked about the curves on screen)

### Beat 3: Theory, part 2: lasers decide which overlaps count (Spectral tab)
8. **AB / EX / EM:** the student flips the toggles. Excitation says which laser lights a dye; each detector sits behind one laser.
9. **Question (new):** Pacific Blue's curve overlaps FITC's. Pacific Blue is lit by the 405 nm laser and FITC is read behind the 488 nm laser. Does Pacific Blue end up in FITC's detector? (Answer: barely, because the laser that FITC's detector sits behind doesn't light Pacific Blue.)
10. The overlap callouts are estimates from spectra; real cytometers measure them with controls.
11. **Question:** which overlap could quietly distort results? (`c1_sp47b`, kept)

### Beat 4: The Learning Compensation deck, self-guided
12. Open the sub-tab. Cyto explains how the deck works (Your turn, Show me, 🧮) once, in a bubble the learner closes with **Got it**.
13. One waiting step for the whole deck: no bubbles or banners until the last slide is done (first live test: a bubble per slide was distracting). See §4.

### Beat 5: The payoff (Compensation tab, compensation ON)
20. The student flips the switch **on**. The diagonal cloud from Beat 1 lies flat, and the ✦ tags return. Prediction paid off: "they weren't dead, it was PE light in the PI detector."
21. Where that matrix came from: the `$SPILL` keyword the cytometer saved in the files (the old `c1_s12c`, now an explanation rather than a spoiler).

### Beat 6: Reading the real matrix
22. Method setup, and what the method uses (`c1_m01`/`c1_m02`, merged into one step).
23. Extract from FCS (`c1_s14`).
24. **Guided read:** a spotlight on the PE row, then the PerCP-Cy5.5 column, then the cell where they cross. Plain sentence: "for every 100 units of PE, the PerCP-Cy5.5 detector reads 30."
25. **Question:** the 0.30 read (`c1_m03`, kept), then the status line (`c1_m04`).
26. **Evidence:** click the 0.30 cell; Sample A; Before/After (`c1_m05`). **Question:** where should the cloud sit (`c1_m06`), tied back to the slider slide.
27. Histograms (`c1_m07`/`c1_m08`), all samples plus why (`c1_m09`/`c1_m10`), the Matrices page (`c1_m11`/`c1_m12`, text shortened).

### Beat 7: Close
28. Recap card: why compensation, what a spillover number means, how to check a matrix.
29. Prediction for Course 2 (`c1_m13`), save (`c1_s33b`), graduation.

## 4. The deck, slide by slide (7 slides)

| # | Slide | Change |
|---|---|---|
| 1 | Physics of Overlap | As now (filter on the detector, laser-lit markers). Cyto frames it: "find whose light lands in PE's detector". |
| 2 | Setting the Zero | Axes named for the teaching pair's detectors instead of "Detector 1/2". |
| 3 | Measure the Spillover | **Worked example first:** a card with round numbers ("rise 100 over a run of 1,000 → 10 per 100 → 10%"). Then the ruler. The answer becomes a sentence: "for every 100 units of PI, the PE detector reads __ extra." 🧮 available. |
| 4 | **Find the Level (new; replaces Compensate All)** | One slanted single-stain cloud and a **"% subtracted" slider** (0 to 2× the true value). Live label: *under-compensated / level ✓ / over-compensated*. Done when held within ±2 points of level for about 1 s. Then the reveal: "the value that levels it is the one you measured on Step 3." This teaches what `c1_m06` later tests on real data. |
| 5 | Same Rule, Every Cell (was "One Rule for Every Cell") | The three points get names and colours: **"PI-only, dim"**, **"PI-only, bright"**, **"PI + PE (really both)"**. Each reading is drawn as a stacked bar: *true signal* + *spillover*. **Worked → half-done → alone:** Cyto subtracts for the dim cell (animated, numbers shown); the student fills one blank for the bright cell; then the student computes the "really both" cell. Arithmetic uses the whole-number % ("≈ 20%"). 🧮 available. |
| 6 | Gate the Cleaned Data | Axes named for the pair, as on Slide 2. |
| 7 | Building the Matrix | Text shortened; the "Compensate All back in Step 5" reference now points to Find the Level. 🧮 available. |

Show me on the maths slides reveals the **next sub-step** (e.g. "Rise = 200, Run = 1,000; now divide"), never the final answer.

## 5. New pieces of UI

1. **Compensation On/Off switch.** A state-showing switch ("Compensation: ON ✦ / OFF") in the Compensation tab header, wired to the existing, tested `experiment_edits.toggle_compensation` (undoable). Object name `CompensationSwitch` so the Academy can spotlight it. Every view re-renders on the event it already publishes. Includes a validator `CompensationStateValidator(on: bool)`, and the user docs regain the toggle section removed in `dbedc87`.
2. **🧮 Calculator.** A small expression field in the deck's answer area: `+ − × ÷ ( ) %`, evaluated safely by parsing the expression (no `eval`), showing the result. Shown on Slides 3, 5 and 7.
3. **Matrix cell spotlight.** `CompensationMatrixTable` exposes rects for a row, a column and a cell through the `get_tutorial_target_rects` hook the Spectral viewer already uses for its sub-tab, with metadata keys for the step.
4. **Deck hand-off.** One VerificationStep on `LearningCompensationCompleteValidator`, with `manual_dismiss_bubble` and a 25-minute quiet period, so the deck runs without interruption.

## 6. Also in this pass (whole of Course 1)

- Fix the 5 string-join typos, with a test that flags `[a-z][.,:][A-Za-z]` inside step text so it can't recur.
- Use *spillover / detector / dye* consistently across Course 1 and the deck.
- Recap cards at the end of Setup and First gate: three bullets each.
- Re-estimate `estimated_minutes` from a timed run of the finished course.

## 7. Build and check

**Order:**
1. On/Off switch and its validator.
2. Calculator and the matrix-cell spotlight.
3. Deck slides (new slider slide, Slides 3 and 5 rebuilt, axis names).
4. Course 1 step rewrite (Beats 1–7).
5. Typo guard and wording pass.
6. Docs.

Commits go on flow `main`, one per item, all handed over together.

**Checks before handing over:**
- Unit tests for the switch, the calculator parser, and each new or rebuilt slide (grading accepts the round-number method).
- `test_question_steps.py` (length limits) and `test_tutorial_numbers.py` (numbers from real data) extended to the new questions.
- A headless play-through test that drives Course 1 start to finish with real tutorial files and asserts the end state Courses 2–3 rely on: roles, the **Cells** gate, the embedded matrix in use **and compensation on**, and a saved workspace.
- Screenshots of every new slide and step, read over before handing over.
- Full pre-commit suite and doctor baseline.

**Then:** you play it through live. After your OK comes the version bump and release, so the professor's deployment picks it up.

## 8. Risks

- **The switch rewrites events for every sample.** The slow part is re-rendering ten samples; check the Gating canvas and Sample Lens refresh, and that undo restores both states.
- **The slider slide on a different panel:** if a learner loads other dyes, the slider range follows the teaching pair's %; test with 2 dyes and with no excitation data.
- **Course length:** the arc adds 2 interactive beats and removes about 5 text steps. The timed run decides the new estimate.
