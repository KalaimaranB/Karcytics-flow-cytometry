"""Course 1 — Flow Cytometry Fundamentals.

Three phases, each ending with a three-line recap:

1. **Setup:** import the 10 tutorial files and tag each tube's role.
2. **First gate:** read the scatter plot, then draw **Cells** from scatter alone.
3. **Compensation, problem first:** with compensation OFF, CD4-bright cells look
   PI-positive (the mystery). The Spectral viewer (emission, then lasers) and the
   Learning Compensation deck explain why; compensation back ON is the payoff.
   Then the learner reads the real matrix, checks it, and saves the workspace
   Course 2 starts from.

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

from karcytics_sdk.plugin import CentralEventBus
from karcytics_sdk.plugin.tutorial_models import (
    QUESTION_PREDICT,
    ActionStep,
    AnswerChoice,
    ConsentStep,
    Course,
    InfoStep,
    InteractionStep,
    QuestionStep,
    VerificationStep,
)
from PySide6.QtWidgets import QAbstractButton, QWidget

from karcytics_plugins.flow_cytometry.analysis import events

from ..analysis.constants import PROPERTIES_VIEW_HISTOGRAM, PROPERTIES_VIEW_PROPERTIES
from ..main_tabs import MainTab
from ..ui.academy_context import MATRIX_HIGHLIGHT_KEY, SPECTRAL_TAB_HIGHLIGHT_KEY
from .constants import PREVIEW_ALL_SAMPLES
from .tutorial_assets import describe_files_location, start_provisioning
from .validators.base import (
    AllOf,
    PropertiesViewValidator,
    TabActiveValidator,
    WorkflowSavedValidator,
)
from .validators.compensation import CompensationSwitchValidator, PreviewShowsValidator
from .validators.gating import AxisChannelValidator, AxisYChannelValidator, GateShapeValidator
from .validators.setup import (
    ExactSampleOpenValidator,
    FlowImportValidator,
    FmoRoleValidator,
    LearningCompensationCompleteValidator,
    LearningCompensationTabOpenValidator,
    RoleAssignmentValidator,
    SampleOpenValidator,
    SingleStainRoleValidator,
    TutorialFilesProvisionedValidator,
    UnstainedRoleValidator,
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
            if remaining_count < 10:  # noqa: PLR2004 - course content: the dataset's 10 samples
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
# Spectral viewer and Learning Compensation deck helpers
# ==============================================================================

DECK_DONE_STEP_ID = "c1_c21_switch_on"  # where Course 1 picks up after the deck

# The deck guides itself (👉 Your turn, 💡 Show me, 🧮 on every slide), so
# Cyto explains it once, then stays out of the way until the last slide is
# done: one bubble the learner closes, and no banner while they work.
DECK_QUIET_MS = 25 * 60_000  # longer than the slowest learner should need


def _show_emission_curves(panel: QWidget) -> None:
    """ActionStep callback: turns the Spectral viewer's EM toggle back on.

    The step before lets the learner switch AB / EX / EM freely; the overlap
    callouts the next step points at are only drawn while EM is on.
    """
    button = panel.findChild(QAbstractButton, "SpectralEMToggle")
    if button is not None and not button.isChecked():
        button.setChecked(True)


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
# Three phases: Setup → First gate (Cells) → Compensation. Each ends with a
# three-line recap. Compensation starts from a mystery (compensation OFF) and
# ends with its payoff (ON); the Spectral viewer and the deck sit in between.
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


def _set_import_step_text(_panel: QWidget) -> None:
    """ActionStep callback: fills in `_import_step.text` with the real
    location the tutorial files were found/downloaded to, resolved by the
    preceding provisioning step (see `tutorial_assets.ensure_tutorial_files`).
    """

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
        "first gate, and solve a spillover mystery to see why and how the "
        "data is compensated."
    ),
    estimated_minutes=50,  # first estimate after the scaffolding rework; re-time live
    badge_reward="Flow Fundamentalist",
    badge_icon="🔬",
    prerequisite_course_ids=[],
    steps=[
        # ── Intro ────────────────────────────────────────────────────────────
        InfoStep(
            id="c1_s1_intro",
            text=(
                "Welcome to Karcytics Flow Cytometry! 🧬<br><br>"
                "Imagine, you are a busy graduate student, and you "
                "isolated cells from three different mouse tissues: "
                "spleen, thymus and bone marrow. However, much to your dismay, "
                "you forgot to label the samples with the type of tissue they came from! "
                "Today's mystery: 3 unknown samples — one is Spleen, one is "
                "Thymus, one is Bone Marrow. Immune cells distributions look different "
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
                "The thymus is where T cells mature and undergo positive "
                "and negative selection. Which cells do you "
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
                "cytometer."
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
                "Cells were labeled with an APC-conjugated anti-CD45 antibody. Later you'll need to "
                "know how bright a cell can be *without* CD45. Which file "
                "shows you that?"
            ),
            question_id="c1_cd45_background",
            choices=[
                AnswerChoice(
                    "Blank",
                    feedback="Close, but the blank contains no fluorophores, so it does not capture the spillover from the other dyes into the APC detector. Its lower boundary is therefore too low.",
                ),
                AnswerChoice("FMO APC", correct=True),
                AnswerChoice(
                    "Sample A",
                    feedback="Sample A contains APC-conjugated anti-CD45, its true APC signal prevents assessment of the spillover/background into the APC channel",
                ),
            ],
            explanation=(
                "The APC FMO includes all fluorophores except APC, "
                "matching the spillover into the APC channel while "
                "lacking true CD45 signal. Its APC signal is background, "
                "defining the CD45-negative boundary."
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
                "fluorophore *except* one, letting us clearly see the boundary between "
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
                "Phase 1 in three lines 📝<br><br>"
                "• **Import:** your 10 files are in, all in one group.<br>"
                "• **Roles** tell Karcytics what each tube is for: Single Stains "
                "help measure spillover, Full Panels are the samples you "
                "analyse, and FMOs show where 'negative' ends for gating.<br>"
                "• FMOs are left out of the final statistics, so they don't skew "
                "your sample averages."
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
            validator=TabActiveValidator(MainTab.GATING),
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
        # Read the scatter plot first: where debris sits, what the second cluster says
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
                "Fragments produce little forward scatter and have little internal structure "
                "to scatter light sideways. Because forward and side scatter can distinguish "
                "intact cells from debris without any fluorescent label, this FSC/SSC gate "
                "is typically the first step."
            ),
            cyto_emotion="thinking",
            allow_interaction=True,
            target_widget_names=["FlowCanvas"],
            next_step_id="c1_s22e_scatter_clusters",
        ),
        # Reflection: what scatter says about the cells themselves (not just debris).
        QuestionStep(
            id="c1_s22e_scatter_clusters",
            text=(
                "Now look past the debris 🔍<br><br>"
                "Above and to the right of the dense lower-left cloud there's a "
                "second, looser cluster: higher **FSC** *and* higher **SSC**.<br><br>"
                "Remember, this tube is unstained, so this is pure light scatter. "
                "What does that position tell you about those cells?"
            ),
            question_id="c1_scatter_clusters",
            choices=[
                AnswerChoice(
                    "They're larger and more internally complex (more granules and organelles)",
                    correct=True,
                ),
                AnswerChoice(
                    "They carry more fluorescent dye",
                    feedback=(
                        "This sample has no dye at all. FSC and SSC are scattered laser "
                        "light, so they describe the cell's physical build."
                    ),
                ),
                AnswerChoice(
                    "They're dead or dying cells",
                    feedback=(
                        "Dying cells usually shrink, so FSC drops. Scatter alone can't "
                        "confirm death, which is why we add the viability dye (PI) later."
                    ),
                ),
                AnswerChoice(
                    "It just means there are more of them",
                    feedback=(
                        "A position on the plot is a measurement per cell. How many cells "
                        "there are shows up as how dense the cloud is."
                    ),
                ),
            ],
            explanation=(
                "Higher FSC means a bigger cell; higher SSC means more inside it "
                "(granules, organelles, a lobed nucleus). Small, smooth lymphocytes "
                "sit low on both axes; granular myeloid cells like granulocytes sit "
                "up and right. So even without antibodies, scatter hints at which "
                "cell types a tissue holds."
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
                "This hierarchy tracks all populations. By default, the gates you apply to one sample will propagate to all other samples in the same group.<br><br>"
                "Made a mistake while gating? **Ctrl+Z** (**Cmd+Z** on a Mac) undoes your last change."
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
            next_step_id="c1_s25b_gate_recap",
        ),
        InfoStep(
            id="c1_s25b_gate_recap",
            text=(
                "Phase 2 in three lines 📝<br><br>"
                "• **Gates** are regions you draw around cells; each one narrows "
                "down inside the last, like a funnel.<br>"
                "• **FSC** (size) and **SSC** (inner complexity) need no dye, so "
                "the **Cells** gate can come first.<br>"
                "• Gates spread to every sample in the same **group**, and "
                "**Ctrl+Z / Cmd+Z** undoes a mistake."
            ),
            cyto_emotion="happy",
            next_step_id="c1_c02_comp_tab",
        ),
        # ── Phase 3 — The mystery: compensation OFF ───────────────────────────
        # A VerificationStep, not an InteractionStep: if the user is already
        # on the tab it passes at once (clicking the active tab emits no
        # currentChanged, so a click-wait would hang). Every tab switch in the
        # courses uses this one-step form.
        VerificationStep(
            id="c1_c02_comp_tab",
            text=(
                "Phase 3 — Compensation ⚖️<br><br>"
                "Every gate after **Cells** uses the light from the dyes. Before you "
                "trust it, there's a puzzle to solve. Click the **Compensation** tab "
                "(highlighted) at the top."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["MainTabBar"],
            validator=TabActiveValidator(MainTab.COMPENSATION),
            on_success_step_id="c1_c03_switch_off",
        ),
        VerificationStep(
            id="c1_c03_switch_off",
            text=(
                "This switch (highlighted) turns **compensation** on or off for "
                "every sample. It's **ON** now: that's what the ✦ next to each "
                "sample means.<br><br>"
                "Click it to turn compensation **OFF**, so you see the readings "
                "exactly as the cytometer recorded them."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["CompensationSwitch"],
            validator=CompensationSwitchValidator(on=False),
            on_success_step_id="c1_c05_open_sample_a",
            failure_hint="Click **Compensation: ON ✦** in the Compensation tab's header.",
        ),
        VerificationStep(
            id="c1_c05_open_sample_a",
            text=(
                "Compensation is **OFF** (the ✦ marks are gone). Go back to the "
                "**Gating** tab and double-click **Sample A** in the **Sample List**."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["MainTabBar", "SampleList"],
            validator=AllOf(
                TabActiveValidator(MainTab.GATING), ExactSampleOpenValidator("Sample A")
            ),
            on_success_step_id="c1_c06_set_axes",
            failure_hint="Open the **Gating** tab, then double-click **Sample A** in the Sample List.",
        ),
        VerificationStep(
            id="c1_c06_set_axes",
            text=(
                "Put two dyes on the plot:<br>"
                "• **X:** → **PE-A** (the CD4 marker, on T helper cells)<br>"
                "• **Y:** → **PerCP-Cy5-5-A** (where **PI** is read; PI marks dead "
                "cells)"
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["AxisSelectorX", "AxisSelectorY"],
            validator=AllOf(AxisChannelValidator("pe-a"), AxisYChannelValidator("percp")),
            on_success_step_id="c1_c07_mystery",
            failure_hint="Set the **X:** dropdown to **PE-A** and the **Y:** dropdown to **PerCP-Cy5-5-A**.",
        ),
        QuestionStep(
            id="c1_c07_mystery",
            text=(
                "The mystery 🕵️<br><br>"
                "Look at the brightest CD4 cells (far right). They sit higher on "
                "the PI axis than the dim ones, and many look PI-positive. PI "
                "marks dead cells. Are bright CD4 T cells especially likely to be "
                "dead?"
            ),
            kind=QUESTION_PREDICT,
            question_id="c1_dead_or_not",
            choices=[
                AnswerChoice("Yes, many of them are dead"),
                AnswerChoice("Something else makes them look PI-positive"),
                AnswerChoice("Can't tell from this plot"),
            ],
            cyto_emotion="thinking",
            allow_interaction=True,
            target_widget_names=["FlowCanvas"],
            next_step_id="c1_sp43_verify_spectral_tab",
        ),
        # ── Why it happens, part 1: emission ──────────────────────────────────────
        VerificationStep(
            id="c1_sp43_verify_spectral_tab",
            text=(
                "To solve it, look at the light itself. Click the **Spectral** tab "
                "(highlighted) at the top."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["MainTabBar"],
            validator=TabActiveValidator(MainTab.SPECTRAL),
            on_success_step_id="c1_sp45_load_six",
        ),
        InfoStep(
            id="c1_sp45_load_six",
            text=(
                "The **Spectral Viewer** 🌈<br><br>"
                "Karcytics read your panel's 6 fluorescence channels from the files "
                "and plotted each **dye's** real, measured spectrum from **FPbase**, "
                "an open database of dyes (cited under the viewer): FITC, PE, PI, "
                "Pacific Blue, APC-Cy7 and APC.<br><br>"
                "Each legend entry shows the **marker** the dye is attached to, like "
                "**CD45 (APC-A)**. CD45 is a protein on the cell with no colour of "
                "its own; the colour comes from the dye on the antibody. So "
                "spillover is about dyes, not markers.<br><br>"
                "PI is the odd one out: it isn't an antibody tag but a dye in its own "
                "right, read in the **PerCP-Cy5.5** detector, so Karcytics plotted "
                "PI's own spectrum."
            ),
            cyto_emotion="happy",
            target_widget_names=["SpectralSourceList", "SpectralCitation"],
            next_step_id="c1_sp45b_broad_hills",
        ),
        InfoStep(
            id="c1_sp45b_broad_hills",
            text=(
                "Where does spillover come from? ⛰️<br><br>"
                "A dye doesn't glow at one exact colour. It glows across a broad hill "
                "of wavelengths, often 100 nm wide or more. Each detector sits under "
                "the peak of one dye's hill, but the hills' shoulders reach into "
                "neighbouring detectors.<br><br>"
                "Find **CD4 (PE)** and **PI** in the legend. PE's hill runs on past "
                "600 nm, right into the colours where PI is read."
            ),
            cyto_emotion="thinking",
            target_widget_names=["SpectralPlotArea"],
            next_step_id="c1_s12e_spectral_theory_2",
        ),
        QuestionStep(
            id="c1_s12e_spectral_theory_2",
            text=(
                "Spillover in action 🌈<br><br>"
                "Some of PE's light lands in the detector where PI is read. Without "
                "compensation, how does a cell that's bright for PE (CD4) but has no "
                "PI look?"
            ),
            question_id="c1_spillover_effect",
            choices=[
                AnswerChoice(
                    "PI-negative, as it should",
                    feedback="The PI detector still catches PE's shoulder, so its reading climbs even though there's no PI.",
                ),
                AnswerChoice(
                    "Dimmer for PE",
                    feedback="Spillover adds to the neighbouring detector; it doesn't take away from PE's own reading.",
                ),
                AnswerChoice("Falsely PI-positive, so it looks dead", correct=True),
            ],
            explanation=(
                "That's a strong lead for your 'dead' CD4 cells. But plenty of curves "
                "overlap here, and not every overlap causes trouble. The next idea, "
                "lasers, explains which ones do."
            ),
            cyto_emotion="thinking",
            allow_interaction=True,
            target_widget_names=["SpectralPlotArea"],
            next_step_id="c1_sp46_ab_ex_em_info",
        ),
        # ── Why it happens, part 2: lasers ────────────────────────────────────────
        InfoStep(
            id="c1_sp46_ab_ex_em_info",
            text=(
                "Lasers light the dyes 🔦<br><br>"
                "A dye only glows when light of the right colour hits it:<br>"
                "• **EX** (excitation): the colours that make the dye glow. It tells "
                "you which laser lights it, e.g. the 488 nm blue laser.<br>"
                "• **AB** (absorbance): the colours it soaks up, close to EX.<br>"
                "• **EM** (emission): the colours it glows back, caught by a "
                "detector.<br><br>"
                "Your cytometer has three lasers: violet (405 nm), blue (488 nm) and "
                "red (640 nm), and each detector sits behind one of them. Try the "
                "**AB / EX / EM** buttons (highlighted) to see each set of curves."
            ),
            cyto_emotion="talking",
            allow_interaction=True,
            target_widget_names=["SpectralABToggle", "SpectralEXToggle", "SpectralEMToggle"],
            next_step_id="c1_sp46b_show_emission",
        ),
        ActionStep(
            id="c1_sp46b_show_emission",
            text="Switching the emission curves back on...",
            action=_show_emission_curves,
            next_step_id="c1_sp46c_laser_question",
        ),
        QuestionStep(
            id="c1_sp46c_laser_question",
            text=(
                "Do lasers matter? 🔦<br><br>"
                "Pacific Blue's emission overlaps FITC's. But Pacific Blue is lit by "
                "the violet laser, and FITC's detector sits behind the blue laser, "
                "which barely excites Pacific Blue. How much Pacific Blue light ends "
                "up in FITC's detector?"
            ),
            question_id="c1_laser_matters",
            choices=[
                AnswerChoice(
                    "A lot: their curves overlap",
                    feedback="Overlapping emission only counts if the dye is glowing in that detector's laser beam. The blue laser leaves Pacific Blue nearly dark.",
                ),
                AnswerChoice("Very little: the blue laser barely lights it", correct=True),
                AnswerChoice(
                    "Exactly the overlap shown on the plot",
                    feedback="The plot shows emission only. Whether that light is produced in the right beam depends on the laser too.",
                ),
            ],
            explanation=(
                "Spillover needs both: a dye's light must overlap the detector's colours, "
                "and that detector's laser must light the dye. PE and PI are both lit by "
                "the blue laser, so their overlap really counts."
            ),
            cyto_emotion="thinking",
            target_widget_names=["SpectralPlotArea"],
            next_step_id="c1_sp47_overlap_callouts",
        ),
        InfoStep(
            id="c1_sp47_overlap_callouts",
            text=(
                "Reading the overlap callouts 🔍<br><br>"
                "Karcytics marks every pair of emission curves that overlap: the "
                "hatched white area is the shared light, and each callout gives an "
                "**Overlap integral %**. Click a callout to dismiss it.<br><br>"
                "Those % come from emission curves alone. Lasers and filters change "
                "the real spillover, which is why labs measure it with controls."
            ),
            cyto_emotion="talking",
            target_widget_names=["SpectralPlotArea"],
            next_step_id="c1_sp47b_which_overlap_matters",
        ),
        QuestionStep(
            id="c1_sp47b_which_overlap_matters",
            text=(
                "Overlap isn't automatically a problem 🧠<br><br>"
                "Two overlaps in your panel: **CD3** (Pacific Blue) with **B220** "
                "(FITC), and **CD4** (PE) with **PI**, the live/dead dye read in "
                "the PerCP-Cy5.5 detector. Left uncorrected, which one could quietly "
                "distort your results?"
            ),
            question_id="c1_overlap_that_matters",
            choices=[
                AnswerChoice(
                    "CD3 with B220",
                    feedback=(
                        "T cells and B cells are separate lineages, so spilled light "
                        "can't invent a believable double-positive. And different "
                        "lasers (405 vs 488 nm) light the two dyes, so little of "
                        "that light reaches the other's detector."
                    ),
                ),
                AnswerChoice("CD4 with PI", correct=True),
                AnswerChoice(
                    "Neither: they're well under 50%",
                    feedback=(
                        "A few percent of a very bright dye is enough to push a "
                        "negative cell past a gate. The size of the overlap matters "
                        "less than what the two signals mean."
                    ),
                ),
            ],
            explanation=(
                "Spillover between PE and PI makes bright, live CD4 cells look dead, so "
                "a live/dead gate would throw real CD4 T cells away. Overlap matters "
                "when both signals can sit on one cell, or one drives a gating decision."
            ),
            cyto_emotion="thinking",
            target_widget_names=["SpectralPlotArea"],
            next_step_id="c1_sp48_learning_switch",
        ),
        # ── The Learning Compensation deck ────────────────────────────────────────
        # A VerificationStep, like every tab switch in the courses: a learner
        # already on the sub-tab passes at once. The spotlight is the tab itself,
        # via the viewer's get_tutorial_target_rects hook (a tab isn't a QWidget
        # the driver's name lookup can find).
        VerificationStep(
            id="c1_sp48_learning_switch",
            text=(
                "Now put the theory to work: click the **Learning Compensation** "
                "sub-tab (highlighted) just above the plot."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            metadata={SPECTRAL_TAB_HIGHLIGHT_KEY: "learning"},
            validator=LearningCompensationTabOpenValidator(),
            on_success_step_id="c1_sp49_work_through_deck",
        ),
        VerificationStep(
            id="c1_sp49_work_through_deck",
            text=(
                "The **Learning Compensation** deck 📚<br><br>"
                "Seven short slides that take you from overlapping light to a full "
                "matrix, with numbers from your own dyes. On each one:<br>"
                "• **👉 Your turn** (top left) says what to do<br>"
                "• **💡 Show me** (top right) draws it if you're stuck<br>"
                "• **🧮** does any sum for you<br><br>"
                "Press **Got it** and I'll stay out of the way until you finish the "
                "last slide."
            ),
            cyto_emotion="talking",
            allow_interaction=True,
            hide_next_button=True,
            manual_dismiss_bubble=True,
            target_widget_names=["SpectralLearningTab"],
            validator=LearningCompensationCompleteValidator(),
            on_success_step_id=DECK_DONE_STEP_ID,
            stuck_hint_text="Still going? 💡 Show me on any slide draws what it needs.",
            stuck_hint_after_ms=DECK_QUIET_MS,
        ),
        # ── The payoff: compensation back ON ──────────────────────────────────
        VerificationStep(
            id="c1_c21_switch_on",
            text=(
                "Deck done! 🎓 Time to solve the mystery. Open the **Compensation** "
                "tab and click the switch to turn compensation back **ON**. Every "
                "sample gets the spillover taken off, as you did on the slider."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["MainTabBar", "CompensationSwitch"],
            validator=CompensationSwitchValidator(on=True),
            on_success_step_id="c1_c22_gating_tab",
            failure_hint="In the **Compensation** tab, click **Compensation: OFF** in the header.",
        ),
        VerificationStep(
            id="c1_c22_gating_tab",
            text=(
                "Compensation is **ON** again (the ✦ marks are back). Go to the "
                "**Gating** tab (highlighted): Sample A is still on PE vs PI."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["MainTabBar"],
            validator=TabActiveValidator(MainTab.GATING),
            on_success_step_id="c1_c23_payoff",
        ),
        InfoStep(
            id="c1_c23_payoff",
            text=(
                "Mystery solved 🔍<br><br>"
                "Far fewer of the bright CD4 cells look PI-positive now. Most of "
                "that 'PI' was **PE light landing in the PI detector**: spillover. "
                "The cells weren't dead; the reading was wrong.<br><br>"
                "You predicted: *{answer:c1_dead_or_not}*.<br><br>"
                "Without compensation, a live/dead gate here would have thrown "
                "away healthy CD4 T cells."
            ),
            cyto_emotion="cheering",
            target_widget_names=["FlowCanvas"],
            next_step_id="c1_c25_comp_tab",
        ),
        VerificationStep(
            id="c1_c25_comp_tab",
            text=(
                "Where did that correction come from? 🗂<br><br>"
                "The cytometer measured the spillover itself, with single-stain "
                "tubes like the ones on the deck's last slide, and saved it in your "
                "files (a **$SPILL** keyword). Karcytics applied it on loading: the "
                "✦ on every sample.<br><br>"
                "Click the **Compensation** tab (highlighted) to see those numbers."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["MainTabBar"],
            validator=TabActiveValidator(MainTab.COMPENSATION),
            on_success_step_id="c1_s14_extract_matrix",
        ),
        # ── Reading the real matrix ───────────────────────────────────────────
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
            next_step_id="c1_c26_matrix_row",
        ),
        InfoStep(
            id="c1_c26_matrix_row",
            text=(
                "Reading the matrix, part 1: rows 👉<br><br>"
                "Each **row** is a **dye**. This one is **PE**'s row: it says "
                "where PE's light goes. The 1 is PE in its own detector; the "
                "other numbers are how much of it spills into each other detector."
            ),
            cyto_emotion="pointing",
            target_widget_names=["CompensationMatrixTable"],
            metadata={MATRIX_HIGHLIGHT_KEY: {"row": "PE-A"}},
            next_step_id="c1_c27_matrix_column",
        ),
        InfoStep(
            id="c1_c27_matrix_column",
            text=(
                "Part 2: columns 👇<br><br>"
                "Each **column** is a **detector**. This one is the "
                "**PerCP-Cy5.5** detector, where PI is read: it says how much "
                "of every dye's light lands there."
            ),
            cyto_emotion="pointing",
            target_widget_names=["CompensationMatrixTable"],
            metadata={MATRIX_HIGHLIGHT_KEY: {"column": "PerCP-Cy5-5-A"}},
            next_step_id="c1_m03_read_matrix",
        ),
        QuestionStep(
            id="c1_m03_read_matrix",
            text=(
                "Read the matrix 🔢<br><br>"
                "This cell (highlighted) is where PE's row meets the PI detector's "
                "column: the spillover behind your mystery. How much of **PE**'s "
                "signal lands in the **PerCP-Cy5-5** detector?"
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
                "0.30 means 30%: for every 100 units of PE, the PI detector reads 30 "
                "extra. It's the largest value in this matrix, which is why bright CD4 "
                "cells looked dead."
            ),
            cyto_emotion="thinking",
            allow_interaction=True,
            target_widget_names=["CompensationMatrixTable"],
            metadata={MATRIX_HIGHLIGHT_KEY: {"row": "PE-A", "column": "PerCP-Cy5-5-A"}},
            next_step_id="c1_m05_plot_pair",
        ),
        VerificationStep(
            id="c1_m05_plot_pair",
            text=(
                "The switch flips every sample at once. To *judge* a matrix, the "
                "preview shows before and after side by side.<br><br>"
                "1. Click the **0.3000** cell (PE row, PerCP-Cy5-5 column). The "
                "preview switches to that pair: the dye on X, the detector on Y.<br>"
                "2. Set **Sample** to **Sample A**."
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
                    feedback="That's the raw plot: the brighter the PE, the more of it spills into the other detector.",
                ),
                AnswerChoice(
                    "Dipping below the PE-negative cells",
                    feedback="That's over-compensation, like pushing the deck's slider too far: more is taken off than spilled in.",
                ),
                AnswerChoice("Level with the PE-negative cells", correct=True),
            ],
            explanation=(
                "Level is the goal, exactly as on the deck's slider: being bright for PE "
                "should say nothing about the PI detector. Tilted up means the value is "
                "too low; pushed down means too high."
            ),
            cyto_emotion="thinking",
            allow_interaction=True,
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
            next_step_id="c1_c30_recap",
        ),
        InfoStep(
            id="c1_c30_recap",
            text=(
                "Compensation in three lines 📝<br><br>"
                "• **Why:** a dye's light also lands in other dyes' detectors "
                "(spillover), and can fake a signal, like 'dead' CD4 cells.<br>"
                "• **What the number means:** 0.30 = for every 100 units of PE, "
                "the PI detector reads 30 extra. Compensation takes that much off "
                "every cell.<br>"
                "• **How to check it:** single-dye cells should sit level with the "
                "negative cells, not climbing and not dipping, in every tube."
            ),
            cyto_emotion="happy",
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
                "Course 2 builds on this workspace, so save it now (with "
                "compensation **ON**).<br><br>"
                "Click the **⚠️ Save Workspace** button (highlighted) at the top right.<br><br>"
                "Give it a name like **Learning flow with Cyto!** and click Save."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["WorkspaceSaveButton"],
            validator=AllOf(CompensationSwitchValidator(on=True), WorkflowSavedValidator()),
            on_success_step_id="c1_s34_graduation",
            failure_hint=(
                "Make sure compensation is **ON** (Compensation tab header), then click "
                "**⚠️ Save Workspace**, give it a name, and click Save."
            ),
        ),
        InfoStep(
            id="c1_s34_graduation",
            text=(
                "All done! You've imported your samples, tagged their roles, "
                "drawn your first gate, and solved a spillover mystery. 🚀<br><br>"
                "Your workspace is saved. In Course 2, we will use this exact "
                "setup to gate out dead cells and find the Leukocytes.<br><br>"
                "Click Next to collect your badge!"
            ),
            cyto_emotion="cheering",
            cyto_animation="cheering",
        ),
    ],
)
