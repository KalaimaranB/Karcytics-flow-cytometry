"""Course 2 — Compensation & Clean-up Gates.

Picks up Course 1's workspace (samples, roles, the Cells gate, the file's
compensation applied) and builds the rest of the base hierarchy on
compensated data: Live Cells on PI, then Leukocytes on CD45.

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

from .constants import RIGHT_PANEL_HINT, RIGHT_PANEL_TARGET
from .validators import (
    AxisChannelValidator,
    AxisOutlierValidator,
    ExactSampleOpenValidator,
    GateShapeValidator,
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
        "With the data compensated, keep only what matters: gate out dead "
        "cells with PI, then find the Leukocytes with an FMO control."
    ),
    estimated_minutes=40,
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
                "had to come first."
            ),
            cyto_emotion="happy",
            cyto_animation="cheering",
            next_step_id="c2_s01c_verify_gating_tab",
        ),
        VerificationStep(
            id="c2_s01c_verify_gating_tab",
            text="Click the **Gating** tab (highlighted) at the top.",
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["MainTabBar"],
            validator=TabActiveValidator(1),  # Gating
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
