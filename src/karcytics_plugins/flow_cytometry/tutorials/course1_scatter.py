"""Course 1, reading the scatter plot: what FSC and SSC say before any gate.

Two questions on the Blank sample's FSC-A / SSC-A plot: where debris sits,
then what the second, higher-scatter cluster says about its cells.
"""

from __future__ import annotations

from karcytics_sdk.plugin.tutorial_models import AnswerChoice, BaseStep, QuestionStep

SCATTER_STEPS: list[BaseStep] = [
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
]
