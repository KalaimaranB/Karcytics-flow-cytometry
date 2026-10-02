"""Karcytics Flow Cytometry — Academy Courses.

Step conventions:
  InfoStep              — teaches a concept; user clicks Next → to continue.
  InteractionStep       — user must click/interact with a named widget to auto-advance.
  VerificationStep      — auto-polls a validator every ~2 s and advances automatically.
                          Set allow_interaction=True only if the user also needs to freely
                          interact with the UI before clicking the manual 'Check ✓' button.
  QuestionStep          — the learner must answer (a "check" question correctly) to move on.

Spotlight convention:
  target_widget_name  — single objectName for InteractionStep highlight.
  target_widget_names — list of objectNames for multi-target InfoStep spotlights.

Main tab bar order (0-indexed): Workspace, Compensation, Gating, Pipeline,
Statistics, Spectral, Population Analysis, Comparisons.

Course 4 picks up where Course 3 left off: Course 3 ends with a real,
gate-tree population ("UMAP B Cells") exported from unsupervised
clustering and cross-checked against the hand-gated "B-cells" population
via a Pipeline AND node. That showed they are (nearly) the same cells;
Course 4 asks the follow-up — *are they measured the same?* — as a
prediction at the start (`c4_same_measure`), and answers it with a
**derived parameter** (B220 ÷ CD45, a per-cell ratio used like any
channel), the **Statistics** tab and the **Comparisons** tab. The
histogram overlay and graduation steps show the prediction back.

The numbers quoted below were measured on the tutorial's compensated
samples with the Course 1–3 gates (Sample A = thymus, B = bone marrow,
C = spleen) — re-check them if the tutorial files or gates change:

- B220 ÷ CD45 medians: B cells ≈ 0.6 (Sample C hand-gated 0.64, UMAP B
  Cells 0.65), T cells ≈ 0.01; ~0% invalid; CV on the ratio 46% vs 44%.
- B-cells % of Leukocytes: A 0.37%, B 43%, C 68%; % Total: A 0.33%, B 33%,
  C 45% (Leukocytes are 89% / 77% / 65% of all events). UMAP B Cells are
  64% of the Leukocytes UMAP ran on.
- AND node: 99.95% of UMAP B Cells fall inside the hand-gated gate; ~93%
  of hand-gated B-cells were found by UMAP.
"""

from karcytics_sdk.plugin.tutorial_models import (
    QUESTION_PREDICT,
    AnswerChoice,
    Course,
    ForcedInteractionStep,
    InfoStep,
    InteractionStep,
    QuestionStep,
    SubTask,
    VerificationStep,
)

from ..analysis.statistics import StatType
from .validators import (
    ActiveGraphDerivedAxisValidator,
    AllOf,
    ComparisonPlotTypeValidator,
    ComparisonsDerivedChannelValidator,
    ComparisonsPlotGeneratedValidator,
    Course3AnalysisCompleteValidator,
    DerivedEditorClosedValidator,
    DerivedRatioExistsValidator,
    ExportDoneValidator,
    HistogramOverlayLayoutValidator,
    PlotTypeValidator,
    PopulationsCheckedValidator,
    SampleAndGateOpenValidator,
    StatsChartTypeValidator,
    StatsCheckedValidator,
    StatsDerivedChannelValidator,
    StatsResultsReadyValidator,
    TabActiveValidator,
    WorkflowSavedValidator,
)

course_4_reporting = Course(
    id="flow_course_4_reporting",
    title="Derived Parameters, Statistics & Comparisons",
    description=(
        "Build a per-cell B220 ÷ CD45 derived parameter, then use your "
        "Course 3 populations — the hand-gated B-cells and the UMAP-exported "
        "UMAP B Cells — to test whether they measure the same, with the "
        "Statistics table and charts and the Comparisons charts."
    ),
    estimated_minutes=35,
    badge_reward="Insight Reporter",
    badge_icon="📊",
    prerequisite_course_ids=["flow_course_3_analysis"],
    steps=[
        InfoStep(
            id="c4_s00_intro",
            text=(
                "Welcome to Course 4! 📊<br><br>"
                "Course 3 left you with two independent ways of finding "
                "B-cells — your own hand-gated **B-cells**, and the "
                "unsupervised **UMAP B Cells** — plus an AND node showing "
                "they're nearly the same cells.<br><br>"
                "This course asks the next question: are they also "
                "**measured** the same? You'll answer it with a new kind of "
                "parameter, real statistics and side-by-side charts."
            ),
            cyto_emotion="happy",
            next_step_id="c4_s00b_objectives",
        ),
        InfoStep(
            id="c4_s00b_objectives",
            text=(
                "What you'll walk away with 🎯<br><br>"
                "By the end of this course, you'll be able to:<br>"
                "• Build a derived parameter — a per-cell formula like "
                "B220 ÷ CD45 — and plot, gate and measure it like any channel<br>"
                "• Pick the statistic that makes a fair comparison between "
                "samples, and read it from a lean table<br>"
                "• Choose a Statistics chart that keeps long population "
                "names readable<br>"
                "• Choose the right Comparisons chart (Violin, Channel "
                "Heatmap, Histogram Overlay, Pseudocolor Overlay) for a "
                "question about two populations<br>"
                "• Export your tables and plots"
            ),
            cyto_emotion="talking",
            next_step_id="c4_s00c_prediction",
        ),
        QuestionStep(
            id="c4_s00c_prediction",
            text=(
                "Make a prediction 🔮<br><br>"
                "UMAP B Cells and your hand-gated B-cells are nearly the same "
                "cells. Measured on B220, how will UMAP's B cells compare with "
                "yours? There's no wrong answer — we'll check at the end."
            ),
            kind=QUESTION_PREDICT,
            question_id="c4_same_measure",
            choices=[
                AnswerChoice("About the same peak and spread"),
                AnswerChoice("Brighter — UMAP keeps the clearest B cells"),
                AnswerChoice("Dimmer — UMAP lets in borderline cells"),
                AnswerChoice("Much broader — clustering is messier"),
            ],
            cyto_emotion="thinking",
            next_step_id="c4_s01_validate_analysis",
        ),
        # ── Validate Course 3's analysis output ─────────────────────────────────
        VerificationStep(
            id="c4_s01_validate_analysis",
            text="Checking for your Course 3 analysis...",
            cyto_emotion="scanning",
            hide_next_button=True,
            validator=Course3AnalysisCompleteValidator(),
            on_success_step_id="c4_d01_intro",
            on_fail_step_id="c4_s01b_incomplete_analysis",
        ),
        InfoStep(
            # This step has allow_interaction unset (defaults False), so the
            # whole app stays blocked behind it — there's no way to actually
            # go finish Course 3 without leaving first. Looping back to the
            # validator (an earlier fix) just replayed this same dead end
            # forever. next_step_id="__abandon__" exits the tutorial cleanly
            # instead — no badge, no completion (see
            # AcademyManager.abandon_course()) — rather than either that
            # dead loop or falling into the "no next_id" branch, which would
            # have completed the course and awarded "Insight Reporter" for
            # reading one message.
            id="c4_s01b_incomplete_analysis",
            text=(
                "Missing your Course 3 export 🔍<br><br>"
                "Course 4 needs the **UMAP B Cells** population and the "
                "**AND** node cross-checking it against **B-cells** — both "
                "built in Course 3. Head back and finish that course first, "
                "then relaunch Course 4."
            ),
            cyto_emotion="thinking",
            next_step_id="__abandon__",
        ),
        # ── Derived parameters: B220 ÷ CD45 ───────────────────────────────────────
        InfoStep(
            id="c4_d01_intro",
            text=(
                "New tool: derived parameters ƒ<br><br>"
                "Every cell is just a row of numbers — FSC, SSC, one per "
                "detector. A **derived parameter** is a new number you "
                "calculate for every cell from the ones it already has, "
                "e.g. **GFP ÷ RFP**.<br><br>"
                "That exact ratio is a classic in reporter experiments: RFP "
                "on a constant promoter says how much plasmid a cell got, GFP "
                "says how active your promoter is — dividing one by the other "
                "cancels out the lucky-transfection noise. Once built, a "
                "derived parameter works like a real channel: plot it, gate "
                "on it, compute statistics on it."
            ),
            cyto_emotion="talking",
            next_step_id="c4_d02_why_b220_cd45",
        ),
        InfoStep(
            id="c4_d02_why_b220_cd45",
            text=(
                "Our version: B220 ÷ CD45 🧬<br><br>"
                "Our panel has no GFP, but it has the same idea built in. "
                '**CD45** is on every leukocyte — our "RFP", a reference '
                "for how much a cell is staining overall. **B220** is itself "
                "a B-cell form of CD45 (CD45R).<br><br>"
                "So **B220 ÷ CD45** asks, per cell: *how much of this cell's "
                "CD45 signal is the B-cell kind?* Let's build it on Sample C's "
                "Leukocytes."
            ),
            cyto_emotion="happy",
            next_step_id="c4_d03_open_leuko",
        ),
        InteractionStep(
            id="c4_d03_open_leuko",
            text=(
                "In the Data hierarchy, right-click **Sample C**, then click "
                "**Leukocytes** in the population menu — the same move you "
                "made in Course 2."
            ),
            target_widget_name="SampleList",
            target_widget_names=["SampleList"],
            event_trigger="population_open_requested",
            cyto_emotion="pointing",
            next_step_id="c4_d04_verify_leuko",
        ),
        VerificationStep(
            id="c4_d04_verify_leuko",
            text="Checking opened population...",
            cyto_emotion="scanning",
            hide_next_button=True,
            validator=SampleAndGateOpenValidator("sample c", "leukocytes"),
            on_success_step_id="c4_d05_gating_tab",
            on_fail_step_id="c4_d04b_wrong_pop",
        ),
        InteractionStep(
            id="c4_d04b_wrong_pop",
            text="Oops! Right-click **Sample C** and choose **Leukocytes** from its menu.",
            cyto_emotion="surprised",
            target_widget_name="SampleList",
            target_widget_names=["SampleList"],
            event_trigger="population_open_requested",
            next_step_id="c4_d04_verify_leuko",
        ),
        VerificationStep(
            # Verification (not Interaction) so it passes straight through if
            # the Gating tab is already open — clicking the active tab emits
            # no currentChanged and would leave an InteractionStep stuck.
            id="c4_d05_gating_tab",
            text="Open the **Gating** tab (its ribbon has the tool we need).",
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["MainTabBar"],
            validator=TabActiveValidator(2),
            on_success_step_id="c4_d06_open_editor",
        ),
        InteractionStep(
            id="c4_d06_open_editor",
            text="Click **ƒ Derived** (highlighted) on the Gating ribbon.",
            target_widget_name="DerivedParamsButton",
            target_widget_names=["DerivedParamsButton"],
            event_trigger="clicked",
            cyto_emotion="pointing",
            next_step_id="c4_d07_build_ratio",
        ),
        VerificationStep(
            id="c4_d07_build_ratio",
            text=(
                "Build the ratio ➗<br><br>"
                "In the Derived Parameters window:<br>"
                "• **Start from:** Ratio A ÷ B<br>"
                "• **A:** B220 (FITC-A) — the marker, on top<br>"
                "• **B:** CD45 (APC-A) — the reference, underneath<br><br>"
                "The formula fills itself in as **[FITC-A] / [APC-A]** and the "
                "name as **B220/CD45** — keep both, then click **Save**."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=[
                "DerivedTemplateCombo",
                "DerivedChannelA",
                "DerivedChannelB",
                "DerivedSaveButton",
            ],
            validator=DerivedRatioExistsValidator("FITC-A", "APC-A"),
            failure_hint=(
                "Pick Ratio A ÷ B, set A to B220 (FITC-A) and B to CD45 (APC-A), then click Save."
            ),
            on_success_step_id="c4_d08_preview",
        ),
        InfoStep(
            id="c4_d08_preview",
            text=(
                "What the preview shows 🔍<br><br>"
                "Your formula has already been run on every cell in Sample C — "
                "the chart is the result, before you save anything.<br><br>"
                "• **Left to right** — each cell's B220 ÷ CD45. Left = little "
                "B220 for its CD45, right = lots. The marks **0.01**, **0.1**, "
                "**1** are each 10× the one before.<br>"
                "• **Bar height** — how many cells have that value.<br>"
                "• **Grey** — the whole sample. It has **two humps**: two kinds "
                "of cell with very different amounts of B220.<br>"
                "• **Blue** — only the population picked in the dropdown, so "
                "you can see which hump is which."
            ),
            cyto_emotion="thinking",
            allow_interaction=True,
            target_widget_names=["DerivedPreviewPopulation", "DerivedPreviewHistogram"],
            next_step_id="c4_d08q_tcell_hump",
        ),
        QuestionStep(
            id="c4_d08q_tcell_hump",
            text=(
                "Before you switch 🤔<br><br>"
                "If you picked **T-cells** in the preview's dropdown, which "
                "hump would the blue bars land on?"
            ),
            question_id="c4_tcell_hump",
            choices=[
                AnswerChoice("The left hump, near 0.01", correct=True),
                AnswerChoice(
                    "The right hump, near 0.6",
                    feedback="That's where cells with lots of B220 sit — and "
                    "B220 is a B-cell marker.",
                ),
                AnswerChoice(
                    "Both humps equally",
                    feedback="Each cell has one ratio, and T cells are alike "
                    "here: lots of CD45, very little B220.",
                ),
            ],
            explanation=(
                "T cells carry plenty of CD45 but almost no B220, so their "
                "ratio is tiny. Switch the dropdown next and check."
            ),
            cyto_emotion="thinking",
            target_widget_names=["DerivedPreviewPopulation", "DerivedPreviewHistogram"],
            next_step_id="c4_d08b_compare",
        ),
        InfoStep(
            id="c4_d08b_compare",
            text=(
                "Check it 🔬<br><br>"
                "Switch the preview's population dropdown:<br>"
                "• **T-cells** — blue sits on the **left** hump, near **0.01**.<br>"
                "• **B-cells** — blue jumps to the **right** hump, near **0.6**.<br><br>"
                "The line under the chart puts numbers on it:<br>"
                "• **median** — the ratio of a typical cell in that population.<br>"
                "• **% invalid** — cells where the ratio can't be computed "
                "(CD45 at or below zero). ~0% here, so CD45 is a safe thing to "
                "divide by.<br><br>"
                "That's the point of the preview: check the parameter does what "
                "you meant **before** you save it and gate on it."
            ),
            cyto_emotion="talking",
            allow_interaction=True,
            target_widget_names=[
                "DerivedPreviewPopulation",
                "DerivedPreviewHistogram",
                "DerivedPreviewSummary",
            ],
            next_step_id="c4_d09_close_editor",
        ),
        VerificationStep(
            id="c4_d09_close_editor",
            text="Close the Derived Parameters window (**Close**, highlighted).",
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["DerivedCloseButton"],
            validator=DerivedEditorClosedValidator(),
            on_success_step_id="c4_d10_histogram",
        ),
        VerificationStep(
            id="c4_d10_histogram",
            text="Switch the graph's plot type to **Histogram**.",
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["DisplayModeCombo"],
            validator=PlotTypeValidator("histogram"),
            on_success_step_id="c4_d11_axis",
        ),
        VerificationStep(
            id="c4_d11_axis",
            text=(
                "Now set the **X:** axis to **ƒ B220/CD45** — derived "
                "parameters are listed after the real channels.<br><br>"
                "(The **＋ New derived parameter…** entry at the very bottom is "
                "a shortcut: anything you build from there lands straight on "
                "that axis.)"
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["AxisSelectorX"],
            validator=ActiveGraphDerivedAxisValidator("FITC-A", "APC-A"),
            on_success_step_id="c4_d12_read_histogram",
        ),
        InfoStep(
            id="c4_d12_read_histogram",
            text=(
                "The preview, full size 📊<br><br>"
                "This is the same picture as the preview, now on a real graph "
                "you can gate on:<br>"
                "• **X axis** — each cell's own **B220 ÷ CD45** value. It's a "
                "**log** scale (the Ratio template's default): **10⁻²** = 0.01, "
                "**10⁻¹** = 0.1, **10⁰** = 1, each step 10× the one before, so "
                "small and large ratios both get room.<br>"
                "• **Y axis** — **Count**: how many cells fall in each thin "
                "slice of X.<br><br>"
                "So every **peak** is a group of cells sharing a similar ratio "
                "— one peak per kind of cell."
            ),
            cyto_emotion="thinking",
            allow_interaction=True,
            target_widget_names=["FlowCanvas"],
            next_step_id="c4_d12b_two_peaks",
        ),
        InfoStep(
            id="c4_d12b_two_peaks",
            text=(
                "Two populations, one axis 🔬<br><br>"
                "• **Left peak, near 0.01** — leukocytes with almost no B220: "
                "**T cells** and other non-B leukocytes. Broad, because their "
                "B220 is just background noise — dividing noise by CD45 smears "
                "it across decades.<br>"
                "• **Right peak, near 0.6** — **B cells**. Tall (most of Sample "
                "C's leukocytes are B cells) and **narrow**: bright B220 over "
                "bright CD45 varies only a little from cell to cell.<br><br>"
                "The peaks sit ~60× apart, so a **Range gate** on the right "
                "peak, drawn inside Leukocytes, picks out B cells — ~97% pure "
                "in this data. Keep it inside Leukocytes: a cell with almost no "
                "CD45 gets a big ratio from almost no B220."
            ),
            cyto_emotion="happy",
            allow_interaction=True,
            target_widget_names=["FlowCanvas"],
            next_step_id="c4_d13_pitfalls",
        ),
        InfoStep(
            id="c4_d13_pitfalls",
            text=(
                "Ratio rules of thumb ⚠️<br><br>"
                "• **Compensate first** — a ratio of uncompensated channels "
                "includes spillover.<br>"
                "• **Relative units** — FITC and APC differ in brightness, so "
                "0.6 doesn't mean 60% of CD45 is B220. Compare ratios between "
                "cells and samples measured on the same panel, not as absolute "
                "values."
            ),
            cyto_emotion="talking",
            next_step_id="c4_d14_invalid_question",
        ),
        QuestionStep(
            id="c4_d14_invalid_question",
            text=(
                "Your turn 🧠<br><br>"
                "On another panel, a ratio shows **40% invalid** events in one "
                "population and ~0% everywhere else. What's the most likely cause?"
            ),
            question_id="c4_ratio_invalid_cause",
            choices=[
                AnswerChoice(
                    "The denominator is dim — near or below zero — in that population",
                    correct=True,
                ),
                AnswerChoice(
                    "The numerator is very bright there",
                    feedback="A bright numerator just gives a big ratio. Invalid "
                    "means the value can't be computed — dividing by ≤ 0.",
                ),
                AnswerChoice(
                    "The axis is on a log scale",
                    feedback="The scale only changes how values are drawn. % invalid "
                    "counts cells whose ratio can't be computed at all.",
                ),
                AnswerChoice(
                    "The population has too many events",
                    feedback="% invalid is a share, so event count doesn't drive it. "
                    "Look at what's being divided by.",
                ),
            ],
            explanation=(
                "Dividing by a value at or below zero has no meaningful answer, "
                "so those cells are marked invalid. A dim denominator makes the "
                "ratio mostly noise — pick a reference that's bright on every "
                "cell you care about, like CD45 here."
            ),
            cyto_emotion="thinking",
            next_step_id="c4_s02_switch_statistics",
        ),
        # ── Statistics tab ────────────────────────────────────────────────────────
        VerificationStep(
            id="c4_s02_switch_statistics",
            text=("Now put numbers on it — click the **Statistics** tab at the top."),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["MainTabBar"],
            validator=TabActiveValidator(4),
            on_success_step_id="c4_s04b_median_question",
        ),
        QuestionStep(
            id="c4_s04b_median_question",
            text=(
                "First, brightness 💡<br><br>"
                "B220 spans four decades on a log axis, and a few cells are far "
                "brighter than the rest. Which number best describes how bright "
                "a **typical** B cell is?"
            ),
            question_id="c4_typical_brightness",
            choices=[
                AnswerChoice("The median (MFI)", correct=True),
                AnswerChoice(
                    "The arithmetic mean",
                    feedback="A handful of very bright cells drag the mean upward "
                    "on log-scaled data, so it overstates a typical cell.",
                ),
                AnswerChoice(
                    "The maximum",
                    feedback="The maximum is one extreme cell — often an outlier or "
                    "a doublet — not a typical one.",
                ),
                AnswerChoice(
                    "% Total",
                    feedback="% Total measures how many cells there are, not how bright they are.",
                ),
            ],
            explanation=(
                "Half the cells are dimmer than the median and half brighter, so "
                "a few extreme cells barely move it — that's why MFI is the "
                "standard brightness statistic in flow."
            ),
            cyto_emotion="thinking",
            next_step_id="c4_s05_select_pops",
        ),
        VerificationStep(
            id="c4_s05_select_pops",
            text=(
                "Trim the population list 🎯<br><br>"
                "Click **Edit Population Selection** (highlighted) to open the "
                "picker — a grid of populations × samples you can drag to move "
                "and resize from its corner for more room. Every population "
                "starts checked by default — click **None** first, then check "
                "4 cells total:<br><br>"
                "• **B-cells** — check it in the **Sample A**, **B** and "
                "**C** columns. Not the row label: in Course 2 the gate "
                "propagated to *every* sample, controls included, so the "
                "row would tick all 10.<br>"
                "• **UMAP B Cells** — only exists on **Sample C**, where you "
                "built it; check just that one cell.<br><br>"
                "Once your 4 cells are checked, close the popup (✕, Esc, or "
                "click outside it) to continue."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["StatsPopulationPickerButton"],
            validator=PopulationsCheckedValidator(
                "_statistics_explorer",
                "b-cells",
                "umap b cells",
                max_checked=4,
                require_popup_closed=True,
            ),
            on_success_step_id="c4_s06q_fair_abundance",
        ),
        QuestionStep(
            id="c4_s06q_fair_abundance",
            text=(
                "A fair comparison ⚖️<br><br>"
                "Leukocytes are 89% of Sample A's events, 77% of B's and only "
                "65% of C's — the rest is debris and dead cells. To compare "
                "**how much of each sample's immune cells are B cells**, which "
                "statistic?"
            ),
            question_id="c4_fair_abundance",
            choices=[
                AnswerChoice("% Parent — the share of Leukocytes", correct=True),
                AnswerChoice(
                    "% Total — the share of every event",
                    feedback="% Total divides by debris and dead cells too, so a "
                    "messier sample looks like it has fewer B cells.",
                ),
                AnswerChoice(
                    "Count",
                    feedback="Count depends on how many events were recorded, "
                    "which differs between tubes.",
                ),
                AnswerChoice(
                    "CV",
                    feedback="CV is how spread out a peak is, not how many cells there are.",
                ),
            ],
            explanation=(
                "% Parent divides by the gate above — here Leukocytes — so debris "
                "drops out. In this data % Total says C has 1.35× B's share of B "
                "cells; % of Leukocytes says 1.6×."
            ),
            cyto_emotion="thinking",
            next_step_id="c4_s06_select_stats",
        ),
        VerificationStep(
            id="c4_s06_select_stats",
            text=(
                "Trim the stat list too ✂️<br><br>"
                "**Count**, **Percent Parent** and **MFI** are checked by "
                "default — keep **Percent Parent** (that's % Parent), uncheck "
                "the other two, and check **Cv** "
                "(how spread out a peak is: high CV = broad, messy population)."
                "<br><br>"
                "That **★** next to CV means it needs a fluorescence channel "
                "picked below — % Parent doesn't, since it counts cells rather "
                "than measuring a marker."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["StatsCheckboxPanel"],
            validator=StatsCheckedValidator(StatType.PERCENT_PARENT, StatType.CV, max_checked=2),
            on_success_step_id="c4_s06a_ratio_channel",
        ),
        VerificationStep(
            id="c4_s06a_ratio_channel",
            text=(
                "Give CV its ★ channel ƒ<br><br>"
                "In the **Channel** dropdown (highlighted), pick **ƒ B220/CD45** "
                "— your derived parameter works here like any detector."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            allow_scroll=True,
            hide_next_button=True,
            target_widget_names=["StatsChannelCombo"],
            validator=StatsDerivedChannelValidator("FITC-A", "APC-A"),
            on_success_step_id="c4_s06b_compute",
        ),
        VerificationStep(
            id="c4_s06b_compute",
            text=(
                "Click '📊 Compute Statistics' (highlighted) to generate the "
                "table. Cyto carries on once it's ready."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            allow_scroll=True,
            hide_next_button=True,
            target_widget_names=["StatsComputeButton"],
            validator=StatsResultsReadyValidator(),
            on_success_step_id="c4_s07_read_table",
        ),
        QuestionStep(
            id="c4_s07_read_table",
            text=(
                "Read the table 🔍<br><br>"
                "Look along the **B-cells** row's **Percent Parent** columns. "
                "Which sample "
                "has almost no B cells?"
            ),
            question_id="c4_few_bcells_sample",
            choices=[
                AnswerChoice("Sample A", correct=True),
                AnswerChoice(
                    "Sample B",
                    feedback="B's B-cells are a solid ~43% of its Leukocytes. Look "
                    "for a value well under 1%.",
                ),
                AnswerChoice(
                    "Sample C",
                    feedback="C has the most — ~68% of its Leukocytes. Look for a "
                    "value well under 1%.",
                ),
            ],
            explanation=(
                "Sample A is the thymus, where T cells mature — B cells are 0.4% "
                "of its Leukocytes, against 43% in bone marrow (B) and 68% in "
                "spleen (C): Course 2's mystery, in numbers."
            ),
            cyto_emotion="thinking",
            allow_interaction=True,
            target_widget_names=["StatsResultsTable"],
            next_step_id="c4_s08_chart_toggle",
        ),
        InteractionStep(
            id="c4_s08_chart_toggle",
            text="Click '📈 Chart' (highlighted) to switch from table to chart view.",
            target_widget_name="StatsChartMode",
            event_trigger="clicked",
            cyto_emotion="pointing",
            next_step_id="c4_s09_chart_question",
        ),
        QuestionStep(
            id="c4_s09_chart_question",
            text=(
                "Pick a chart 📈<br><br>"
                "Population names here are long paths, like **Cells / Live Cells "
                "/ Leukocytes / B-cells**, so the bar chart tilts them. Which "
                "chart types keep long names readable?"
            ),
            question_id="c4_long_names_chart",
            multi_select=True,
            choices=[
                AnswerChoice("Horizontal Bar", correct=True),
                AnswerChoice("Heatmap", correct=True),
                AnswerChoice(
                    "Grouped Bar",
                    feedback="That's the one on screen now — its names sit under "
                    "the bars, tilted to fit.",
                ),
            ],
            explanation=(
                "Both put population names on the side, one per row, where long "
                "text reads straight across. Grouped Bar suits a handful of short "
                "names."
            ),
            cyto_emotion="thinking",
            allow_interaction=True,
            target_widget_names=["StatsChartCanvas"],
            next_step_id="c4_s13_heatmap",
        ),
        VerificationStep(
            id="c4_s13_heatmap",
            text="Switch the chart-type dropdown (highlighted) to **Heatmap**.",
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["StatsChartTypeCombo"],
            validator=StatsChartTypeValidator("heatmap"),
            on_success_step_id="c4_s14_heatmap_read",
        ),
        InfoStep(
            id="c4_s14_heatmap_read",
            text=(
                "One-glance comparison 🗺️<br><br>"
                "Rows are populations, columns are samples; the dropdown next "
                "to the chart type picks which statistic fills the cells.<br><br>"
                "Switch it to **Percent Parent** and look at Sample C: your B-cells "
                "are **68%** of Leukocytes, UMAP B Cells **64%** of the "
                "Leukocytes UMAP ran on. Close, with UMAP a little stricter — "
                "one clue for your prediction."
            ),
            cyto_emotion="happy",
            allow_interaction=True,
            target_widget_names=["StatsChartCanvas"],
            next_step_id="c4_s15_switch_comparisons",
        ),
        # ── Comparisons tab ───────────────────────────────────────────────────────
        VerificationStep(
            id="c4_s15_switch_comparisons",
            text=("Numbers done; now shapes. Click the **Comparisons** tab at the top."),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["MainTabBar"],
            validator=TabActiveValidator(7),
            on_success_step_id="c4_s17_comparisons_intro",
        ),
        InfoStep(
            id="c4_s17_comparisons_intro",
            text=(
                "Comparing distributions 🎨<br><br>"
                "Statistics gave single numbers; this tab plots the whole "
                "*distribution* of each population. Four chart types, each "
                "answering a different question about your two B-cell methods."
            ),
            cyto_emotion="talking",
            next_step_id="c4_s17b_select_pops",
        ),
        VerificationStep(
            id="c4_s17b_select_pops",
            text=(
                "Pick your population here too 🎯<br><br>"
                "This tab has its own population picker, separate from the "
                "one on the Statistics tab. Click **Edit Population "
                "Selection** (highlighted) and check **B-cells** in the "
                "**Sample A**, **B** and **C** columns (the row label would "
                "tick the controls too).<br><br>"
                "Violin (the first chart type below) only allows one "
                "population per sample, so this is the one to use for it. "
                "A later step brings **UMAP B Cells** into the mix once "
                "you reach a chart type that can show more than one "
                "population per sample. Close the popup (✕, Esc, or click "
                "outside it) once you're done."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["ComparisonsPopulationPickerButton"],
            validator=PopulationsCheckedValidator(
                "_comparisons_viewer",
                "b-cells",
                max_checked=3,
                require_popup_closed=True,
            ),
            on_success_step_id="c4_s18_violin",
        ),
        VerificationStep(
            id="c4_s18_violin",
            text="Select '🎻 Violin Plot'.",
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["ComparisonsPlotTypeCombo"],
            validator=ComparisonPlotTypeValidator("violin"),
            on_success_step_id="c4_s18a_violin_options",
        ),
        InfoStep(
            id="c4_s18a_violin_options",
            text=(
                "Before you generate: what these settings do 🎛️<br><br>"
                "• **Orientation** — vertical or horizontal violins.<br>"
                "• **Axis Range** — clips the axis to a percentile so a few "
                "bright outliers don't squash the rest of the distribution "
                "into a sliver near zero. Leave at 100 for the full range.<br>"
                "• **Show box plot overlay** — draws median/IQR whiskers "
                "inside each violin.<br>"
                "• **Show individual data points** — overlays up to 500 raw "
                "events per sample as dots."
            ),
            cyto_emotion="talking",
            allow_interaction=True,
            target_widget_names=["ComparisonsOptionsPanel"],
            next_step_id="c4_s18b_violin_generate",
        ),
        VerificationStep(
            id="c4_s18b_violin_generate",
            text=(
                "Click '🔬 Generate Plot' (highlighted) to render it with the "
                "settings from the last step. Cyto carries on once it's ready."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            allow_scroll=True,
            hide_next_button=True,
            target_widget_names=["ComparisonsGenerateButton"],
            validator=ComparisonsPlotGeneratedValidator("violin"),
            on_success_step_id="c4_s19_violin_info",
        ),
        InfoStep(
            id="c4_s19_violin_info",
            text=(
                "Wide violin = many cells at that intensity. Three organs, "
                "one population — the same Thymus/Bone Marrow/Spleen "
                "B-cell story as the table, now as shape instead of a "
                "percentage."
            ),
            cyto_emotion="happy",
            allow_interaction=True,
            target_widget_names=["ComparisonsPlotDisplay"],
            next_step_id="c4_s20_channel_heatmap",
        ),
        VerificationStep(
            id="c4_s20_channel_heatmap",
            text="Select '🗺️ Channel Heatmap'.",
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["ComparisonsPlotTypeCombo"],
            validator=ComparisonPlotTypeValidator("channel heatmap"),
            on_success_step_id="c4_s20a_add_umap_pop",
        ),
        VerificationStep(
            id="c4_s20a_add_umap_pop",
            text=(
                "Bring in UMAP B Cells 🎯<br><br>"
                "Heatmap (and every chart type from here on) can show more "
                "than one population per sample, unlike Violin. Open "
                "**Edit Population Selection** (highlighted) again and "
                "also check **UMAP B Cells** for Sample C — leave your "
                "existing B-cells checks alone, just add this one. Now you "
                "have both methods side by side: the real comparison this "
                "whole course has been building to.<br><br>"
                "Close the popup once you're done."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["ComparisonsPopulationPickerButton"],
            validator=PopulationsCheckedValidator(
                "_comparisons_viewer",
                "b-cells",
                "umap b cells",
                max_checked=4,
                require_popup_closed=True,
            ),
            on_success_step_id="c4_s20a1_heatmap_channels",
        ),
        InfoStep(
            id="c4_s20a1_heatmap_channels",
            text=(
                "About that Channels list 📡<br><br>"
                "Violin only ever used one channel, so switching here reset "
                "the checklist back to **everything checked** — channel "
                "checks only carry over between chart types that share the "
                "same single-vs-multi channel mode, never across a mode "
                "change. Leave everything checked, or trim to just the "
                "channels you care about (e.g. B220) for a cleaner grid."
            ),
            cyto_emotion="talking",
            allow_interaction=True,
            target_widget_names=["ComparisonsChannelSection"],
            next_step_id="c4_s20b_channel_heatmap_generate",
        ),
        VerificationStep(
            id="c4_s20b_channel_heatmap_generate",
            text=(
                "Click '🔬 Generate Plot' (highlighted) to render it. Cyto "
                "carries on once it's ready."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            allow_scroll=True,
            hide_next_button=True,
            target_widget_names=["ComparisonsGenerateButton"],
            validator=ComparisonsPlotGeneratedValidator("channel heatmap"),
            on_success_step_id="c4_s21_channel_heatmap_info",
        ),
        InfoStep(
            id="c4_s21_channel_heatmap_info",
            text=(
                "Every marker at once 🗺️<br><br>"
                "Both Sample C B-cell rows should light up the same way, "
                "marker by marker — the same **profile**, not just the same "
                "B220.<br><br>"
                "(The **Radar Chart** in the same dropdown draws this as one "
                "shape per population — handy for big panels with many "
                "markers. We'll skip it here.)"
            ),
            cyto_emotion="talking",
            allow_interaction=True,
            target_widget_names=["ComparisonsPlotDisplay"],
            next_step_id="c4_s24_histogram",
        ),
        VerificationStep(
            id="c4_s24_histogram",
            text="Select '📊 Histogram Overlay'.",
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["ComparisonsPlotTypeCombo"],
            validator=ComparisonPlotTypeValidator("histogram overlay"),
            on_success_step_id="c4_s24a_histogram_settings",
        ),
        InfoStep(
            id="c4_s24a_histogram_settings",
            text=(
                "What these settings do 🎛️<br><br>"
                "• **Layout** — Ridge (the default, also called 'waterfall') "
                "stacks each population in its own row; Overlay draws them "
                "all on one shared axis instead.<br>"
                "• **Smooth curve (KDE)** — a smooth density estimate "
                "instead of raw histogram bars.<br>"
                "• **Normalise to peak** — scales each curve so its own "
                "peak hits 1.0, so a small population stays visible next "
                "to a big one. Turn off to compare absolute event counts.<br>"
                "• **X-axis scale** — Linear, Log₁₀, or Biexponential.<br><br>"
                "The Channels list reset again — Channel Heatmap was "
                "multi-channel, Histogram is single-channel."
            ),
            cyto_emotion="talking",
            allow_interaction=True,
            target_widget_names=["ComparisonsOptionsPanel", "ComparisonsChannelSection"],
            next_step_id="c4_s24a2_histogram_layout",
        ),
        VerificationStep(
            id="c4_s24a2_histogram_layout",
            text=(
                "Set it up to test your prediction 🔀<br><br>"
                "• **Channels:** check only **ƒ B220/CD45** — your ratio.<br>"
                "• **Layout:** pick **'Overlay (all on one axis)'**, so the "
                "curves sit on top of each other."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            allow_scroll=True,
            hide_next_button=True,
            target_widget_names=["ComparisonsChannelSection", "ComparisonsOptionsPanel"],
            validator=AllOf(
                ComparisonsDerivedChannelValidator("FITC-A", "APC-A"),
                HistogramOverlayLayoutValidator("overlay"),
            ),
            on_success_step_id="c4_s24b_histogram_generate",
        ),
        VerificationStep(
            id="c4_s24b_histogram_generate",
            text=(
                "Click '🔬 Generate Plot' (highlighted) to render it. Cyto "
                "carries on once it's ready."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            allow_scroll=True,
            hide_next_button=True,
            target_widget_names=["ComparisonsGenerateButton"],
            validator=ComparisonsPlotGeneratedValidator("histogram overlay"),
            on_success_step_id="c4_s25_histogram_info",
        ),
        InfoStep(
            id="c4_s25_histogram_info",
            text=(
                "Your prediction, tested 🔮<br><br>"
                "You predicted: **{answer:c4_same_measure}**.<br><br>"
                "Find Sample C's two curves — B-cells and UMAP B Cells. They "
                "sit almost on top of each other: median ratio **0.64** vs "
                "**0.65**, and a near-identical spread (CV **46%** vs "
                "**44%**). B220 alone says the same: medians within 1%. Same "
                "cells, measured the same — UMAP's just a touch tighter.<br><br>"
                "(Sample A's lumpy curve comes from only ~1,000 thymus "
                "B cells — too few for a clean peak.)"
            ),
            cyto_emotion="thinking",
            allow_interaction=True,
            target_widget_names=["ComparisonsPlotDisplay"],
            next_step_id="c4_s26_pseudocolor",
        ),
        VerificationStep(
            id="c4_s26_pseudocolor",
            text="Last chart type: select '🌈 Pseudocolor Overlay'.",
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["ComparisonsPlotTypeCombo"],
            validator=ComparisonPlotTypeValidator("pseudocolor overlay"),
            on_success_step_id="c4_s26b_pseudocolor_generate",
        ),
        VerificationStep(
            id="c4_s26b_pseudocolor_generate",
            text=(
                "Click '🔬 Generate Plot' (highlighted) to render it. Cyto "
                "carries on once it's ready."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            allow_scroll=True,
            hide_next_button=True,
            target_widget_names=["ComparisonsGenerateButton"],
            validator=ComparisonsPlotGeneratedValidator("pseudocolor overlay"),
            on_success_step_id="c4_s27_pseudocolor_info",
        ),
        InfoStep(
            id="c4_s27_pseudocolor_info",
            text=(
                "A different kind of comparison 🌈<br><br>"
                "This one skips channel expression entirely — no shared "
                "Channels list at all this time, because it isn't "
                "comparing a marker's intensity. It overlays population "
                "*shapes* on one sample, side by side, using its own X/Y "
                "Axis Channel pickers in **Plot Options** instead. Good "
                "for sanity-checking that your manual and UMAP-derived "
                "B-cells actually occupy the same region on a real 2D "
                "plot, not just matching numbers."
            ),
            cyto_emotion="happy",
            allow_interaction=True,
            target_widget_names=["ComparisonsPlotDisplay"],
            next_step_id="c4_s27b_export",
        ),
        # ── Take it with you (export) ────────────────────────────────────────────
        ForcedInteractionStep(
            id="c4_s27b_export",
            text=(
                "Take it with you 📤<br><br>"
                "Both tabs export. Do these two, in either order — Cyto "
                "carries on once both files are saved.<br><br>"
                "Also worth knowing: **📋 Copy All** on Statistics puts the "
                "table on your clipboard, and its Chart view has its own "
                "**📸 Export**."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            allow_scroll=True,
            target_widget_names=["ComparisonsExportButton", "StatsExportButton", "MainTabBar"],
            auto_advance_when_complete=True,
            sub_tasks=[
                SubTask(
                    id="c4_export_comparisons_plot",
                    instruction="Here on Comparisons: '📸 Export' saves this plot (PNG, PDF or SVG).",
                    target_widget_name="ComparisonsExportButton",
                    validator=ExportDoneValidator("_comparisons_viewer", "plot"),
                ),
                SubTask(
                    id="c4_export_stats_csv",
                    instruction="On Statistics: '📤 Export CSV' saves the table for a spreadsheet.",
                    target_widget_name="StatsExportButton",
                    validator=ExportDoneValidator("_statistics_explorer", "csv"),
                ),
            ],
            next_step_id="c4_s27k_save_workspace",
        ),
        # ── Save workspace + real completion ─────────────────────────────────────
        VerificationStep(
            id="c4_s27k_save_workspace",
            text=(
                "Last step: save your progress. Click the **⚠️ Save "
                "Workspace** button (highlighted) at the top right."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["WorkspaceSaveButton"],
            validator=WorkflowSavedValidator(),
            on_success_step_id="c4_s27z_graduation",
            failure_hint="Click **⚠️ Save Workspace**, give it a name, and click Save to finish.",
        ),
        InfoStep(
            # The true end of Course 4 — no next_step_id, so
            # AcademyManager.next_step() treats this as course completion
            # and awards badge_reward ("Insight Reporter") the moment the
            # user clicks Next. Matches Course 3's own ending convention
            # (c3_s58_graduation): a real save-workspace step immediately
            # before it, then a plain graduation message with no further
            # step to loop back to.
            id="c4_s27z_graduation",
            text=(
                "Course 4 is complete — you're officially an **Insight "
                "Reporter**! 🏆<br><br>"
                "**The verdict.** You predicted: *{answer:c4_same_measure}*. "
                "The evidence:<br>"
                "• **Same cells** — 99.95% of UMAP B Cells sit inside your "
                "gate, and UMAP found ~93% of yours.<br>"
                "• **Same measurement** — ratio peaks at 0.64 vs 0.65, with "
                "matching spread and marker profiles.<br><br>"
                "Two independent methods, one answer — that's the kind of "
                "cross-check worth putting in a report."
            ),
            cyto_emotion="cheering",
            cyto_animation="cheering",
        ),
    ],
)
