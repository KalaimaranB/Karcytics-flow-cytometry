"""Course 1, Phase 3: compensation, problem first.

The learner turns compensation OFF and meets CD4-bright cells that look
PI-positive (the mystery), learns why in the Spectral viewer and the Learning
Compensation deck (course1_spectral), turns compensation back ON for the
payoff, then reads the real matrix and checks it. Ends with the save Course 2
starts from.
"""

from __future__ import annotations

from karcytics_sdk.plugin.tutorial_models import (
    QUESTION_PREDICT,
    AnswerChoice,
    BaseStep,
    InfoStep,
    InteractionStep,
    QuestionStep,
    VerificationStep,
)

from ..main_tabs import MainTab
from ..ui.academy_context import MATRIX_HIGHLIGHT_KEY
from .constants import PREVIEW_ALL_SAMPLES
from .course1_spectral import SPECTRAL_STEPS
from .validators.base import AllOf, TabActiveValidator, WorkflowSavedValidator
from .validators.compensation import CompensationSwitchValidator, PreviewShowsValidator
from .validators.gating import AxisChannelValidator, AxisYChannelValidator
from .validators.setup import ExactSampleOpenValidator

COMPENSATION_STEPS: list[BaseStep] = [
    # ── The mystery: compensation OFF ─────────────────────────────────────
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
        validator=AllOf(TabActiveValidator(MainTab.GATING), ExactSampleOpenValidator("Sample A")),
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
    *SPECTRAL_STEPS,
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
]
