"""Karcytics Flow Cytometry — Academy Courses.

Step conventions:
  InfoStep              — teaches a concept; user clicks Next → to continue.
  InteractionStep       — user must click/interact with a named widget to auto-advance.
  VerificationStep      — auto-polls a validator every ~2 s and advances automatically.
                          Set allow_interaction=True only if the user also needs to freely
                          interact with the UI before clicking the manual 'Check ✓' button.
  QuestionStep          — the learner must answer (a "check" question correctly) to move on.

Spotlight convention:
  target_widget_name  — single objectName for InteractionStep highlight.
  target_widget_names — list of objectNames for multi-target InfoStep spotlights.

Main tabs: see main_tabs.MainTab (validators name tabs, not positions).

Course 5 checks the whole gating strategy before Course 7 reports numbers
from it. Course 4 compared one hand-drawn population with one cluster; the
Sample Lens compares every final population with every cluster of the same
run (Course 4's UMAP + HDBSCAN run on Sample C's Leukocytes).

What the learner finds, measured on the tutorial files with the Course 1–4
guide gates (re-check if the tutorial files, guides or Course 4's run
settings change):

- One finding: a cluster of CD3− B220− leukocytes (NK or myeloid cells,
  ~3,200 events) that no final population holds. Course 3 points at that
  "double negative" corner in a question but never gates it. Propose gates
  recovers it with 2 rectangles (B220 × CD3, then CD4 × CD8; some runs add a 3rd) at F1 ≈ 0.87.
- Across samples, Sample A (thymus) is an outlier on DP: 59% of its T cells
  are CD4+CD8+ against ~1% in B and C. That's biology, not a gating error.
- Dragging the T-cells gate's top CD3 edge from 8,000 down to ~2,000 (where
  Course 3's guide used to end) cuts the CD4 T cells in two; the lens blames
  T-cells. Much lower (≤ 1,500) also empties a cluster, so the text says ~2,000.

UMAP + HDBSCAN runs differ, and so can the findings. After the missed cells
are gated, the course checks what the learner's own run still reports
(`_fill_leftovers`): a cut gets fixed on the spot (one tester's T-cells box,
drawn short of the old guide's B220 edge, cut a T-cell cluster: keeps 90%),
a merge such as "DN holds 2 clusters" is explained and left for Course 6.

Cluster numbers differ run to run, so steps that name one get their text
from the validator (the `_missed_click_step` / `_cut_read_step` idiom, as in
Course 4's `_best_bcell_step`).
"""

from karcytics_sdk.plugin.tutorial_models import (
    QUESTION_PREDICT,
    AnswerChoice,
    Course,
    InfoStep,
    QuestionStep,
    VerificationStep,
)

from ..analysis.sample_lens import Finding, FindingKind
from ..main_tabs import MainTab
from .validators import (
    AllOf,
    ClusteredRunValidator,
    LensColumnsValidator,
    LensFindingFocusedValidator,
    LensFindingValidator,
    LensFocusValidator,
    LensNoFindingsValidator,
    LensPlotViewValidator,
    LensPopulationSelectedValidator,
    LensProposalAddedValidator,
    LensProposalValidator,
    LensRunMethodValidator,
    LensRunReadyValidator,
    LensSampleValidator,
    LineageGatingCompleteValidator,
    TabActiveValidator,
    WorkflowSavedValidator,
)

TCELL_AXES = ("FITC-A", "Pacific Blue-A")  # B220 x CD3, where the T-cells gate lives


def _missed_text(finding: Finding) -> str:
    return (
        "One finding 🔎<br><br>"
        f"The panel says **Cluster {finding.clusters[0]} isn't in any population**: "
        f"{finding.size:,} events that form their own island, yet sit in none of your "
        "final populations.<br><br>"
        "Click that finding."
    )


def _cut_text(finding: Finding) -> str:
    return (
        "Caught it ✂️<br><br>"
        f"**'T-cells' cuts cluster {finding.clusters[0]} in two.** Of that cluster's "
        f"cells that reach the T-cells gate, it now keeps only {finding.shares[0]:.0%}; "
        "the rest fall just outside the new top edge.<br><br>"
        "On the left map, look for a grey slice through a coloured island: those are "
        "the CD4 T cells your edge just dropped."
    )


def _proposal_text(axes: list[str]) -> str:
    steps = ", then ".join(f"**{a}**" for a in axes)
    text = (
        "The proposal 📐<br><br>"
        "The gating path now shows the proposed gates, one plot per step, with the "
        "cluster in colour. Each step narrows down what the one before kept.<br><br>"
        f"Your run's cluster took **{len(axes)}**: {steps}. The search adds a step only "
        "while it improves the match, so the count depends on the run (often two)."
    )
    if len(set(axes)) < len(axes):
        text += (
            "<br><br>A pair came back: drawn on fewer cells, the second box can sit "
            "tighter around the cluster."
        )
    if len(axes) > 2:  # noqa: PLR2004
        text += (
            "<br><br>A step that barely helps can go: untick its box and the scores "
            "update. Keep them all for now."
        )
    return text


def _leftover_line(finding: Finding) -> str:
    gate = (finding.population or "").rsplit(" / ", 1)[-1]
    if finding.kind is FindingKind.CUTS:
        return (
            f"• **{finding.title}**: the gate keeps {finding.shares[0]:.0%} of that "
            "cluster's cells that reach it; the rest fall just outside. Its edge runs "
            "through a population."
        )
    if finding.kind is FindingKind.MERGES and gate == "DN":
        return (
            f"• **{finding.title}**: DN, the CD4− CD8− corner of T-cells, holds cells of "
            "two clusters. Often that's the CD3− population next door reaching into "
            "T-cells at its lower edge. Worth a look, not a fix: Course 6 asks two more "
            "methods about it."
        )
    if finding.kind is FindingKind.MERGES:
        return (
            f"• **{finding.title}**: one gate holds two different clusters: two "
            "populations that may need separate gates, or one the run split. Course 6 "
            "asks two more methods."
        )
    return f"• **{finding.title}**"


def _fill_leftovers(findings: list[Finding]) -> None:
    """Fill the leftover and prediction texts from what this run still reports."""
    _leftover_step.text = (
        "Not quite clean 🔍<br><br>"
        f"The missed cells are gated, but your run reports **{len(findings)} more**:<br>"
        + "<br>".join(_leftover_line(f) for f in findings)
        + "<br><br>Runs differ: UMAP + HDBSCAN draws its clusters a little differently "
        "each time, so your run can see an edge another run didn't. Click a finding "
        "to see its cells ringed on the map."
    )
    cuts = any(f.kind is FindingKind.CUTS for f in findings)
    extra = (
        f" Your run also reported **{len(findings)} more**"
        + (", and you widened a gate that cut a population" if cuts else "")
        + "."
        if findings
        else ""
    )
    _prediction_back_step.text = (
        "Your prediction 🔮<br><br>"
        "At the start you predicted: **{answer:c5_what_turns_up}**.<br><br>"
        "The lens found a group of leukocytes no gate held, and you turned it "
        f"into real gates.{extra} Then you made a cut on purpose and watched the "
        "lens catch it within seconds."
    )


# Module-level so their validators can rewrite the text with the real
# cluster number on every poll (cluster numbers aren't stable run to run).
_missed_click_step: VerificationStep = VerificationStep(
    id="c5_s24_click_missed",
    text="Reading your findings...",
    cyto_emotion="pointing",
    allow_interaction=True,
    hide_next_button=True,
    target_widget_names=["SampleLensFindings"],
    validator=LensFindingFocusedValidator(
        FindingKind.MISSED,
        on_found=lambda f: setattr(_missed_click_step, "text", _missed_text(f)),
    ),
    on_success_step_id="c5_s25_missed_read",
    failure_hint="Click the card that says the cluster **isn't in any population**.",
)

_cut_read_step: InfoStep = InfoStep(
    id="c5_s46_cut_read",
    text="Caught it ✂️",
    cyto_emotion="surprised",
    allow_interaction=True,
    target_widget_names=["SampleLensFindings", "SampleLensMap"],
    next_step_id="c5_s47_cut_blame",
)

_proposal_read_step: InfoStep = InfoStep(
    id="c5_s31_proposal_read",
    text="The proposal 📐",
    cyto_emotion="talking",
    allow_interaction=True,
    target_widget_names=["SampleLensPath"],
    next_step_id="c5_s32_scores",
)


_leftover_step: InfoStep = InfoStep(
    id="c5_s37b_leftovers",
    text="Not quite clean 🔍",
    cyto_emotion="thinking",
    allow_interaction=True,
    target_widget_names=["SampleLensFindings", "SampleLensMap"],
    next_step_id="c5_s37c_any_cut",
)

_prediction_back_step: InfoStep = InfoStep(
    id="c5_s50_prediction_back",
    text=(
        "Your prediction 🔮<br><br>"
        "At the start you predicted: **{answer:c5_what_turns_up}**.<br><br>"
        "The lens found a group of leukocytes no gate held, and you turned it "
        "into real gates. Then you made a cut on purpose and watched the lens "
        "catch it within seconds."
    ),
    cyto_emotion="happy",
    next_step_id="c5_s51_when",
)

course_5_sample_lens = Course(
    id="flow_course_5_sample_lens",
    title="Sample Lens: Check Every Gate",
    description=(
        "Hold your whole gating strategy up against Course 4's clusters: "
        "backgate every population (in a focus view built for it), find the "
        "cells no gate holds and turn "
        "them into real gates, read flags across samples, and catch a bad "
        "gate edge the moment you draw it."
    ),
    estimated_minutes=44,
    badge_reward="Gate Auditor",
    badge_icon="🔎",
    prerequisite_course_ids=["flow_course_4_analysis"],
    steps=[
        InfoStep(
            id="c5_s00_intro",
            text=(
                "Welcome to Course 5! 🔎<br><br>"
                "In Course 4 an algorithm that never saw your gates found the "
                "B cells on its own, and they matched yours.<br><br>"
                "That checked **one** population. This course checks **all** of "
                "them, before Course 7 reports any numbers."
            ),
            cyto_emotion="happy",
            next_step_id="c5_s01_predict",
        ),
        QuestionStep(
            id="c5_s01_predict",
            text=(
                "Make a prediction 🤔<br><br>"
                "Your Course 3 gates followed the guides and passed every check. "
                "Compared against Course 4's clusters, what will turn up?"
            ),
            kind=QUESTION_PREDICT,
            question_id="c5_what_turns_up",
            choices=[
                AnswerChoice("Nothing: every cluster matches a gate"),
                AnswerChoice("A group of cells none of my gates holds"),
                AnswerChoice("A gate edge running through a population"),
                AnswerChoice("Most of my gates are wrong"),
            ],
            explanation="No wrong answer. You'll see what the lens finds in a few minutes.",
            cyto_emotion="thinking",
            next_step_id="c5_s02_validate",
        ),
        # ── Check Courses 3–4 are in place ──────────────────────────────────────
        VerificationStep(
            id="c5_s02_validate",
            text="Checking for your Course 3 gates and Course 4 clustering run...",
            cyto_emotion="scanning",
            hide_next_button=True,
            validator=AllOf(LineageGatingCompleteValidator(), ClusteredRunValidator("sample c")),
            on_success_step_id="c5_s03_why",
            on_fail_step_id="c5_s02b_incomplete",
        ),
        InfoStep(
            # Exits rather than looping against a dead end, as Course 4's
            # c4_s01b_incomplete_gating does.
            id="c5_s02b_incomplete",
            text=(
                "Missing something 🔍<br><br>"
                "Course 5 needs the **Leukocytes**, **T-cells** and **B-cells** "
                "gates from Course 3, and Course 4's **UMAP + HDBSCAN** run on "
                "**Sample C**. Finish those courses first, then relaunch Course 5."
            ),
            cyto_emotion="thinking",
            next_step_id="__abandon__",
        ),
        InfoStep(
            id="c5_s03_why",
            text=(
                "Why check at all? 🧐<br><br>"
                "A gate is a judgement call. It can pass every check and still "
                "slice through a population, or miss one entirely, and nothing "
                "on the Gating tab tells you.<br><br>"
                "Many cytometry programs give one page per sample that shows "
                "every gate. The **Sample Lens** does that, and then compares "
                "your gates with the clusters, so it can point at the gates "
                "that look wrong."
            ),
            cyto_emotion="talking",
            next_step_id="c5_s04_open_tab",
        ),
        VerificationStep(
            id="c5_s04_open_tab",
            text=(
                "Click the **Sample Lens** tab at the top, between **Population "
                "Analysis** and **Statistics**."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["MainTabBar"],
            validator=TabActiveValidator(MainTab.SAMPLE_LENS),
            on_success_step_id="c5_s05_layout",
        ),
        InfoStep(
            id="c5_s05_layout",
            text=(
                "The lens at a glance 🗺️<br><br>"
                "**Left column:** pick the sample and the clustering run; below "
                "them, your populations and the audit findings.<br>"
                "**Top right, Gating path:** empty for now. Click a population "
                "and every gate above it appears here.<br>"
                "**Bottom right:** the run's map, drawn twice, and **Across "
                "samples**, the selected population in every sample."
            ),
            cyto_emotion="talking",
            target_widget_names=[
                "lens_sidebar",
                "SampleLensPath",
                "SampleLensMap",
                "SampleLensAcross",
            ],
            next_step_id="c5_s06_pick_sample",
        ),
        VerificationStep(
            id="c5_s06_pick_sample",
            text=(
                "Choose **Sample C** in the **Sample** dropdown: the spleen, the "
                "sample Course 4 clustered."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["SampleLensSampleCombo"],
            validator=AllOf(LensSampleValidator("sample c"), LensRunReadyValidator()),
            on_success_step_id="c5_s07_run",
            failure_hint="Open the **Sample** dropdown at the top left and pick **Sample C**.",
        ),
        VerificationStep(
            id="c5_s07_run",
            text=(
                "Your Course 4 run, reused ♻️<br><br>"
                "The **Clustering run** dropdown lists every run on **Leukocytes** "
                "and picked the newest: your **UMAP + HDBSCAN** run from Course 4. "
                "If you made other runs since, pick that one.<br><br>"
                "A sample without a run gets a **Run UMAP + clustering** button "
                "instead. You won't need it today."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["SampleLensRunCombo"],
            validator=LensRunMethodValidator("umap_hdbscan"),
            on_success_step_id="c5_s08_why_leukocytes",
            failure_hint="Open **Clustering run** and pick your UMAP + HDBSCAN run from Course 4.",
        ),
        QuestionStep(
            id="c5_s08_why_leukocytes",
            text=(
                "Course 4 clustered **Leukocytes**, not All Events. For checking "
                "gates, why is that the right starting point?"
            ),
            question_id="c5_why_leukocytes",
            choices=[
                AnswerChoice(
                    "UMAP can't handle more than one gate's worth of cells",
                    feedback="It can; Course 4 subsampled for speed. The reason is about what the clusters would contain.",
                ),
                AnswerChoice(
                    "Debris and dead cells would form clusters you removed on purpose",
                    correct=True,
                ),
                AnswerChoice(
                    "All Events has no CD3 or B220 signal",
                    feedback="Every event has all the channels. It's the debris and dead cells that would get in the way.",
                ),
            ],
            explanation=(
                "Cluster after your clean-up gates. Otherwise debris and dead cells "
                "form islands of their own, and the lens reports them as "
                "populations you 'missed', when you dropped them on purpose."
            ),
            cyto_emotion="thinking",
            next_step_id="c5_s09_scope",
        ),
        InfoStep(
            id="c5_s09_scope",
            text=(
                "What gets judged ⚖️<br><br>"
                "The line under the title says exactly what the lens is judging: "
                "your **final populations** (gates with nothing drawn below them) "
                "under Leukocytes, on the events the run used.<br><br>"
                "Here that's the four CD4/CD8 quadrants and **B-cells**."
            ),
            cyto_emotion="talking",
            target_widget_names=["SampleLensScope"],
            next_step_id="c5_s10_why_not_umap",
        ),
        QuestionStep(
            id="c5_s10_why_not_umap",
            text=(
                "**UMAP B Cells** is a population too, but the lens leaves it "
                "out of the judging. Why?"
            ),
            question_id="c5_why_not_umap_export",
            choices=[
                AnswerChoice(
                    "It came from the clustering, so it would just agree with itself",
                    correct=True,
                ),
                AnswerChoice(
                    "It's too small to judge",
                    feedback="It's about 64% of the run, the biggest population there is. Think about where it came from.",
                ),
                AnswerChoice(
                    "The AND node hides it",
                    feedback="The AND node only combines populations; it changes nothing about them. Think about where UMAP B Cells came from.",
                ),
            ],
            explanation=(
                "UMAP B Cells is an exported cluster. Comparing it with the clusters "
                "would compare the clusters with themselves. The AND node is left "
                "out too: it recombines gates, it isn't a gate of its own."
            ),
            cyto_emotion="thinking",
            next_step_id="c5_s11_path_intro",
        ),
        # ── Gating path (backgating) ────────────────────────────────────────────
        InfoStep(
            id="c5_s11_path_intro",
            text=(
                "Backgating 🔙<br><br>"
                "Gating goes forward: each gate narrows the cells down. "
                "**Backgating** goes the other way: take a final population and "
                "show where its cells sat at **every** earlier step.<br><br>"
                "If a population sits at the edge of a gate somewhere upstream, "
                "that gate is probably cutting it.<br><br>"
                "Backgating needs no clustering run: it works on any sample, so you "
                "can open the lens just to check a population's path."
            ),
            cyto_emotion="talking",
            next_step_id="c5_s12_select_bcells",
        ),
        VerificationStep(
            id="c5_s12_select_bcells",
            text="In **Populations** on the left, click **B-cells**.",
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["SampleLensHierarchy"],
            validator=LensPopulationSelectedValidator("B-cells"),
            on_success_step_id="c5_s13_path_read",
            failure_hint="Click the **B-cells** row in the Populations list on the left.",
        ),
        InfoStep(
            id="c5_s13_path_read",
            text=(
                "The gating path 🧭<br><br>"
                "One plot per gate from All Events down to B-cells, each on that "
                "gate's own axes. Grey is the gate's parent; **colour** is the "
                "selected population, B-cells.<br><br>"
                "Scroll the strip sideways if a plot is cut off."
            ),
            cyto_emotion="talking",
            allow_interaction=True,
            target_widget_names=["SampleLensPath"],
            next_step_id="c5_s14_path_question",
        ),
        QuestionStep(
            id="c5_s14_path_question",
            text=(
                "Look at the first plot, **All Events → Cells** (FSC vs SSC). "
                "What are the grey points outside the colour?"
            ),
            question_id="c5_backgate_grey",
            choices=[
                AnswerChoice(
                    "B cells the Cells gate dropped",
                    feedback="Dropped B cells would still be coloured: colour marks every B cell, wherever it sits.",
                ),
                AnswerChoice(
                    "Noise from the plot's colour map",
                    feedback="Grey here is real events: the gate's parent population, drawn under the B cells.",
                ),
                AnswerChoice("Everything that isn't a B cell", correct=True),
            ],
            explanation=(
                "Grey is the whole parent, colour the B cells inside it. On a plot "
                "of All Events, nearly everything is grey: debris, dead cells, T "
                "cells. Backgating shows where your population sits among them."
            ),
            cyto_emotion="thinking",
            allow_interaction=True,
            target_widget_names=["SampleLensPath"],
            next_step_id="c5_s15_select_tcells",
        ),
        VerificationStep(
            id="c5_s15_select_tcells",
            text="Now click **CD4+**, one of the quadrants under T-cells.",
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["SampleLensHierarchy"],
            validator=LensPopulationSelectedValidator("CD4+"),
            on_success_step_id="c5_s16_path_tcells",
            failure_hint="Click **CD4+** under T-cells in the Populations list.",
        ),
        InfoStep(
            id="c5_s16_path_tcells",
            text=(
                "Five steps deep 🪜<br><br>"
                "Now the path runs Cells → Live Cells → Leukocytes → T-cells → "
                "CD4+. On every plot the CD4 T cells sit well inside the gate: "
                "nothing upstream is clipping them.<br><br>"
                "That's what a healthy path looks like."
            ),
            cyto_emotion="happy",
            allow_interaction=True,
            target_widget_names=["SampleLensPath"],
            next_step_id="c5_s17_path_live",
        ),
        InfoStep(
            id="c5_s17_path_live",
            text=(
                "These plots are live ⚡<br><br>"
                "They show your real gates. Drag one here and it's edited exactly "
                "as on the Gating tab: counts update, the change propagates to "
                "the other samples, and **Ctrl+Z** undoes it.<br><br>"
                "You'll use that later. Leave them as they are for now."
            ),
            cyto_emotion="talking",
            target_widget_names=["SampleLensPath"],
            next_step_id="c5_s17b_focus",
        ),
        # ── Focus mode: bigger plots, other views ───────────────────────────────
        VerificationStep(
            id="c5_s17b_focus",
            text=(
                "Room to look 🔍<br><br>"
                "These plots are small. Click **Focus** above the path: the sidebar "
                "and maps step aside and the plots get the whole tab."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["SampleLensFocusButton"],
            validator=LensFocusValidator(True),
            on_success_step_id="c5_s17c_columns",
            failure_hint="Click **Focus**, at the right of the *Gating path* title.",
        ),
        VerificationStep(
            id="c5_s17c_columns",
            text=(
                "Pick **2** in **Plots per row**. Each plot grows to half the width; "
                "scroll down for the rest of the path."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["SampleLensColumnsCombo"],
            validator=LensColumnsValidator(2),
            on_success_step_id="c5_s17d_view",
        ),
        VerificationStep(
            id="c5_s17d_view",
            text=(
                "**Cells → Live Cells** is a histogram: its gate is a range on PI.<br><br>"
                "In that plot's view menu (top right of the plot), pick "
                "**Dot plot vs SSC-A**."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["SampleLensPlotView"],
            validator=LensPlotViewValidator("live cells", "vs:SSC-A"),
            on_success_step_id="c5_s17e_view_read",
            failure_hint="Open the menu above the **Cells → Live Cells** plot and pick **Dot plot vs SSC-A**.",
        ),
        InfoStep(
            id="c5_s17e_view_read",
            text=(
                "Same gate, another view 🔁<br><br>"
                "A range gate only needs PI, so it fits a histogram or any dot plot "
                "with PI across. Here it's a band, still draggable.<br><br>"
                "The other plots offer Pseudocolor, Dot plot and Contour. Their "
                "**Histogram** is greyed out: a 2-D gate on one axis would drop "
                "half of what it selects."
            ),
            cyto_emotion="talking",
            allow_interaction=True,
            target_widget_names=["SampleLensPath"],
            next_step_id="c5_s17f_unfocus",
        ),
        VerificationStep(
            id="c5_s17f_unfocus",
            text=(
                "Pick **All** in **Plots per row** again, then click **Exit focus** "
                "(or press Esc). The maps are next."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["SampleLensColumnsCombo", "SampleLensFocusButton"],
            validator=AllOf(LensColumnsValidator(0), LensFocusValidator(False)),
            on_success_step_id="c5_s18_map_intro",
            failure_hint="Open **Plots per row**, pick **All**, then click **Exit focus**.",
        ),
        # ── The run, twice ──────────────────────────────────────────────────────
        InfoStep(
            id="c5_s18_map_intro",
            text=(
                "The same map, twice 🗺️🗺️<br><br>"
                "Both plots are Course 4's UMAP, cell for cell.<br>"
                "**Left:** each cell coloured by the final population it ended up "
                "in.<br>"
                "**Right:** the same cells coloured by HDBSCAN cluster, numbered "
                "on the map."
            ),
            cyto_emotion="talking",
            allow_interaction=True,
            target_widget_names=["SampleLensMap"],
            next_step_id="c5_s19_map_grey",
        ),
        QuestionStep(
            id="c5_s19_map_grey",
            text=(
                "On the **left** map some cells are grey. The legend calls them "
                "*in no final population*. Which cells are those?"
            ),
            question_id="c5_map_grey",
            choices=[
                AnswerChoice(
                    "Cells HDBSCAN couldn't place in a cluster",
                    feedback="That's grey on the right map, HDBSCAN's noise. The left map is coloured by your gates.",
                ),
                AnswerChoice("Leukocytes that none of your final gates hold", correct=True),
                AnswerChoice(
                    "Cells outside Leukocytes",
                    feedback="The run only contains Leukocytes. Grey on the left is about your gates below Leukocytes.",
                ),
            ],
            explanation=(
                "Left is your gating, right is the clustering. A whole grey island "
                "on the left is a population you never gated. A grey slice "
                "through a coloured island is an edge cutting one."
            ),
            cyto_emotion="thinking",
            allow_interaction=True,
            target_widget_names=["SampleLensMap"],
            next_step_id="c5_s20_compare_maps",
        ),
        InfoStep(
            id="c5_s20_compare_maps",
            text=(
                "Spot the difference 👀<br><br>"
                "Where the two maps agree, an island is one colour on the left "
                "and one cluster on the right. Where they disagree, your gates "
                "and the clustering split the cells differently.<br><br>"
                "You could compare them by eye. The lens does it for you."
            ),
            cyto_emotion="thinking",
            allow_interaction=True,
            target_widget_names=["SampleLensMap"],
            next_step_id="c5_s21_findings_intro",
        ),
        # ── Audit findings ──────────────────────────────────────────────────────
        InfoStep(
            id="c5_s21_findings_intro",
            text=(
                "Audit findings 📋<br><br>"
                "Three ways gates and clusters can disagree:<br>"
                "◯ **isn't in any population**: a cluster no gate holds.<br>"
                "⊕ **holds N different clusters**: one gate catches two groups.<br>"
                "✂ **cuts cluster N in two**: a gate edge runs through a cluster."
            ),
            cyto_emotion="talking",
            target_widget_names=["SampleLensFindings"],
            next_step_id="c5_s22_second_opinion",
        ),
        QuestionStep(
            id="c5_s22_second_opinion",
            text=(
                "A what-if, not your data: **suppose** the lens said a gate "
                "**holds 2 different clusters**. Would that prove the gate is "
                "wrong?"
            ),
            question_id="c5_second_opinion",
            choices=[
                AnswerChoice(
                    "Yes: clusters are the true populations",
                    feedback="Clustering depends on its settings. It can split one population in two, so it isn't ground truth.",
                ),
                AnswerChoice(
                    "No: it's a prompt to look, and biology decides",
                    correct=True,
                ),
                AnswerChoice(
                    "Only if both clusters are large",
                    feedback="Size doesn't make the clustering right. Look at the cells and decide whether they're one population.",
                ),
            ],
            explanation=(
                "Treat the clustering as a second opinion. Two clusters in one gate "
                "may be two cell types, or one type in two states. You check the "
                "markers and decide."
            ),
            cyto_emotion="thinking",
            next_step_id="c5_s23_wait_findings",
        ),
        VerificationStep(
            id="c5_s23_wait_findings",
            text="Reading your findings...",
            cyto_emotion="scanning",
            hide_next_button=True,
            validator=LensFindingValidator(FindingKind.MISSED),
            on_success_step_id="c5_s24_click_missed",
        ),
        _missed_click_step,
        InfoStep(
            id="c5_s25_missed_read",
            text=(
                "Circled on both maps ⭕<br><br>"
                "**Right:** a clean cluster of its own.<br>"
                "**Left:** the same cells, almost all grey. None of your final "
                "populations holds them."
            ),
            cyto_emotion="surprised",
            allow_interaction=True,
            target_widget_names=["SampleLensMap"],
            next_step_id="c5_s26_what_are_they",
        ),
        QuestionStep(
            id="c5_s26_what_are_they",
            text=(
                "These cells are Leukocytes (CD45+), but low on **CD3** and low "
                "on **B220**. What are they most likely?"
            ),
            question_id="c5_missed_identity",
            choices=[
                AnswerChoice(
                    "T cells that lost their CD3",
                    feedback="T cells keep CD3; it's part of their receptor. These were never T cells.",
                ),
                AnswerChoice(
                    "Debris that slipped through",
                    feedback="Debris wouldn't be CD45+ and survive the Cells and Live Cells gates. These are real leukocytes.",
                ),
                AnswerChoice(
                    "Other leukocytes, such as NK cells or myeloid cells",
                    correct=True,
                ),
            ],
            explanation=(
                "Leukocytes that are neither T nor B: NK cells, monocytes, "
                "granulocytes, dendritic cells. This panel can't tell them apart, "
                "but it can see they're there."
            ),
            cyto_emotion="thinking",
            next_step_id="c5_s27_course3_callback",
        ),
        InfoStep(
            id="c5_s27_course3_callback",
            text=(
                "You've met them before 🧩<br><br>"
                "In Course 3, a question pointed at the lower-left corner of "
                "**B220 vs CD3**: \"a 'double negative' group that's neither T nor "
                'B cells". You gated T-cells and B-cells, and nothing else.<br><br>'
                "Nobody missed them on purpose. They just never got a gate, and "
                "the lens noticed."
            ),
            cyto_emotion="talking",
            next_step_id="c5_s28_propose_intro",
        ),
        # ── Propose gates ───────────────────────────────────────────────────────
        InfoStep(
            id="c5_s28_propose_intro",
            text=(
                "From cluster to gates 🛠️<br><br>"
                "In Course 4 you **exported** a cluster: a list of this sample's "
                "cells.<br><br>"
                "**Propose gates** does something else: it searches for a short "
                "chain of ordinary rectangle gates on real markers that catches "
                "the cluster, the kind of gates you'd draw yourself."
            ),
            cyto_emotion="talking",
            next_step_id="c5_s29_why_gates",
        ),
        QuestionStep(
            id="c5_s29_why_gates",
            text=("Why turn the cluster into gates instead of exporting it as in Course 4?"),
            question_id="c5_gates_vs_export",
            choices=[
                AnswerChoice(
                    "Gates are faster to compute",
                    feedback="Speed isn't the point. Think about what happens on Samples A and B.",
                ),
                AnswerChoice(
                    "Gates work on every sample; an export only lists Sample C's cells",
                    correct=True,
                ),
                AnswerChoice(
                    "Exports can't be used in Statistics",
                    feedback="They can, as Course 7 will show. The difference is which samples they mean anything on.",
                ),
            ],
            explanation=(
                "An exported cluster is a list of specific cells from one sample. "
                "Gates are shapes on markers, so they propagate and mean the same "
                "thing on every sample, today's and next month's."
            ),
            cyto_emotion="thinking",
            next_step_id="c5_s30_propose",
        ),
        VerificationStep(
            id="c5_s30_propose",
            text="On the finding's card, click **Propose gates**.",
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["SampleLensProposeButton"],
            validator=LensProposalValidator(
                on_found=lambda axes: setattr(_proposal_read_step, "text", _proposal_text(axes))
            ),
            on_success_step_id="c5_s31_proposal_read",
            failure_hint="Click **Propose gates** on the *isn't in any population* card.",
        ),
        _proposal_read_step,
        InfoStep(
            id="c5_s32_scores",
            text=(
                "How good is it? 🎯<br><br>"
                "The bar above scores the last step against the cluster:<br>"
                "• **Recall**: the share of the cluster's cells the gates catch.<br>"
                "• **Precision**: the share of the caught cells that are in the cluster.<br>"
                "• **F1**: both in one number. 1.0 would be a perfect match."
            ),
            cyto_emotion="talking",
            target_widget_names=["lens_proposal_bar"],
            next_step_id="c5_s33_precision",
        ),
        QuestionStep(
            id="c5_s33_precision",
            text=(
                "Say recall is **99%** but precision is **77%**. What does that "
                "tell you about the proposed gates?"
            ),
            question_id="c5_precision_recall",
            choices=[
                AnswerChoice(
                    "They miss almost a quarter of the cluster",
                    feedback="That would be low recall. At 99% recall, nearly all of the cluster is inside.",
                ),
                AnswerChoice(
                    "They catch nearly all of it, plus some cells from outside it",
                    correct=True,
                ),
                AnswerChoice(
                    "They're 77% likely to be right",
                    feedback="Precision isn't a probability of being right. It's the share of caught cells that belong to the cluster.",
                ),
            ],
            explanation=(
                "High recall, lower precision: a generous box. Rectangles can't "
                "follow a curved island exactly, so they take in some neighbours. "
                "Fine-tune the edges later, like any gate."
            ),
            cyto_emotion="thinking",
            next_step_id="c5_s34_accept",
        ),
        VerificationStep(
            id="c5_s34_accept",
            text="Happy with it? Click **Add gates to tree**.",
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["SampleLensAcceptProposal"],
            validator=LensProposalAddedValidator(),
            on_success_step_id="c5_s35_added",
            failure_hint="Click **Add gates to tree** in the bar above the gating path.",
        ),
        InfoStep(
            id="c5_s35_added",
            text=(
                "Real gates now ✅<br><br>"
                "The chain sits under **Leukocytes**, named after its cluster. "
                "They're ordinary gates: rename them, edit them, and they've "
                "already propagated to Samples A and B.<br><br>"
                "Nothing changes until you add a proposal. **Cancel** would have "
                "discarded it."
            ),
            cyto_emotion="happy",
            allow_interaction=True,
            target_widget_names=["SampleLensHierarchy"],
            next_step_id="c5_s36_finding_gone",
        ),
        VerificationStep(
            id="c5_s36_finding_gone",
            text="Watch the findings panel...",
            cyto_emotion="scanning",
            hide_next_button=True,
            target_widget_names=["SampleLensFindings"],
            validator=LensFindingValidator(FindingKind.MISSED, present=False),
            on_success_step_id="c5_s36b_whats_left",
        ),
        VerificationStep(
            # Branches on the learner's own run: runs differ, and so can what
            # the lens still reports once the missed cells are gated.
            id="c5_s36b_whats_left",
            text="Checking what else your run reports...",
            cyto_emotion="scanning",
            hide_next_button=True,
            target_widget_names=["SampleLensFindings"],
            validator=LensNoFindingsValidator(on_findings=_fill_leftovers),
            max_retries=1,  # one more poll, in case the lens is still re-auditing
            on_success_step_id="c5_s37_clean",
            on_fail_step_id="c5_s37b_leftovers",
        ),
        InfoStep(
            id="c5_s37_clean",
            text=(
                "No disagreements 🎉<br><br>"
                "The cluster now sits in a final population, so the finding is "
                "gone, and the left map has one grey island fewer.<br><br>"
                "The lens recomputes after every gate change, wherever you make "
                "it. You'll rely on that in a moment."
            ),
            cyto_emotion="cheering",
            allow_interaction=True,
            target_widget_names=["SampleLensFindings", "SampleLensMap"],
            next_step_id="c5_s38_across_intro",
        ),
        _leftover_step,
        VerificationStep(
            id="c5_s37c_any_cut",
            text="Looking for cuts...",
            cyto_emotion="scanning",
            hide_next_button=True,
            target_widget_names=["SampleLensFindings"],
            validator=LensFindingValidator(FindingKind.CUTS, present=False),
            on_success_step_id="c5_s38_across_intro",
            on_fail_step_id="c5_s37d_fix_cut",
        ),
        VerificationStep(
            id="c5_s37d_fix_cut",
            text=(
                "Fix the cut ✂️<br><br>"
                "Click the cut finding: the gating path shows its gate, and the map "
                "rings the cluster.<br><br>"
                "Drag that gate's edge **outward**, on the side where the ringed "
                "cells spill over, until the finding goes. **Ctrl+Z** undoes a drag.<br><br>"
                "Your gate passed Course 3's check; it just runs closer to this "
                "population than it should."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["SampleLensFindings", "SampleLensPath"],
            validator=LensFindingValidator(FindingKind.CUTS, present=False),
            on_success_step_id="c5_s37e_cut_fixed",
            failure_hint=(
                "Click the cut finding, then drag its gate's edge outward on the gating "
                "path until the finding disappears."
            ),
        ),
        InfoStep(
            id="c5_s37e_cut_fixed",
            text=(
                "Fixed ✅<br><br>"
                "A gate that passed every check still clipped a population, and only "
                "the comparison with the clusters showed it. That's the lens's job.<br><br>"
                "Later you'll make a cut on purpose, to see how the lens decides "
                "which gate to blame."
            ),
            cyto_emotion="cheering",
            allow_interaction=True,
            target_widget_names=["SampleLensFindings", "SampleLensMap"],
            next_step_id="c5_s38_across_intro",
        ),
        # ── Across samples ──────────────────────────────────────────────────────
        InfoStep(
            id="c5_s38_across_intro",
            text=(
                "Across samples 📊<br><br>"
                "The table shows the selected population in every sample that "
                "has it: **% parent**, **events**, **on edge**, and **flags**.<br><br>"
                "Controls are left out: their stains differ from the panel, so "
                "their percentages aren't comparable."
            ),
            cyto_emotion="talking",
            target_widget_names=["SampleLensAcross"],
            next_step_id="c5_s39_select_dp",
        ),
        VerificationStep(
            id="c5_s39_select_dp",
            text="Click **DP** under T-cells: the CD4+ CD8+ quadrant.",
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["SampleLensHierarchy"],
            validator=LensPopulationSelectedValidator("DP"),
            on_success_step_id="c5_s40_outlier",
            failure_hint="Click the **DP** quadrant under T-cells in the Populations list.",
        ),
        QuestionStep(
            id="c5_s40_outlier",
            text=(
                "Sample A is flagged as an **outlier**: more than half its T cells "
                "are DP, against about 1% in B and C. Is the DP gate wrong on "
                "Sample A?"
            ),
            question_id="c5_thymus_outlier",
            choices=[
                AnswerChoice(
                    "Yes: the quadrant must be misplaced there",
                    feedback="It's the same quadrant on every sample; propagation copied it. The difference is in the cells.",
                ),
                AnswerChoice(
                    "No: Sample A is the thymus, where T cells pass through a DP stage",
                    correct=True,
                ),
                AnswerChoice(
                    "Can't tell without re-running UMAP",
                    feedback="You already know enough. Recall from Course 3 which tissue Sample A is.",
                ),
            ],
            explanation=(
                "Young T cells in the thymus are CD4+ CD8+ before they pick a side. "
                "The flag is right that A is different, and biology says why. A "
                "flag asks you to look; it doesn't say what's wrong."
            ),
            cyto_emotion="thinking",
            allow_interaction=True,
            target_widget_names=["SampleLensAcross"],
            next_step_id="c5_s41_on_edge",
        ),
        InfoStep(
            id="c5_s41_on_edge",
            text=(
                "On edge 📏<br><br>"
                "**On edge** is the share of the parent sitting right at the gate's "
                "boundary. Above 5%, the edge runs through dense data: a small "
                "shift in the gate, or in the staining, moves the result a lot, "
                "and the table flags it.<br><br>"
                "A flag just over the line, say 5.2%, is worth a look, not an alarm."
            ),
            cyto_emotion="talking",
            target_widget_names=["SampleLensAcross"],
            next_step_id="c5_s42_on_edge_question",
        ),
        QuestionStep(
            id="c5_s42_on_edge_question",
            text=(
                "Two gates give the same 30% on every sample. One has **0.5%** of "
                "its parent on edge, the other **12%**. Which number would you "
                "trust more next month?"
            ),
            question_id="c5_on_edge_trust",
            choices=[
                AnswerChoice("The gate with 0.5% on edge", correct=True),
                AnswerChoice(
                    "The gate with 12% on edge",
                    feedback="12% of the parent sits right on its boundary, so a slight shift in staining swings the result.",
                ),
                AnswerChoice(
                    "Both equally: the percentages match",
                    feedback="Same number today, but one sits on a cliff edge. A small shift moves it a lot.",
                ),
            ],
            explanation=(
                "An edge through empty space barely notices small shifts. An edge "
                "through a crowd swings with every change in staining or gate."
            ),
            cyto_emotion="thinking",
            next_step_id="c5_s43_break_intro",
        ),
        # ── Break it, then catch it ─────────────────────────────────────────────
        InfoStep(
            id="c5_s43_break_intro",
            text=(
                "Make the mistake on purpose 🧪<br><br>"
                "Now a **cut**, made on purpose so you can watch the lens name the "
                "gate. Earlier versions of Course 3 had a T-cells guide box whose top "
                "stopped at **2,000** on CD3, right through the CD4 T cells.<br><br>"
                "Let's draw it that way again and watch the lens react."
            ),
            cyto_emotion="talking",
            next_step_id="c5_s44_select_tcells",
        ),
        VerificationStep(
            id="c5_s44_select_tcells",
            text="Click **T-cells** in Populations.",
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["SampleLensHierarchy"],
            validator=LensPopulationSelectedValidator("T-cells"),
            on_success_step_id="c5_s45_drag_edge",
            failure_hint="Click the **T-cells** row in the Populations list.",
        ),
        VerificationStep(
            id="c5_s45_drag_edge",
            text=(
                "In the gating path, find the last plot: **Leukocytes → T-cells** "
                "(B220 vs CD3). Scroll the strip sideways if it's cut off.<br><br>"
                "Click the T-cells rectangle, then drag its **top** edge down to "
                "the dashed purple guide: about **2,000** on CD3, into the upper "
                "cluster. Not lower."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["SampleLensPath"],
            metadata={"guide_rect": (-400.0, 3000.0, 300.0, 2000.0), "guide_axes": TCELL_AXES},
            validator=LensFindingValidator(
                FindingKind.CUTS,
                gate="T-cells",
                on_found=lambda f: setattr(_cut_read_step, "text", _cut_text(f)),
            ),
            on_success_step_id="c5_s46_cut_read",
            failure_hint=(
                "Drag the T-cells rectangle's top edge down to about 2,000 on CD3. "
                "If a cluster vanished instead, you went too low: press Ctrl+Z and try again."
            ),
        ),
        _cut_read_step,
        QuestionStep(
            id="c5_s47_cut_blame",
            text=(
                "The cells you dropped would have ended up in **CD4+**, yet the "
                "finding names **T-cells**. Why?"
            ),
            question_id="c5_cut_blame",
            choices=[
                AnswerChoice(
                    "CD4+ is a quadrant, and the lens ignores quadrants",
                    feedback="The quadrants are final populations; the lens judges them. It names the gate where the cells were actually lost.",
                ),
                AnswerChoice(
                    "It names the gate on the path that loses the most of the cluster",
                    correct=True,
                ),
                AnswerChoice(
                    "T-cells is the gate you selected",
                    feedback="The finding doesn't depend on your selection. It walks the path and finds where the cells are lost.",
                ),
            ],
            explanation=(
                "CD4+ is just where the surviving cells end up. The lens walks the "
                "path from Leukocytes down and names the gate that drops the most "
                "of the cluster: T-cells, the edge you moved."
            ),
            cyto_emotion="thinking",
            next_step_id="c5_s48_fix",
        ),
        VerificationStep(
            id="c5_s48_fix",
            text=(
                "Now fix it: press **Ctrl+Z** until the edge is back, or drag the "
                "top edge up to the dashed guide, above the upper cluster (about "
                "**8,000**).<br><br>"
                "Watch the finding disappear."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["SampleLensPath", "SampleLensFindings"],
            metadata={"guide_rect": (-400.0, 3000.0, 300.0, 8000.0), "guide_axes": TCELL_AXES},
            validator=AllOf(
                LensFindingValidator(FindingKind.CUTS, present=False),
                LensFindingValidator(FindingKind.MISSED, present=False),
            ),
            on_success_step_id="c5_s49_fixed",
            failure_hint="Undo with Ctrl+Z, or drag the T-cells top edge back above the CD3+ cluster.",
        ),
        QuestionStep(
            id="c5_s49_fixed",
            text=(
                "Fixed ✅<br><br>"
                "With the 2,000 edge, about half of Sample C's CD4 T cells were "
                "outside T-cells. What would that have done to Course 7's report?"
            ),
            question_id="c5_cut_consequence",
            choices=[
                AnswerChoice(
                    "Nothing: percentages are relative anyway",
                    feedback="Relative to the wrong parent is still wrong. T-cells' share of Leukocytes would have been too low.",
                ),
                AnswerChoice(
                    "Only Sample C's numbers would be off",
                    feedback="Propagation copies the gate to every sample, so the same edge would clip T cells everywhere.",
                ),
                AnswerChoice(
                    "Too few T cells, and too few CD4+, on every sample",
                    correct=True,
                ),
            ],
            explanation=(
                "One edge, propagated, skews every sample: Sample C's T cells drop "
                "from about 22% to 16% of Leukocytes. It passed every check, and "
                "only the comparison with the clusters showed it."
            ),
            cyto_emotion="thinking",
            next_step_id="c5_s50_prediction_back",
        ),
        # ── Wrap-up ─────────────────────────────────────────────────────────────
        _prediction_back_step,
        InfoStep(
            id="c5_s51_when",
            text=(
                "When to use the lens 🗓️<br><br>"
                "• After building a new gating strategy, before reporting.<br>"
                "• When one sample's numbers look odd: check its path and flags.<br>"
                "• After adjusting a gate: findings update as you drag.<br>"
                "• Any time, just to backgate: no clustering run needed."
            ),
            cyto_emotion="talking",
            next_step_id="c5_s52_limits",
        ),
        QuestionStep(
            id="c5_s52_limits",
            text=(
                "On your own data, the lens reports **no findings at all**. What can you conclude?"
            ),
            question_id="c5_no_findings",
            choices=[
                AnswerChoice(
                    "My gates and the clusters agree on these cells",
                    correct=True,
                ),
                AnswerChoice(
                    "My gating is correct",
                    feedback="Agreement isn't proof: a population the run's channels can't see, or that was clustered out, wouldn't show up.",
                ),
                AnswerChoice(
                    "The clustering failed",
                    feedback="A run that agrees with your gates is a good sign, not a failure. It just isn't proof either.",
                ),
            ],
            explanation=(
                "No findings means the two methods agree on the events and channels "
                "the run used. That's strong evidence, not proof: the lens can only "
                "judge what the run clustered."
            ),
            cyto_emotion="thinking",
            next_step_id="c5_s53_save",
        ),
        VerificationStep(
            id="c5_s53_save",
            text=(
                "Course 6 gets second opinions on these gates and Course 7 reports "
                "their numbers, including your new cluster gates. Save your progress.<br><br>"
                "Click the **⚠️ Save Workspace** button (highlighted) at the top right."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["WorkspaceSaveButton"],
            validator=WorkflowSavedValidator(),
            on_success_step_id="c5_s54_graduation",
            failure_hint="Click **⚠️ Save Workspace**, give it a name, and click Save to finish.",
        ),
        InfoStep(
            # The true end of Course 5: no next_step_id, so the Academy awards
            # the badge when the learner clicks Next (as Course 4 does).
            id="c5_s54_graduation",
            text=(
                "Your workspace is updated!<br><br>Course 5 is complete — you're "
                "officially a **Gate Auditor**! 🏆<br><br>"
                "Your gates have been checked. In Course 6 you'll ask two more "
                "clustering methods for a second opinion."
            ),
            cyto_emotion="cheering",
            cyto_animation="cheering",
        ),
    ],
)
