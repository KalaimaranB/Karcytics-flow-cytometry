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
    QUESTION_PREDICT,
    ActionStep,
    AnswerChoice,
    BranchingStep,  # noqa: F401
    ConsentStep,
    Course,
    ForcedInteractionStep,  # noqa: F401
    InfoStep,
    InteractionStep,
    QuestionStep,
    SubTask,  # noqa: F401
    VerificationStep,
)

from ..analysis.constants import PROPERTIES_VIEW_HISTOGRAM, PROPERTIES_VIEW_PROPERTIES
from .constants import PREVIEW_ALL_SAMPLES, PREVIEW_VIEW_BOTH
from .tutorial_assets import start_provisioning
from .validators import (
    FlowImportValidator,
    FmoRoleValidator,
    GateShapeValidator,
    LearningCompensationCompleteValidator,
    PreviewShowsValidator,
    PropertiesViewValidator,
    RoleAssignmentValidator,
    SampleOpenValidator,
    SingleStainRoleValidator,
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


def route_by_properties_view(panel, step_id, switch_step_id, ready_step_id):
    """Skip the "switch back to Properties" step when the panel is already there.

    The Properties Panel's top pane can be left on its Histogram view (the
    choice is remembered between sessions), which hides the Role dropdown the
    role-assignment steps need.
    """
    step = next((s for s in course_1_fundamentals.steps if s.id == step_id), None)
    if step is None:
        return
    on_properties = panel.state.view.properties_view == PROPERTIES_VIEW_PROPERTIES
    step.next_step_id = ready_step_id if on_properties else switch_step_id


# ==============================================================================
# Course 1 — Flow Cytometry Fundamentals
#
# The gate-drawing step (Cells below) doesn't wire its own ActionStep-based
# failure routing: `c1_cells_validator` above implements
# `GateShapeValidator.describe_failure()`, and `AcademyStepDriver` (SDK)
# calls it automatically on a failed VerificationStep — showing the
# explanation banner, auto-renaming/deleting the gate, and routing to the
# validator's own `misnamed_retry_step_id`/`shape_retry_step_id` in one
# generic path shared by every course that uses `GateShapeValidator`.
# Three phases: Setup → First gate (Cells) → Compensation
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
        "Your samples just arrived. We'll set up the experiment, draw the "
        "first gate, and see why and how the data is compensated."
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
                "from organ to organ, and by the end of Course 3 you'll "
                "have a confident, evidence-based answer for which is "
                "which. (Course 4 goes even deeper if you want it — but "
                "it's not required to crack the case.)<br><br>"
                "Let's start by loading our files."
            ),
            cyto_emotion="happy",
            cyto_animation="cheering",
            next_step_id="c1_s1a_prediction",
        ),
        QuestionStep(
            id="c1_s1a_prediction",
            text=(
                "Make a prediction 🔮<br><br>"
                "The thymus is where T cells grow up. Which cells do you "
                "expect the thymus sample to have *very few* of? There's no "
                "wrong answer — Course 3 will tell you."
            ),
            kind=QUESTION_PREDICT,
            question_id="c1_thymus_few",
            choices=[
                AnswerChoice("B cells"),
                AnswerChoice("T cells"),
                AnswerChoice("Immune cells of any kind"),
            ],
            cyto_emotion="thinking",
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
                "• Draw your first gate, **Cells**, from scatter alone<br>"
                "• Read a spillover matrix and judge whether it is doing "
                "its job<br><br>"
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
            next_step_id="c1_s4b_fmo_question",
        ),
        QuestionStep(
            id="c1_s4b_fmo_question",
            text=(
                "Quick check ✅<br><br>"
                "CD45 is stained with the dye **APC**. Later you'll need to "
                "know how bright a cell can be *without* CD45. Which file "
                "shows you that?"
            ),
            question_id="c1_cd45_background",
            choices=[
                AnswerChoice(
                    "Blank",
                    feedback="Close, but Blank has no dyes at all, so it misses the glow the other dyes spill into the APC detector. Its edge sits too low.",
                ),
                AnswerChoice("FMO APC", correct=True),
                AnswerChoice(
                    "Sample A",
                    feedback="Sample A has CD45 stained, so its real signal hides the background you're looking for.",
                ),
            ],
            explanation=(
                "FMO APC has every dye except APC: the same spillover as your "
                "samples, but no real CD45 signal. Whatever it shows in the APC "
                "channel is background, so that's where CD45-negative ends."
            ),
            cyto_emotion="thinking",
            next_step_id="c1_s5_check_properties_view",
        ),
        # The Role dropdown lives on the panel's Properties view — get the
        # user back there first if they left it on Histogram.
        ActionStep(
            id="c1_s5_check_properties_view",
            text="Checking the Properties Panel...",
            action=lambda panel: route_by_properties_view(
                panel,
                "c1_s5_check_properties_view",
                "c1_s5_switch_to_properties",
                "c1_s5_blank_role",
            ),
            next_step_id="c1_s5_switch_to_properties",
        ),
        VerificationStep(
            id="c1_s5_switch_to_properties",
            text=(
                "One thing first: the **Properties Panel** (right) is showing its "
                "**Histogram** view, and we need the sample details instead.<br><br>"
                "Click **Properties** at the top of the panel (highlighted) to switch back."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["PropertiesViewToggle"],
            validator=PropertiesViewValidator(PROPERTIES_VIEW_PROPERTIES),
            on_success_step_id="c1_s5_blank_role",
            failure_hint="Click **Properties** at the top of the Properties Panel on the right.",
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
            next_step_id="c1_s20_gating_intro",
        ),
        # ── Phase 2 — First gate ──────────────────────────────────────────────────
        InfoStep(
            id="c1_s20_gating_intro",
            text=(
                "Phase 2 — Your first gate 🎯<br><br>"
                "Gating means drawing regions on plots to select specific "
                "cell populations — and we do it hierarchically: each new gate "
                "narrows down INSIDE the last one, like a funnel, so "
                "everything downstream is automatically purified of "
                "whatever you excluded earlier.<br><br>"
                "The hierarchy we're heading for:<br>"
                "**All Events → Cells → Live → Leukocytes**<br><br>"
                "Today we draw **Cells**. It uses scatter only, no dyes, so it "
                "can come before compensation. First, switch to the **Gating** tab."
            ),
            cyto_emotion="talking",
            next_step_id="c1_s22_verify_gating_tab",
        ),
        VerificationStep(
            id="c1_s22_verify_gating_tab",
            text=(
                "Click the **Gating** tab (highlighted) at the top. "
                "This shows the polygon, rectangle, and range drawing tools."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["MainTabBar"],
            validator=TabActiveValidator(1),  # Gating
            on_success_step_id="c1_s22b_open_sample",
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
        QuestionStep(
            id="c1_s22d_scatter_physics",
            text=(
                "Read the plot 💡<br><br>"
                "**FSC** (forward scatter) tracks a particle's size; **SSC** "
                "(side scatter) tracks how much is inside it. Debris is "
                "fragments: small and simple. Where on this plot does it sit?"
            ),
            question_id="c1_debris_location",
            choices=[
                AnswerChoice("Bottom-left: low FSC, low SSC", correct=True),
                AnswerChoice(
                    "Top-right: high FSC, high SSC",
                    feedback="That's big, granular cells. Fragments scatter little light either way.",
                ),
                AnswerChoice(
                    "Bottom-right: high FSC, low SSC",
                    feedback="High FSC means large. Fragments are small.",
                ),
            ],
            explanation=(
                "Fragments bend little light forward and have little inside to "
                "bounce light sideways. Scatter alone separates intact cells "
                "from junk, before a single dye is involved, which is why it's "
                "the first gate."
            ),
            cyto_emotion="thinking",
            allow_interaction=True,
            target_widget_names=["FlowCanvas"],
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
                "• The debris cloud in the bottom-left corner<br>"
                "• A good chunk of splatter throughout the entire canvas<br><br>"
                "We want to draw a gate that excludes the debris. "
                "This ensures all downstream analysis excludes junk events.<br><br>"
                "When you draw the gate in the next step, a popup will ask you for its name. Be sure to call it **Cells**!"
            ),
            cyto_emotion="talking",
            next_step_id="c1_s23b_open_histogram",
        ),
        # First gate only: draw it with the gate histograms open, so the user
        # sees what the gate keeps on each channel. Switched back right after
        # (c1_s24a_back_to_properties) — later steps read the Properties view.
        VerificationStep(
            id="c1_s23b_open_histogram",
            text=(
                "Before you draw, let's open a second view of the gate.<br><br>"
                "At the top of the **Properties Panel** (right), click **Histogram** "
                "(highlighted).<br><br>"
                "It shows the same cells as two histograms — **FSC-A** on top, "
                "**SSC-A** below — and updates live while you draw."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["PropertiesViewToggle"],
            validator=PropertiesViewValidator(PROPERTIES_VIEW_HISTOGRAM),
            on_success_step_id="c1_s24_cells_gate",
            failure_hint="Click **Histogram** at the top of the Properties Panel on the right.",
        ),
        InteractionStep(
            id="c1_s24_cells_gate",
            text=(
                "Draw the gate:<br><br>"
                "1. Click **Polygon** in the Gating ribbon (highlighted above)<br>"
                "2. Click each vertex around the oval cell cloud on the plot (highlighted)<br>"
                "3. Double-click to close the polygon<br>"
                "4. Type **Cells** in the popup and hit Enter!<br><br>"
                "As you click, watch the **histograms** on the right (highlighted): "
                "the coloured part is what your gate keeps, the grey is what it leaves out.<br><br>"
                "Your gate will be evaluated automatically once you finish drawing."
            ),
            cyto_emotion="pointing",
            target_widget_name="MainPanel",
            event_trigger="gate_added_to_tree",
            target_widget_names=["Tool_polygon", "FlowCanvas", "GateHistogramPanel"],
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
            on_success_step_id="c1_s24a_back_to_properties",
            on_fail_step_id="c1_s24_cells_gate_retry",
        ),
        InfoStep(
            id="c1_s24_cells_gate_misnamed",
            text="I renamed the gate to **Cells** for you. Let's proceed!",
            cyto_emotion="happy",
            next_step_id="c1_s24a_back_to_properties",
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
        VerificationStep(
            id="c1_s24a_back_to_properties",
            text=(
                "Gate drawn. ✅<br><br>"
                "The **Histogram** view is there whenever you want a second look at "
                "a gate. The steps ahead read the gate's statistics, so click "
                "**Properties** (highlighted) to switch the panel back."
            ),
            cyto_emotion="happy",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["PropertiesViewToggle"],
            validator=PropertiesViewValidator(PROPERTIES_VIEW_PROPERTIES),
            on_success_step_id="c1_s24b_cells_hierarchy_intro",
            failure_hint="Click **Properties** at the top of the Properties Panel on the right.",
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
            next_step_id="c1_s12_comp_intro",
        ),
        # ── Phase 3 — Compensation ────────────────────────────────────────────
        InfoStep(
            id="c1_s12_comp_intro",
            text=(
                "Phase 3 — Compensation ⚖️<br><br>"
                "Every gate after **Cells** sits on a fluorescence channel, so "
                "the dyes have to be untangled first.<br><br>"
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
                "Look at the sample tree — every sample now has a **✦** "
                "tag next to its name. That's how Karcytics marks a sample as "
                "compensated, so at a glance you always know whether you're "
                "looking at raw or corrected data.<br><br>"
                "Before we look at that matrix, it's worth understanding "
                "what it is actually correcting — because **spillover** "
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
        QuestionStep(
            id="c1_s12e_spectral_theory_2",
            text=(
                "Spillover in action 🌈<br><br>"
                "FITC's glow spills into the PE detector. Without compensation, "
                "how does a cell that's bright for FITC but carries no PE look?"
            ),
            question_id="c1_spillover_effect",
            choices=[
                AnswerChoice(
                    "PE-negative, as it should",
                    feedback="The PE detector still catches FITC's shoulder, so its reading climbs even though there's no PE.",
                ),
                AnswerChoice(
                    "Dimmer for FITC",
                    feedback="Spillover adds to the neighbouring detector; it doesn't take away from FITC's own reading.",
                ),
                AnswerChoice("Falsely PE-positive", correct=True),
            ],
            explanation=(
                "Compensation fixes this: your Single Stains show what fraction "
                "of each dye leaks into each other detector, and that leak is "
                "subtracted from every event. First, let's look at the real "
                "spectra of the dyes in your panel."
            ),
            cyto_emotion="thinking",
            next_step_id="c1_sp43_verify_spectral_tab",
        ),
        # ── Why spillover happens: the Spectral viewer and masterclass ─────────
        VerificationStep(
            id="c1_sp43_verify_spectral_tab",
            text="Click the **Spectral** tab (highlighted) at the top.",
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["MainTabBar"],
            validator=TabActiveValidator(5),
            on_success_step_id="c1_sp44_spectral_intro",
        ),
        InfoStep(
            id="c1_sp44_spectral_intro",
            text=(
                "The **Spectral Viewer** 🌈<br><br>"
                "Every curve here is pulled live from **FPbase** — an open, "
                "community-maintained online database of real fluorescent "
                "protein and dye spectra (fpbase.org). This isn't simulated data; "
                "it's the actual physics of the dyes in your panel."
            ),
            cyto_emotion="talking",
            target_widget_names=["SpectralPlotArea"],
            next_step_id="c1_sp45_load_six",
        ),
        InfoStep(
            id="c1_sp45_load_six",
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
            next_step_id="c1_sp46_ab_ex_em_info",
        ),
        InfoStep(
            id="c1_sp46_ab_ex_em_info",
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
            next_step_id="c1_sp47_overlap_theory",
        ),
        InfoStep(
            id="c1_sp47_overlap_theory",
            text=(
                "Overlap isn't automatically a problem 🧠<br><br>"
                "Hover between two EM curves to see an **Overlap integral %**. "
                "CD3 (Pacific Blue) and B220 (FITC) may overlap somewhat, but "
                "it's harmless: a cell is essentially never both a T-cell and a "
                "B-cell, so spillover between those two channels can't create a "
                "biologically confusing double-positive population.<br><br>"
                "CD4 (PE) and CD8 (APC-Cy7) overlap matters more — thymocytes "
                "really can co-express both (you'll gate that double-positive "
                "population in Course 3). Overlap between markers that CAN legitimately "
                "co-occur needs careful compensation; overlap between markers on "
                "mutually-exclusive lineages usually doesn't."
            ),
            cyto_emotion="thinking",
            target_widget_names=["SpectralPlotArea"],
            next_step_id="c1_sp48_learning_switch",
        ),
        InteractionStep(
            id="c1_sp48_learning_switch",
            text=(
                "Let's put the theory into practice — click the **Learning "
                "Compensation** sub-tab inside this viewer."
            ),
            target_widget_name="SpectralTabs",
            target_widget_names=["SpectralTabs"],
            event_trigger="currentChanged",
            cyto_emotion="pointing",
            next_step_id="c1_sp49_slideshow",
        ),
        VerificationStep(
            id="c1_sp49_slideshow",
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
            on_success_step_id="c1_s13b_verify_comp_tab",
            failure_hint="Take your time working through the slideshow — I'll continue once you reach the final slide.",
            stuck_hint_after_ms=120000,
        ),
        # A VerificationStep, not an InteractionStep: if the user is already
        # on Compensation it passes at once (clicking the active tab emits
        # no currentChanged, so a click-wait would hang). Every tab switch
        # in the courses uses this one-step form.
        VerificationStep(
            id="c1_s13b_verify_comp_tab",
            text=(
                "Click the **Compensation** tab (highlighted) at the top — "
                "that's where Karcytics keeps its compensation tools."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["MainTabBar"],
            validator=TabActiveValidator(2),  # Compensation
            on_success_step_id="c1_m01_method_setup",
        ),
        # ── Judging the matrix you already have ───────────────────────────────
        InfoStep(
            id="c1_m01_method_setup",
            text=(
                "The **Compensation** tab ⚖️<br><br>"
                "There is more than one way to get a spillover matrix: read the "
                "one the cytometer saved in the files, estimate one from your "
                "controls, import one, or type it in. The **Method** dropdown "
                "(highlighted) picks which.<br><br>"
                "The tab opens on **Method setup**, which explains the selected "
                "method and shows what it would use. Yours is on *Embedded in "
                "the FCS files*: the default whenever the files carry a matrix."
            ),
            cyto_emotion="talking",
            target_widget_names=["CompensationMethodCombo", "CompensationSetupPageButton"],
            next_step_id="c1_m02_inputs",
        ),
        InfoStep(
            id="c1_m02_inputs",
            text=(
                "What the method will use 🔎<br><br>"
                "The table lists every sample and the matrix inside its file. One "
                "says *read from this sample*; the rest say *same matrix*: all ten "
                "tubes were run with one set of cytometer settings.<br><br>"
                "If a file ever says *different matrix*, stop and find out why "
                "before trusting either."
            ),
            cyto_emotion="thinking",
            target_widget_names=["MethodInputsTable"],
            next_step_id="c1_s14_extract_matrix",
        ),
        InteractionStep(
            id="c1_s14_extract_matrix",
            text=(
                "Click **📄 Extract from FCS** (highlighted).<br><br>"
                "This reads the matrix from the file and opens it on the "
                "**Matrix** page."
            ),
            target_widget_name="ExtractFCSButton",
            event_trigger="clicked",
            cyto_emotion="pointing",
            next_step_id="c1_m03_read_matrix",
        ),
        QuestionStep(
            id="c1_m03_read_matrix",
            text=(
                "Read the matrix 🔢<br><br>"
                "Each **row** is a dye; each **column** is a detector its light "
                "lands in. How much of **PE**'s signal lands in the "
                "**PerCP-Cy5-5** detector?"
            ),
            question_id="c1_pe_into_percp",
            choices=[
                AnswerChoice(
                    "0.04",
                    feedback="That's the other direction: the PerCP-Cy5-5 row, PE column. Start from the PE row.",
                ),
                AnswerChoice("0.30", correct=True),
                AnswerChoice(
                    "1.00",
                    feedback="That's the diagonal: a dye in its own detector, always 1. Look along the PE row.",
                ),
            ],
            explanation=(
                "PE row, PerCP-Cy5-5 column: for every 100 units of PE, that "
                "detector picks up 30. It is the largest value in this matrix, "
                "and PerCP-Cy5-5 is where PI, our live/dead dye, is read."
            ),
            cyto_emotion="thinking",
            allow_interaction=True,
            target_widget_names=["CompensationMatrixTable"],
            next_step_id="c1_m04_status_line",
        ),
        InfoStep(
            id="c1_m04_status_line",
            text=(
                "Where did these numbers come from? 🏷️<br><br>"
                "The status line (highlighted) always says: the matrix's size, the "
                "**method** behind it, and how many samples it is applied to. If "
                "you later change a value by hand, it says that too.<br><br>"
                "A matrix you can't trace is a matrix you can't defend."
            ),
            cyto_emotion="talking",
            target_widget_names=["CompensationStatusLine"],
            next_step_id="c1_m05_plot_pair",
        ),
        VerificationStep(
            id="c1_m05_plot_pair",
            text=(
                "Numbers are claims; the plots are the evidence.<br><br>"
                "1. Click the **0.3000** cell (PE row, PerCP-Cy5-5 column). The "
                "preview switches to that pair: the dye on X, the detector on Y.<br>"
                "2. Set **Sample** to **Sample A**, a tube with plenty of "
                "PE-bright cells."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["CompensationMatrixTable", "PreviewSampleCombo"],
            validator=PreviewShowsValidator(x="PE-A", y="PerCP-Cy5-5-A", sample_name="Sample A"),
            on_success_step_id="c1_m06_read_scatter",
            failure_hint=(
                "Click the 0.3000 cell in the PE-A row, then choose Sample A in the "
                "**Sample** dropdown above the plots."
            ),
        ),
        QuestionStep(
            id="c1_m06_read_scatter",
            text=(
                "Before and after 👀<br><br>"
                "Left: the raw signal. Right: the same cells with this matrix. "
                "The big cloud is PE-bright cells that carry no PI. With a good "
                "matrix, how should it sit on the **After** plot?"
            ),
            question_id="c1_compensated_shape",
            choices=[
                AnswerChoice(
                    "Climbing diagonally as PE gets brighter",
                    feedback="That's the raw plot: the brighter the PE, the more of it leaks into the other detector.",
                ),
                AnswerChoice(
                    "Dipping below the PE-negative cells",
                    feedback="That's over-compensation: the value is too high and takes away more than leaked in.",
                ),
                AnswerChoice("Level with the PE-negative cells", correct=True),
            ],
            explanation=(
                "Level is the goal: being bright for PE should say nothing about "
                "the PerCP-Cy5-5 detector. Tilted up means the value is too low; "
                "pushed down means too high."
            ),
            cyto_emotion="thinking",
            allow_interaction=True,
            target_widget_names=["CompensationPreviewArea"],
            next_step_id="c1_m07_view_both",
        ),
        VerificationStep(
            id="c1_m07_view_both",
            text=("A second way to look: set **View** (highlighted) to **Scatter + histograms**."),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["PreviewViewCombo"],
            validator=PreviewShowsValidator(view=PREVIEW_VIEW_BOTH),
            on_success_step_id="c1_m08_histograms",
            failure_hint="Open the **View** dropdown above the plots and pick Scatter + histograms.",
        ),
        InfoStep(
            id="c1_m08_histograms",
            text=(
                "Histograms: one detector at a time 📊<br><br>"
                "Grey is before, colour is after. In **PerCP-Cy5-5** the "
                "peak slides left: that signal was never PI, it was PE leaking "
                "in. **PE**'s own histogram barely moves, because little "
                "spills *into* PE.<br><br>"
                "Scatter shows whether a population is level; histograms show "
                "how far a whole detector's reading moved."
            ),
            cyto_emotion="talking",
            target_widget_names=["CompensationPreviewArea"],
            next_step_id="c1_m09_all_samples",
        ),
        VerificationStep(
            id="c1_m09_all_samples",
            text=(
                "One tube is one opinion. Set **Sample** (highlighted) to "
                "**All samples**: one row of plots per tube, drawn in the "
                "background."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["PreviewSampleCombo"],
            validator=PreviewShowsValidator(sample=PREVIEW_ALL_SAMPLES),
            on_success_step_id="c1_m10_why_all",
            failure_hint="Open the **Sample** dropdown and pick All samples, at the bottom of the list.",
        ),
        QuestionStep(
            id="c1_m10_why_all",
            text=(
                "Scroll through the rows 🧪<br><br>"
                "One matrix is applied to every tube. Why check it on all of "
                "them rather than on one?"
            ),
            question_id="c1_why_all_samples",
            choices=[
                AnswerChoice(
                    "A value can look right on one tube and be off on another",
                    correct=True,
                ),
                AnswerChoice(
                    "Each tube needs its own matrix",
                    feedback="One matrix serves the experiment: same dyes, same cytometer settings. The check is that it holds everywhere.",
                ),
                AnswerChoice(
                    "Only full-panel samples get compensated",
                    feedback="Controls are compensated too: an FMO only sets a threshold if it was treated like the samples.",
                ),
            ],
            explanation=(
                "A tube with few bright cells for a dye can't show whether that "
                "dye's value is right. Tubes that are bright there can. Looking "
                "across all of them covers every dye."
            ),
            cyto_emotion="thinking",
            allow_interaction=True,
            target_widget_names=["CompensationPreviewArea"],
            next_step_id="c1_m11_open_matrices",
        ),
        InteractionStep(
            id="c1_m11_open_matrices",
            text=("Every matrix you make is kept, by name. Click **🗂 Matrices** (highlighted)."),
            target_widget_name="CompensationMatricesPageButton",
            event_trigger="clicked",
            cyto_emotion="pointing",
            next_step_id="c1_m12_library",
        ),
        InfoStep(
            id="c1_m12_library",
            text=(
                "Your matrices 🗂<br><br>"
                "*Embedded in the FCS files* is listed and marked **✓ in use**: "
                "it is the one Karcytics applied on import. From this page you "
                "can compare two matrices, export one, or apply a different one "
                "to every sample.<br><br>"
                "Nothing to apply today. The cytometer's matrix is in use and, "
                "on the pair we checked, it does its job."
            ),
            cyto_emotion="happy",
            target_widget_names=["MatrixLibraryList"],
            next_step_id="c1_m13_prediction",
        ),
        QuestionStep(
            id="c1_m13_prediction",
            text=(
                "One for next time 🔮<br><br>"
                "In Course 2 you'll estimate a matrix from your **FMO** tubes. "
                "Each FMO lacks one dye, and shows what spills into that dye's "
                "detector. There is no PerCP-Cy5-5 FMO. What will the estimate "
                "say about spill into PerCP-Cy5-5?"
            ),
            kind=QUESTION_PREDICT,
            question_id="c1_fmo_blind_spot",
            choices=[
                AnswerChoice("Nothing: it has no tube to measure it from"),
                AnswerChoice("About the same 0.30 the file has"),
                AnswerChoice("A rough value worked out from the other tubes"),
            ],
            cyto_emotion="thinking",
            next_step_id="c1_s33b_save_interaction",
        ),
        VerificationStep(
            id="c1_s33b_save_interaction",
            text=(
                "Saving your progress 💾<br><br>"
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
                "All done! You've imported your samples, tagged their roles, "
                "drawn your first gate and compensated the data. 🚀<br><br>"
                "Your workspace is saved. In Course 2, we will use this exact "
                "setup to gate out dead cells and find the Leukocytes.<br><br>"
                "Click Next to collect your badge!"
            ),
            cyto_emotion="cheering",
            cyto_animation="cheering",
        ),
    ],
)
