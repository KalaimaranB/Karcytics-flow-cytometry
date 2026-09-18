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
    Course,
    ForcedInteractionStep,
    InfoStep,
    InteractionStep,
    SubTask,
    VerificationStep,
)

from .validators import (
    AxisChannelValidator,
    AxisYChannelValidator,
    Course1StateValidator,
    ExactSampleOpenValidator,
    GateActiveValidator,
    GateShapeValidator,
    LearningCompensationCompleteValidator,
    PipelineOrientationValidator,
    PopupClosedValidator,
    QuadrantPositionNamedValidator,
    SampleAndGateOpenValidator,
    TabActiveValidator,
    WorkflowSavedValidator,
)

# ==============================================================================
# Course 2 Gate Quality Validators & Routers
# ==============================================================================

c2_tcells_validator = GateShapeValidator(
    # Matches the on-canvas guide_rect=(-400.0, 2000.0, 300.0, 2000.0) drawn
    # for c2_s07_draw_tcell below. The old (-1000, 5000, 100, 10000) target
    # didn't match that guide box, though the ±10%-of-axis-range tolerance
    # happened to be wide enough that it never actually rejected a correctly
    # drawn gate here — realigned anyway so the guide box shown is always
    # exactly what gets validated (see c1_live_validator in course1.py for a
    # case where this same kind of mismatch WAS wide enough to matter).
    target_bounds=(-400.0, 2000.0, 300.0, 2000.0),
    target_name="T-cells",
    misnamed_retry_step_id="c2_s07_tcell_gate_misnamed",
    shape_retry_step_id="c2_s07_tcell_gate_retry",
)

c2_bcells_validator = GateShapeValidator(
    # Must match the on-canvas guide_range=(4000.0, 100000.0) drawn for
    # c2_s18_draw_bcell below — it previously said 262144.0 (the raw axis's
    # absolute max) here, so a gate drawn to trace the visible guide box
    # (topping out at 100000) fell far short of the required tolerance
    # window around 262144 and was wrongly rejected as a bad shape.
    target_bounds=(3000.0, 100000.0, 0.0, 0.0),
    target_name="B-cells",
    misnamed_retry_step_id="c2_s18_bcell_gate_misnamed",
    shape_retry_step_id="c2_s18_bcell_gate_retry",
)

c2_quadrant_validator = GateShapeValidator(
    target_bounds=(3000.0, 7000.0, 3000.0, 7000.0),
    target_name=None,
    # No naming step for a QuadrantGate (it auto-names Q1-Q4), so
    # misnamed_retry_step_id is never reached — GateShapeValidator only
    # diagnoses a name mismatch when target_name is set.
    shape_retry_step_id="c2_s37_quadrant_gate_retry",
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
# Course 2 — Immunophenotyping, Pipeline & Spectral Mastery
# Finale of the intro content: gate T-cells and B-cells out of Leukocytes,
# split T-cells into CD4/CD8 subsets, navigate the Pipeline view, and cover
# spectral/compensation theory.
# ==============================================================================

course_2_gating = Course(
    id="flow_course_2_gating",
    title="Immunophenotyping, Pipeline & Spectral Mastery",
    description=(
        "Identify T-cells and B-cells inside your Leukocytes, split T-cells into "
        "CD4/CD8 subsets, master the Pipeline view, and understand spillover and "
        "compensation theory."
    ),
    estimated_minutes=45,
    badge_reward="Immunophenotyper",
    badge_icon="🧬",
    prerequisite_course_ids=["flow_course_1_fundamentals"],
    steps=[
        # ── Checkpoint ───────────────────────────────────────────────────────
        VerificationStep(
            id="c2_s00_verify",
            validator=Course1StateValidator(),
            text=(
                "Checking your workspace...<br><br>"
                "Making sure all 10 samples are loaded, roles are assigned, and the "
                "base gates (**Cells** → **Live Cells** → **Leukocytes**) exist — confirming "
                "the Course 1 workflow was opened correctly."
            ),
            allow_interaction=False,
            cyto_emotion="thinking",
            next_step_id="c2_s01_intro",
            failure_hint=(
                "This course picks up where Course 1 left off — make sure you opened the "
                "workspace you saved at the end of Course 1, with all samples, roles, and "
                "the Cells → Live Cells → Leukocytes gates already built."
            ),
        ),
        InfoStep(
            id="c2_s01_intro",
            text=(
                "Welcome to Course 2! 🎯<br><br>"
                "Our **Leukocytes** are gated. Now let's identify who's actually inside "
                "that population: **T-cells** and **B-cells**, using two different gating "
                "techniques."
            ),
            cyto_emotion="happy",
            cyto_animation="cheering",
            next_step_id="c2_s01a_objectives",
        ),
        InfoStep(
            id="c2_s01a_objectives",
            text=(
                "What you'll walk away with 🎯<br><br>"
                "By the end of this course, you'll be able to:<br>"
                "• Gate the same population two different ways (2-marker "
                "scatter vs. histogram + FMO overlay) and know when to "
                "reach for each<br>"
                "• Split a population 4 ways at once with a **Quadrant** gate<br>"
                "• Read the **Pipeline** view the way a real gating strategy "
                "gets documented<br>"
                "• Explain spectral overlap, and when it actually needs "
                "careful compensation<br><br>"
                "And by the end, you'll have a confident, evidence-backed "
                "answer to the sample-ID mystery."
            ),
            cyto_emotion="talking",
            next_step_id="c2_s01c_verify_gating_tab",
        ),
        # Checks the tab FIRST — if the user is already on Gating (very
        # likely, arriving straight from Course 1), this passes immediately
        # instead of waiting on a currentChanged that will never fire.
        VerificationStep(
            id="c2_s01c_verify_gating_tab",
            text="Checking tab...",
            cyto_emotion="scanning",
            hide_next_button=True,
            allow_interaction=False,
            validator=TabActiveValidator(2),
            on_success_step_id="c2_s02_open_sample",
            on_fail_step_id="c2_s01b_gating_switch",
        ),
        InteractionStep(
            id="c2_s01b_gating_switch",
            text=(
                "Let's go find them — click the **Gating** tab at the top, "
                "that's where the drawing tools live."
            ),
            cyto_emotion="pointing",
            target_widget_name="MainTabBar",
            target_widget_names=["MainTabBar"],
            event_trigger="currentChanged",
            next_step_id="c2_s01c_verify_gating_tab",
        ),
        VerificationStep(
            id="c2_s02_open_sample",
            text="Double-click **Sample A** in the Data hierarchy to open it in a Graph Window.",
            validator=ExactSampleOpenValidator("sample a"),
            allow_interaction=True,
            cyto_emotion="pointing",
            target_widget_names=["SampleList"],
            on_success_step_id="c2_s03_tcell_intro",
            failure_hint="Make sure you double-clicked **Sample A** specifically in the Data hierarchy.",
        ),
        # ── T-cells (2-marker plot: B220 vs CD3) ────────────────────────────────
        InfoStep(
            id="c2_s03_tcell_intro",
            text=(
                "**Gate 1: T-cells (CD3+, B220−)** 🧬<br><br>"
                "**CD3** is the pan-T-cell marker and **B220** is the pan-B-cell marker — "
                "plotting them against each other separates both populations, and "
                "everything else, in one view.<br><br>"
                "We'll set X = B220 and Y = CD3, inside **Leukocytes**."
            ),
            cyto_emotion="talking",
            next_step_id="c2_s04_set_x",
        ),
        VerificationStep(
            id="c2_s04_set_x",
            text="Set the X axis to **FITC-A** — the B220 detector.",
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["AxisSelectorX"],
            validator=AxisChannelValidator("fitc"),
            on_success_step_id="c2_s05_set_y",
            failure_hint="Make sure the **X:** axis dropdown is set to **FITC-A**, the B220 detector.",
        ),
        VerificationStep(
            id="c2_s05_set_y",
            text="Now set the Y axis to **Pacific Blue-A** — the CD3 detector.",
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["AxisSelectorY"],
            validator=AxisYChannelValidator("pacific blue"),
            on_success_step_id="c2_s06_tcell_plot_read",
            failure_hint="Make sure the **Y:** axis dropdown is set to **Pacific Blue-A**, the CD3 detector.",
        ),
        InfoStep(
            id="c2_s06_tcell_plot_read",
            text=(
                "Reading the plot 🔍<br><br>"
                "**T-cells** are CD3+, B220− — high on the Y axis, low on the X axis "
                "(upper-left). Don't confuse them with the cluster in the "
                "bottom-left: that's CD3−, B220− — a 'double negative' population "
                "that's neither a T-cell nor a B-cell, and not what we're gating "
                "here.<br><br>"
                "As you draw the rectangle in the next step, watch the **Group "
                "Preview** thumbnails (bottom-right panel) update live — that's how "
                "the same gate looks across every other sample as you draw it."
            ),
            cyto_emotion="thinking",
            target_widget_names=["FlowCanvas", "GroupPreviewPanel"],
            next_step_id="c2_s07_draw_tcell",
        ),
        InteractionStep(
            id="c2_s07_draw_tcell",
            text=(
                "Draw the **T-cells** gate:<br><br>"
                "1. Select the **Rect** tool.<br>"
                "2. Draw a rectangle around the upper-left cluster — high CD3 "
                "(Y), low B220 (X).<br>"
                "3. Name it **T-cells**.<br><br>"
            ),
            cyto_emotion="pointing",
            target_widget_names=["Tool_rectangle", "FlowCanvas", "GroupPreviewPanel"],
            target_widget_name="FlowCanvas",
            event_trigger="gate_created",
            metadata={"guide_rect": (-400.0, 2000.0, 300.0, 2000.0)},
            next_step_id="c2_s07_draw_tcell_verify",
            stuck_hint_text=(
                "Still there? Click the **Rect** tool, then drag around the upper-left "
                "cluster (high CD3, low B220)."
            ),
            stuck_hint_after_ms=45000,
        ),
        VerificationStep(
            id="c2_s07_draw_tcell_verify",
            text="Karcytics is scanning automatically...",
            cyto_emotion="scanning",
            allow_interaction=False,
            hide_next_button=True,
            validator=c2_tcells_validator,
            on_success_step_id="c2_s08_tcell_done",
            on_fail_step_id="c2_s07_tcell_gate_retry",
        ),
        InfoStep(
            id="c2_s07_tcell_gate_misnamed",
            text="I renamed the gate to **T-cells** for you. Let's proceed!",
            cyto_emotion="happy",
            next_step_id="c2_s08_tcell_done",
        ),
        InfoStep(
            id="c2_s07_tcell_gate_retry",
            text=(
                "That gate didn't quite capture the right area!<br><br>"
                "I deleted it for you. Make sure your rectangle covers the upper-left cluster (CD3+, B220-).<br><br>"
                "Try drawing it again."
            ),
            cyto_emotion="surprised",
            target_widget_names=["FlowCanvas"],
            metadata={"guide_rect": (-400.0, 2000.0, 300.0, 2000.0)},
            next_step_id="c2_s07_draw_tcell",
        ),
        InfoStep(
            id="c2_s08_tcell_done",
            text=(
                "**T-cells** gated! ✅<br><br>"
                "Auto-Propagation just copied this gate to every other Full Panel "
                "sample in the group — Samples B and C already have it too."
            ),
            cyto_emotion="happy",
            next_step_id="c2_s09_switch_sample_intro",
        ),
        # ── B-cells (Histogram + FMO Overlay technique, on Sample C) ────────────
        InfoStep(
            id="c2_s09_switch_sample_intro",
            text=(
                "**Gate 2: B-cells (B220+)** 🎨<br><br>"
                "Sample A doesn't contain enough B-cells to comfortably gate — "
                "we need to switch to **Sample C** first.<br><br>"
                "There's a fast way to jump straight to a specific population on "
                "a different sample, instead of double-clicking and re-navigating "
                "the hierarchy by hand."
            ),
            cyto_emotion="talking",
            next_step_id="c2_s10_open_leuko_c",
        ),
        InteractionStep(
            id="c2_s10_open_leuko_c",
            text=(
                "In the Data hierarchy, right-click on **Sample C**, then click "
                "**Leukocytes** in the population menu that appears — this opens "
                "Sample C directly at that gate."
            ),
            target_widget_name="SampleList",
            target_widget_names=["SampleList"],
            event_trigger="population_open_requested",
            cyto_emotion="pointing",
            next_step_id="c2_s11_verify_leuko_c",
        ),
        VerificationStep(
            id="c2_s11_verify_leuko_c",
            text="Checking opened population...",
            cyto_emotion="scanning",
            hide_next_button=True,
            allow_interaction=False,
            validator=SampleAndGateOpenValidator("sample c", "leukocytes"),
            on_success_step_id="c2_s14_bcell_intro",
            on_fail_step_id="c2_s11b_wrong_pop",
        ),
        InteractionStep(
            id="c2_s11b_wrong_pop",
            text=(
                "Oops! Right-click **Sample C** specifically, and choose **Leukocytes** from its menu."
            ),
            cyto_emotion="surprised",
            target_widget_name="SampleList",
            target_widget_names=["SampleList"],
            event_trigger="population_open_requested",
            next_step_id="c2_s11_verify_leuko_c",
        ),
        InfoStep(
            id="c2_s14_bcell_intro",
            text=(
                "Notice the axes and the **T-cells** gate are already here — the "
                "'No-Jump' rule you learned in Course 1 locked B220 (X) and CD3 "
                "(Y) in for this group the moment you first set them on Sample A, "
                "and the gate itself propagated straight over.<br><br>"
                "This sample also has a clear B220+, CD3− population: real "
                "B-cells. But let's try something new: instead of another "
                "rectangle, we'll gate it with a **Histogram** and a live **FMO "
                "overlay**."
            ),
            cyto_emotion="talking",
            target_widget_names=["FlowCanvas"],
            next_step_id="c2_s15_histogram_mode",
        ),
        InteractionStep(
            id="c2_s15_histogram_mode",
            text=(
                "Switch the **Display Mode** dropdown (above the plot) from "
                "**Pseudocolor** to **Histogram**."
            ),
            target_widget_name="DisplayModeCombo",
            target_widget_names=["DisplayModeCombo"],
            event_trigger="activated",
            cyto_emotion="pointing",
            next_step_id="c2_s16_fmo_overlay",
        ),
        InteractionStep(
            id="c2_s16_fmo_overlay",
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
            next_step_id="c2_s17_threshold_info",
        ),
        InfoStep(
            id="c2_s17_threshold_info",
            text=(
                "Reading the overlay 📏<br><br>"
                "The gray population in the background is the FMO overlay — it's "
                "the negative signal for FITC. You'll see two distinct real "
                "populations: the left one overlaps the gray FMO (that's "
                "negative), the right one is your target **B-cells**.<br><br>"
                "The red dashed **99th %tile (Gate Threshold)** line is computed "
                "automatically from the FMO's distribution — 99% of true "
                "background sits to its left."
            ),
            cyto_emotion="talking",
            next_step_id="c2_s18_draw_bcell",
        ),
        InteractionStep(
            id="c2_s18_draw_bcell",
            text=(
                "Build a **Range** gate — the only gate type allowed on a histogram — "
                "to select the right-hand (positive) population:<br><br>"
                "Click and drag horizontally starting at (or just past) the red "
                "threshold line, capturing the bright B220+ peak.<br><br>"
                "Name the gate **B-cells**."
            ),
            cyto_emotion="pointing",
            target_widget_names=["Tool_range", "FlowCanvas"],
            target_widget_name="FlowCanvas",
            event_trigger="gate_created",
            metadata={"guide_range": (4000.0, 100000.0)},
            stuck_hint_text=(
                "Still there? Click the **Range** tool, then drag starting at the red "
                "threshold line across the bright B220+ peak."
            ),
            stuck_hint_after_ms=45000,
            next_step_id="c2_s18_draw_bcell_verify",
        ),
        VerificationStep(
            id="c2_s18_draw_bcell_verify",
            text="Checking...",
            cyto_emotion="scanning",
            allow_interaction=False,
            hide_next_button=True,
            validator=c2_bcells_validator,
            on_success_step_id="c2_s19_bcell_done",
            on_fail_step_id="c2_s18_bcell_gate_retry",
        ),
        InfoStep(
            id="c2_s18_bcell_gate_misnamed",
            text="I renamed the gate to **B-cells** for you. Let's proceed!",
            cyto_emotion="happy",
            next_step_id="c2_s19_bcell_done",
        ),
        InfoStep(
            id="c2_s18_bcell_gate_retry",
            text=(
                "That gate didn't quite capture the right range!<br><br>"
                "I deleted it for you. Make sure you start at the red threshold line and cover the bright B220+ peak.<br><br>"
                "Try drawing it again."
            ),
            cyto_emotion="surprised",
            target_widget_names=["FlowCanvas"],
            metadata={"guide_range": (4000.0, 100000.0)},
            next_step_id="c2_s18_draw_bcell",
        ),
        InfoStep(
            id="c2_s19_bcell_done",
            text=(
                "**B-cells** gated! ✅<br><br>"
                "Two different techniques, same rigor: both are anchored to their "
                "FMO control's true background, not a guess.<br><br>"
                "When to reach for which: a 2-marker scatter plot (like your "
                "**T-cells** gate) is fastest when two populations separate "
                "cleanly on two axes at once. A histogram + FMO overlay is "
                "better when you only have one marker to work with, or the "
                "positive/negative split is subtle enough that you want the "
                "FMO's exact threshold line rather than eyeballing a 2D "
                "boundary."
            ),
            cyto_emotion="happy",
            next_step_id="c2_s20_hierarchy_view",
        ),
        InfoStep(
            id="c2_s20_hierarchy_view",
            text=(
                "Scroll (if needed) in the **Gating Hierarchy** panel — you'll see "
                "**T-cells** and **B-cells** as sibling populations, both branching "
                "directly out of **Leukocytes**."
            ),
            cyto_emotion="talking",
            allow_interaction=True,
            target_widget_names=["GatingHierarchyScrollArea"],
            next_step_id="c2_s24_verify_pipeline_tab",
        ),
        # ── Pipeline mastery ─────────────────────────────────────────────────────
        VerificationStep(
            id="c2_s24_verify_pipeline_tab",
            text="Checking tab...",
            cyto_emotion="scanning",
            hide_next_button=True,
            allow_interaction=False,
            validator=TabActiveValidator(3),
            on_success_step_id="c2_s25_pipeline_read",
            on_fail_step_id="c2_s23_pipeline_switch",
        ),
        InteractionStep(
            id="c2_s23_pipeline_switch",
            text=(
                "Let's see your whole gating strategy at a glance — click "
                "the **Pipeline** tab at the top."
            ),
            cyto_emotion="pointing",
            target_widget_name="MainTabBar",
            target_widget_names=["MainTabBar"],
            event_trigger="currentChanged",
            next_step_id="c2_s24_verify_pipeline_tab",
        ),
        InfoStep(
            id="c2_s25_pipeline_read",
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
            next_step_id="c2_s26_orientation",
        ),
        VerificationStep(
            id="c2_s26_orientation",
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
            on_success_step_id="c2_s27_pipeline_explain",
            failure_hint="Make sure the **Layout:** dropdown in the Pipeline ribbon is set to **Horizontal**.",
        ),
        InfoStep(
            id="c2_s27_pipeline_explain",
            text=(
                "Getting around the canvas 🧭<br><br>"
                "You can freely drag any node to reposition it. "
                "To pan the whole canvas, hold the "
                "middle mouse button and drag.<br><br>"
                "The **+ AND** / **+ OR** / **+ NOT** buttons build boolean logic nodes "
                "that combine populations — we'll put those to real use in "
                "Course 3."
            ),
            cyto_emotion="talking",
            target_widget_names=["PipelineCanvas"],
            next_step_id="c2_s29_verify_gating_tab",
        ),
        VerificationStep(
            id="c2_s29_verify_gating_tab",
            text="Checking tab...",
            cyto_emotion="scanning",
            hide_next_button=True,
            allow_interaction=False,
            validator=TabActiveValidator(2),
            on_success_step_id="c2_s30_reenter_tcells_intro",
            on_fail_step_id="c2_s28_gating_switch",
        ),
        InteractionStep(
            id="c2_s28_gating_switch",
            text=("Time for one more split — click the **Gating** tab at the top to head back."),
            cyto_emotion="pointing",
            target_widget_name="MainTabBar",
            target_widget_names=["MainTabBar"],
            event_trigger="currentChanged",
            next_step_id="c2_s29_verify_gating_tab",
        ),
        # ── CD4/CD8 quadrant split (still on Sample C) ──────────────────────────
        InfoStep(
            id="c2_s30_reenter_tcells_intro",
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
            next_step_id="c2_s31_dblclick_tcells",
        ),
        InteractionStep(
            id="c2_s31_dblclick_tcells",
            text=(
                "In the **Gating Hierarchy** panel, double-click **T-cells** to make it "
                "the active population."
            ),
            target_widget_name="GatingHierarchyView",
            target_widget_names=["GatingHierarchyView"],
            event_trigger="gate_double_clicked",
            cyto_emotion="pointing",
            next_step_id="c2_s32_verify_tcells_active",
        ),
        VerificationStep(
            id="c2_s32_verify_tcells_active",
            text="Checking active population...",
            cyto_emotion="scanning",
            hide_next_button=True,
            allow_interaction=False,
            validator=GateActiveValidator("t-cells"),
            on_success_step_id="c2_s33_quadrant_intro",
            on_fail_step_id="c2_s32b_wrong_node",
        ),
        InteractionStep(
            id="c2_s32b_wrong_node",
            text="Oops! Double-click **T-cells** specifically in the hierarchy.",
            cyto_emotion="surprised",
            target_widget_name="GatingHierarchyView",
            target_widget_names=["GatingHierarchyView"],
            event_trigger="gate_double_clicked",
            next_step_id="c2_s32_verify_tcells_active",
        ),
        InfoStep(
            id="c2_s33_quadrant_intro",
            text=(
                "Splitting **T-cells** by CD4/CD8 ✂️<br><br>"
                "**CD4+** helpers, **CD8+** killers, and — in some tissues — cells that "
                "are BOTH CD4+ and CD8+ ('Double Positive', **DP**), or neither "
                "('Double Negative', **DN**). A single **Quadrant** gate splits a plot "
                "into all 4 regions at once."
            ),
            cyto_emotion="thinking",
            next_step_id="c2_s35_set_x_cd4",
        ),
        VerificationStep(
            id="c2_s35_set_x_cd4",
            text="Set the X axis to **PE-A** — the CD4 detector.",
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["AxisSelectorX"],
            validator=AxisChannelValidator("pe-a"),
            on_success_step_id="c2_s36_set_y_cd8",
            failure_hint="Make sure the **X:** axis dropdown is set to **PE-A**, the CD4 detector.",
        ),
        VerificationStep(
            id="c2_s36_set_y_cd8",
            text="Set the Y axis to **APC-Cy7-A** — the CD8 detector.",
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["AxisSelectorY"],
            validator=AxisYChannelValidator("apc-cy7"),
            on_success_step_id="c2_s37_draw_quadrant",
            failure_hint="Make sure the **Y:** axis dropdown is set to **APC-Cy7-A**, the CD8 detector.",
        ),
        InteractionStep(
            id="c2_s37_draw_quadrant",
            text=(
                "Click the **Quadrant** tool (highlighted), then click once on the "
                "plot where the CD4−/CD8− and CD4+/CD8+ boundaries should sit.<br><br>"
            ),
            cyto_emotion="thinking",
            target_widget_names=["Tool_quadrant", "FlowCanvas"],
            target_widget_name="FlowCanvas",
            event_trigger="gate_created",
            metadata={"guide_quadrant": (5000.0, 5000.0)},
            next_step_id="c2_s37_draw_quadrant_verify",
            stuck_hint_text=(
                "Still there? Click the **Quadrant** tool, then click once where the "
                "CD4/CD8 boundaries should sit."
            ),
            stuck_hint_after_ms=45000,
        ),
        VerificationStep(
            id="c2_s37_draw_quadrant_verify",
            text="Karcytics is scanning automatically...",
            cyto_emotion="scanning",
            allow_interaction=False,
            hide_next_button=True,
            validator=c2_quadrant_validator,
            on_success_step_id="c2_s38_quadrant_naming_info",
            on_fail_step_id="c2_s37_quadrant_gate_retry",
        ),
        InfoStep(
            id="c2_s37_quadrant_gate_retry",
            text=(
                "That quadrant didn't quite hit the right spot!<br><br>"
                "I deleted it for you. Make sure the crosshair separates the CD4 and CD8 populations correctly (around 10^3 on both axes).<br><br>"
                "Try drawing it again."
            ),
            cyto_emotion="surprised",
            target_widget_names=["FlowCanvas"],
            metadata={"guide_quadrant": (5000.0, 5000.0)},
            next_step_id="c2_s37_draw_quadrant",
        ),
        InfoStep(
            id="c2_s38_quadrant_naming_info",
            text=(
                "Behind the Scenes: Quadrant Naming ⚠️<br><br>"
                "The 4 new leaves in your Gating Hierarchy are named **Q1**–**Q4**."
                "With X=CD4, Y=CD8, the geometry is fixed:<br>"
                "• **Q1** (upper-left) = CD4− CD8+ → **CD8+**<br>"
                "• **Q2** (upper-right) = CD4+ CD8+ → **DP**<br>"
                "• **Q3** (lower-left) = CD4− CD8− → **DN**<br>"
                "• **Q4** (lower-right) = CD4+ CD8− → **CD4+**<br><br>"
                "We will right-click each leaf in the Gating Hierarchy and choose **Rename "
                "Gate** in the next step — scroll down in that panel if you need to, the 4 new "
                "leaves are nested under T-cells."
            ),
            cyto_emotion="talking",
            target_widget_names=["GatingHierarchyScrollArea"],
            next_step_id="c2_s39_rename_quadrants",
        ),
        ForcedInteractionStep(
            id="c2_s39_rename_quadrants",
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
            next_step_id="c2_s40_quadrant_done",
        ),
        InfoStep(
            id="c2_s40_quadrant_done",
            text=(
                "Immunophenotyping complete! 🎉<br><br>"
                "**T-cells**, **B-cells**, and 4 CD4/CD8 subsets, all cleanly gated."
            ),
            cyto_emotion="happy",
            next_step_id="c2_s41_recap_transition",
        ),
        # ── Spectral theory ──────────────────────────────────────────────────────
        InfoStep(
            id="c2_s41_recap_transition",
            text=(
                "Let's recap 📋<br><br>"
                "You've gated **T-cells** and **B-cells** out of **Leukocytes**, split "
                "T-cells into CD4+/CD8+/DP/DN, and learned to navigate the "
                "**Pipeline** view.<br><br>"
                "One thing we haven't touched yet: WHY these markers don't "
                "interfere with each other on the detector side. Let's look at "
                "the **Spectral** tab."
            ),
            cyto_emotion="talking",
            next_step_id="c2_s43_verify_spectral_tab",
        ),
        VerificationStep(
            id="c2_s43_verify_spectral_tab",
            text="Checking tab...",
            cyto_emotion="scanning",
            hide_next_button=True,
            allow_interaction=False,
            validator=TabActiveValidator(5),
            on_success_step_id="c2_s44_spectral_intro",
            on_fail_step_id="c2_s42_spectral_switch",
        ),
        InteractionStep(
            id="c2_s42_spectral_switch",
            text="Let's go find out why — click the **Spectral** tab at the top.",
            cyto_emotion="pointing",
            target_widget_name="MainTabBar",
            target_widget_names=["MainTabBar"],
            event_trigger="currentChanged",
            next_step_id="c2_s43_verify_spectral_tab",
        ),
        InfoStep(
            id="c2_s44_spectral_intro",
            text=(
                "The **Spectral Viewer** 🌈<br><br>"
                "Every curve here is pulled live from **FPbase** — an open, "
                "community-maintained online database of real fluorescent "
                "protein and dye spectra (fpbase.org). This isn't simulated data; "
                "it's the actual physics of the dyes in your panel."
            ),
            cyto_emotion="talking",
            target_widget_names=["SpectralPlotArea"],
            next_step_id="c2_s45_load_six",
        ),
        InfoStep(
            id="c2_s45_load_six",
            text=(
                "Karcytics already detected all 6 of your panel's markers (CD45, "
                "CD3, CD4, CD8, B220, PI) from the FCS channel headers and "
                "plotted every one of their spectra automatically — no need to "
                "add them by hand.<br><br>"
                "(You can still double-click any channel in **Available "
                "Channels** to add others, or click a spectrum's legend entry "
                "to remove it.)"
            ),
            cyto_emotion="happy",
            target_widget_names=["SpectralSourceList"],
            next_step_id="c2_s46_ab_ex_em_info",
        ),
        InfoStep(
            id="c2_s46_ab_ex_em_info",
            text=(
                "Reading AB / EX / EM 🔬<br><br>"
                "• **AB** (Absorbance) — the wavelengths the dye physically absorbs. "
                "Mostly a chemistry detail.<br>"
                "• **EX** (Excitation) — the wavelengths that make the dye 'light "
                "up'. This tells you which laser to use (e.g. the 488 nm Blue "
                "laser).<br>"
                "• **EM** (Emission) — the wavelengths the dye shoots back out. This "
                "tells you which detector captures the signal.<br><br>"
                "Toggle the **AB / EX / EM** buttons above the plot to see each "
                "curve set on its own."
            ),
            cyto_emotion="talking",
            target_widget_names=["SpectralABToggle", "SpectralEXToggle", "SpectralEMToggle"],
            next_step_id="c2_s47_overlap_theory",
        ),
        InfoStep(
            id="c2_s47_overlap_theory",
            text=(
                "Overlap isn't automatically a problem 🧠<br><br>"
                "Hover between two EM curves to see an **Overlap integral %**. "
                "CD3 (Pacific Blue) and B220 (FITC) may overlap somewhat, but "
                "it's harmless: a cell is essentially never both a T-cell and a "
                "B-cell, so spillover between those two channels can't create a "
                "biologically confusing double-positive population.<br><br>"
                "CD4 (PE) and CD8 (APC-Cy7) overlap matters more — thymocytes "
                "really can co-express both, which is exactly the **DP** population "
                "you just gated. Overlap between markers that CAN legitimately "
                "co-occur needs careful compensation; overlap between markers on "
                "mutually-exclusive lineages usually doesn't."
            ),
            cyto_emotion="thinking",
            target_widget_names=["SpectralPlotArea"],
            next_step_id="c2_s48_learning_switch",
        ),
        InteractionStep(
            id="c2_s48_learning_switch",
            text=(
                "Let's put the theory into practice — click the **Learning "
                "Compensation** sub-tab inside this viewer."
            ),
            target_widget_name="SpectralTabs",
            target_widget_names=["SpectralTabs"],
            event_trigger="currentChanged",
            cyto_emotion="pointing",
            next_step_id="c2_s49_slideshow",
        ),
        VerificationStep(
            id="c2_s49_slideshow",
            text=(
                "The **Compensation Masterclass**<br><br>"
                "I'll step back and let you work through this interactive "
                "slideshow at your own pace — it walks through spillover, single-"
                "stain controls, and matrix inversion using REAL numbers measured "
                "from the dyes you just loaded, not textbook examples.<br><br>"
                "The final slide asks you to reason through which control tubes "
                "you'd actually need to run to build a real compensation matrix. "
                "I'll find you again once you've worked through it!"
            ),
            validator=LearningCompensationCompleteValidator(),
            allow_interaction=True,
            hide_next_button=True,
            manual_dismiss_bubble=True,
            cyto_emotion="thinking",
            target_widget_names=["SpectralLearningTab"],
            on_success_step_id="c2_s50_mystery_intro",
            failure_hint="Take your time working through the slideshow — I'll continue once you reach the final slide.",
            stuck_hint_after_ms=120000,
        ),
        # ── Finale: the tissue-ID mystery ────────────────────────────────────────
        InfoStep(
            id="c2_s50_mystery_intro",
            text=(
                "Welcome back! Incredible job. 🎉<br><br>"
                "You've gated **T-cells** and **B-cells** with two different techniques, "
                "split T-cells by CD4/CD8, mastered the **Pipeline** view, and "
                "understand exactly why and when spillover matters.<br><br>"
                "Before we call it: remember the opening mystery? Three "
                "unidentified samples — one **Thymus**, one **Bone Marrow**, one **Spleen**. "
                "You've actually already gathered enough evidence to form a real "
                "hypothesis. Let's think it through."
            ),
            cyto_emotion="cheering",
            next_step_id="c2_s50a2_verify_gating_tab",
        ),
        VerificationStep(
            id="c2_s50a2_verify_gating_tab",
            text="Checking tab...",
            cyto_emotion="scanning",
            hide_next_button=True,
            allow_interaction=False,
            validator=TabActiveValidator(2),
            on_success_step_id="c2_s50b_quickstat_open",
            on_fail_step_id="c2_s50a_gating_switch",
        ),
        InteractionStep(
            id="c2_s50a_gating_switch",
            text="Click the **Gating** tab at the top — that's where the quick-stats grid lives.",
            cyto_emotion="pointing",
            target_widget_name="MainTabBar",
            target_widget_names=["MainTabBar"],
            event_trigger="currentChanged",
            next_step_id="c2_s50a2_verify_gating_tab",
        ),
        InteractionStep(
            id="c2_s50b_quickstat_open",
            text=(
                "One tool you haven't needed yet: click the **Quick-Stats** icon (⊞, "
                "highlighted) next to the **Auto-Propagate** toggle."
            ),
            target_widget_name="AllSamplesOverviewButton",
            target_widget_names=["AllSamplesOverviewButton"],
            event_trigger="clicked",
            cyto_emotion="pointing",
            next_step_id="c2_s50c_quickstat_info",
        ),
        InfoStep(
            id="c2_s50c_quickstat_info",
            text=(
                "That's the quick stats view 📊<br><br>"
                "Every population's counts across every sample, at a glance — "
                "**Cells**, **Live Cells**, **Leukocytes**, **T-cells**, **B-cells**, and your 4 "
                "CD4/CD8 subsets, all in one grid.<br><br>"
                "Can't see Sample A, B, or C's row? Scroll — both horizontally "
                "and vertically — until you find it. Leave it open; we'll walk "
                "through it together."
            ),
            cyto_emotion="talking",
            allow_interaction=True,
            target_widget_names=["AllSamplesOverviewPopup"],
            next_step_id="c2_s51_mystery_sample_a",
        ),
        InfoStep(
            id="c2_s51_mystery_sample_a",
            text=(
                "**Sample A**: T-cells, but barely any B-cells 🔬<br><br>"
                "Find Sample A's row. Its **T-cells** % Total is high, and its "
                "**B-cells** % Total is close to zero — matching what you saw "
                "hands-on: a clean T-cell population on the B220 vs CD3 plot, "
                "and not enough B-cells there to comfortably gate.<br><br>"
                "Abundant T-cells with scarce B-cells is exactly the signature "
                "of the one organ that *makes* T-cells: the **Thymus**. B-cells "
                "aren't produced there, so they're never expected in force."
            ),
            cyto_emotion="thinking",
            allow_interaction=True,
            target_widget_names=["AllSamplesOverviewPopup"],
            next_step_id="c2_s52_mystery_sample_b",
        ),
        InfoStep(
            id="c2_s52_mystery_sample_b",
            text=(
                "What about **Sample B**? 🤔<br><br>"
                "You opened Sample B briefly back in Course 1, just to see the "
                "CD45+ leukocyte cluster — but never dug into its T-cell/B-cell "
                "split. Find its row here: almost no T-cells, but a solid "
                "B220+ population.<br><br>"
                "An organ producing B-cells while having next to no mature "
                "T-cells points to the **Bone Marrow** — B-lymphopoiesis happens "
                "there, while T-cells don't mature until they migrate on to the "
                "Thymus."
            ),
            cyto_emotion="thinking",
            allow_interaction=True,
            target_widget_names=["AllSamplesOverviewPopup"],
            next_step_id="c2_s53_mystery_sample_c",
        ),
        InfoStep(
            id="c2_s53_mystery_sample_c",
            text=(
                "And **Sample C**: a bit of everything 🧩<br><br>"
                "Find Sample C's row: solid % Total for BOTH T-cells and "
                "B-cells, plus healthy counts across all 4 CD4/CD8 subsets — "
                "everything you gated by hand this course, now confirmed in "
                "the numbers.<br><br>"
                "Mature populations of BOTH lineages, side by side, points to a "
                "peripheral organ where B- and T-cells circulate together: the "
                "**Spleen**."
            ),
            cyto_emotion="thinking",
            allow_interaction=True,
            target_widget_names=["AllSamplesOverviewPopup"],
            next_step_id="c2_s53b_quickstat_close",
        ),
        VerificationStep(
            id="c2_s53b_quickstat_close",
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
            on_success_step_id="c2_s54_mystery_reveal",
            failure_hint="Press **Esc**, or click the **×** in the popup's top-right corner, to close it.",
        ),
        InfoStep(
            id="c2_s54_mystery_reveal",
            text=(
                "Your conclusion 🧠<br><br>"
                "• **Sample A** = **Thymus** (T-cells present, B-cells scarce)<br>"
                "• **Sample B** = **Bone Marrow** (B220+ present, T-cells scarce)<br>"
                "• **Sample C** = **Spleen** (both lineages present together)<br><br>"
                "That's not a guess — it's a conclusion backed by gates you "
                "drew yourself and real stats you just read across every "
                "sample."
            ),
            cyto_emotion="happy",
            next_step_id="c2_s57_save_interaction",
        ),
        VerificationStep(
            id="c2_s57_save_interaction",
            text=(
                "Course 3 requires the gating and populations we just built. We need to save "
                "our progress.<br><br>"
                "Click the **⚠️ Save Workspace** button (highlighted) at the top right."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["WorkspaceSaveButton"],
            validator=WorkflowSavedValidator(),
            on_success_step_id="c2_s56_graduation",
            failure_hint="Click **⚠️ Save Workspace**, give it a name, and click Save to finish.",
        ),
        InfoStep(
            id="c2_s56_graduation",
            text=(
                "Your workspace is updated!<br><br>Course 2 is complete — you're officially an **Immunophenotyper**! 🏆"
            ),
            cyto_emotion="cheering",
            cyto_animation="cheering",
            next_step_id="c2_s55_course3_teaser",
        ),
        InfoStep(
            id="c2_s55_course3_teaser",
            text=(
                "Course 3 goes deeper 🔬<br><br>"
                "In Course 3 you'll build on this result with real statistics, "
                "chart every population across all three samples in five "
                "different ways, and let **UMAP + HDBSCAN** independently cluster "
                "the raw data with zero manual gating — extra rigor on top of "
                "what you've already nailed."
            ),
            cyto_emotion="pointing",
            next_step_id="c2_s58_outro",
        ),
        InfoStep(
            id="c2_s58_outro",
            text=("See you in Course 3!"),
            cyto_emotion="happy",
            cyto_animation="cheering",
        ),
    ],
)
