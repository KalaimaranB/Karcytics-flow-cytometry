"""Course 1, why spillover happens: the Spectral viewer and the Compensation Masterclass.

The learner loads the panel's dyes in the Spectral viewer, reads the overlap
callouts, judges which overlap matters, then works through the Learning
Compensation slideshow. Its last step hands back to the Compensation tab.
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


def _show_emission_curves(panel: QWidget) -> None:
    """ActionStep callback: turns the Spectral viewer's EM toggle back on.

    The step before lets the learner switch AB / EX / EM freely; the overlap
    callouts the next step points at are only drawn while EM is on.
    """
    button = panel.findChild(QAbstractButton, "SpectralEMToggle")
    if button is not None and not button.isChecked():
        button.setChecked(True)


SPECTRAL_STEPS: list[BaseStep] = [
    VerificationStep(
        id="c1_sp43_verify_spectral_tab",
        text="Click the **Spectral** tab (highlighted) at the top.",
        cyto_emotion="pointing",
        allow_interaction=True,
        hide_next_button=True,
        target_widget_names=["MainTabBar"],
        validator=TabActiveValidator(MainTab.SPECTRAL),
        on_success_step_id="c1_sp44_spectral_intro",
    ),
    InfoStep(
        id="c1_sp44_spectral_intro",
        text=(
            "The **Spectral Viewer** 🌈<br><br>"
            "Every curve here is pulled live from **FPbase** — an open, "
            "community-maintained online database of real fluorescent "
            "protein and dye spectra (fpbase.org). This isn't simulated data; "
            "The full citation sits under the viewer, with links to FPbase and "
            "its paper."
        ),
        cyto_emotion="talking",
        target_widget_names=["SpectralPlotArea", "SpectralCitation"],
        next_step_id="c1_sp45_load_six",
    ),
    InfoStep(
        id="c1_sp45_load_six",
        text=(
            "Karcytics read your panel's 6 fluorescence channels from the FCS "
            "headers and plotted each **fluorophore's** spectrum automatically: "
            "FITC, PE, PI, Pacific Blue, APC-Cy7 and APC.<br><br>"
            "PI is the odd one out: it isn't an antibody tag but a dye in its "
            "own right, read in the **PerCP-Cy5.5** detector, so Karcytics "
            "plotted PI's own spectrum rather than PerCP-Cy5.5's.<br><br>"
            "Each legend entry also shows the **marker** that dye is attached to, "
            "like **CD45 (APC-A)**. A marker such as CD45 is just a protein on the "
            "cell and has no colour of its own. The colour comes from the "
            "fluorophore on the antibody, so spillover is a property of the "
            "dyes, not the markers.<br><br>"
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
            "• **EX** (Excitation) — the wavelengths that make the dye 'light "
            "up'. This tells you which laser to use, such as the 488 nm blue laser."
            "• **EM** (Emission) — the wavelengths the dye emits. This tells you "
            "which detector captures the signal."
            "Try the **AB / EX / EM** buttons (highlighted) to see each curve "
            "set on its own. Spillover is about **EM**: it's emitted light "
            "landing in the wrong detector."
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
        next_step_id="c1_sp47_overlap_callouts",
    ),
    InfoStep(
        id="c1_sp47_overlap_callouts",
        text=(
            "Reading the overlap callouts 🔍<br><br>"
            "Karcytics has already marked every pair of emission curves that "
            "overlap: the hatched white area is the shared light, and each "
            "callout gives an **Overlap integral %** for that pair. That's why "
            "the plot is busy as soon as it loads. Click a callout to dismiss "
            "it.<br><br>"
            "The % is estimated from the published spectra alone. Your "
            "cytometer's lasers and filters shift the real spillover, which is "
            "why we still measure it from controls."
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
            "the PerCP-Cy5.5 detector. Left uncorrected, which one could quietly distort your "
            "results?"
        ),
        question_id="c1_overlap_that_matters",
        choices=[
            AnswerChoice(
                "CD3 with B220",
                feedback=(
                    "T cells and B cells are separate lineages, so leaked light "
                    "can't invent a believable double-positive. And different "
                    "lasers (405 vs 488 nm) excite the two dyes, so little of "
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
            "PE leaking into the PI detector makes bright, live CD4+ cells look "
            "dead, so the live/dead gate throws real CD4 T cells away. Overlap "
            "matters when both signals can sit on one cell, or one drives a "
            "gating decision. You'll meet this PE → PerCP-Cy5.5 leak again in "
            "the matrix."
        ),
        cyto_emotion="thinking",
        target_widget_names=["SpectralPlotArea"],
        next_step_id="c1_sp48_learning_switch",
    ),
    # A VerificationStep, like every tab switch in the courses: a learner
    # already on the sub-tab passes at once. The spotlight is the tab
    # itself, via the viewer's get_tutorial_target_rects hook (a tab isn't
    # a QWidget the driver's name lookup can find).
    VerificationStep(
        id="c1_sp48_learning_switch",
        text=(
            "Let's put the theory into practice — click the **Learning "
            "Compensation** sub-tab (highlighted) just above the plot."
        ),
        cyto_emotion="pointing",
        allow_interaction=True,
        hide_next_button=True,
        metadata={SPECTRAL_TAB_HIGHLIGHT_KEY: "learning"},
        validator=LearningCompensationTabOpenValidator(),
        on_success_step_id="c1_sp49_slideshow",
    ),
    VerificationStep(
        id="c1_sp49_slideshow",
        text=(
            "The **Compensation Masterclass**<br><br>"
            "I'll step back and let you work through this interactive "
            "slideshow at your own pace — it walks through spillover, single-"
            "stain controls, and matrix inversion with numbers worked out from "
            "the real spectra of the dyes you just loaded, and the lasers that "
            "excite them.<br><br>"
            "It teaches with your panel's biggest leak. With these dyes that's "
            "PI's light reaching the **PE** detector: the flip side of the "
            "PE → PI leak you just met, and it makes dead cells look CD4+.<br><br>"
            "Each slide's next move is in the **👉 Your turn** box on the left. "
            "Stuck? Press **💡 Show me** at the top and it draws the move on the plot.<br><br>"
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
]
