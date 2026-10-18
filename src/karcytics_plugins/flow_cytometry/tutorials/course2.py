"""Course 2 — Compensation & Clean-up Gates.

Picks up Course 1's workspace (samples, roles, the Cells gate, the file's
compensation applied). First the learner builds a matrix of their own from
the FMO tubes, compares it with the file's and fine-tunes it; then, with the
file's matrix back in use, the rest of the base hierarchy: Live Cells on PI
and Leukocytes on CD45.

Step conventions and spotlight conventions: see course1.py's header.
"""

from karcytics_sdk.plugin.tutorial_models import (
    AnswerChoice,
    Course,
    InfoStep,
    InteractionStep,
    QuestionStep,
    VerificationStep,
)

from ..main_tabs import MainTab
from .constants import RIGHT_PANEL_HINT, RIGHT_PANEL_TARGET
from .validators import (
    AllOf,
    AxisChannelValidator,
    AxisOutlierValidator,
    CompensationFitGateValidator,
    CompensationMethodValidator,
    CompensationPageValidator,
    EditorMatrixValidator,
    EmbeddedMatrixInUseValidator,
    ExactSampleOpenValidator,
    GateShapeValidator,
    IllustrationPlayedValidator,
    MatricesComparedValidator,
    PreviewShowsValidator,
    SavedMatrixValidator,
    SetupAndCellsStateValidator,
    SpecificSampleOpenValidator,
    TabActiveValidator,
    WorkflowSavedValidator,
)

# ==============================================================================
# Course 2 Gate Quality Validators
#
# Failure routing is `GateShapeValidator.describe_failure()`'s, as in Course 1.
# ==============================================================================

c2_live_validator = GateShapeValidator(
    # Must match the on-canvas guide_range=(-1000.0, 10000.0) drawn for
    # c2_s27f_draw_live_gate below — it previously said 50000.0 here, so a
    # gate drawn to exactly trace the dotted guide box the user is shown
    # (topping out at 10000) fell short of this validator's ±10%-of-axis-
    # range tolerance window around 50000 and was wrongly rejected as a
    # bad shape even when perfectly, correctly drawn.
    target_bounds=(-1000.0, 10000.0, 0.0, 0.0),
    target_name="Live Cells",
    misnamed_retry_step_id="c2_s27f_live_gate_misnamed",
    shape_retry_step_id="c2_s27f_live_gate_retry",
)

c2_leukocytes_validator = GateShapeValidator(
    target_bounds=(2000.0, 200000.0, 500.0, 37000.0),
    target_name="Leukocytes",
    misnamed_retry_step_id="c2_s30h_leukocytes_gate_misnamed",
    shape_retry_step_id="c2_s30h_leukocytes_gate_retry",
)


course_2_compensation = Course(
    id="flow_course_2_compensation",
    title="Compensation & Clean-up Gates",
    description=(
        "Build a spillover matrix from your FMO controls, check it against "
        "the cytometer's, then gate out dead cells and find the Leukocytes."
    ),
    estimated_minutes=50,
    badge_reward="Signal Cleaner",
    badge_icon="⚖️",
    prerequisite_course_ids=["flow_course_1_fundamentals"],
    steps=[
        # ── Checkpoint ───────────────────────────────────────────────────────
        VerificationStep(
            id="c2_s00_verify",
            validator=SetupAndCellsStateValidator(),
            text=(
                "Checking your workspace...<br><br>"
                "Making sure all 10 samples are loaded and compensated, roles are "
                "assigned, and the **Cells** gate exists — confirming the Course 1 "
                "workflow was opened correctly."
            ),
            allow_interaction=False,
            cyto_emotion="thinking",
            next_step_id="c2_s01_intro",
            failure_hint=(
                "This course picks up where Course 1 left off — make sure you opened the "
                "workspace you saved at the end of Course 1, with all samples, roles, "
                "compensation and the Cells gate in place."
            ),
        ),
        InfoStep(
            id="c2_s01_intro",
            text=(
                "Welcome to Course 2! 🎯<br><br>"
                "Your data is compensated and the **Cells** gate has removed the "
                "debris. Two more gates finish the clean-up, each drawn *inside* "
                "the one before:<br>"
                "**All Events → Cells → Live → Leukocytes**<br><br>"
                "Both sit on fluorescence channels, which is why compensation "
                "had to come first. So before the gates, one more look at the "
                "matrix: this time you'll build your own."
            ),
            cyto_emotion="happy",
            cyto_animation="cheering",
            next_step_id="c2_b01_why_build",
        ),
        # ── Building a matrix from the FMO controls ───────────────────────────
        InfoStep(
            id="c2_b01_why_build",
            text=(
                "Why build your own matrix? 🧮<br><br>"
                "In Course 1 you read the matrix the cytometer saved in the files. "
                "Two reasons to make one yourself:<br>"
                "• some files carry no matrix at all<br>"
                "• a second, independent estimate is the best check on the first<br><br>"
                "Your **FMO** tubes can provide one. You'll estimate it, compare "
                "it with the file's, and decide which to keep."
            ),
            cyto_emotion="talking",
            next_step_id="c2_b02_verify_comp_tab",
        ),
        VerificationStep(
            id="c2_b02_verify_comp_tab",
            text="Click the **Compensation** tab (highlighted) at the top.",
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["MainTabBar"],
            validator=TabActiveValidator(MainTab.COMPENSATION),
            on_success_step_id="c2_b03_pick_fmo",
        ),
        VerificationStep(
            id="c2_b03_pick_fmo",
            text=(
                "Set **Method** (highlighted) to **FMO controls**, and stay on the "
                "**⚙ Method setup** page."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["CompensationMethodCombo", "CompensationSetupPageButton"],
            validator=AllOf(CompensationMethodValidator("fmo"), CompensationPageValidator("setup")),
            on_success_step_id="c2_b04_how_it_works",
            failure_hint="Open the **Method** dropdown and pick FMO controls; click **⚙ Method setup** if another page is showing.",
        ),
        InfoStep(
            id="c2_b04_how_it_works",
            text=(
                "How the FMO method works 💡<br><br>"
                "An FMO tube has every dye but one. So whatever its *missing* "
                "dye's detector records must have leaked in from the others. "
                "Karcytics measures that leak in each FMO tube, then solves all "
                "of them together for the matrix.<br><br>"
                "This is Karcytics' own method, not a published standard, so the "
                "page (highlighted) spells out every step and its limits. Read "
                "it once: a method you can't explain is one you can't defend."
            ),
            cyto_emotion="talking",
            target_widget_names=["MethodSetupPanel"],
            next_step_id="c2_b05_tube_table",
        ),
        QuestionStep(
            id="c2_b05_tube_table",
            text=(
                "What it will use 🔎<br><br>"
                "The table shows each FMO tube, the dye it **Lacks**, and **How "
                "we know**. The *e450* tube's name doesn't say Pacific Blue. How "
                "was it placed?"
            ),
            question_id="c2_fmo_placed_by_data",
            choices=[
                AnswerChoice("It is dim in that channel, unlike the other FMO tubes", correct=True),
                AnswerChoice(
                    "From the tube's name",
                    feedback="Names are only a fallback guess. The How we know column says this one came from its data.",
                ),
                AnswerChoice(
                    "From its Role",
                    feedback="The role only says it is an FMO control, not which dye was left out.",
                ),
            ],
            explanation=(
                "A tube without a dye is the odd one out in that dye's detector. "
                "That is worked out once and kept; the Missing dye dropdown "
                "lets you correct it."
            ),
            cyto_emotion="thinking",
            allow_interaction=True,
            target_widget_names=["MethodInputsTable"],
            next_step_id="c2_b06_reveal",
        ),
        InfoStep(
            id="c2_b06_reveal",
            text=(
                "The blind spot 🕳️<br><br>"
                "Look at the table's last row: **(no FMO control) · "
                "PerCP-Cy5-5-A · not estimated — left at 0**.<br><br>"
                "In Course 1 you predicted: *{answer:c1_fmo_blind_spot}*.<br><br>"
                "With no tube lacking that dye, the method has nothing to measure "
                "the leak from. It says so rather than guessing. Remember this "
                "detector: it is where PI is read."
            ),
            cyto_emotion="surprised",
            target_widget_names=["MethodInputsTable"],
            next_step_id="c2_b07_fit_on_cells",
        ),
        VerificationStep(
            id="c2_b07_fit_on_cells",
            text=("Set **Fit on** (highlighted) to **Cells**, the gate you drew in Course 1."),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["MethodGateCombo"],
            validator=CompensationFitGateValidator("Cells"),
            on_success_step_id="c2_b08_why_cells",
            failure_hint="Open the **Fit on** dropdown near the top of Method setup and pick Cells.",
        ),
        QuestionStep(
            id="c2_b08_why_cells",
            text=(
                "The **Events used** column now counts only the events inside "
                "Cells. Why fit on those rather than on everything recorded?"
            ),
            question_id="c2_why_fit_on_cells",
            choices=[
                AnswerChoice(
                    "Fewer events make the fit faster",
                    feedback="Speed isn't the point: the method samples at most 100,000 events per tube either way.",
                ),
                AnswerChoice(
                    "Debris and clumps give signal that isn't dye spill",
                    correct=True,
                ),
                AnswerChoice(
                    "Compensation only applies inside gates",
                    feedback="The finished matrix is applied to every event. The gate only chooses which events the estimate learns from.",
                ),
            ],
            explanation=(
                "Fragments and aggregates glow for their own reasons. Let them "
                "into the fit and their signal is read as spill. This is why "
                "the Cells gate came before compensation."
            ),
            cyto_emotion="thinking",
            allow_interaction=True,
            target_widget_names=["MethodInputsTable", "MethodGateCombo"],
            next_step_id="c2_b09_play",
        ),
        VerificationStep(
            id="c2_b09_play",
            text=(
                "See it happen 🎬<br><br>"
                "Scroll down this page to **See it step by step**. It draws the "
                "fit on one of your own tubes.<br><br>"
                "Press **▶ Play** and watch all four steps: what the tube "
                "recorded, an ordinary fit, the robust fit, and the spill removed."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["MethodSetupPanel"],
            validator=IllustrationPlayedValidator(),
            on_success_step_id="c2_b10_greyed_points",
            failure_hint="Scroll to the bottom of Method setup and press **▶ Play**; wait for step 4 of 4.",
        ),
        QuestionStep(
            id="c2_b10_greyed_points",
            text=("From step 3 on, some points are drawn in grey. What are they?"),
            question_id="c2_robust_outliers",
            choices=[
                AnswerChoice(
                    "Events deleted from the tube",
                    feedback="Nothing is deleted. They stay in the data and are compensated like every other event.",
                ),
                AnswerChoice(
                    "Events outside the Cells gate",
                    feedback="Those were never in the plot: Fit on already left them out.",
                ),
                AnswerChoice("Events the fit gave little weight to", correct=True),
            ],
            explanation=(
                "Dead cells and stray bright events sit far from the line. The "
                "robust fit down-weights them, so a few odd events can't drag "
                "the slope. Compare the two lines in step 3."
            ),
            cyto_emotion="thinking",
            allow_interaction=True,
            target_widget_names=["MethodSetupPanel"],
            next_step_id="c2_b11_run",
        ),
        InteractionStep(
            id="c2_b11_run",
            text="Now run it: click **🧮 Estimate from FMOs** (highlighted).",
            target_widget_name="RunMethodButton",
            event_trigger="clicked",
            cyto_emotion="pointing",
            next_step_id="c2_b12_grey_cells",
        ),
        InfoStep(
            id="c2_b12_grey_cells",
            text=(
                "Your own matrix 🎉<br><br>"
                "Most cells are plain: the method measured them. The whole "
                "**PerCP-Cy5-5** column is *grey italic*: not measured, left at 0, "
                "exactly as the setup table warned.<br><br>"
                "The status line now names **FMO controls** and adds *matrix "
                "changed since it was applied*: the samples still hold the values "
                "the file's matrix gave them until you apply this one."
            ),
            cyto_emotion="happy",
            target_widget_names=["CompensationMatrixTable", "CompensationStatusLine"],
            next_step_id="c2_b13_open_matrices",
        ),
        InteractionStep(
            id="c2_b13_open_matrices",
            text=(
                "Two matrices, two methods. Put them side by side: click "
                "**🗂 Matrices** (highlighted)."
            ),
            target_widget_name="CompensationMatricesPageButton",
            event_trigger="clicked",
            cyto_emotion="pointing",
            next_step_id="c2_b14_compare",
        ),
        VerificationStep(
            id="c2_b14_compare",
            text=(
                "1. In the list, select **FMO controls · Cells**.<br>"
                "2. Set **Compare with** to **Embedded in the FCS files**.<br><br>"
                "Cells that differ are tinted and show the difference in brackets."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["MatrixLibraryList", "MatrixCompareCombo"],
            validator=MatricesComparedValidator("fmo", "cytometer"),
            on_success_step_id="c2_b15_which_matters",
            failure_hint="Click FMO controls · Cells in the list on the left, then pick Embedded in the FCS files in **Compare with**.",
        ),
        QuestionStep(
            id="c2_b15_which_matters",
            text=(
                "Most cells agree to within a few hundredths: two independent "
                "methods, nearly the same answer. Next we gate live cells on "
                "**PI**, read in PerCP-Cy5-5. Which difference matters most for "
                "that gate?"
            ),
            question_id="c2_difference_that_matters",
            choices=[
                AnswerChoice(
                    "APC into APC-Cy7",
                    feedback="The two methods nearly agree there, and neither detector is the one PI is read in.",
                ),
                AnswerChoice("PE into PerCP-Cy5-5", correct=True),
                AnswerChoice(
                    "Pacific Blue into APC-Cy7",
                    feedback="A small difference, and not in the detector PI is read in.",
                ),
            ],
            explanation=(
                "The file says 0.30; our estimate has nothing there. Left at 0, "
                "every PE-bright cell would keep PE's leak in the PI detector "
                "and look more dead than it is."
            ),
            cyto_emotion="thinking",
            allow_interaction=True,
            target_widget_names=["MatrixCompareTable"],
            next_step_id="c2_b16_back_to_matrix",
        ),
        InteractionStep(
            id="c2_b16_back_to_matrix",
            text="Let's see that on real cells. Click **Matrix** (highlighted).",
            target_widget_name="CompensationMatrixPageButton",
            event_trigger="clicked",
            cyto_emotion="pointing",
            next_step_id="c2_b17_see_the_tilt",
        ),
        VerificationStep(
            id="c2_b17_see_the_tilt",
            text=(
                "1. Click the grey **0.0000** cell in the **PE-A** row, "
                "**PerCP-Cy5-5-A** column.<br>"
                "2. Set **Sample** to **Sample A**.<br><br>"
                "The After plot looks just like the raw one: the cloud still "
                "climbs. Our matrix is doing nothing for this pair."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["CompensationMatrixTable", "PreviewSampleCombo"],
            validator=AllOf(
                EditorMatrixValidator("fmo"),
                PreviewShowsValidator(x="PE-A", y="PerCP-Cy5-5-A", sample_name="Sample A"),
            ),
            on_success_step_id="c2_b18_fine_tune",
            failure_hint=(
                "The **Matrix** dropdown above the table should show the FMO controls "
                "matrix. Click the PE-A row's PerCP-Cy5-5-A cell, then choose Sample A."
            ),
        ),
        VerificationStep(
            id="c2_b18_fine_tune",
            text=(
                "Fine-tune it ✍️<br><br>"
                "Double-click that cell, type **0.30** and press Enter.<br><br>"
                "Watch the **After** plot as you do."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["CompensationMatrixTable", "CompensationPreviewArea"],
            validator=EditorMatrixValidator("fmo", "PE-A", "PerCP-Cy5-5-A", 0.30),
            on_success_step_id="c2_b19_fine_tuned",
            failure_hint="Double-click the PE-A row's PerCP-Cy5-5-A cell, type 0.30, then press Enter.",
        ),
        InfoStep(
            id="c2_b19_fine_tuned",
            text=(
                "Level. 🎯<br><br>"
                "The cloud dropped flat, the cell turned **green bold** (edited "
                "by hand), and the status line warns of **unapplied edits**: the "
                "change lives in the editor until you apply it.<br><br>"
                "This is the routine after any automatic method: look at each "
                "pair that matters, and adjust the value until the population "
                "sits level. Too low and it tilts up; too high and it dips below."
            ),
            cyto_emotion="happy",
            target_widget_names=["CompensationMatrixTable", "CompensationStatusLine"],
            next_step_id="c2_b20_save",
        ),
        VerificationStep(
            id="c2_b20_save",
            text=(
                "Keep it. Go to **🗂 Matrices**, click **💾 Save current as…** and "
                "give it a name, like **FMO + PI fix**."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["CompensationMatricesPageButton", "MatrixSaveButton"],
            validator=SavedMatrixValidator("fmo", fine_tuned=True),
            on_success_step_id="c2_b21_other_methods",
            failure_hint="On the Matrices page, click **💾 Save current as…**, type a name and confirm.",
        ),
        InfoStep(
            id="c2_b21_other_methods",
            text=(
                "The other methods, briefly 📚<br><br>"
                "• **Single-stain controls**: one tube per dye; the classic way, "
                "when you have them.<br>"
                "• **Import from a file**: a matrix made elsewhere, as a CSV.<br>"
                "• **Manual entry**: every value starts at 0 and you type each one.<br><br>"
                "Whichever you use, the routine is the same: run it, read what "
                "it rested on, check the plots, fine-tune."
            ),
            cyto_emotion="talking",
            target_widget_names=["CompensationMethodCombo"],
            next_step_id="c2_b22_choose",
        ),
        VerificationStep(
            id="c2_b22_choose",
            text=(
                "Which one do we keep? ⚖️<br><br>"
                "The cytometer's matrix was measured for all six dyes. Ours "
                "agrees with it where it could measure, and needed a typed-in "
                "value where it couldn't. So the file's matrix stays, now with "
                "an independent check behind it. (You'd keep your own if the files "
                "carried none, or if yours sat level on a pair where the file's "
                "tilted.)<br><br>"
                "In the list, select **Embedded in the FCS files** and click "
                "**✅ Apply to all samples**."
            ),
            cyto_emotion="thinking",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["MatrixLibraryList", "ApplyAllButton"],
            validator=EmbeddedMatrixInUseValidator(),
            on_success_step_id="c2_b23_recap",
            failure_hint=(
                "On the Matrices page, click Embedded in the FCS files in the list, "
                "then **✅ Apply to all samples**."
            ),
        ),
        InfoStep(
            id="c2_b23_recap",
            text=(
                "Compensation, done properly ✅<br><br>"
                "You estimated a matrix, read what it was built on, found its "
                "blind spot, compared it with a second method, fixed a value by "
                "eye, and chose which to use, knowing why.<br><br>"
                "Now the gates that depend on it."
            ),
            cyto_emotion="cheering",
            next_step_id="c2_s01c_verify_gating_tab",
        ),
        VerificationStep(
            id="c2_s01c_verify_gating_tab",
            text="Click the **Gating** tab (highlighted) at the top.",
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["MainTabBar"],
            validator=TabActiveValidator(MainTab.GATING),
            on_success_step_id="c2_s26_live_intro",
        ),
        # Live gate
        InfoStep(
            id="c2_s26_live_intro",
            text=(
                "**Gate 2: Live**<br><br>"
                "Dead cells absorb PI dye and glow brightly (high signal). "
                "Live cells keep it out — they appear dim.<br><br>"
                "We gate *inside* the Cells population to keep only "
                "live cells. This is called hierarchical gating.<br><br>"
                "When you draw the gate in a few steps, be sure to name it **Live Cells** in the naming popup!"
            ),
            cyto_emotion="talking",
            next_step_id="c2_s27_open_pi",
        ),
        # ── Step 1: Open the PI single stain sample ─────────────────────────
        InteractionStep(
            id="c2_s27_open_pi",
            text=(
                "Time to gate live vs dead cells.<br><br>"
                "Dead cells absorb PI dye and glow bright. Live cells keep "
                "it out and stay dim.<br><br>"
                "First, double-click the **Specimen_001_PI** Single Stain sample "
                "in the **Sample List** to open it. This sample has only the PI "
                "viability dye — perfect for clearly seeing dead vs live."
            ),
            cyto_emotion="pointing",
            target_widget_names=["SampleList"],
            target_widget_name="SampleList",
            event_trigger="sample_double_clicked",
            next_step_id="c2_s27_verify_pi",
        ),
        VerificationStep(
            id="c2_s27_verify_pi",
            text="Checking opened sample...",
            cyto_emotion="scanning",
            hide_next_button=True,
            allow_interaction=False,
            validator=SpecificSampleOpenValidator("SINGLE_STAIN"),
            on_success_step_id="c2_s27b_set_axis",
            on_fail_step_id="c2_s27_fail",
        ),
        InteractionStep(
            id="c2_s27_fail",
            text=(
                "Oops! You opened the wrong sample.<br><br>"
                "Please double-click the **Specimen_001_PI** sample to open it."
            ),
            cyto_emotion="surprised",
            target_widget_names=["SampleList"],
            target_widget_name="SampleList",
            event_trigger="sample_double_clicked",
            next_step_id="c2_s27_verify_pi",
        ),
        # ── Step 2: Change X axis to the PI channel ──────────────────────────
        VerificationStep(
            id="c2_s27b_set_axis",
            text=(
                "Now set the X axis to the PI channel.<br>"
                "Click the **X:** dropdown (highlighted) and select "
                "**PerCP-Cy5-5-A** — that is the PI detector channel.<br><br>"
                "Checking..."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["AxisSelectorX"],
            validator=AxisChannelValidator("percp"),
            on_success_step_id="c2_s27c_biexp_explain",
            failure_hint="Make sure the **X:** axis dropdown is set to **PerCP-Cy5-5-A**, the PI detector channel.",
        ),
        # ── Step 3: Explain biexponential and populations ───────────────────
        QuestionStep(
            id="c2_s27c_biexp_explain",
            text=(
                "Read the PI plot 🔬<br><br>"
                "Two clusters: a big, dim one on the left and a smaller, "
                "bright one on the right. PI can only get into cells whose "
                "membranes are damaged. Which cluster is the dead cells?"
            ),
            question_id="c2_dead_cluster",
            choices=[
                AnswerChoice(
                    "The big, dim one on the left",
                    feedback="Dim means little PI got in: intact membranes kept it out. Those are the live cells.",
                ),
                AnswerChoice(
                    "Neither: PI marks live cells",
                    feedback="PI can't cross a healthy membrane. It only reaches the DNA of cells that are breaking down.",
                ),
                AnswerChoice("The smaller, bright one on the right", correct=True),
            ],
            explanation=(
                "Also notice Karcytics opened this sample at your Cells gate, "
                "and switched X to Biexponential: compensated data can go "
                "negative for real cells, and only Biexponential shows those "
                "values properly."
            ),
            cyto_emotion="thinking",
            allow_interaction=True,
            target_widget_names=["FlowCanvas"],
            next_step_id="c2_s27d_outlier_fix",
        ),
        # ── Step 4: Fix Outliers ────────────────────────────────────────────
        VerificationStep(
            id="c2_s27d_outlier_fix",
            text=(
                "However, look closely at the left edge of the dim population — "
                "it seems a bit cut off!<br><br>"
                "By default, Karcytics hides the extreme 0.1% of outliers to prevent "
                "single noise spikes from ruining the scale. Let's turn that off here "
                "to see the full tail.<br><br>"
                "1. Click **⚙ Transforms** (highlighted)<br>"
                "2. Change **Outliers:** from **0.1% (Def)** to **0%**<br><br>"
                "Checking..."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["TransformsButton", "OutlierCombo"],
            validator=AxisOutlierValidator(0.0),
            on_success_step_id="c2_s27f_draw_live_gate",
            failure_hint="Open **⚙ Transforms** and make sure **Outliers:** is set to **0%**, not the default 0.1%.",
        ),
        # ── Step 5: Draw the vertical Range gate ────────────────────────────────
        InteractionStep(
            id="c2_s27f_draw_live_gate",
            text=(
                "Now draw the Live cell gate.<br><br>"
                "The dark purple box shows the target region. Drag from the left edge of the "
                "box to the right edge to capture the live cells.<br><br>"
                "1. Click the **Range** tool (highlighted in the ribbon)<br>"
                "2. Drag horizontally across the left cluster. Start from the far left edge (around -10³) and end just past the dense red center (around 5000).<br>"
                "3. Type **Live Cells** in the naming popup!<br><br>" + RIGHT_PANEL_HINT
            ),
            cyto_emotion="pointing",
            target_widget_names=["Tool_range", "FlowCanvas", RIGHT_PANEL_TARGET],
            target_widget_name="MainPanel",
            event_trigger="gate_added_to_tree",
            metadata={"guide_range": (-1000.0, 10000.0)},
            next_step_id="c2_s27f_draw_live_gate_verify",
            stuck_hint_text=(
                "Still there? Click the **Range** tool, then drag across the dark purple box "
                "from left edge to right edge."
            ),
            stuck_hint_after_ms=45000,
        ),
        VerificationStep(
            id="c2_s27f_draw_live_gate_verify",
            text="Checking...",
            cyto_emotion="scanning",
            allow_interaction=False,
            hide_next_button=True,
            validator=c2_live_validator,
            on_success_step_id="c2_s27g_settings_intro",
            on_fail_step_id="c2_s27f_live_gate_retry",
        ),
        InfoStep(
            id="c2_s27f_live_gate_misnamed",
            text="I renamed the gate to **Live Cells** for you. Let's proceed!",
            cyto_emotion="happy",
            next_step_id="c2_s27g_settings_intro",
        ),
        InfoStep(
            id="c2_s27f_live_gate_retry",
            text=(
                "That gate didn't quite capture the right range!<br><br>"
                "I deleted it for you. Make sure the high bound doesn't cross into the dead cells on the right.<br><br>"
                "Try drawing it again."
            ),
            cyto_emotion="surprised",
            target_widget_names=["FlowCanvas"],
            metadata={"guide_range": (-1000.0, 10000.0)},
            next_step_id="c2_s27f_draw_live_gate",
        ),
        InteractionStep(
            id="c2_s27g_settings_intro",
            text=(
                "Visual Settings ⚙️<br><br>"
                "Before we move on, click the **⚙ Settings** button above the plot (highlighted).<br><br>"
                "This opens a menu where you can adjust the Detail and Smoothing sliders. "
                "These are purely cosmetic and don't affect your underlying data or gates — "
                "they just help you visualize dense clusters more clearly.<br><br>"
                "Play around with them to see how the plot updates instantly, and close the window when you're done!"
            ),
            cyto_emotion="talking",
            target_widget_name="PseudocolorSettingsButton",
            event_trigger="clicked",
            target_widget_names=["PseudocolorSettingsButton"],
            next_step_id="c2_s28_stats_intro",
        ),
        QuestionStep(
            id="c2_s28_stats_intro",
            text=(
                "Understanding the stats 📊<br><br>"
                "The **Properties Panel** shows **% Parent** (share of the gate "
                "above) and **% Total** (share of every event in the tube). If "
                "Live Cells is 90% of Cells, and Cells is 70% of all events, "
                "what is Live Cells' % Total?"
            ),
            question_id="c2_percent_total",
            choices=[
                AnswerChoice(
                    "90%",
                    feedback="That's % Parent: the share of Cells only. % Total also counts the 30% that Cells left out.",
                ),
                AnswerChoice("63%", correct=True),
                AnswerChoice(
                    "70%",
                    feedback="That's Cells' share. Live Cells is only part of Cells, so its share of everything is smaller.",
                ),
            ],
            explanation=(
                "Shares multiply down the hierarchy: 90% of 70% is 63%. The "
                "panel also shows the Event Count, and the Group "
                "Preview below shows this gate on every sample at once."
            ),
            cyto_emotion="thinking",
            allow_interaction=True,
            target_widget_names=["PropertiesPanel"],
            next_step_id="c2_s29_leuko_intro",
        ),
        # Leukocytes gate
        InfoStep(
            id="c2_s29_leuko_intro",
            text=(
                "**Gate 3: Leukocytes** (CD45+)<br><br>"
                "CD45 is expressed on ALL white blood cells — T cells, B cells, NK cells, "
                "monocytes — but NOT on red blood cells, platelets or debris.<br><br>"
                "Gating CD45-bright cells isolates your immune population for everything that follows.<br><br>"
                "Here's the plan:<br>"
                "① Open the FMO APC control → see the true background ceiling<br>"
                "② Draw the gate right there on the FMO, explicitly excluding that background<br>"
                "③ Switch to a full-panel sample to confirm the same gate captures the real "
                "CD45+ cluster<br><br>"
                "When you draw the gate, be sure to name it **Leukocytes** in the naming popup!"
            ),
            cyto_emotion="talking",
            next_step_id="c2_s30a_open_fmo",
        ),
        # ── Step 1: Open FMO to see background ───────────────────────────────
        InteractionStep(
            id="c2_s30a_open_fmo",
            text=(
                "Step ①: Open the FMO control.<br><br>"
                "Double-click the **FMO APC** sample in the **Sample List** to open it. "
                "This sample contains everything *except* the APC dye, so any signal "
                "in the APC channel here is pure background."
            ),
            cyto_emotion="pointing",
            target_widget_names=["SampleList"],
            target_widget_name="SampleList",
            event_trigger="sample_double_clicked",
            next_step_id="c2_s30a_verify_fmo",
        ),
        VerificationStep(
            id="c2_s30a_verify_fmo",
            text="Checking opened sample...",
            cyto_emotion="scanning",
            hide_next_button=True,
            allow_interaction=False,
            validator=ExactSampleOpenValidator("FMO APC"),
            on_success_step_id="c2_s30b_set_x",
            on_fail_step_id="c2_s30a_fail",
        ),
        InteractionStep(
            id="c2_s30a_fail",
            text=(
                "Oops! You opened the wrong sample.<br><br>"
                "Please double-click the **FMO APC** sample to open it."
            ),
            cyto_emotion="surprised",
            target_widget_names=["SampleList"],
            target_widget_name="SampleList",
            event_trigger="sample_double_clicked",
            next_step_id="c2_s30a_verify_fmo",
        ),
        VerificationStep(
            id="c2_s30b_set_x",
            text=(
                "Set X-axis to **APC-A** (the CD45 channel).<br><br>"
                "(The Y-axis is already Side Scatter by default, which is perfect for leukocyte gating).<br><br>"
                "Checking..."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["AxisSelectorX"],
            validator=AxisChannelValidator("apc"),
            on_success_step_id="c2_s30d_outlier",
            failure_hint="Make sure the **X:** axis dropdown is set to **APC-A**, the CD45 channel.",
        ),
        InfoStep(
            id="c2_s30d_outlier",
            text=(
                "Same outlier trick as before ⚠️<br><br>"
                "The default 0.1% trim is hiding a sliver of cells at the edge of the "
                "APC-A axis again. Click **⚙ Transforms** → set **Outliers** to **0%** → close "
                "the dialog, then click Next."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            target_widget_names=["TransformsButton"],
            next_step_id="c2_s30e_read_fmo",
        ),
        InfoStep(
            id="c2_s30e_read_fmo",
            text=(
                "Reading the FMO plot 🔍<br><br>"
                "The big dense cluster near X=0 isn't spillover — those cells "
                "simply have no signal at all in the APC-A channel, no "
                "antibody and no meaningful background.<br><br>"
                "The real background to watch is the sparse scatter of "
                "events trailing off to the right of that cluster — that's "
                "autofluorescence, the small amount of non-specific light "
                "every cell naturally emits. That's exactly what an FMO "
                "control is designed to reveal.<br><br>"
                "We're going to draw the Leukocytes gate right here, on this "
                "FMO — since it has zero real CD45 signal, everything on "
                "this plot IS background by definition, so we can exclude "
                "it with total confidence before we've even looked at a "
                "real sample.<br><br>"
                "You may also notice the **SSC-A** axis appears to have a lower cutoff. "
                "That's the biexponential transform compressing the near-zero region — "
                "it's a visual effect only. Compensation never touches FSC or SSC channels, "
                "so the scatter data is exactly as measured by the instrument."
            ),
            cyto_emotion="talking",
            allow_interaction=True,
            target_widget_names=["FlowCanvas"],
            next_step_id="c2_s30g_preview_intro",
        ),
        # ── Step 2: Draw the gate on the FMO itself ────────────────────────────
        InfoStep(
            id="c2_s30g_preview_intro",
            text=(
                "Use the **Group Preview** to watch it propagate! 👥<br><br>"
                "Look at the bottom-right panel — it shows mini-plots of every other sample "
                "on the same axes. Scroll down inside it to find the Sample A/B/C "
                "thumbnails.<br><br>"
                "As you draw the gate in the next step — right here on the FMO — watch "
                "those thumbnails update live. That's Auto-Propagation copying your "
                "exact boundary onto every full-panel sample in real time."
            ),
            cyto_emotion="talking",
            allow_interaction=True,
            target_widget_names=["GroupPreviewPanel"],
            next_step_id="c2_s30h_draw_gate",
        ),
        InteractionStep(
            id="c2_s30h_draw_gate",
            text=(
                "Step ②: Draw the Leukocyte gate — right here on the FMO.<br><br>"
                "1. Select the **Rect** tool.<br>"
                "2. The dark purple box marks the CD45+ region. Start your rectangle "
                "at roughly X=10² (right where the autofluorescence tail ends) and drag "
                "all the way to the right edge, covering the full height of the **SSC-A** axis.<br>"
                "3. Type **Leukocytes** in the naming popup!<br><br>"
                "Watch the **Group Preview** thumbnails as you drag — you'll see this exact "
                "boundary appear on Samples A, B, and C instantly.<br><br>" + RIGHT_PANEL_HINT
            ),
            cyto_emotion="pointing",
            target_widget_names=["Tool_rectangle", "FlowCanvas", RIGHT_PANEL_TARGET],
            target_widget_name="MainPanel",
            event_trigger="gate_added_to_tree",
            metadata={"guide_rect": (2000.0, 200000.0, 500.0, 37000.0)},
            next_step_id="c2_s30h_draw_gate_verify",
            stuck_hint_text=(
                "Still there? Click the **Rect** tool, then drag across the dark purple box "
                "covering the CD45+ region."
            ),
            stuck_hint_after_ms=45000,
        ),
        VerificationStep(
            id="c2_s30h_draw_gate_verify",
            text="Checking...",
            cyto_emotion="scanning",
            allow_interaction=False,
            hide_next_button=True,
            validator=c2_leukocytes_validator,
            on_success_step_id="c2_s30f_open_sample",
            on_fail_step_id="c2_s30h_leukocytes_gate_retry",
        ),
        InfoStep(
            id="c2_s30h_leukocytes_gate_misnamed",
            text="I renamed the gate to **Leukocytes** for you. Let's proceed!",
            cyto_emotion="happy",
            next_step_id="c2_s30f_open_sample",
        ),
        InfoStep(
            id="c2_s30h_leukocytes_gate_retry",
            text=(
                "That gate didn't quite capture the right area!<br><br>"
                "I deleted it for you. Make sure your rectangle starts past the autofluorescence and covers the full SSC-A height.<br><br>"
                "Try drawing it again."
            ),
            cyto_emotion="surprised",
            target_widget_names=["FlowCanvas"],
            metadata={"guide_rect": (2000.0, 200000.0, 500.0, 37000.0)},
            next_step_id="c2_s30h_draw_gate",
        ),
        # ── Step 3: Switch to a full-panel sample to confirm ───────────────────
        InteractionStep(
            id="c2_s30f_open_sample",
            text=(
                "Step ③: Confirm on a real sample.<br><br>"
                "Double-click **Sample B** in the sample list. Unlike the FMO, Sample B "
                "has ALL antibodies including CD45-APC — and since Auto-Propagation is "
                "on, the exact **Leukocytes** gate you just drew should already be "
                "sitting on this plot too."
            ),
            cyto_emotion="pointing",
            target_widget_names=["SampleList"],
            target_widget_name="SampleList",
            event_trigger="sample_double_clicked",
            next_step_id="c2_s30f_verify_sample",
        ),
        VerificationStep(
            id="c2_s30f_verify_sample",
            text="Checking opened sample...",
            cyto_emotion="scanning",
            hide_next_button=True,
            allow_interaction=False,
            validator=ExactSampleOpenValidator("Sample B"),
            on_success_step_id="c2_s30f1b_verify_propagated",
            on_fail_step_id="c2_s30f_fail",
        ),
        InteractionStep(
            id="c2_s30f_fail",
            text=(
                "Oops! You opened the wrong sample.<br><br>Please double-click **Sample B** to open it."
            ),
            cyto_emotion="surprised",
            target_widget_names=["SampleList"],
            target_widget_name="SampleList",
            event_trigger="sample_double_clicked",
            next_step_id="c2_s30f_verify_sample",
        ),
        VerificationStep(
            id="c2_s30f1b_verify_propagated",
            text="Checking that your gate propagated to Sample B...",
            cyto_emotion="scanning",
            hide_next_button=True,
            allow_interaction=False,
            validator=c2_leukocytes_validator,
            on_success_step_id="c2_s30f2_set_x_sample_a",
            failure_hint="If the Leukocytes gate hasn't appeared here yet, make sure Auto-Propagation is enabled and try re-opening Sample B.",
        ),
        InfoStep(
            id="c2_s30f2_set_x_sample_a",
            text=(
                "Confirmed! ✅<br><br>"
                "The exact same **Leukocytes** rectangle you drew on the FMO now sits "
                "right here on Sample B, and it cleanly separates the CD45− cluster "
                "on the left from the real CD45+ leukocytes on the right — proof that "
                "a boundary set against pure background does its job on real stained "
                "data too.<br><br>"
                "Karcytics also preserved your gating context here, opening directly into "
                "the **Live** gate (highlighted in white in the hierarchy view), and "
                "locked the zoom/axis scaling to match what you had on the FMO."
            ),
            cyto_emotion="happy",
            allow_interaction=True,
            target_widget_names=["AxisSelectorX", "GatingHierarchySampleView"],
            next_step_id="c2_s30f3_persistence_explain",
        ),
        InfoStep(
            id="c2_s30f3_persistence_explain",
            text=(
                "Behind the Scenes: The **No-Jump** Rule<br><br>"
                "In Karcytics, the auto-zoom calculation only happens *once* the very first time you select a channel. "
                "From that point on, the view is completely locked for that channel across all samples in the group.<br><br>"
                "This guarantees that as you draw deeper gates and switch between controls and full samples, the plot "
                "won't aggressively jump around or zoom in. You will always maintain your bearings!"
            ),
            cyto_emotion="talking",
            next_step_id="c2_s32_auto_propagation",
        ),
        # Auto-propagation
        InfoStep(
            id="c2_s32_auto_propagation",
            text=(
                "Brilliant! Three-gate hierarchy built on our controls. 🎉<br><br>"
                "Because Auto-Propagation is enabled, Karcytics has automatically "
                "copied all three gates — Cells, Live, and Leukocytes — "
                "to the Full Panel samples in the background. Imagine doing "
                "that by hand across dozens of samples in a real study — "
                "this is the payoff.<br><br>"
                "The toggle to the right indicates Auto-propagation is "
                "enabled."
                "<br><br>"
                "You can verify this by looking at the Gate Hierarchy panel."
            ),
            cyto_emotion="happy",
            target_widget_names=["GatingHierarchySampleView"],
            next_step_id="c2_s33b_save_interaction",
        ),
        VerificationStep(
            id="c2_s33b_save_interaction",
            text=(
                "Saving your progress 💾<br><br>"
                "Course 3 requires the foundation we just built. We need to save "
                "this workspace so we can load it later.<br><br>"
                "Click the **⚠️ Save Workspace** button (highlighted) at the top right "
                "and save it."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["WorkspaceSaveButton"],
            validator=WorkflowSavedValidator(),
            on_success_step_id="c2_s34_graduation",
            failure_hint="Click **⚠️ Save Workspace**, give it a name, and click Save to finish.",
        ),
        InfoStep(
            id="c2_s34_graduation",
            text=(
                "All done! Debris, dead cells and non-immune cells are gone: you've "
                "identified the core immune population in our samples. 🚀<br><br>"
                "Your workspace is saved. In Course 3, we will use this exact "
                "setup to finally solve the mystery of what these three "
                "samples are.<br><br>"
                "Click Next to collect your badge!"
            ),
            cyto_emotion="cheering",
            cyto_animation="cheering",
        ),
    ],
)
