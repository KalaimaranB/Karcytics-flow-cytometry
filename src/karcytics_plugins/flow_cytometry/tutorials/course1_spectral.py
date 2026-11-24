"""Course 1, why spillover happens, and how it's undone: the Spectral viewer and
the Learning Compensation deck.

Comes right after the mystery (CD4-bright cells that look PI-positive with
compensation off), in the order the ideas are needed:

1. **Emission** (theory, part 1): dyes glow over a broad hill of colours, so PE's
   light reaches the detector where PI is read.
2. **Excitation and lasers** (theory, part 2): a detector only sees dyes its own
   laser lights up, so only some overlaps matter.
3. **The deck**, which guides itself: find the overlap, set zero, measure the
   spillover, subtract it by hand, apply it to single cells, gate, and see what
   a full matrix takes. Cyto explains it once and stays quiet until it's done,
   then hands back to the Compensation tab.
"""

from __future__ import annotations

from karcytics_sdk.plugin.tutorial_models import (
    ActionStep,
    AnswerChoice,
    BaseStep,
    InfoStep,
    QuestionStep,
    VerificationStep,
)
from PySide6.QtWidgets import QAbstractButton, QWidget

from ..main_tabs import MainTab
from ..ui.academy_context import SPECTRAL_TAB_HIGHLIGHT_KEY
from .validators.base import TabActiveValidator
from .validators.setup import (
    LearningCompensationCompleteValidator,
    LearningCompensationTabOpenValidator,
)

DECK_DONE_STEP_ID = "c1_c21_switch_on"  # where Course 1 picks up after the deck


def _show_emission_curves(panel: QWidget) -> None:
    """ActionStep callback: turns the Spectral viewer's EM toggle back on.

    The step before lets the learner switch AB / EX / EM freely; the overlap
    callouts the next step points at are only drawn while EM is on.
    """
    button = panel.findChild(QAbstractButton, "SpectralEMToggle")
    if button is not None and not button.isChecked():
        button.setChecked(True)


# ── Theory, part 1: emission ──────────────────────────────────────────────────

_EMISSION_STEPS: list[BaseStep] = [
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
]

# ── Theory, part 2: excitation and lasers ─────────────────────────────────────

_LASER_STEPS: list[BaseStep] = [
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
]

# ── The Learning Compensation deck ────────────────────────────────────────────

# The deck guides itself (👉 Your turn, 💡 Show me, 🧮 on every slide), so
# Cyto explains it once, then stays out of the way until the last slide is
# done: one bubble the learner closes, and no banner while they work.
DECK_QUIET_MS = 25 * 60_000  # longer than the slowest learner should need

_DECK_STEPS: list[BaseStep] = [
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
]


SPECTRAL_STEPS: list[BaseStep] = [*_EMISSION_STEPS, *_LASER_STEPS, *_DECK_STEPS]
