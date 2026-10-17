"""Karcytics Flow Cytometry — Academy Courses.

Step conventions:
  InfoStep              — teaches a concept; user clicks Next → to continue.
  InteractionStep       — user must click/interact with a named widget to auto-advance.
  VerificationStep      — auto-polls a validator every ~2 s and advances automatically.
                          Set allow_interaction=True only if the user also needs to freely
                          interact with the UI before clicking the manual 'Check ✓' button.

Spotlight convention:
  target_widget_name  — single objectName for InteractionStep highlight.
  target_widget_names — list of objectNames for multi-target InfoStep spotlights.

Panel reference (confirmed from the tutorial FCS file headers, $PnN/$PnS):
  CD45 = APC-A          | FMO APC
  CD3  = Pacific Blue-A | FMO e450 (this dataset names the Pacific-Blue FMO control "e450")
  CD4  = PE-A           | FMO PE
  CD8  = APC-Cy7-A      | FMO APCCy7
  B220 = FITC-A         | FMO FITC
  PI   = PerCP-Cy5-5-A  | (viability, single stain)

"""

from karcytics_sdk.plugin.tutorial_models import (
    AnswerChoice,
    Course,
    ForcedInteractionStep,
    InfoStep,
    InteractionStep,
    QuestionStep,
    SubTask,
    VerificationStep,
)

from .constants import RIGHT_PANEL_HINT, RIGHT_PANEL_TARGET
from .validators import (
    AxisChannelValidator,
    AxisYChannelValidator,
    BaseGatesStateValidator,
    ExactSampleOpenValidator,
    FmoOverlayValidator,
    GateActiveValidator,
    GateEditTracker,
    GateShapeValidator,
    PipelineOrientationValidator,
    PlotTypeValidator,
    PopupClosedValidator,
    QuadrantPositionNamedValidator,
    SampleAndGateOpenValidator,
    TabActiveValidator,
    WorkflowSavedValidator,
)

# ==============================================================================
# Course 3 Gate Quality Validators & Routers
# ==============================================================================

c3_tcells_validator = GateShapeValidator(
    # Matches the on-canvas guide_rect=(-400.0, 2000.0, 300.0, 8000.0) drawn
    # for c3_s07_draw_tcell below. The old (-1000, 5000, 100, 10000) target
    # didn't match that guide box, though the ±10%-of-axis-range tolerance
    # happened to be wide enough that it never actually rejected a correctly
    # drawn gate here — realigned anyway so the guide box shown is always
    # exactly what gets validated (see c1_live_validator in course1.py for a
    # case where this same kind of mismatch WAS wide enough to matter).
    # The CD3 top sits above the 99.9th percentile of every sample's T cells:
    # at the old 2000 it ran through the CD4 T cells' median and dropped
    # about half of them (the Sample Lens flagged it as a cut).
    target_bounds=(-400.0, 2000.0, 300.0, 8000.0),
    target_name="T-cells",
    misnamed_retry_step_id="c3_s07_tcell_gate_misnamed",
    shape_retry_step_id="c3_s07_tcell_gate_retry",
)

# Shared by the edit step and the undo step that follows it.
c3_tcells_edit = GateEditTracker("T-cells")

c3_bcells_validator = GateShapeValidator(
    # Must match the on-canvas guide_range=(4000.0, 100000.0) drawn for
    # c3_s18_draw_bcell below — it previously said 262144.0 (the raw axis's
    # absolute max) here, so a gate drawn to trace the visible guide box
    # (topping out at 100000) fell far short of the required tolerance
    # window around 262144 and was wrongly rejected as a bad shape.
    target_bounds=(3000.0, 100000.0, 0.0, 0.0),
    target_name="B-cells",
    misnamed_retry_step_id="c3_s18_bcell_gate_misnamed",
    shape_retry_step_id="c3_s18_bcell_gate_retry",
)

c3_quadrant_validator = GateShapeValidator(
    target_bounds=(3000.0, 7000.0, 3000.0, 7000.0),
    target_name=None,
    # No naming step for a QuadrantGate (it auto-names Q1-Q4), so
    # misnamed_retry_step_id is never reached — GateShapeValidator only
    # diagnoses a name mismatch when target_name is set.
    shape_retry_step_id="c3_s37_quadrant_gate_retry",
)

# Gate-drawing steps (T-cells / B-cells / Quadrant below) no longer wire
# their own ActionStep-based failure routing: the validators above
# implement `GateShapeValidator.describe_failure()` (see validators.py),
# and `AcademyStepDriver` (SDK) calls it automatically on a failed
# VerificationStep — showing the explanation banner, auto-renaming/deleting
# the gate, and routing to the validator's own retry step in one generic
# path shared by every course that uses `GateShapeValidator` (see course1.py
# for the first migration of this pattern).


# ==============================================================================
# Course 3 — Immunophenotyping & the Pipeline
# Finale of the intro content: gate T-cells and B-cells out of Leukocytes,
# split T-cells into CD4/CD8 subsets, navigate the Pipeline view, and solve
# the tissue-ID mystery.
# ==============================================================================

course_3_gating = Course(
    id="flow_course_3_gating",
    title="Immunophenotyping & the Pipeline",
    description=(
        "Identify T-cells and B-cells inside your Leukocytes, split T-cells into "
        "CD4/CD8 subsets, master the Pipeline view, and work out which organ each "
        "mystery sample came from."
    ),
    estimated_minutes=40,
    badge_reward="Immunophenotyper",
    badge_icon="🧬",
    prerequisite_course_ids=["flow_course_2_compensation"],
    steps=[
        # ── Checkpoint ───────────────────────────────────────────────────────
        VerificationStep(
            id="c3_s00_verify",
            validator=BaseGatesStateValidator(),
            text=(
                "Checking your workspace...<br><br>"
                "Making sure all 10 samples are loaded, roles are assigned, and the "
                "base gates (**Cells** → **Live Cells** → **Leukocytes**) exist — confirming "
                "the Course 2 workflow was opened correctly."
            ),
            allow_interaction=False,
            cyto_emotion="thinking",
            next_step_id="c3_s01_intro",
            failure_hint=(
                "This course picks up where Course 2 left off — make sure you opened the "
                "workspace you saved at the end of Course 2, with all samples, roles, and "
                "the Cells → Live Cells → Leukocytes gates already built."
            ),
        ),
        InfoStep(
            id="c3_s01_intro",
            text=(
                "Welcome to Course 3! 🎯<br><br>"
                "Our **Leukocytes** are gated. Now let's identify who's actually inside "
                "that population: **T-cells** and **B-cells**, using two different gating "
                "techniques."
            ),
            cyto_emotion="happy",
            cyto_animation="cheering",
            next_step_id="c3_s01a_objectives",
        ),
        InfoStep(
            id="c3_s01a_objectives",
            text=(
                "What you'll walk away with 🎯<br><br>"
                "By the end of this course, you'll be able to:<br>"
                "• Gate the same population two different ways (2-marker "
                "scatter vs. histogram + FMO overlay) and know when to "
                "reach for each<br>"
                "• Split a population 4 ways at once with a **Quadrant** gate<br>"
                "• Read the **Pipeline** view the way a real gating strategy "
                "gets documented<br>"
                "• Turn gated populations into evidence, and name each "
                "sample's organ from it<br><br>"
                "And by the end, you'll have a confident, evidence-backed "
                "answer to the sample-ID mystery."
            ),
            cyto_emotion="talking",
            next_step_id="c3_s01c_verify_gating_tab",
        ),
        # Passes at once if the user is already on Gating (very likely,
        # arriving straight from Course 2).
        VerificationStep(
            id="c3_s01c_verify_gating_tab",
            text=(
                "Let's go find them — click the **Gating** tab at the top, "
                "that's where the drawing tools live."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["MainTabBar"],
            validator=TabActiveValidator(1),
            on_success_step_id="c3_s02_open_sample",
        ),
        VerificationStep(
            id="c3_s02_open_sample",
            text="Double-click **Sample A** in the Data hierarchy to open it in a Graph Window.",
            validator=ExactSampleOpenValidator("sample a"),
            allow_interaction=True,
            cyto_emotion="pointing",
            target_widget_names=["SampleList"],
            on_success_step_id="c3_s03_tcell_intro",
            failure_hint="Make sure you double-clicked **Sample A** specifically in the Data hierarchy.",
        ),
        # ── T-cells (2-marker plot: B220 vs CD3) ────────────────────────────────
        InfoStep(
            id="c3_s03_tcell_intro",
            text=(
                "**Gate 1: T-cells (CD3+, B220−)** 🧬<br><br>"
                "**CD3** is the pan-T-cell marker and **B220** is the pan-B-cell marker — "
                "plotting them against each other separates both populations, and "
                "everything else, in one view.<br><br>"
                "We'll set X = B220 and Y = CD3, inside **Leukocytes**."
            ),
            cyto_emotion="talking",
            next_step_id="c3_s04_set_x",
        ),
        VerificationStep(
            id="c3_s04_set_x",
            text="Set the X axis to **FITC-A** — the B220 detector.",
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["AxisSelectorX"],
            validator=AxisChannelValidator("fitc"),
            on_success_step_id="c3_s05_set_y",
            failure_hint="Make sure the **X:** axis dropdown is set to **FITC-A**, the B220 detector.",
        ),
        VerificationStep(
            id="c3_s05_set_y",
            text="Now set the Y axis to **Pacific Blue-A** — the CD3 detector.",
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["AxisSelectorY"],
            validator=AxisYChannelValidator("pacific blue"),
            on_success_step_id="c3_s06_tcell_plot_read",
            failure_hint="Make sure the **Y:** axis dropdown is set to **Pacific Blue-A**, the CD3 detector.",
        ),
        QuestionStep(
            id="c3_s06_tcell_plot_read",
            text=(
                "Read the plot 🔍<br><br>"
                "X is **B220** (a B-cell marker), Y is **CD3** (a T-cell "
                "marker). Where are the **T-cells**?"
            ),
            question_id="c3_tcell_location",
            choices=[
                AnswerChoice(
                    "Lower-left: low on both",
                    feedback="Low on both is CD3− B220−: a 'double negative' group that's neither T nor B cells.",
                ),
                AnswerChoice("Upper-left: CD3 high, B220 low", correct=True),
                AnswerChoice(
                    "Lower-right: B220 high, CD3 low",
                    feedback="B220 without CD3 is a B cell. You'll gate those next, a different way.",
                ),
            ],
            explanation=(
                "T cells carry CD3 but not B220: high on Y, low on X. As you "
                "draw the rectangle next, watch the Group Preview thumbnails "
                "(bottom-right) update live across every sample."
            ),
            cyto_emotion="thinking",
            allow_interaction=True,
            target_widget_names=["FlowCanvas"],
            next_step_id="c3_s07_draw_tcell",
        ),
        InteractionStep(
            id="c3_s07_draw_tcell",
            text=(
                "Draw the **T-cells** gate:<br><br>"
                "1. Select the **Rect** tool.<br>"
                "2. Draw a rectangle around the upper-left cluster — high CD3 "
                "(Y), low B220 (X).<br>"
                "3. Name it **T-cells**.<br><br>" + RIGHT_PANEL_HINT
            ),
            cyto_emotion="pointing",
            target_widget_names=["Tool_rectangle", "FlowCanvas", RIGHT_PANEL_TARGET],
            target_widget_name="MainPanel",
            event_trigger="gate_added_to_tree",
            metadata={"guide_rect": (-400.0, 2000.0, 300.0, 8000.0)},
            next_step_id="c3_s07_draw_tcell_verify",
            stuck_hint_text=(
                "Still there? Click the **Rect** tool, then drag around the upper-left "
                "cluster (high CD3, low B220)."
            ),
            stuck_hint_after_ms=45000,
        ),
        VerificationStep(
            id="c3_s07_draw_tcell_verify",
            text="Karcytics is scanning automatically...",
            cyto_emotion="scanning",
            allow_interaction=False,
            hide_next_button=True,
            validator=c3_tcells_validator,
            on_success_step_id="c3_s08_tcell_done",
            on_fail_step_id="c3_s07_tcell_gate_retry",
        ),
        InfoStep(
            id="c3_s07_tcell_gate_misnamed",
            text="I renamed the gate to **T-cells** for you. Let's proceed!",
            cyto_emotion="happy",
            next_step_id="c3_s08_tcell_done",
        ),
        InfoStep(
            id="c3_s07_tcell_gate_retry",
            text=(
                "That gate didn't quite capture the right area!<br><br>"
                "I deleted it for you. Make sure your rectangle covers the upper-left cluster (CD3+, B220-).<br><br>"
                "Try drawing it again."
            ),
            cyto_emotion="surprised",
            target_widget_names=["FlowCanvas"],
            metadata={"guide_rect": (-400.0, 2000.0, 300.0, 8000.0)},
            next_step_id="c3_s07_draw_tcell",
        ),
        InfoStep(
            id="c3_s08_tcell_done",
            text=(
                "**T-cells** gated! ✅<br><br>"
                "Auto-Propagation just copied this gate to every other sample "
                "in the group — Samples B and C (and the controls) already have it too."
            ),
            cyto_emotion="happy",
            next_step_id="c3_e01_gates_arent_final",
        ),
        # ── Editing a gate, and undoing it ──────────────────────────────────────
        InfoStep(
            id="c3_e01_gates_arent_final",
            text=(
                "A gate is never final ✏️<br><br>"
                "You'll often draw a gate on one sample, see it on another, and "
                "want an edge a little tighter or wider. You don't redraw it: "
                "with the **Select** tool (highlighted) you click a gate, then "
                "drag an edge to resize it or drag its middle to move it."
            ),
            cyto_emotion="talking",
            target_widget_names=["Tool_select"],
            next_step_id="c3_e01b_back_to_parent",
        ),
        VerificationStep(
            # Drawing a gate opens its own plot (MainPanel._on_gate_drawn), and
            # that plot shows only the gate's cells: the T-cells rectangle is
            # drawn on Leukocytes, one level up. Passes at once if the learner
            # is already there.
            id="c3_e01b_back_to_parent",
            text=(
                "First, find the gate 🔼<br><br>"
                "Drawing a gate took you **inside** it, so you can keep gating: "
                "this plot shows only the T cells. The T-cells rectangle itself "
                "lives one level up, on **Leukocytes**.<br><br>"
                "Click **↑ Parent Gate** above the plot."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["ParentGateButton"],
            validator=SampleAndGateOpenValidator("sample a", "leukocytes"),
            on_success_step_id="c3_e02_edit_gate",
            failure_hint="Click **↑ Parent Gate** above the plot until it shows Sample A's Leukocytes.",
        ),
        VerificationStep(
            id="c3_e02_edit_gate",
            text=(
                "Try it on **T-cells**:<br><br>"
                "1. Click the **Select** tool.<br>"
                "2. Click the T-cells gate, then drag its right edge a little "
                "to the left.<br><br>"
                "Keep an eye on the **Group Preview** on the right as you let go."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["Tool_select", "FlowCanvas", RIGHT_PANEL_TARGET],
            validator=c3_tcells_edit.edited(),
            on_success_step_id="c3_e03_edit_everywhere",
            failure_hint="Pick the **Select** tool, click the T-cells rectangle, and drag one of its edges.",
        ),
        QuestionStep(
            id="c3_e03_edit_everywhere",
            text=(
                "You resized the gate on **Sample A**. What happened to T-cells on Samples B and C?"
            ),
            question_id="c3_edit_propagates",
            choices=[
                AnswerChoice(
                    "Nothing, until the gate is copied again",
                    feedback="Auto-Propagation re-applies every edit to the whole group, not just the first drawing.",
                ),
                AnswerChoice("They changed too: the group shares one gate", correct=True),
                AnswerChoice(
                    "They were removed from those samples",
                    feedback="Editing never deletes a gate. The same gate, in its new shape, is on every sample in the group.",
                ),
            ],
            explanation=(
                "One gate, every sample: that keeps them comparable. Anything "
                "gated inside it is recounted too, which is why an early gate "
                "deserves the most care."
            ),
            cyto_emotion="thinking",
            allow_interaction=True,
            target_widget_names=[RIGHT_PANEL_TARGET],
            next_step_id="c3_e04_undo",
        ),
        VerificationStep(
            id="c3_e04_undo",
            text=(
                "Now put it back. Press **Ctrl+Z** (**Cmd+Z** on a Mac).<br><br>"
                "The gate returns to the shape you drew, on every sample. "
                "**Ctrl+Y** (**Cmd+Shift+Z** on a Mac) is Redo, should you want "
                "the edit after all.<br><br>"
                "*Nothing happening? Click the plot once so it has focus, then try again.*"
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["FlowCanvas", RIGHT_PANEL_TARGET],
            validator=c3_tcells_edit.undone(),
            on_success_step_id="c3_e05_undo_limits",
            failure_hint="Click the plot, then press Ctrl+Z (Cmd+Z on a Mac) until the gate is back to its first shape.",
        ),
        QuestionStep(
            id="c3_e05_undo_limits",
            text=(
                "Undo steps back through changes to your **analysis**, one at a "
                "time. But it doesn't cover everything. Which of these will "
                "Undo *not* bring back?"
            ),
            question_id="c3_undo_limits",
            choices=[
                AnswerChoice("The axis scale a plot had before you changed it", correct=True),
                AnswerChoice(
                    "A gate you deleted",
                    feedback="Deleting a gate is one undo step. It comes back with every gate that was inside it.",
                ),
                AnswerChoice(
                    "The role a sample had before you changed it",
                    feedback="Roles are part of the analysis, so a role change is an undo step like any other.",
                ),
            ],
            explanation=(
                "Undo covers gates, roles, groups, compensation and derived "
                "parameters. It leaves how you are looking at the data alone: "
                "axis scales, zoom, which sample is open. Matrix edits not yet "
                "applied have their own Revert Edits button."
            ),
            cyto_emotion="thinking",
            next_step_id="c3_s09_switch_sample_intro",
        ),
        # ── B-cells (Histogram + FMO Overlay technique, on Sample C) ────────────
        InfoStep(
            id="c3_s09_switch_sample_intro",
            text=(
                "**Gate 2: B-cells (B220+)** 🎨<br><br>"
                "Sample A doesn't contain enough B-cells to comfortably gate — "
                "we need to switch to **Sample C** first.<br><br>"
                "There's a fast way to jump straight to a specific population on "
                "a different sample, instead of double-clicking and re-navigating "
                "the hierarchy by hand."
            ),
            cyto_emotion="talking",
            next_step_id="c3_s10_open_leuko_c",
        ),
        InteractionStep(
            id="c3_s10_open_leuko_c",
            text=(
                "In the Data hierarchy, right-click on **Sample C**, then click "
                "**Leukocytes** in the population menu that appears — this opens "
                "Sample C directly at that gate."
            ),
            target_widget_name="SampleList",
            target_widget_names=["SampleList"],
            event_trigger="population_open_requested",
            cyto_emotion="pointing",
            next_step_id="c3_s11_verify_leuko_c",
        ),
        VerificationStep(
            id="c3_s11_verify_leuko_c",
            text="Checking opened population...",
            cyto_emotion="scanning",
            hide_next_button=True,
            allow_interaction=False,
            validator=SampleAndGateOpenValidator("sample c", "leukocytes"),
            on_success_step_id="c3_s14_bcell_intro",
            on_fail_step_id="c3_s11b_wrong_pop",
        ),
        InteractionStep(
            id="c3_s11b_wrong_pop",
            text=(
                "Oops! Right-click **Sample C** specifically, and choose **Leukocytes** from its menu."
            ),
            cyto_emotion="surprised",
            target_widget_name="SampleList",
            target_widget_names=["SampleList"],
            event_trigger="population_open_requested",
            next_step_id="c3_s11_verify_leuko_c",
        ),
        InfoStep(
            id="c3_s14_bcell_intro",
            text=(
                "Notice the axes and the **T-cells** gate are already here — the "
                "'No-Jump' rule you learned in Course 2 locked B220 (X) and CD3 "
                "(Y) in for this group the moment you first set them on Sample A, "
                "and the gate itself propagated straight over.<br><br>"
                "This sample also has a clear B220+, CD3− population: real "
                "B-cells. But let's try something new: instead of another "
                "rectangle, we'll gate it with a **Histogram** and a live **FMO "
                "overlay**."
            ),
            cyto_emotion="talking",
            target_widget_names=["FlowCanvas"],
            next_step_id="c3_s15_histogram_mode",
        ),
        InteractionStep(
            id="c3_s15_histogram_mode",
            text=(
                "Switch the **Display Mode** dropdown (above the plot) from "
                "**Pseudocolor** to **Histogram**."
            ),
            target_widget_name="DisplayModeCombo",
            target_widget_names=["DisplayModeCombo"],
            event_trigger="activated",
            cyto_emotion="pointing",
            next_step_id="c3_s15_verify_histogram",
        ),
        VerificationStep(
            id="c3_s15_verify_histogram",
            text="Checking display mode...",
            cyto_emotion="scanning",
            allow_interaction=False,
            hide_next_button=True,
            validator=PlotTypeValidator("histogram"),
            on_success_step_id="c3_s16_fmo_overlay",
            on_fail_step_id="c3_s15_histogram_retry",
        ),
        InteractionStep(
            id="c3_s15_histogram_retry",
            text=(
                "Oops, that's not Histogram mode!<br><br>"
                "Make sure you select **Histogram** from the Display Mode dropdown."
            ),
            target_widget_name="DisplayModeCombo",
            target_widget_names=["DisplayModeCombo"],
            event_trigger="activated",
            cyto_emotion="surprised",
            next_step_id="c3_s15_verify_histogram",
        ),
        InteractionStep(
            id="c3_s16_fmo_overlay",
            text=(
                "Now use the **FMO Overlay:** dropdown (next to the axis selectors) "
                "and select the **FMO FITC** control.<br><br>"
                "Watch what happens: the FMO's histogram appears in gray behind "
                "your real data, and Karcytics auto-switches your drawing tool to "
                "**Range** for you."
            ),
            target_widget_name="AxisSelectorFMO",
            target_widget_names=["AxisSelectorFMO"],
            event_trigger="currentTextChanged",
            cyto_emotion="pointing",
            next_step_id="c3_s16_verify_fmo",
        ),
        VerificationStep(
            id="c3_s16_verify_fmo",
            text="Checking FMO selection...",
            cyto_emotion="scanning",
            allow_interaction=False,
            hide_next_button=True,
            validator=FmoOverlayValidator("fmo fitc"),
            on_success_step_id="c3_s17_threshold_info",
            on_fail_step_id="c3_s16_fmo_retry",
        ),
        InteractionStep(
            id="c3_s16_fmo_retry",
            text=(
                "Wait, that's not the FITC FMO!<br><br>"
                "Make sure you select **FMO FITC** from the dropdown so the "
                "threshold line calculation matches your B220 (FITC) axis."
            ),
            target_widget_name="AxisSelectorFMO",
            target_widget_names=["AxisSelectorFMO"],
            event_trigger="currentTextChanged",
            cyto_emotion="surprised",
            next_step_id="c3_s16_verify_fmo",
        ),
        QuestionStep(
            id="c3_s17_threshold_info",
            text=(
                "Read the overlay 📏<br><br>"
                "The gray curve is the **FMO FITC**: every dye except B220's. "
                "The red dashed line marks its 99th percentile. Why set the "
                "B220 threshold from this FMO instead of the Blank?"
            ),
            question_id="c3_why_fmo_threshold",
            multi_select=True,
            choices=[
                AnswerChoice(
                    "It has no cells, so its background is zero",
                    feedback="An FMO has plenty of cells, just no B220 antibody. Its FITC signal is real background.",
                ),
                AnswerChoice(
                    "Like your samples, it has the other dyes' spillover into FITC",
                    correct=True,
                ),
                AnswerChoice(
                    "The Blank is brighter in FITC",
                    feedback="It's the reverse: with no dyes at all, the Blank is too dim, so a threshold from it sits too low.",
                ),
                AnswerChoice(
                    "Its cells were stained and handled like your samples",
                    correct=True,
                ),
            ],
            explanation=(
                "The FMO is your sample minus B220: everything that lights up "
                "FITC except B220 itself. 99% of that background sits left of "
                "the red line, so the hump to its right is real B-cells."
            ),
            cyto_emotion="thinking",
            allow_interaction=True,
            target_widget_names=["FlowCanvas"],
            next_step_id="c3_s18_draw_bcell",
        ),
        InteractionStep(
            id="c3_s18_draw_bcell",
            text=(
                "Build a **Range** gate — the only gate type allowed on a histogram — "
                "to select the right-hand (positive) population:<br><br>"
                "Click and drag horizontally starting at (or just past) the red "
                "threshold line, capturing the bright B220+ peak.<br><br>"
                "Name the gate **B-cells**.<br><br>" + RIGHT_PANEL_HINT
            ),
            cyto_emotion="pointing",
            target_widget_names=["Tool_range", "FlowCanvas", RIGHT_PANEL_TARGET],
            target_widget_name="MainPanel",
            event_trigger="gate_added_to_tree",
            metadata={"guide_range": (4000.0, 100000.0)},
            stuck_hint_text=(
                "Still there? Click the **Range** tool, then drag starting at the red "
                "threshold line across the bright B220+ peak."
            ),
            stuck_hint_after_ms=45000,
            next_step_id="c3_s18_draw_bcell_verify",
        ),
        VerificationStep(
            id="c3_s18_draw_bcell_verify",
            text="Checking...",
            cyto_emotion="scanning",
            allow_interaction=False,
            hide_next_button=True,
            validator=c3_bcells_validator,
            on_success_step_id="c3_s19_bcell_done",
            on_fail_step_id="c3_s18_bcell_gate_retry",
        ),
        InfoStep(
            id="c3_s18_bcell_gate_misnamed",
            text="I renamed the gate to **B-cells** for you. Let's proceed!",
            cyto_emotion="happy",
            next_step_id="c3_s19_bcell_done",
        ),
        InfoStep(
            id="c3_s18_bcell_gate_retry",
            text=(
                "That gate didn't quite capture the right range!<br><br>"
                "I deleted it for you. Make sure you start at the red threshold line and cover the bright B220+ peak.<br><br>"
                "Try drawing it again."
            ),
            cyto_emotion="surprised",
            target_widget_names=["FlowCanvas"],
            metadata={"guide_range": (4000.0, 100000.0)},
            next_step_id="c3_s18_draw_bcell",
        ),
        QuestionStep(
            id="c3_s19_bcell_done",
            text=(
                "**B-cells** gated! ✅<br><br>"
                "You've used two techniques, both anchored to an FMO. In your "
                "next experiment, you need cells positive vs. negative for "
                "**one** marker, and the split is subtle. Which do you reach for?"
            ),
            question_id="c3_histogram_or_scatter",
            choices=[
                AnswerChoice("A histogram with the FMO overlay", correct=True),
                AnswerChoice(
                    "A two-marker scatter rectangle",
                    feedback="Scatter shines when two markers separate populations cleanly at once. One subtle marker needs the FMO's exact threshold.",
                ),
                AnswerChoice(
                    "Gate by eye on the sample alone",
                    feedback="Without a control, a subtle split is a guess. The FMO shows where background ends.",
                ),
            ],
            explanation=(
                "One marker means one axis, which a histogram shows best, and "
                "the FMO's threshold line puts the cut on evidence. A scatter "
                "rectangle is fastest when two markers separate populations "
                "cleanly."
            ),
            cyto_emotion="happy",
            next_step_id="c3_s20_hierarchy_view",
        ),
        InfoStep(
            id="c3_s20_hierarchy_view",
            text=(
                "Scroll (if needed) in the **Gating Hierarchy** panel — you'll see "
                "**T-cells** and **B-cells** as sibling populations, both branching "
                "directly out of **Leukocytes**."
            ),
            cyto_emotion="talking",
            allow_interaction=True,
            target_widget_names=["GatingHierarchyScrollArea"],
            next_step_id="c3_s24_verify_pipeline_tab",
        ),
        # ── Pipeline mastery ─────────────────────────────────────────────────────
        VerificationStep(
            id="c3_s24_verify_pipeline_tab",
            text=(
                "Let's see your whole gating strategy at a glance — click "
                "the **Pipeline** tab at the top."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["MainTabBar"],
            validator=TabActiveValidator(3),
            on_success_step_id="c3_s25_pipeline_read",
        ),
        InfoStep(
            id="c3_s25_pipeline_read",
            text=(
                "The **Pipeline** view 🌿<br><br>"
                "Your entire gating strategy as a flowchart: **Leukocytes** splits "
                "into **T-cells** and **B-cells**. Every node is the same gate object as "
                "in the tree view — just visualized differently.<br><br>"
                "This isn't just a prettier tree: a flowchart like this is "
                "the standard way gating strategies get documented and "
                "shared in real papers and labs — it's what you'd screenshot "
                "to explain your analysis to a collaborator, not the nested "
                "sidebar list."
            ),
            cyto_emotion="talking",
            target_widget_names=["PipelineCanvas"],
            next_step_id="c3_s26_orientation",
        ),
        VerificationStep(
            id="c3_s26_orientation",
            text=(
                "Change the **Layout:** dropdown in the Pipeline ribbon from "
                "**Vertical** to **Horizontal** to quickly view the entire plot chain "
                "in a single glance."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["PipelineOrientationCombo"],
            validator=PipelineOrientationValidator("horizontal"),
            on_success_step_id="c3_s27_pipeline_explain",
            failure_hint="Make sure the **Layout:** dropdown in the Pipeline ribbon is set to **Horizontal**.",
        ),
        InfoStep(
            id="c3_s27_pipeline_explain",
            text=(
                "Getting around the canvas 🧭<br><br>"
                "You can freely drag any node to reposition it. "
                "To pan the whole canvas, hold the "
                "middle mouse button and drag.<br><br>"
                "The **+ AND** / **+ OR** / **+ NOT** buttons build boolean logic nodes "
                "that combine populations — we'll put those to real use in "
                "Course 4."
            ),
            cyto_emotion="talking",
            target_widget_names=["PipelineCanvas"],
            next_step_id="c3_s27b_pipeline_thumbnails",
        ),
        InfoStep(
            id="c3_s27b_pipeline_thumbnails",
            text=(
                "One more thing before you go — why the node plots look the way "
                "they do 🔍<br><br>"
                "**Leukocytes** shows CD3 vs B220 because that's the exact view "
                "you were in when you drew **T-cells**, the first split beneath "
                "it. **B-cells** shares that same B220 (X) axis, so its range "
                "gate rides along too — that's the shaded band on the right.<br><br>"
                "Notice that band is on a **pseudocolor** plot, even though you "
                "actually drew the B-cells gate back in **Histogram** mode. Same "
                "threshold either way — a 1D range only ever needs its one axis, "
                "so it projects cleanly onto Leukocytes' 2D view here as a "
                "vertical line instead of forcing a whole separate histogram "
                "into this spot.<br><br>"
                "**B-cells** itself, though, renders as a **histogram** — you drew "
                "that gate as a 1D range on B220 alone, with no second axis to "
                "fall back on. Karcytics remembers exactly how each gate was "
                "drawn and reconstructs that same view for its node here, so "
                "every plot in the Pipeline shows the real evidence behind it "
                "instead of a generic icon."
            ),
            cyto_emotion="thinking",
            target_widget_names=["PipelineCanvas"],
            next_step_id="c3_s29_verify_gating_tab",
        ),
        VerificationStep(
            id="c3_s29_verify_gating_tab",
            text=("Time for one more split — click the **Gating** tab at the top to head back."),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["MainTabBar"],
            validator=TabActiveValidator(1),
            on_success_step_id="c3_s30_reenter_tcells_intro",
        ),
        # ── CD4/CD8 quadrant split (still on Sample C) ──────────────────────────
        InfoStep(
            id="c3_s30_reenter_tcells_intro",
            text=(
                "Great progress! 🎉<br><br>"
                "You've gated **T-cells** and **B-cells** with two different techniques, "
                "explored the quick stats view, and learned to navigate the "
                "**Pipeline** view.<br><br>"
                "One more split: not all T-cells are equal. **Sample C** should still "
                "be open right where you left it — let's dive back into its "
                "**T-cells** population."
            ),
            cyto_emotion="happy",
            next_step_id="c3_s31_dblclick_tcells",
        ),
        InteractionStep(
            id="c3_s31_dblclick_tcells",
            text=(
                "In the **Gating Hierarchy** panel, double-click **T-cells** to make it "
                "the active population."
            ),
            target_widget_name="GatingHierarchyView",
            target_widget_names=["GatingHierarchyView"],
            event_trigger="gate_double_clicked",
            cyto_emotion="pointing",
            next_step_id="c3_s32_verify_tcells_active",
        ),
        VerificationStep(
            id="c3_s32_verify_tcells_active",
            text="Checking active population...",
            cyto_emotion="scanning",
            hide_next_button=True,
            allow_interaction=False,
            validator=GateActiveValidator("t-cells"),
            on_success_step_id="c3_s33_quadrant_intro",
            on_fail_step_id="c3_s32b_wrong_node",
        ),
        InteractionStep(
            id="c3_s32b_wrong_node",
            text="Oops! Double-click **T-cells** specifically in the hierarchy.",
            cyto_emotion="surprised",
            target_widget_name="GatingHierarchyView",
            target_widget_names=["GatingHierarchyView"],
            event_trigger="gate_double_clicked",
            next_step_id="c3_s32_verify_tcells_active",
        ),
        InfoStep(
            id="c3_s33_quadrant_intro",
            text=(
                "Splitting **T-cells** by CD4/CD8 ✂️<br><br>"
                "**CD4+** helpers, **CD8+** killers, and — in some tissues — cells that "
                "are BOTH CD4+ and CD8+ ('Double Positive', **DP**), or neither "
                "('Double Negative', **DN**). A single **Quadrant** gate splits a plot "
                "into all 4 regions at once."
            ),
            cyto_emotion="thinking",
            next_step_id="c3_s35_set_x_cd4",
        ),
        VerificationStep(
            id="c3_s35_set_x_cd4",
            text="Set the X axis to **PE-A** — the CD4 detector.",
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["AxisSelectorX"],
            validator=AxisChannelValidator("pe-a"),
            on_success_step_id="c3_s36_set_y_cd8",
            failure_hint="Make sure the **X:** axis dropdown is set to **PE-A**, the CD4 detector.",
        ),
        VerificationStep(
            id="c3_s36_set_y_cd8",
            text="Set the Y axis to **APC-Cy7-A** — the CD8 detector.",
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["AxisSelectorY"],
            validator=AxisYChannelValidator("apc-cy7"),
            on_success_step_id="c3_s37_draw_quadrant",
            failure_hint="Make sure the **Y:** axis dropdown is set to **APC-Cy7-A**, the CD8 detector.",
        ),
        InteractionStep(
            id="c3_s37_draw_quadrant",
            text=(
                "Click the **Quadrant** tool (highlighted), then click once on the "
                "plot where the CD4−/CD8− and CD4+/CD8+ boundaries should sit.<br><br>"
                + RIGHT_PANEL_HINT
            ),
            cyto_emotion="thinking",
            target_widget_names=["Tool_quadrant", "FlowCanvas", RIGHT_PANEL_TARGET],
            target_widget_name="MainPanel",
            event_trigger="gate_added_to_tree",
            metadata={"guide_quadrant": (5000.0, 5000.0)},
            next_step_id="c3_s37_draw_quadrant_verify",
            stuck_hint_text=(
                "Still there? Click the **Quadrant** tool, then click once where the "
                "CD4/CD8 boundaries should sit."
            ),
            stuck_hint_after_ms=45000,
        ),
        VerificationStep(
            id="c3_s37_draw_quadrant_verify",
            text="Karcytics is scanning automatically...",
            cyto_emotion="scanning",
            allow_interaction=False,
            hide_next_button=True,
            validator=c3_quadrant_validator,
            on_success_step_id="c3_s38_quadrant_naming_info",
            on_fail_step_id="c3_s37_quadrant_gate_retry",
        ),
        InfoStep(
            id="c3_s37_quadrant_gate_retry",
            text=(
                "That quadrant didn't quite hit the right spot!<br><br>"
                "I deleted it for you. Make sure the crosshair separates the CD4 and CD8 populations correctly (around 10^3 on both axes).<br><br>"
                "Try drawing it again."
            ),
            cyto_emotion="surprised",
            target_widget_names=["FlowCanvas"],
            metadata={"guide_quadrant": (5000.0, 5000.0)},
            next_step_id="c3_s37_draw_quadrant",
        ),
        QuestionStep(
            id="c3_s38_quadrant_naming_info",
            text=(
                "Quadrant naming ⚠️<br><br>"
                "Your 4 new leaves are named **Q1**–**Q4**. With X = **CD4** and "
                "Y = **CD8**, which quadrant holds CD4+ CD8− cells, the helper "
                "T cells?"
            ),
            question_id="c3_cd4_quadrant",
            choices=[
                AnswerChoice(
                    "Upper-left",
                    feedback="High on Y means CD8+. Upper-left is CD4− CD8+: the killer T cells.",
                ),
                AnswerChoice(
                    "Upper-right",
                    feedback="High on both is double positive (DP): young T cells, common in the thymus.",
                ),
                AnswerChoice("Lower-right", correct=True),
            ],
            explanation=(
                "The layout is fixed: Q1 upper-left = CD8+, Q2 upper-right = DP, "
                "Q3 lower-left = DN, Q4 lower-right = CD4+. Next you'll rename "
                "each leaf under T-cells in the Gating Hierarchy."
            ),
            cyto_emotion="thinking",
            allow_interaction=True,
            target_widget_names=["FlowCanvas", "GatingHierarchyScrollArea"],
            next_step_id="c3_s39_rename_quadrants",
        ),
        ForcedInteractionStep(
            id="c3_s39_rename_quadrants",
            text="Rename all 4 quadrant leaves so each subset is clearly labeled.",
            cyto_emotion="thinking",
            allow_interaction=True,
            target_widget_names=["GatingHierarchyScrollArea"],
            auto_advance_when_complete=True,
            stuck_hint_text=(
                "Still working on it? Right-click each quadrant leaf (Q1-Q4) in the "
                "hierarchy, choose **Rename Gate**, and type the label shown for it above."
            ),
            stuck_hint_after_ms=60000,
            sub_tasks=[
                SubTask(
                    id="rename_q4_cd4",
                    instruction=(
                        "Right-click 'Q4' (lower-right), choose 'Rename Gate', and type 'CD4+'."
                    ),
                    target_widget_name="GatingHierarchySampleView",
                    event_trigger="rename_requested",
                    validator=QuadrantPositionNamedValidator("Q4", "cd4+"),
                ),
                SubTask(
                    id="rename_q1_cd8",
                    instruction=(
                        "Right-click 'Q1' (upper-left), choose 'Rename Gate', and type 'CD8+'."
                    ),
                    target_widget_name="GatingHierarchySampleView",
                    event_trigger="rename_requested",
                    validator=QuadrantPositionNamedValidator("Q1", "cd8+"),
                ),
                SubTask(
                    id="rename_q2_dp",
                    instruction=(
                        "Right-click 'Q2' (upper-right), choose 'Rename Gate', and type 'DP'."
                    ),
                    target_widget_name="GatingHierarchySampleView",
                    event_trigger="rename_requested",
                    validator=QuadrantPositionNamedValidator("Q2", "dp"),
                ),
                SubTask(
                    id="rename_q3_dn",
                    instruction=(
                        "Right-click 'Q3' (lower-left), choose 'Rename Gate', and type 'DN'."
                    ),
                    target_widget_name="GatingHierarchySampleView",
                    event_trigger="rename_requested",
                    validator=QuadrantPositionNamedValidator("Q3", "dn"),
                ),
            ],
            next_step_id="c3_s40_quadrant_done",
        ),
        InfoStep(
            id="c3_s40_quadrant_done",
            text=(
                "Immunophenotyping complete! 🎉<br><br>"
                "**T-cells**, **B-cells**, and 4 CD4/CD8 subsets, all cleanly gated."
            ),
            cyto_emotion="happy",
            next_step_id="c3_s41_recap_transition",
        ),
        # ── Recap ────────────────────────────────────────────────────────────────
        InfoStep(
            id="c3_s41_recap_transition",
            text=(
                "Let's recap 📋<br><br>"
                "You've gated **T-cells** and **B-cells** out of **Leukocytes**, split "
                "T-cells into CD4+/CD8+/DP/DN, and learned to navigate the "
                "**Pipeline** view.<br><br>"
                "That's every population we need. Time to crack the case."
            ),
            cyto_emotion="talking",
            next_step_id="c3_s50_mystery_intro",
        ),
        # ── Finale: the tissue-ID mystery ────────────────────────────────────────
        InfoStep(
            id="c3_s50_mystery_intro",
            text=(
                "Welcome back! Incredible job. 🎉<br><br>"
                "You've gated **T-cells** and **B-cells** with two different techniques, "
                "split T-cells by CD4/CD8, and mastered the **Pipeline** view.<br><br>"
                "Before we call it: remember the opening mystery? Three "
                "unidentified samples — one **Thymus**, one **Bone Marrow**, one **Spleen**. "
                "You've actually already gathered enough evidence to form a real "
                "hypothesis. Let's think it through."
            ),
            cyto_emotion="cheering",
            next_step_id="c3_s50a2_verify_gating_tab",
        ),
        VerificationStep(
            id="c3_s50a2_verify_gating_tab",
            text="Click the **Gating** tab at the top — that's where the quick-stats grid lives.",
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["MainTabBar"],
            validator=TabActiveValidator(1),
            on_success_step_id="c3_s50b_quickstat_open",
        ),
        InteractionStep(
            id="c3_s50b_quickstat_open",
            text=(
                "One tool you haven't needed yet: click the **Quick-Stats** icon (⊞, "
                "highlighted) next to the **Auto-Propagate** toggle."
            ),
            target_widget_name="AllSamplesOverviewButton",
            target_widget_names=["AllSamplesOverviewButton"],
            event_trigger="clicked",
            cyto_emotion="pointing",
            next_step_id="c3_s50c_quickstat_info",
        ),
        InfoStep(
            id="c3_s50c_quickstat_info",
            text=(
                "That's the quick stats view 📊<br><br>"
                "Every population (rows) across every sample (columns), at a "
                "glance: **Cells**, **Live Cells**, **Leukocytes**, **T-cells**, "
                "**B-cells**, and your 4 CD4/CD8 subsets. Each cell is **% "
                "Parent**: its share of the gate above it.<br><br>"
                "Can't see Sample A, B, or C's column? Scroll — both "
                "horizontally and vertically — until you find it. Leave it "
                "open; we'll walk through it together."
            ),
            cyto_emotion="talking",
            allow_interaction=True,
            target_widget_names=["AllSamplesOverviewPopup"],
            next_step_id="c3_s51_mystery_sample_a",
        ),
        QuestionStep(
            id="c3_s51_mystery_sample_a",
            text=(
                "Case file: **Sample A** 🔬<br><br>"
                "Find Sample A's column and compare its **T-cells** and "
                "**B-cells**, each a share of Leukocytes. Which organ is it?"
            ),
            question_id="c3_sample_a_organ",
            choices=[
                AnswerChoice(
                    "Spleen",
                    feedback="The spleen holds plenty of both lineages. Sample A has almost no B cells.",
                ),
                AnswerChoice("Thymus", correct=True),
                AnswerChoice(
                    "Bone marrow",
                    feedback="Bone marrow makes B cells, so they'd be plentiful. Sample A's are close to zero.",
                ),
            ],
            explanation=(
                "The thymus is where T cells mature. B cells aren't made there, so they never show up in force."
            ),
            cyto_emotion="thinking",
            allow_interaction=True,
            target_widget_names=["AllSamplesOverviewPopup"],
            next_step_id="c3_s52_mystery_sample_b",
        ),
        QuestionStep(
            id="c3_s52_mystery_sample_b",
            text=(
                "Case file: **Sample B** 🤔<br><br>"
                "Now Sample B's column. How do its **T-cells** and **B-cells** "
                "compare? Which organ is it?"
            ),
            question_id="c3_sample_b_organ",
            choices=[
                AnswerChoice(
                    "Spleen",
                    feedback="The spleen has mature T cells too. Sample B has almost none.",
                ),
                AnswerChoice(
                    "Thymus",
                    feedback="The thymus is packed with T cells. Sample B has almost none.",
                ),
                AnswerChoice("Bone marrow", correct=True),
            ],
            explanation=(
                "B cells are made in the bone marrow. T cells leave it early and only mature later, in the thymus."
            ),
            cyto_emotion="thinking",
            allow_interaction=True,
            target_widget_names=["AllSamplesOverviewPopup"],
            next_step_id="c3_s53_mystery_sample_c",
        ),
        QuestionStep(
            id="c3_s53_mystery_sample_c",
            text=(
                "Case file: **Sample C** 🧩<br><br>"
                "Last, Sample C's column: solid shares of **both** T-cells and "
                "B-cells, plus all 4 CD4/CD8 subsets. Which organ is it?"
            ),
            question_id="c3_sample_c_organ",
            choices=[
                AnswerChoice("Spleen", correct=True),
                AnswerChoice(
                    "Thymus",
                    feedback="The thymus has very few B cells. Sample C has plenty.",
                ),
                AnswerChoice(
                    "Bone marrow",
                    feedback="Bone marrow has very few mature T cells. Sample C has plenty.",
                ),
            ],
            explanation=(
                "Mature B and T cells circulate together through the spleen, so both lineages show up side by side."
            ),
            cyto_emotion="thinking",
            allow_interaction=True,
            target_widget_names=["AllSamplesOverviewPopup"],
            next_step_id="c3_s53b_quickstat_close",
        ),
        VerificationStep(
            id="c3_s53b_quickstat_close",
            text=(
                "Once you're confident in what you're seeing, close the popup "
                "(press Esc, or click the × in its top-right corner) — I'll "
                "continue automatically."
            ),
            cyto_emotion="talking",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["AllSamplesOverviewPopup"],
            validator=PopupClosedValidator("AllSamplesOverviewPopup"),
            on_success_step_id="c3_s54_mystery_reveal",
            failure_hint="Press **Esc**, or click the **×** in the popup's top-right corner, to close it.",
        ),
        InfoStep(
            id="c3_s54_mystery_reveal",
            text=(
                "Your conclusion 🧠<br><br>"
                "• **Sample A** = **Thymus** (T-cells present, B-cells scarce)<br>"
                "• **Sample B** = **Bone Marrow** (B220+ present, T-cells scarce)<br>"
                "• **Sample C** = **Spleen** (both lineages present together)<br><br>"
                "Back in Course 1 you predicted the thymus would have very few: "
                "**{answer:c1_thymus_few}**. Sample A's B-cells are just 0.4% of "
                "its Leukocytes.<br><br>"
                "That's not a guess — it's a conclusion backed by gates you "
                "drew yourself and real stats you just read across every "
                "sample."
            ),
            cyto_emotion="happy",
            next_step_id="c3_s57_save_interaction",
        ),
        VerificationStep(
            id="c3_s57_save_interaction",
            text=(
                "Course 4 requires the gating and populations we just built. We need to save "
                "our progress.<br><br>"
                "Click the **⚠️ Save Workspace** button (highlighted) at the top right."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["WorkspaceSaveButton"],
            validator=WorkflowSavedValidator(),
            on_success_step_id="c3_s56_graduation",
            failure_hint="Click **⚠️ Save Workspace**, give it a name, and click Save to finish.",
        ),
        InfoStep(
            # The true end of Course 3 — no next_step_id, so
            # AcademyManager.next_step() treats this as course completion and
            # awards badge_reward the moment the user clicks Next. What's
            # next (Course 4) is already shown on the Academy catalog card,
            # so this doesn't need its own teaser steps the way it used to —
            # matches Course 1's compact one-step ending.
            id="c3_s56_graduation",
            text=(
                "Your workspace is updated!<br><br>Course 3 is complete — "
                "you're officially an **Immunophenotyper**! 🏆<br><br>"
                "See you in Course 4!"
            ),
            cyto_emotion="cheering",
            cyto_animation="cheering",
        ),
    ],
)
