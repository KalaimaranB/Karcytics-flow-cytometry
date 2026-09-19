"""Karcytics Flow Cytometry — Academy Courses.

Step conventions:
  InfoStep           — teaches a concept; user clicks Next → to continue.
  InteractionStep    — user must click/interact with a named widget to auto-advance.
  VerificationStep   — auto-polls a validator every ~2 s and advances automatically.
                       Set allow_interaction=True only if the user also needs to freely
                       interact with the UI before clicking the manual 'Check ✓' button.

Spotlight convention:
  target_widget_name  — single objectName for InteractionStep highlight.
  target_widget_names — list of objectNames for multi-target InfoStep spotlights.
"""

from karcytics_sdk.plugin.tutorial_models import (
    ActionStep,
    BranchingStep,  # noqa: F401
    ConsentStep,
    Course,
    ForcedInteractionStep,  # noqa: F401
    InfoStep,
    InteractionStep,
    SubTask,  # noqa: F401
    VerificationStep,
)

from .tutorial_assets import start_provisioning
from .validators import (
    AxisChannelValidator,
    AxisOutlierValidator,
    ExactSampleOpenValidator,
    FlowImportValidator,
    FmoRoleValidator,
    GateShapeValidator,
    RoleAssignmentValidator,
    SampleOpenValidator,
    SingleStainRoleValidator,
    SpecificSampleOpenValidator,
    TabActiveValidator,
    TutorialFilesProvisionedValidator,
    UnstainedRoleValidator,
    WorkflowSavedValidator,
)

# ==============================================================================
# Course 1 Gate Quality Validators & Routers
# ==============================================================================

c1_cells_validator = GateShapeValidator(
    target_bounds=(8000.0, 248000.0, 500.0, 38000.0),
    target_poly=[
        (8000, 38000),
        (248000, 34000),
        (248000, 500),
        (8000, 1000),
    ],
    target_name="Cells",
    misnamed_retry_step_id="c1_s24_cells_gate_misnamed",
    shape_retry_step_id="c1_s24_cells_gate_retry",
)

c1_live_validator = GateShapeValidator(
    # Must match the on-canvas guide_range=(-1000.0, 10000.0) drawn for
    # c1_s27f_draw_live_gate below — it previously said 50000.0 here, so a
    # gate drawn to exactly trace the dotted guide box the user is shown
    # (topping out at 10000) fell short of this validator's ±10%-of-axis-
    # range tolerance window around 50000 and was wrongly rejected as a
    # bad shape even when perfectly, correctly drawn.
    target_bounds=(-1000.0, 10000.0, 0.0, 0.0),
    target_name="Live Cells",
    misnamed_retry_step_id="c1_s27f_live_gate_misnamed",
    shape_retry_step_id="c1_s27f_live_gate_retry",
)

c1_leukocytes_validator = GateShapeValidator(
    target_bounds=(2000.0, 200000.0, 500.0, 37000.0),
    target_name="Leukocytes",
    misnamed_retry_step_id="c1_s30h_leukocytes_gate_misnamed",
    shape_retry_step_id="c1_s30h_leukocytes_gate_retry",
)

c1_import_validator = FlowImportValidator()


def route_import_failure(
    panel, validator, step_id, incorrect_next_id, too_few_next_id, default_next_id
):
    current_step = next((s for s in course_1_fundamentals.steps if s.id == step_id), None)
    incorrect_step = next(
        (s for s in course_1_fundamentals.steps if s.id == incorrect_next_id), None
    )

    if validator.incorrect_sample_ids:
        from karcytics_sdk.plugin import CentralEventBus

        from karcytics_plugins.flow_cytometry.analysis import events

        changed = False
        for sid in validator.incorrect_sample_ids:
            if sid in panel.state.data.experiment.samples:
                panel.state.data.experiment.remove_sample(sid)
                changed = True
        if changed:
            CentralEventBus.publish(events.EXPERIMENT_DATA_CHANGED, {"source": "Tutorial"})
            CentralEventBus.publish(events.SAMPLE_UPDATED, {"source": "Tutorial"})
            CentralEventBus.publish(events.SAMPLE_LOADED, {"source": "Tutorial"})

        remaining_count = len(panel.state.data.experiment.samples)
        if incorrect_step:
            if remaining_count < 10:  # noqa: PLR2004
                incorrect_step.next_step_id = "c1_s2_import"
                incorrect_step.text = (
                    "Oops — you've loaded an incorrect sample that doesn't belong in this tutorial.<br><br>"
                    "I've automatically removed it for you! Since we still don't have all 10 required files, let's load the rest."
                )
            else:
                incorrect_step.next_step_id = "c1_s3_verify_import"
                incorrect_step.text = (
                    "Oops — you've loaded an incorrect sample that doesn't belong in this tutorial.<br><br>"
                    "I've automatically removed it for you! Let's continue."
                )

        if current_step:
            current_step.next_step_id = incorrect_next_id
            current_step.text = "Removing incorrect samples..."
    elif getattr(validator, "too_few", False):
        if current_step:
            current_step.next_step_id = too_few_next_id
            current_step.text = "Analyzing sample count..."
    elif current_step:
        current_step.next_step_id = default_next_id
        current_step.text = "Analyzing sample count..."


# ==============================================================================
# Course 1 — Flow Cytometry Fundamentals
#
# Gate-drawing steps (Cells / Live Cells / Leukocytes below) no longer wire
# their own ActionStep-based failure routing: `c1_cells_validator` /
# `c1_live_validator` / `c1_leukocytes_validator` above implement
# `GateShapeValidator.describe_failure()`, and `AcademyStepDriver` (SDK)
# calls it automatically on a failed VerificationStep — showing the
# explanation banner, auto-renaming/deleting the gate, and routing to the
# validator's own `misnamed_retry_step_id`/`shape_retry_step_id` in one
# generic path shared by every course that uses `GateShapeValidator`.
# Three phases: Setup → Compensation → Gating
# ==============================================================================

# Held as a variable (rather than built inline in the steps list below) so
# `_set_import_step_text` can mutate its `.text` in place once provisioning
# finishes and we actually know where the files ended up — Downloads or
# already in the project's own assets folder. The Downloads phrasing here is
# just the fallback shown until that ActionStep runs.
_import_step = InteractionStep(
    id="c1_s2_import",
    text=(
        "Let's get your files in. Click **➕ Add Samples** (highlighted) "
        "to open the file picker — your 10 tutorial files are "
        "waiting in Downloads → **Karcytics CytoAcademy Flow Files**. "
        "Select all 10."
    ),
    target_widget_names=["ImportDataButton"],
    target_widget_name="WorkspaceRibbon",
    event_trigger="samples_loaded",
    cyto_emotion="pointing",
    next_step_id="c1_s3_verify_import",
)


def _set_import_step_text(_panel) -> None:  # noqa: ANN001
    """ActionStep callback: fills in `_import_step.text` with the real
    location the tutorial files were found/downloaded to, resolved by the
    preceding provisioning step (see `tutorial_assets.ensure_tutorial_files`).
    """
    from .tutorial_assets import describe_files_location

    _import_step.text = (
        "Let's get your files in. Click **➕ Add Samples** (highlighted) "
        f"to open the file picker — {describe_files_location()}. Select all 10."
    )


# Held as a variable for the same reason as `_import_step` above: its
# validator calls back into `_provisioning_step.text = ...` on every poll so
# the bubble shows live "3/10 files done" progress instead of a single
# static "may take a minute" message for the whole download — previously
# that progress only ever showed up in the log, never in the UI.
_provisioning_step: VerificationStep = VerificationStep(
    id="c1_s1d_provisioning_wait",
    text=(
        "Getting your 10 tutorial files ready 📂<br><br>"
        "If they're already on this computer, this is instant. "
        "Otherwise Karcytics is downloading them now from the "
        "tutorial dataset (~100MB) — this only happens once, and "
        "may take a minute on a slower connection."
    ),
    cyto_emotion="scanning",
    cyto_animation="scanning",
    allow_interaction=False,
    hide_next_button=True,
    validator=TutorialFilesProvisionedValidator(
        on_progress=lambda text: setattr(_provisioning_step, "text", text)
    ),
    on_success_step_id="c1_s1e_set_import_text",
    failure_hint="Still downloading the tutorial files — this can take about a minute on a slower connection.",
)


course_1_fundamentals = Course(
    id="flow_course_1_fundamentals",
    title="Flow Cytometry Fundamentals",
    description=(
        "Your samples just arrived. We'll set up the experiment, "
        "clean the data with compensation, and gate our cell populations."
    ),
    estimated_minutes=50,
    badge_reward="Flow Fundamentalist",
    badge_icon="🔬",
    prerequisite_course_ids=[],
    steps=[
        # ── Intro ────────────────────────────────────────────────────────────
        InfoStep(
            id="c1_s1_intro",
            text=(
                "Welcome to Karcytics Flow Cytometry! 🧬<br><br>"
                "Today's mystery: 3 unknown samples — one is Spleen, one is "
                "Thymus, one is Bone Marrow. Immune cells look different "
                "from organ to organ, and by the end of Course 2 you'll "
                "have a confident, evidence-based answer for which is "
                "which. (Course 3 goes even deeper if you want it — but "
                "it's not required to crack the case.)<br><br>"
                "Let's start by loading our files."
            ),
            cyto_emotion="happy",
            cyto_animation="cheering",
            next_step_id="c1_s1b_objectives",
        ),
        InfoStep(
            id="c1_s1b_objectives",
            text=(
                "What you'll walk away with 🎯<br><br>"
                "By the end of this course, you'll be able to:<br>"
                "• Import raw FCS files and correctly tag every tube's role<br>"
                "• Explain why compensation is necessary, and apply a "
                "spillover matrix<br>"
                "• Build a real gating hierarchy (Cells → Live → "
                "Leukocytes) from scatter and viability data<br>"
                "• Use an FMO control to place an evidence-based gate "
                "boundary instead of guessing<br><br>"
                "These are the exact skills you'd use on a real "
                "cytometer — tutorial or not."
            ),
            cyto_emotion="talking",
            next_step_id="c1_s1c_ask_provision",
        ),
        # ── Phase 1 — Setup (Import & Roles) ─────────────────────────────────
        ConsentStep(
            id="c1_s1c_ask_provision",
            text=(
                "Do you need to download the tutorial dataset files?<br><br>"
                "If you haven't downloaded them yet, I can fetch them for you now (~100MB). "
                "If you already have them, you can skip this step."
            ),
            accept_text="Download Files",
            decline_text="Skip",
            on_accept_step_id="c1_s1c_provision_files",
            on_decline_step_id="c1_s1e_set_import_text",
            cyto_emotion="talking",
        ),
        ActionStep(
            id="c1_s1c_provision_files",
            text="Preparing your tutorial files...",
            action=start_provisioning,
            next_step_id="c1_s1d_provisioning_wait",
        ),
        _provisioning_step,
        ActionStep(
            id="c1_s1e_set_import_text",
            text="Locating your files...",
            action=_set_import_step_text,
            next_step_id="c1_s2_import",
        ),
        _import_step,
        VerificationStep(
            id="c1_s3_verify_import",
            text="Scanning files — checking all 10 samples loaded correctly…",
            cyto_emotion="scanning",
            cyto_animation="scanning",
            validator=c1_import_validator,
            on_success_step_id="c1_s3b_groups_intro",
            on_fail_step_id="c1_s3_fail",
            max_retries=3,
            allow_interaction=False,
            target_widget_names=["ImportDataButton"],
        ),
        ActionStep(
            id="c1_s3_fail",
            text="Checking what went wrong...",
            action=lambda panel: route_import_failure(
                panel,
                c1_import_validator,
                "c1_s3_fail",
                "c1_s3_fail_incorrect",
                "c1_s3_fail_too_few",
                "c1_s2_import",
            ),
            next_step_id="c1_s2_import",
        ),
        InfoStep(
            id="c1_s3_fail_incorrect",
            text=(
                "Oops — you've loaded an incorrect sample that doesn't belong in this tutorial.<br><br>"
                "I've automatically removed it for you! Let's continue."
            ),
            cyto_emotion="surprised",
            next_step_id="c1_s3_verify_import",
            allow_interaction=True,
            target_widget_names=["ImportDataButton"],
        ),
        InfoStep(
            id="c1_s3_fail_too_few",
            text=(
                "Hmm — I couldn't find all 10 samples.<br><br>"
                "Make sure you selected the Blank, PI, all 5 FMOs, "
                "and Samples A, B, C from the picker. Please load the rest!"
            ),
            cyto_emotion="sad",
            next_step_id="c1_s2_import",
            allow_interaction=True,
            target_widget_names=["ImportDataButton"],
        ),
        InfoStep(
            id="c1_s3b_groups_intro",
            text=(
                "One concept before we go further: Groups 📁<br><br>"
                "Look at the **Groups** panel in the sidebar — every sample you "
                "just imported sits under one default group, **All Samples**. A "
                "Group is simply a named subset of your samples, and it "
                "controls something important: gating actions (and later, "
                "locked axis scales) only propagate to OTHER samples in the "
                "SAME group.<br><br>"
                "Since all 10 of your samples are currently in **All Samples**, "
                "a gate you draw on one sample will automatically apply to "
                "the rest — that's the propagation you'll rely on throughout "
                "this course.<br><br>"
                "Why make a custom group? If you're analyzing completely different "
                "tissue types that need different gating strategies, or juggling "
                "multiple experiments in the same workspace, separating them into "
                "different groups ensures their gates don't interfere. You won't "
                "need to do that for this tutorial, though."
            ),
            cyto_emotion="talking",
            target_widget_names=["GroupsPanel"],
            next_step_id="c1_s4_roles_intro",
        ),
        # Role assignment intro
        InfoStep(
            id="c1_s4_roles_intro",
            text=(
                "All 10 files are in! ✅<br><br>"
                "Let's assign the purpose of each file — "
                "we call this a **Role**. The roles are:<br>"
                "• **Blank** → Unstained (no dye — background autofluorescence)<br>"
                "• **PI** → Single Stain (one dye to correct spectral overlap)<br>"
                "• **FMO_*** → FMO Control (all dyes minus one — identifies true background for gating)<br>"
                "• **Samples A/B/C** → Full Panel (experiment samples)<br><br>"
                "We'll assign them one step at a time."
            ),
            cyto_emotion="talking",
            next_step_id="c1_s5_blank_role",
        ),
        # Blank → Unstained
        VerificationStep(
            id="c1_s5_blank_role",
            text=(
                "**Step 1 of 4** — Blank sample.<br><br>"
                "In the **Sample List** (left, highlighted), double click on **Blank**. "
                "Then in the **Properties Panel** (right, highlighted), "
                "find the Role dropdown and set it to **Unstained**.<br><br>"
                "I'll advance automatically once it's set!"
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["SampleList", "PropertiesPanel"],
            validator=UnstainedRoleValidator(),
            on_success_step_id="c1_s7_pi_role",
            failure_hint="Double-check you selected **Blank** in the Sample List, then set its Role to **Unstained** in the Properties Panel.",
        ),
        # PI → Single Stain
        VerificationStep(
            id="c1_s7_pi_role",
            text=(
                "**Step 2 of 4** — PI file.<br><br>"
                "**PI (Propidium Iodide)** is our viability dye — just one "
                "dye, which makes it the perfect single-stain control "
                "for its channel.<br><br>"
                "Double click on the PI file in the **Sample List** and set its "
                "Role to **Single Stain**. Karcytics will detect it automatically."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["SampleList", "PropertiesPanel"],
            validator=SingleStainRoleValidator(),
            on_success_step_id="c1_s9_fmo_role",
            failure_hint="Double-check you selected the **PI** file in the Sample List, then set its Role to **Single Stain**.",
        ),
        # FMOs → FMO Control
        VerificationStep(
            id="c1_s9_fmo_role",
            text=(
                "**Step 3 of 4** — FMO controls.<br><br>"
                "**FMO (Fluorescence Minus One)**. Each FMO file has every "
                "dye *except* one, letting us clearly see the boundary between "
                "the true negative background and actual positive signals for that missing dye.<br><br>"
                "Doing this one-by-one is tedious! Click **🏷️ Bulk Assign Roles** "
                "(highlighted in the ribbon).<br><br>"
                "In the dialog, select all 5 FMO files, set them to the "
                "**FMO Control** role, and click Assign."
            ),
            cyto_emotion="talking",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["BulkAssignRoleButton"],
            validator=FmoRoleValidator(),
            on_success_step_id="c1_s10_set_all_roles",
            failure_hint="Make sure you selected all 5 FMO files in **Bulk Assign Roles** and set them to **FMO Control**.",
        ),
        VerificationStep(
            id="c1_s10_set_all_roles",
            text=(
                "**Step 4 of 4** — mystery samples.<br><br>"
                "Use the **🏷️ Bulk Assign Roles** button again to select "
                "Samples A, B, and C and set their Role to **Full Panel**.<br><br>"
                "I'll keep an eye on your progress and we'll move forward once all the tubes are set up."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["BulkAssignRoleButton"],
            validator=RoleAssignmentValidator(),
            on_success_step_id="c1_s11_role_summary",
            failure_hint="Make sure Samples A, B, and C are all set to **Full Panel** via Bulk Assign Roles.",
        ),
        InfoStep(
            id="c1_s11_role_summary",
            text=(
                "Perfect! Roles are all set.<br><br>"
                "Why do we do this? These tags are used to:<br>"
                "• Single Stains build the matrix to correct spectral overlap<br>"
                "• Full Panels receive the correction and get analyzed<br>"
                "• FMOs guide your gating to separate positive from negative, but get excluded from final test statistics so they don't skew your sample averages."
            ),
            cyto_emotion="happy",
            next_step_id="c1_s12_comp_intro",
        ),
        # ── Phase 2 — Compensation ────────────────────────────────────────────
        InfoStep(
            id="c1_s12_comp_intro",
            text=(
                "Phase 2 — Compensation ⚖️<br><br>"
                "Fluorescent dyes spill light into adjacent detectors. "
                "Compensation removes this cross-talk mathematically — and "
                "it's exactly why we tagged Single Stain and Full Panel "
                "roles first: the math needs to know which files ARE the "
                "controls before it can correct the samples."
            ),
            cyto_emotion="thinking",
            next_step_id="c1_s12c_auto_applied_info",
        ),
        InfoStep(
            id="c1_s12c_auto_applied_info",
            text=(
                "Karcytics found a **$SPILL** keyword embedded in your Blank's "
                "FCS file header and auto-applied the compensation matrix "
                "to all samples when they were loaded! ✅<br><br>"
                "Look at the sample tree — every sample now has a **[Comp]** "
                "tag next to its name. That's how Karcytics marks a sample as "
                "compensated, so at a glance you always know whether you're "
                "looking at raw or corrected data.<br><br>"
                "But before we go build one ourselves, it's worth understanding "
                "what that matrix is actually correcting — because **spillover** "
                "isn't just a term to memorize, it's a real physical property of "
                "how dyes emit light."
            ),
            cyto_emotion="happy",
            target_widget_names=["SampleList"],
            next_step_id="c1_s12d_spectral_theory_1",
        ),
        InfoStep(
            id="c1_s12d_spectral_theory_1",
            text=(
                "Where does spillover actually come from? <br><br>"
                "A fluorescent dye doesn't glow at one exact wavelength — it emits "
                "across a broad, hill-shaped range spanning 100nm or more. "
                "Detectors sit under the peak of one dye's hill, but that hill's "
                "shoulders still spill into neighboring detectors.<br><br>"
                "Two dyes with peaks 50nm apart can still overlap by 20-30% or "
                "more — that overlap is exactly the spillover compensation exists "
                "to correct."
            ),
            cyto_emotion="thinking",
            next_step_id="c1_s12e_spectral_theory_2",
        ),
        InfoStep(
            id="c1_s12e_spectral_theory_2",
            text=(
                "For every pair of channels, Karcytics uses your Single Stain "
                "controls to estimate what fraction of one dye's signal leaks "
                "into the other's detector, then subtracts that estimated "
                "leakage from every event.<br><br>"
                "You'll see this overlap directly, curve by curve, with real "
                "published spectra later on Course 2's Spectral tab. For now, "
                "let's build that matrix yourself so you know exactly what Karcytics "
                "just did for you automatically."
            ),
            cyto_emotion="talking",
            next_step_id="c1_s13b_verify_comp_tab",
        ),
        # Checks the tab FIRST — if the user is already on Compensation
        # (e.g. from browsing earlier), this passes immediately without
        # ever showing a "click the tab" prompt that could never fire
        # (currentChanged never emits for a tab that's already active).
        VerificationStep(
            id="c1_s13b_verify_comp_tab",
            text="Checking tab...",
            cyto_emotion="scanning",
            hide_next_button=True,
            allow_interaction=False,
            validator=TabActiveValidator(1),
            on_success_step_id="c1_s14_extract_matrix",
            on_fail_step_id="c1_s13_switch_comp_tab",
        ),
        InteractionStep(
            id="c1_s13_switch_comp_tab",
            text=(
                "Click the **Compensation** tab (highlighted) at the top — "
                "that's where Karcytics keeps its compensation tools."
            ),
            cyto_emotion="pointing",
            target_widget_names=["MainTabBar"],
            target_widget_name="MainTabBar",
            event_trigger="currentChanged",
            next_step_id="c1_s13b_verify_comp_tab",
        ),
        InteractionStep(
            id="c1_s14_extract_matrix",
            text=(
                "Click **📄 Extract from FCS** (highlighted) in the ribbon.<br><br>"
                "This reads the $SPILL keyword from the first file that has it."
            ),
            target_widget_name="ExtractFCSButton",
            event_trigger="clicked",
            cyto_emotion="pointing",
            next_step_id="c1_s15_view_matrix",
        ),
        InfoStep(
            id="c1_s15_view_matrix",
            text=(
                "A dialog has popped up showing the extracted matrix values!<br><br>"
                "Take a moment to look at it. The diagonal is usually 1.0, and "
                "other numbers show how much light spills into adjacent detectors.<br><br>"
                "Click **OK** on the dialog to close it, then click Next here."
            ),
            cyto_emotion="talking",
            next_step_id="c1_s16_apply_matrix",
        ),
        InteractionStep(
            id="c1_s16_apply_matrix",
            text=(
                "Finally, click **✅ Apply to All** (highlighted).<br><br>"
                "Since Karcytics already auto-applied the matrix on import, this "
                "won't actually change anything right now, but this is exactly "
                "what you would do for uncompensated data.<br><br>"
                "A popup will tell you that the samples were skipped because "
                "they are already compensated. You can close it."
            ),
            target_widget_name="ApplyAllButton",
            event_trigger="clicked",
            cyto_emotion="pointing",
            next_step_id="c1_s20_gating_intro",
        ),
        # ── Phase 3 — Gating ──────────────────────────────────────────────────
        InfoStep(
            id="c1_s20_gating_intro",
            text=(
                "Phase 3 — Gating 🎯<br><br>"
                "Your data is clean and compensated. Gating means drawing "
                "regions on scatter plots to select specific cell "
                "populations — and we do it hierarchically: each new gate "
                "narrows down INSIDE the last one, like a funnel, so "
                "everything downstream is automatically purified of "
                "whatever you excluded earlier.<br><br>"
                "We'll build this hierarchy:<br>"
                "**All Events → Cells → Live → Leukocytes**<br><br>"
                "First, switch to the **Gating** tab."
            ),
            cyto_emotion="talking",
            next_step_id="c1_s22_verify_gating_tab",
        ),
        VerificationStep(
            id="c1_s22_verify_gating_tab",
            text="Checking tab...",
            cyto_emotion="scanning",
            hide_next_button=True,
            allow_interaction=False,
            validator=TabActiveValidator(2),
            on_success_step_id="c1_s22b_open_sample",
            on_fail_step_id="c1_s21_switch_gating_tab",
        ),
        InteractionStep(
            id="c1_s21_switch_gating_tab",
            text=(
                "Click the **Gating** tab (highlighted) at the top. "
                "This shows the polygon, rectangle, and range drawing tools."
            ),
            cyto_emotion="pointing",
            target_widget_names=["MainTabBar"],
            target_widget_name="MainTabBar",
            event_trigger="currentChanged",
            next_step_id="c1_s22_verify_gating_tab",
        ),
        # Open Blank Sample first — gate applies to whichever sample is open
        InteractionStep(
            id="c1_s22b_open_sample",
            text=(
                "Before drawing any gates, we start with the **Blank** (Unstained) sample.<br><br>"
                "In the **Sample List**, find the **Blank** file and double-click it. "
                "This opens its scatter plot in the centre canvas.<br><br>"
                "We use the unstained sample first because it has no dyes, making it "
                "the perfect baseline to find the physical cell population based purely on size and complexity."
            ),
            cyto_emotion="pointing",
            target_widget_names=["SampleList"],
            target_widget_name="SampleList",
            event_trigger="sample_double_clicked",
            next_step_id="c1_s22c_verify_sample_open",
        ),
        VerificationStep(
            id="c1_s22c_verify_sample_open",
            text="Checking opened sample...",
            cyto_emotion="scanning",
            hide_next_button=True,
            allow_interaction=False,
            validator=SampleOpenValidator(),
            on_success_step_id="c1_s22d_scatter_physics",
            on_fail_step_id="c1_s22b_fail",
        ),
        InteractionStep(
            id="c1_s22b_fail",
            text=(
                "Oops! You opened the wrong sample.<br><br>"
                "Please double-click the **Blank** sample to open it."
            ),
            cyto_emotion="surprised",
            target_widget_names=["SampleList"],
            target_widget_name="SampleList",
            event_trigger="sample_double_clicked",
            next_step_id="c1_s22c_verify_sample_open",
        ),
        InfoStep(
            id="c1_s22d_scatter_physics",
            text=(
                "What FSC and SSC actually measure 💡<br><br>"
                "Forward Scatter (FSC) is laser light bent slightly forward as it "
                "passes around a cell — bigger cells bend more light forward, so "
                "FSC roughly tracks cell SIZE.<br><br>"
                "Side Scatter (SSC) is light bounced sideways off internal "
                "structures — granules, a lobed nucleus, organelles — so SSC "
                "roughly tracks internal COMPLEXITY.<br><br>"
                "Plotting them together is the classic first gate: it separates "
                "intact cells from debris before you've added a single dye."
            ),
            cyto_emotion="thinking",
            next_step_id="c1_s23_cells_intro",
        ),
        # Cells gate
        InfoStep(
            id="c1_s23_cells_intro",
            text=(
                "**Gate 1: Cells**<br><br>"
                "The current plot shows **FSC-A** (cell size) vs **SSC-A** "
                "(cell complexity). You'll see:<br>"
                "• 2 main clusters of cells<br>"
                "• A small debris cloud in the bottom-left corner<br>"
                "• A good chunk of splatter throughout the entire canvas<br><br>"
                "We want to draw a gate that excludes the debris. "
                "This ensures all downstream analysis excludes junk events.<br><br>"
                "When you draw the gate in the next step, a popup will ask you for its name. Be sure to call it **Cells**!"
            ),
            cyto_emotion="talking",
            next_step_id="c1_s24_cells_gate",
        ),
        InteractionStep(
            id="c1_s24_cells_gate",
            text=(
                "Draw the gate:<br><br>"
                "1. Click **Polygon** in the Gating ribbon (highlighted above)<br>"
                "2. Click each vertex around the oval cell cloud on the plot (highlighted)<br>"
                "3. Double-click to close the polygon<br>"
                "4. Type **Cells** in the popup and hit Enter!<br><br>"
                "Your gate will be evaluated automatically once you finish drawing."
            ),
            cyto_emotion="pointing",
            target_widget_name="MainPanel",
            event_trigger="gate_added_to_tree",
            target_widget_names=["Tool_polygon", "FlowCanvas"],
            metadata={
                "guide_data_poly": [(8000, 38000), (248000, 34000), (248000, 500), (8000, 1000)]
            },
            next_step_id="c1_s24_cells_gate_verify",
            stuck_hint_text=(
                "Still there? Click **Polygon** in the Gating ribbon, then click around the "
                "cell cloud and double-click to close the shape."
            ),
            stuck_hint_after_ms=45000,
        ),
        VerificationStep(
            id="c1_s24_cells_gate_verify",
            text="Evaluating your gate...",
            cyto_emotion="scanning",
            allow_interaction=False,
            hide_next_button=True,
            target_widget_names=["FlowCanvas"],
            metadata={
                "guide_data_poly": [(8000, 38000), (248000, 34000), (248000, 500), (8000, 1000)]
            },
            validator=c1_cells_validator,
            on_success_step_id="c1_s24b_cells_hierarchy_intro",
            on_fail_step_id="c1_s24_cells_gate_retry",
        ),
        InfoStep(
            id="c1_s24_cells_gate_misnamed",
            text="I renamed the gate to **Cells** for you. Let's proceed!",
            cyto_emotion="happy",
            next_step_id="c1_s24b_cells_hierarchy_intro",
        ),
        InfoStep(
            id="c1_s24_cells_gate_retry",
            text=(
                "That gate didn't quite match the shape!<br><br>"
                "I deleted it for you. Make sure you cover the main cluster of cells while excluding the debris at the bottom left.<br><br>"
                "Try drawing it again."
            ),
            cyto_emotion="surprised",
            target_widget_names=["FlowCanvas"],
            metadata={
                "guide_data_poly": [(8000, 38000), (248000, 34000), (248000, 500), (8000, 1000)]
            },
            next_step_id="c1_s24_cells_gate",
        ),
        InfoStep(
            id="c1_s24b_cells_hierarchy_intro",
            text=(
                "Perfect shape! 🎯<br><br>"
                "Notice that your new gate has appeared in the **Gating Hierarchy** panel on the left.<br><br>"
                "This hierarchy tracks all populations. By default, the gates you apply to one sample will propagate to all other samples in the same group."
            ),
            cyto_emotion="happy",
            target_widget_names=["GatingHierarchySampleView"],
            next_step_id="c1_s25_singlets_intro",
        ),
        InfoStep(
            id="c1_s25_singlets_intro",
            text=(
                "Great job! 🎯<br><br>"
                "Typically, the next step is gating for **Singlets** to remove clumps "
                "of cells (doublets). You'd do this by plotting **FSC-A** vs FSC-H and "
                "drawing a narrow diagonal gate down the center line.<br><br>"
                "Doublets have a disproportionately larger Area than Height, so they "
                "appear as a separate population shifted to the right of the diagonal. "
                "You would filter them out by only keeping the events on the diagonal.<br><br>"
                "Our dataset doesn't include the -H or -W parameters, so we won't "
                "gate for singlets today, but it's a crucial step in real experiments!"
            ),
            cyto_emotion="thinking",
            next_step_id="c1_s26_live_intro",
        ),
        # Live gate
        InfoStep(
            id="c1_s26_live_intro",
            text=(
                "**Gate 2: Live**<br><br>"
                "Dead cells absorb PI dye and glow brightly (high signal). "
                "Live cells keep it out — they appear dim.<br><br>"
                "We gate *inside* the Cells population to keep only "
                "live cells. This is called hierarchical gating.<br><br>"
                "When you draw the gate in a few steps, be sure to name it **Live Cells** in the naming popup!"
            ),
            cyto_emotion="talking",
            next_step_id="c1_s27_open_pi",
        ),
        # ── Step 1: Open the PI single stain sample ─────────────────────────
        InteractionStep(
            id="c1_s27_open_pi",
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
            next_step_id="c1_s27_verify_pi",
        ),
        VerificationStep(
            id="c1_s27_verify_pi",
            text="Checking opened sample...",
            cyto_emotion="scanning",
            hide_next_button=True,
            allow_interaction=False,
            validator=SpecificSampleOpenValidator("SINGLE_STAIN"),
            on_success_step_id="c1_s27b_set_axis",
            on_fail_step_id="c1_s27_fail",
        ),
        InteractionStep(
            id="c1_s27_fail",
            text=(
                "Oops! You opened the wrong sample.<br><br>"
                "Please double-click the **Specimen_001_PI** sample to open it."
            ),
            cyto_emotion="surprised",
            target_widget_names=["SampleList"],
            target_widget_name="SampleList",
            event_trigger="sample_double_clicked",
            next_step_id="c1_s27_verify_pi",
        ),
        # ── Step 2: Change X axis to the PI channel ──────────────────────────
        VerificationStep(
            id="c1_s27b_set_axis",
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
            on_success_step_id="c1_s27c_biexp_explain",
            failure_hint="Make sure the **X:** axis dropdown is set to **PerCP-Cy5-5-A**, the PI detector channel.",
        ),
        # ── Step 3: Explain biexponential and populations ───────────────────
        InfoStep(
            id="c1_s27c_biexp_explain",
            text=(
                "Reading the PI plot 🔬<br><br>"
                "Two populations: a large, dense cluster on the left (live cells) "
                "and a smaller, brighter cluster on the right (dead cells "
                "absorbing PI).<br><br>"
                "Notice Karcytics opened this sample directly at your **Cells** "
                "population, not the top-level view — it preserves your gating "
                "context every time you switch samples.<br><br>"
                "Also notice the X axis auto-switched to **Biexponential**. "
                "Compensated fluorescence data can score negative for real "
                "cells, and Linear/Log scales can't display negatives properly "
                "— Biexponential can, so Karcytics reaches for it automatically "
                "whenever it detects a fluorescence channel."
            ),
            cyto_emotion="talking",
            next_step_id="c1_s27d_outlier_fix",
        ),
        # ── Step 4: Fix Outliers ────────────────────────────────────────────
        VerificationStep(
            id="c1_s27d_outlier_fix",
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
            on_success_step_id="c1_s27f_draw_live_gate",
            failure_hint="Open **⚙ Transforms** and make sure **Outliers:** is set to **0%**, not the default 0.1%.",
        ),
        # ── Step 5: Draw the vertical Range gate ────────────────────────────────
        InteractionStep(
            id="c1_s27f_draw_live_gate",
            text=(
                "Now draw the Live cell gate.<br><br>"
                "The dark purple box shows the target region. Drag from the left edge of the "
                "box to the right edge to capture the live cells.<br><br>"
                "1. Click the **Range** tool (highlighted in the ribbon)<br>"
                "2. Drag horizontally across the left cluster. Start from the far left edge (around -10³) and end just past the dense red center (around 5000).<br>"
                "3. Type **Live Cells** in the naming popup!<br><br>"
            ),
            cyto_emotion="pointing",
            target_widget_names=["Tool_range", "FlowCanvas"],
            target_widget_name="MainPanel",
            event_trigger="gate_added_to_tree",
            metadata={"guide_range": (-1000.0, 10000.0)},
            next_step_id="c1_s27f_draw_live_gate_verify",
            stuck_hint_text=(
                "Still there? Click the **Range** tool, then drag across the dark purple box "
                "from left edge to right edge."
            ),
            stuck_hint_after_ms=45000,
        ),
        VerificationStep(
            id="c1_s27f_draw_live_gate_verify",
            text="Checking...",
            cyto_emotion="scanning",
            allow_interaction=False,
            hide_next_button=True,
            validator=c1_live_validator,
            on_success_step_id="c1_s27g_settings_intro",
            on_fail_step_id="c1_s27f_live_gate_retry",
        ),
        InfoStep(
            id="c1_s27f_live_gate_misnamed",
            text="I renamed the gate to **Live Cells** for you. Let's proceed!",
            cyto_emotion="happy",
            next_step_id="c1_s27g_settings_intro",
        ),
        InfoStep(
            id="c1_s27f_live_gate_retry",
            text=(
                "That gate didn't quite capture the right range!<br><br>"
                "I deleted it for you. Make sure the high bound doesn't cross into the dead cells on the right.<br><br>"
                "Try drawing it again."
            ),
            cyto_emotion="surprised",
            target_widget_names=["FlowCanvas"],
            metadata={"guide_range": (-1000.0, 10000.0)},
            next_step_id="c1_s27f_draw_live_gate",
        ),
        InteractionStep(
            id="c1_s27g_settings_intro",
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
            next_step_id="c1_s28_stats_intro",
        ),
        InfoStep(
            id="c1_s28_stats_intro",
            text=(
                "Understanding the Stats 📊<br><br>"
                "Now that you've gated **Live Cells**, check the Property Panel:<br>"
                "- Event Count: How many cells fall inside your gate.<br>"
                "- % Parent: Percentage of the parent population (e.g. out of **Cells**).<br>"
                "- % Total: Percentage of all recorded events in the tube.<br><br>"
                "Also, glance at the **Group Preview** below \u2014 it shows this gate applied to "
                "every sample in your workspace instantly!"
            ),
            cyto_emotion="talking",
            target_widget_names=["PropertiesPanel"],
            next_step_id="c1_s29_leuko_intro",
        ),
        # Leukocytes gate
        InfoStep(
            id="c1_s29_leuko_intro",
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
            next_step_id="c1_s30a_open_fmo",
        ),
        # ── Step 1: Open FMO to see background ───────────────────────────────
        InteractionStep(
            id="c1_s30a_open_fmo",
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
            next_step_id="c1_s30a_verify_fmo",
        ),
        VerificationStep(
            id="c1_s30a_verify_fmo",
            text="Checking opened sample...",
            cyto_emotion="scanning",
            hide_next_button=True,
            allow_interaction=False,
            validator=ExactSampleOpenValidator("FMO APC"),
            on_success_step_id="c1_s30b_set_x",
            on_fail_step_id="c1_s30a_fail",
        ),
        InteractionStep(
            id="c1_s30a_fail",
            text=(
                "Oops! You opened the wrong sample.<br><br>"
                "Please double-click the **FMO APC** sample to open it."
            ),
            cyto_emotion="surprised",
            target_widget_names=["SampleList"],
            target_widget_name="SampleList",
            event_trigger="sample_double_clicked",
            next_step_id="c1_s30a_verify_fmo",
        ),
        VerificationStep(
            id="c1_s30b_set_x",
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
            on_success_step_id="c1_s30d_outlier",
            failure_hint="Make sure the **X:** axis dropdown is set to **APC-A**, the CD45 channel.",
        ),
        InfoStep(
            id="c1_s30d_outlier",
            text=(
                "Same outlier trick as before ⚠️<br><br>"
                "The default 0.1% trim is hiding a sliver of cells at the edge of the "
                "APC-A axis again. Click **⚙ Transforms** → set **Outliers** to **0%** → close "
                "the dialog, then click Next."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            target_widget_names=["TransformsButton"],
            next_step_id="c1_s30e_read_fmo",
        ),
        InfoStep(
            id="c1_s30e_read_fmo",
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
            next_step_id="c1_s30g_preview_intro",
        ),
        # ── Step 2: Draw the gate on the FMO itself ────────────────────────────
        InfoStep(
            id="c1_s30g_preview_intro",
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
            next_step_id="c1_s30h_draw_gate",
        ),
        InteractionStep(
            id="c1_s30h_draw_gate",
            text=(
                "Step ②: Draw the Leukocyte gate — right here on the FMO.<br><br>"
                "1. Select the **Rect** tool.<br>"
                "2. The dark purple box marks the CD45+ region. Start your rectangle "
                "at roughly X=10² (right where the autofluorescence tail ends) and drag "
                "all the way to the right edge, covering the full height of the **SSC-A** axis.<br>"
                "3. Type **Leukocytes** in the naming popup!<br><br>"
                "Watch the **Group Preview** thumbnails as you drag — you'll see this exact "
                "boundary appear on Samples A, B, and C instantly.<br><br>"
            ),
            cyto_emotion="pointing",
            target_widget_names=["Tool_rectangle", "FlowCanvas"],
            target_widget_name="MainPanel",
            event_trigger="gate_added_to_tree",
            metadata={"guide_rect": (2000.0, 200000.0, 500.0, 37000.0)},
            next_step_id="c1_s30h_draw_gate_verify",
            stuck_hint_text=(
                "Still there? Click the **Rect** tool, then drag across the dark purple box "
                "covering the CD45+ region."
            ),
            stuck_hint_after_ms=45000,
        ),
        VerificationStep(
            id="c1_s30h_draw_gate_verify",
            text="Checking...",
            cyto_emotion="scanning",
            allow_interaction=False,
            hide_next_button=True,
            validator=c1_leukocytes_validator,
            on_success_step_id="c1_s30f_open_sample",
            on_fail_step_id="c1_s30h_leukocytes_gate_retry",
        ),
        InfoStep(
            id="c1_s30h_leukocytes_gate_misnamed",
            text="I renamed the gate to **Leukocytes** for you. Let's proceed!",
            cyto_emotion="happy",
            next_step_id="c1_s30f_open_sample",
        ),
        InfoStep(
            id="c1_s30h_leukocytes_gate_retry",
            text=(
                "That gate didn't quite capture the right area!<br><br>"
                "I deleted it for you. Make sure your rectangle starts past the autofluorescence and covers the full SSC-A height.<br><br>"
                "Try drawing it again."
            ),
            cyto_emotion="surprised",
            target_widget_names=["FlowCanvas"],
            metadata={"guide_rect": (2000.0, 200000.0, 500.0, 37000.0)},
            next_step_id="c1_s30h_draw_gate",
        ),
        # ── Step 3: Switch to a full-panel sample to confirm ───────────────────
        InteractionStep(
            id="c1_s30f_open_sample",
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
            next_step_id="c1_s30f_verify_sample",
        ),
        VerificationStep(
            id="c1_s30f_verify_sample",
            text="Checking opened sample...",
            cyto_emotion="scanning",
            hide_next_button=True,
            allow_interaction=False,
            validator=ExactSampleOpenValidator("Sample B"),
            on_success_step_id="c1_s30f1b_verify_propagated",
            on_fail_step_id="c1_s30f_fail",
        ),
        InteractionStep(
            id="c1_s30f_fail",
            text=(
                "Oops! You opened the wrong sample.<br><br>Please double-click **Sample B** to open it."
            ),
            cyto_emotion="surprised",
            target_widget_names=["SampleList"],
            target_widget_name="SampleList",
            event_trigger="sample_double_clicked",
            next_step_id="c1_s30f_verify_sample",
        ),
        VerificationStep(
            id="c1_s30f1b_verify_propagated",
            text="Checking that your gate propagated to Sample B...",
            cyto_emotion="scanning",
            hide_next_button=True,
            allow_interaction=False,
            validator=c1_leukocytes_validator,
            on_success_step_id="c1_s30f2_set_x_sample_a",
            failure_hint="If the Leukocytes gate hasn't appeared here yet, make sure Auto-Propagation is enabled and try re-opening Sample B.",
        ),
        InfoStep(
            id="c1_s30f2_set_x_sample_a",
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
            next_step_id="c1_s30f3_persistence_explain",
        ),
        InfoStep(
            id="c1_s30f3_persistence_explain",
            text=(
                "Behind the Scenes: The **No-Jump** Rule<br><br>"
                "In Karcytics, the auto-zoom calculation only happens *once* the very first time you select a channel. "
                "From that point on, the view is completely locked for that channel across all samples in the group.<br><br>"
                "This guarantees that as you draw deeper gates and switch between controls and full samples, the plot "
                "won't aggressively jump around or zoom in. You will always maintain your bearings!"
            ),
            cyto_emotion="talking",
            next_step_id="c1_s32_auto_propagation",
        ),
        # Auto-propagation
        InfoStep(
            id="c1_s32_auto_propagation",
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
            next_step_id="c1_s33b_save_interaction",
        ),
        VerificationStep(
            id="c1_s33b_save_interaction",
            text=(
                "Phase 4 — Saving your progress 💾<br><br>"
                "Course 2 requires the foundation we just built. We need to save "
                "this workspace so we can load it later.<br><br>"
                "Click the **⚠️ Save Workspace** button (highlighted) at the top right.<br><br>"
                "Give it a name like **Learning flow with Cyto!** and click Save."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["WorkspaceSaveButton"],
            validator=WorkflowSavedValidator(),
            on_success_step_id="c1_s34_graduation",
            failure_hint="Click **⚠️ Save Workspace**, give it a name, and click Save to finish.",
        ),
        InfoStep(
            id="c1_s34_graduation",
            text=(
                "All done! You've successfully imported, cleaned, and "
                "identified the core immune population in our samples. 🚀<br><br>"
                "Your workspace is saved. In Course 2, we will use this exact "
                "setup to finally solve the mystery of what these three "
                "samples are.<br><br>"
                "Click Next to collect your badge!"
            ),
            cyto_emotion="cheering",
            cyto_animation="cheering",
        ),
    ],
)
