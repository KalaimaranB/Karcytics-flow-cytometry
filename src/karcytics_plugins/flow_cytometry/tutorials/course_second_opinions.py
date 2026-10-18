"""Karcytics Flow Cytometry — Academy Courses.

Step conventions: see course5.py.

Main tabs: see main_tabs.MainTab (validators name tabs, not positions).

Course 6, "Second Opinions", runs two more clustering methods on the cells
Course 4 clustered with UMAP + HDBSCAN (Sample C's Leukocytes, PI and CD45
left out), then holds the gates up against them in the Sample Lens. Each
method chooses its grain differently: HDBSCAN by a minimum cluster size,
FlowSOM by k, PhenoGraph by a resolution.

What the learner finds, measured on the tutorial files after Courses 1–5
(re-check if the tutorial files, guides or run settings change):

- FlowSOM at k = 10 splits the B cells over several B220+ metaclusters; at
  k = 5 they merge into one or two.
- PhenoGraph (k = 30 neighbours) finds ~31 clusters at resolution 1.0 and
  ~16 at 0.5. Two small clusters stand apart (no links): B220+ CD4+ CD3+
  CD8+ (~1.4%) and B220+ CD3+ CD8+ (~0.5%). They could be doublets, but
  these files have no FSC-H / FSC-W, so the course never assumes it.
- In the lens at resolution 0.5, PhenoGraph reports: cuts on Course 5's
  proposed "Cluster N" gates (FlowSOM agrees), a small T-cells cut, "DP holds
  two clusters" (the standing-apart one, ~22% of DP; only PhenoGraph) and
  "DN holds two clusters" (FlowSOM agrees). DN is ~20% of T-cells and most
  of it is the CD3-dim edge of the CD3− cluster next door: the T-cells
  gate's lower CD3 edge reaches into it.
- At resolution 1.0, three more findings appear (cuts on B-cells, T-cells
  and DN); with FlowSOM at k = 8 all are "Only this run finds it".

Cluster numbers differ run to run, so steps that name one get their text
from the validator (the `_best_bcell_step` idiom of Course 4).
"""

import re
from typing import Any

from karcytics_sdk.plugin.tutorial_models import (
    QUESTION_PREDICT,
    AnswerChoice,
    Course,
    InfoStep,
    QuestionStep,
    VerificationStep,
)

from ..analysis.population_matching import PATH_SEP
from ..main_tabs import MainTab
from .validators import (
    AllOf,
    ClusteredRunValidator,
    ClusteringMethodValidator,
    FlowsomColorValidator,
    FlowsomKValidator,
    FlowsomResultsReadyValidator,
    LensAgreementValidator,
    LensKValidator,
    LensResolutionValidator,
    LensRunMethodValidator,
    LensRunReadyValidator,
    LensSampleValidator,
    LineageGatingCompleteValidator,
    NewRunSelectedValidator,
    PhenographColorValidator,
    PhenographResolutionValidator,
    PhenographResultsReadyValidator,
    TabActiveValidator,
    UmapChannelExcludedValidator,
    UmapGateSelectedValidator,
    UmapSampleSelectedValidator,
    WorkflowSavedValidator,
    clusters_positive_for,
)

EXCLUDED = ("PerCP-Cy5-5-A", "APC-A")  # PI and CD45, as in Course 4

# ==============================================================================
# Dynamic texts: filled in by the validators from the learner's own run.
# ==============================================================================

_SEEN: dict[str, Any] = {}  # numbers one step measures and a later one compares


def _b220_text(tree: Any) -> str:
    tags = clusters_positive_for(tree, "B220")
    _SEEN["k10"] = tags
    return (
        "B220 lights up a big part of the tree: your B cells 🅱️<br><br>"
        f"But look at the legend: they're split over **{len(tags)} metaclusters** "
        f"({', '.join(tags)}), every one of them **B220+**."
    )


def _k5_text(tree: Any) -> str:
    before = len(_SEEN.get("k10", [])) or "several"
    after = len(clusters_positive_for(tree, "B220"))
    return (
        "Fewer, cleaner populations 🎯<br><br>"
        f"The B cells went from **{before}** B220+ metaclusters to **{after}**, "
        "while the T-cell branches kept their own colours. Nothing reran: FlowSOM "
        "just regrouped its 100 nodes.<br><br>"
        "A good k gives each family of branches one colour. Keep k = 5: the lens "
        "uses this run later."
    )


def _apart(graph: Any) -> dict[str, str]:
    """Phenotype -> "**C12** (B220+ CD3+, 1.4%)" for the clusters with no link to any other.

    Keyed by phenotype, since cluster numbers change with the resolution.
    """
    total = max(int(graph._counts.sum()), 1)
    return {
        graph._phenotype(c): (
            f"**{graph._name(c)}** ({graph._phenotype(c)}, {graph._counts[c] / total:.1%})"
        )
        for c in range(len(graph._counts))
        if graph.stands_apart(c) and graph._counts[c]
    }


def _fill_first_run(graph: Any) -> None:
    n = len(graph._counts)
    apart = _apart(graph)
    _SEEN["pg_n"] = n
    _SEEN["pg_apart"] = set(apart)
    _pg_reveal_step.text = (
        "The cluster graph 🕸️<br><br>"
        "You predicted: **{answer:cm_pg_count}**.<br><br>"
        f"PhenoGraph found **{n} clusters**. Nobody gave it a number: at "
        "resolution 1.0, that's how many groups the links between cells form.<br><br>"
        "Each circle is a **cluster** (bigger, more cells). A line joins two "
        "clusters whose cells are each other's neighbours; the thicker, the more "
        "linked. Positions only keep linked clusters close."
    )
    _pg_apart_step.text = (
        (
            "Standing apart 🏝️<br><br>"
            f"**{len(apart)}** cluster{'s' if len(apart) != 1 else ''} "
            f"{'have' if len(apart) != 1 else 'has'} no line to any other: "
            + ", ".join(apart.values())
            + ".<br><br>A circle on its own is a group of cells unlike all the "
            "rest: often small, always worth a look. The legend marks them "
            "*stands apart*."
        )
        if apart
        else (
            "Standing apart 🏝️<br><br>"
            "Every cluster here links to another. A circle with no lines would "
            "**stand apart**: a group unlike all the rest, worth a look."
        )
    )


def _pg_b220_text(graph: Any) -> str:
    tags = clusters_positive_for(graph, "B220")
    ids = {graph._name(c): c for c in range(len(graph._counts))}
    mine = {ids[t] for t in tags if t in ids}
    links = sum(
        1 for c in mine for other, _s in graph._links.get(c, []) if other in mine and other > c
    )
    joined = (
        "Most are joined by lines: one big population, cut along a gradient of marker levels."
        if links >= len(mine) - 1
        else "Few lines join them, so some may be separate B-cell groups."
    )
    return (
        f"B220 lights up **{len(tags)} of {len(graph._counts)} clusters**: "
        f"your B cells, the biggest population here 🅱️<br><br>{joined}<br><br>"
        "Like FlowSOM at k = 10, PhenoGraph at resolution 1.0 splits a big "
        "population finely. Unlike FlowSOM, you didn't ask for that number."
    )


def _pg_res05_text(graph: Any) -> str:
    before = _SEEN.get("pg_n", "the")
    apart = _apart(graph)
    first = _SEEN.get("pg_apart", set())
    kept = [text for phenotype, text in apart.items() if phenotype in first]
    new = [text for phenotype, text in apart.items() if phenotype not in first]
    lines = []
    if kept:
        lines.append(
            "Still standing apart: " + ", ".join(kept) + ". A group that keeps "
            "apart at both resolutions is a steady feature of the data."
        )
    if new:
        lines.append(
            "Newly apart: " + ", ".join(new) + ". Merged into one cluster, its "
            "links to the rest are too weak to draw."
        )
    return (
        f"From **{before}** clusters to **{len(graph._counts)}** 🔁<br><br>"
        "Clusters that were split along a gradient merged; the links between "
        "cells didn't change, only how finely they're divided."
        + "".join(f"<br><br>{line}" for line in lines)
    )


_PROPOSED = re.compile(r"^Cluster \d+( · pre-gate \d+)?$")


def _gate(finding: Any) -> str:
    return (finding.population or "").rsplit(PATH_SEP, 1)[-1]


def _what(finding: Any) -> tuple[Any, str]:
    """What a finding says, without cluster numbers (they change with the resolution)."""
    return finding.kind, _gate(finding)


def _pg_findings_text(pairs: list[tuple[Any, Any]]) -> str:
    _SEEN["pg_findings"] = {_what(f) for f, _a in pairs}
    proposed = [f for f, _a in pairs if _PROPOSED.match(_gate(f))]
    shared = [f for f, a in pairs if a.found_by and f not in proposed]
    alone = [f for f, a in pairs if not a.found_by and f not in proposed]
    lines = []
    if proposed:
        lines.append(
            f"• **{len(proposed)}** on your proposed Cluster gates. You fitted "
            "those to UMAP's cluster in Course 5, so another method's borders "
            "won't match them, and UMAP itself reports nothing there."
        )
    if shared:
        names = ", ".join(sorted({_gate(f) for f in shared}))
        lines.append(f"• **{len(shared)}** another run also finds ({names}). Agreement counts.")
    if alone:
        names = ", ".join(sorted({_gate(f) for f in alone}))
        lines.append(f"• **{len(alone)}** only PhenoGraph finds ({names}).")
    return (
        f"PhenoGraph's view of your gates 🔍<br><br>**{len(pairs)} findings.** "
        "The grey line under each says whether your other runs report it:<br>" + "<br>".join(lines)
    )


def _pg_res10_text(lens: Any) -> str:
    before = _SEEN.get("pg_findings", set())
    pairs = list(zip(lens._model.findings, lens._model.agreements, strict=False))
    now = {_what(f) for f, _a in pairs}
    new = [(f, a) for f, a in pairs if _what(f) not in before]
    gone = len(before - now)
    alone = sum(1 for _f, a in new if not a.found_by)
    listed = "<br>".join(f"• {f.title}" for f, _a in new)
    summary = (
        f"**{len(new)} new** finding{'s' if len(new) != 1 else ''}"
        if new
        else "**no new** findings"
    ) + (f", {gone} gone" if gone else "")
    return (
        f"Same gates, finer grain 🔬<br><br>At resolution 1.0: {summary}."
        + (f"<br>{listed}<br>{alone} of the new ones only this run finds." if new else "")
        + "<br><br>Your gates didn't move. A finding that comes and goes with the "
        "resolution is about the method's grain; one that holds at both, and that "
        "another method shares, is about your gates."
    )


# Steps whose text the validators fill in (module-level, as in Course 4).
_b220_read_step: InfoStep = InfoStep(
    id="cm_f11_b220_read",
    text="B220 lights up a big part of the tree: your B cells 🅱️",
    cyto_emotion="surprised",
    allow_interaction=True,
    target_widget_names=["FlowsomTreeCanvas", "FlowsomLegend"],
    next_step_id="cm_f12_k_high",
)

_k5_read_step: InfoStep = InfoStep(
    id="cm_f16_k5_read",
    text="Fewer, cleaner populations 🎯",
    cyto_emotion="happy",
    allow_interaction=True,
    target_widget_names=["FlowsomTreeCanvas", "FlowsomLegend"],
    next_step_id="cm_f17_noise_reveal",
)

_pg_reveal_step: InfoStep = InfoStep(
    id="cm_p07_reveal",
    text="The cluster graph 🕸️<br><br>You predicted: **{answer:cm_pg_count}**.",
    cyto_emotion="surprised",
    allow_interaction=True,
    target_widget_names=["PhenographGraphCanvas", "PhenographLegend"],
    next_step_id="cm_p08_colour_b220",
)

_pg_b220_step: InfoStep = InfoStep(
    id="cm_p09_b220_read",
    text="B220 lights up your B cells 🅱️",
    cyto_emotion="happy",
    allow_interaction=True,
    target_widget_names=["PhenographGraphCanvas", "PhenographLegend"],
    next_step_id="cm_p10_apart",
)

_pg_apart_step: InfoStep = InfoStep(
    id="cm_p10_apart",
    text="Standing apart 🏝️",
    cyto_emotion="thinking",
    allow_interaction=True,
    target_widget_names=["PhenographGraphCanvas", "PhenographLegend"],
    next_step_id="cm_p11_apart_question",
)

_pg_res05_step: InfoStep = InfoStep(
    id="cm_p14_res05_read",
    text="Fewer clusters 🔁",
    cyto_emotion="happy",
    allow_interaction=True,
    target_widget_names=["PhenographGraphCanvas", "PhenographLegend"],
    next_step_id="cm_p15_which_resolution",
)

_pg_findings_step: InfoStep = InfoStep(
    id="cm_l09_pg_findings",
    text="PhenoGraph's view of your gates 🔍",
    cyto_emotion="talking",
    allow_interaction=True,
    target_widget_names=["SampleLensFindings"],
    next_step_id="cm_l10_cuts",
)

_pg_res10_step: InfoStep = InfoStep(
    id="cm_l14_res10_read",
    text="Same gates, finer grain 🔬",
    cyto_emotion="thinking",
    allow_interaction=True,
    target_widget_names=["SampleLensFindings"],
    next_step_id="cm_l15_weigh",
)

course_second_opinions = Course(
    id="flow_course_clustering_methods",
    title="Second Opinions: FlowSOM & PhenoGraph",
    description=(
        "Run two more clustering methods on the cells UMAP clustered: read "
        "FlowSOM's tree and PhenoGraph's cluster graph, see how each chooses "
        "its grain, then ask the Sample Lens which findings the methods agree on."
    ),
    estimated_minutes=45,
    badge_reward="Second Opinion",
    badge_icon="🩺",
    prerequisite_course_ids=["flow_course_5_sample_lens"],
    steps=[
        InfoStep(
            id="cm_s00_intro",
            text=(
                "Welcome to Course 6! 🩺<br><br>"
                "UMAP + HDBSCAN gave you one opinion on Sample C. Today you ask "
                "two more methods that work differently:<br>"
                "• **FlowSOM**, the method most used in cytometry, where you choose "
                "how many populations (**k**).<br>"
                "• **PhenoGraph**, which links each cell to its most similar cells "
                "and lets the links decide; you choose how fine (**resolution**).<br><br>"
                "Then the Sample Lens shows which findings they agree on."
            ),
            cyto_emotion="happy",
            next_step_id="cm_s01_predict",
        ),
        QuestionStep(
            id="cm_s01_predict",
            text=(
                "Make a prediction 🔮<br><br>"
                "In Course 5, UMAP + HDBSCAN had nothing left to say about your "
                "gates. Asked the same question, what will the two new methods do?"
            ),
            kind=QUESTION_PREDICT,
            question_id="cm_methods_agree",
            choices=[
                AnswerChoice("Find nothing either"),
                AnswerChoice("Each report something different"),
                AnswerChoice("Agree on some findings, not others"),
            ],
            cyto_emotion="thinking",
            next_step_id="cm_s02_check",
        ),
        VerificationStep(
            id="cm_s02_check",
            text="Checking for your gates and Course 4's clustering run...",
            cyto_emotion="scanning",
            hide_next_button=True,
            validator=AllOf(LineageGatingCompleteValidator(), ClusteredRunValidator("sample c")),
            on_success_step_id="cm_s03_tab",
            on_fail_step_id="cm_s02b_missing",
        ),
        InfoStep(
            # Exits rather than looping against a dead end, as Course 4's
            # c4_s01b_incomplete_gating does.
            id="cm_s02b_missing",
            text=(
                "Missing something 🔍<br><br>"
                "This course needs the **Leukocytes**, **T-cells** and **B-cells** "
                "gates from Course 3, and Course 4's **UMAP + HDBSCAN** run on "
                "**Sample C**. Finish those courses first, then relaunch this one."
            ),
            cyto_emotion="thinking",
            next_step_id="__abandon__",
        ),
        VerificationStep(
            id="cm_s03_tab",
            text="Click the **Population Analysis** tab at the top.",
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["MainTabBar"],
            validator=TabActiveValidator(MainTab.POPULATION_ANALYSIS),
            on_success_step_id="cm_s04_sample",
        ),
        VerificationStep(
            id="cm_s04_sample",
            text="Same cells as Course 4: set **Sample** to 'Sample C'.",
            cyto_emotion="pointing",
            allow_interaction=True,
            allow_scroll=True,
            hide_next_button=True,
            target_widget_names=["UmapSampleCombo"],
            validator=UmapSampleSelectedValidator("sample c"),
            on_success_step_id="cm_s05_gate",
        ),
        VerificationStep(
            id="cm_s05_gate",
            text="Set **Population (Gate)** to 'Leukocytes'.",
            cyto_emotion="pointing",
            allow_interaction=True,
            allow_scroll=True,
            hide_next_button=True,
            target_widget_names=["UmapGateCombo"],
            validator=UmapGateSelectedValidator("leukocytes"),
            on_success_step_id="cm_f01_flowsom_intro",
        ),
        # ── FlowSOM ─────────────────────────────────────────────────────────────
        InfoStep(
            id="cm_f01_flowsom_intro",
            text=(
                "FlowSOM 🌳<br><br>"
                "HDBSCAN found clusters by **density** and set the scattered "
                "cells aside as noise (cluster -1).<br><br>"
                "**FlowSOM** works differently: it sorts the cells into about 100 "
                "small groups called **nodes**, links similar nodes into a tree, "
                "and groups the tree into **metaclusters**, its populations."
            ),
            cyto_emotion="talking",
            next_step_id="cm_f02_noise_predict",
        ),
        QuestionStep(
            id="cm_f02_noise_predict",
            text=(
                "Make a prediction 🔮<br><br>"
                "HDBSCAN set some cells aside as noise. What will FlowSOM do "
                "with those same cells?"
            ),
            kind=QUESTION_PREDICT,
            question_id="cm_flowsom_noise",
            choices=[
                AnswerChoice("Leave them out as noise too"),
                AnswerChoice("Collect them in one noise metacluster"),
                AnswerChoice("Put them in a metacluster, like every other cell"),
            ],
            cyto_emotion="thinking",
            next_step_id="cm_f03_new_run",
        ),
        VerificationStep(
            id="cm_f03_new_run",
            text=(
                "In **History**, pick **[ New Run ]** if a past run is showing: "
                "the settings unlock again."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            allow_scroll=True,
            hide_next_button=True,
            target_widget_names=["UmapHistoryCombo"],
            validator=NewRunSelectedValidator(),
            on_success_step_id="cm_f04_choose_flowsom",
        ),
        VerificationStep(
            id="cm_f04_choose_flowsom",
            text=(
                "Set **Algorithm** to **FlowSOM** (top of the left panel), and in "
                "the channel list leave **PI and CD45 unchecked**, as in Course 4."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            allow_scroll=True,
            hide_next_button=True,
            target_widget_names=["ClusteringMethodCombo", "UmapChannelList"],
            validator=AllOf(
                ClusteringMethodValidator("flowsom"), UmapChannelExcludedValidator(*EXCLUDED)
            ),
            on_success_step_id="cm_f05_flowsom_settings",
            failure_hint="Pick FlowSOM under Algorithm, then uncheck only PI and CD45.",
        ),
        InfoStep(
            id="cm_f05_flowsom_settings",
            text=(
                "FlowSOM's settings ⚙️<br><br>"
                "**Grid size** 10 means 10 × 10 = 100 nodes.<br>"
                "**Metaclusters (k)** is how many populations to make: roughly "
                "how many cell types you expect. Leave it at 10 for now; you'll "
                "change it after the run.<br>"
                "**Training passes** can stay.<br><br>"
                "**Events used** jumped to 100%: FlowSOM is fast enough for "
                "every cell."
            ),
            cyto_emotion="talking",
            allow_interaction=True,
            allow_scroll=True,
            target_widget_names=["FlowsomParams", "UmapSubsampleGroup"],
            next_step_id="cm_f06_run_flowsom",
        ),
        VerificationStep(
            id="cm_f06_run_flowsom",
            text=(
                "Name the run, e.g. **Sample C FlowSOM**, and click "
                "**🧬 Run Analysis**. It takes a few seconds."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            allow_scroll=True,
            hide_next_button=True,
            target_widget_names=["UmapRunNameInput", "RunAnalysisButton"],
            validator=FlowsomResultsReadyValidator(),
            on_success_step_id="cm_f07_tree_anatomy",
        ),
        InfoStep(
            id="cm_f07_tree_anatomy",
            text=(
                "The FlowSOM tree 🌳<br><br>"
                "Each circle is a **node**: a small group of very similar cells. "
                "Bigger circle, more cells.<br>"
                "Lines join each node to the nodes most like it, so a branch is "
                "a family of related cells.<br>"
                "Colours are the metaclusters.<br><br>"
                "Like UMAP's axes, positions and line lengths mean nothing. "
                "Only the connections do."
            ),
            cyto_emotion="talking",
            allow_interaction=True,
            target_widget_names=["FlowsomTreeCanvas"],
            next_step_id="cm_f08_colour_cd3",
        ),
        VerificationStep(
            id="cm_f08_colour_cd3",
            text=(
                "Scientists read this tree one marker at a time. Open **Colour "
                "by** and pick **CD3**, the T-cell marker."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["FlowsomColorCombo"],
            validator=FlowsomColorValidator("CD3"),
            on_success_step_id="cm_f09_cd3_read",
        ),
        InfoStep(
            id="cm_f09_cd3_read",
            text=(
                "The bright nodes are your T cells 💡<br><br>"
                "They sit together on their own branches: the tree keeps related "
                "cells together. Colour runs from the dimmest node to the "
                "brightest, so even small differences show.<br><br>"
                "Hover a bright node: the bottom right shows its cells and its "
                "metacluster's phenotype."
            ),
            cyto_emotion="happy",
            allow_interaction=True,
            target_widget_names=["FlowsomTreeCanvas"],
            next_step_id="cm_f10_colour_b220",
        ),
        VerificationStep(
            id="cm_f10_colour_b220",
            text="Now colour by **B220**, the B-cell marker.",
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["FlowsomColorCombo"],
            validator=FlowsomColorValidator(
                "B220", on_found=lambda tree: setattr(_b220_read_step, "text", _b220_text(tree))
            ),
            on_success_step_id="cm_f11_b220_read",
        ),
        _b220_read_step,
        QuestionStep(
            id="cm_f12_k_high",
            text=(
                "Several metaclusters, one phenotype, one family of branches. "
                "What does that most likely mean?"
            ),
            question_id="cm_flowsom_k_high",
            choices=[
                AnswerChoice(
                    "FlowSOM found new B-cell subsets",
                    feedback="Possible, but their phenotypes match. Same phenotype first suggests too many metaclusters.",
                ),
                AnswerChoice(
                    "The run went wrong",
                    feedback="It didn't. FlowSOM did exactly what k asked: it made 10 groups.",
                ),
                AnswerChoice(
                    "k is higher than this panel needs",
                    correct=True,
                ),
            ],
            explanation=(
                "FlowSOM always makes exactly k metaclusters. Four markers "
                "describe about five populations here, so at k = 10 the "
                "biggest one, the B cells, gets split."
            ),
            cyto_emotion="thinking",
            next_step_id="cm_f13_phenotypes",
        ),
        InfoStep(
            id="cm_f13_phenotypes",
            text=(
                "Naming metaclusters 🧬<br><br>"
                "Each legend line gives a metacluster's share of cells and its "
                "**phenotype**. Per marker, the dimmest metacluster is **−**, "
                "the brightest **+**, and **lo** is in between. The heatmap "
                "shows the same for every marker at once.<br><br>"
                "**B220+ CD3−** is B cells, **CD3+ CD4+** CD4 T cells, "
                "**CD3+ CD8+** CD8 T cells."
            ),
            cyto_emotion="talking",
            allow_interaction=True,
            target_widget_names=["FlowsomLegend", "FlowsomHeatmap"],
            next_step_id="cm_f14_all_negative",
        ),
        QuestionStep(
            id="cm_f14_all_negative",
            text=(
                "Find the metacluster that's **−** for all four markers. In "
                "this panel, what could those cells be?"
            ),
            question_id="cm_flowsom_all_negative",
            choices=[
                AnswerChoice(
                    "Dead cells",
                    feedback="Course 3's PI gate removed dead cells before Leukocytes, so they aren't in this run.",
                ),
                AnswerChoice(
                    "Cells none of these markers label, like NK or myeloid cells",
                    correct=True,
                ),
                AnswerChoice(
                    "B cells that lost their B220",
                    feedback="B cells keep B220. These cells carry none of the four markers.",
                ),
            ],
            explanation=(
                "Four markers can't name every leukocyte: NK cells, monocytes "
                "and others carry none of them. They're the cells Course 5's "
                "lens found outside every gate, the ones you turned into "
                "Cluster gates."
            ),
            cyto_emotion="thinking",
            allow_interaction=True,
            target_widget_names=["FlowsomLegend", "FlowsomHeatmap"],
            next_step_id="cm_f15_set_k5",
        ),
        VerificationStep(
            id="cm_f15_set_k5",
            text="Set **Metaclusters (k)** to **5** (above the tree) and watch the colours.",
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["FlowsomKSpin"],
            validator=FlowsomKValidator(
                5, on_found=lambda tree: setattr(_k5_read_step, "text", _k5_text(tree))
            ),
            on_success_step_id="cm_f16_k5_read",
        ),
        _k5_read_step,
        InfoStep(
            id="cm_f17_noise_reveal",
            text=(
                "You predicted: **{answer:cm_flowsom_noise}**.<br><br>"
                "FlowSOM put **every** cell in a metacluster: the legend's shares "
                "add up to 100%. HDBSCAN's noise cells landed with whichever "
                "population they're nearest. Remember that: it shapes what the "
                "lens says about FlowSOM later."
            ),
            cyto_emotion="happy",
            next_step_id="cm_p01_intro",
        ),
        # ── PhenoGraph ──────────────────────────────────────────────────────────
        InfoStep(
            id="cm_p01_intro",
            text=(
                "PhenoGraph 🕸️<br><br>"
                "PhenoGraph links each cell to its **30 most similar cells**, then "
                "links two cells more strongly the more of those neighbours they "
                "share. Groups of cells linked more to each other than to the rest "
                "become **clusters**.<br><br>"
                "You don't choose how many: **resolution** sets how finely the "
                "links are divided. Only clusters smaller than 10 cells are set "
                "aside, so there's almost no noise."
            ),
            cyto_emotion="talking",
            next_step_id="cm_p02_predict",
        ),
        QuestionStep(
            id="cm_p02_predict",
            text=(
                "Make a prediction 🔮<br><br>"
                "FlowSOM made 10 metaclusters because you asked for 10. At its "
                "default settings, how many clusters will PhenoGraph find?"
            ),
            kind=QUESTION_PREDICT,
            question_id="cm_pg_count",
            choices=[
                AnswerChoice("Fewer than 10"),
                AnswerChoice("About 10"),
                AnswerChoice("More than 10"),
            ],
            cyto_emotion="thinking",
            next_step_id="cm_p03_new_run",
        ),
        VerificationStep(
            id="cm_p03_new_run",
            text="In **History**, pick **[ New Run ]**.",
            cyto_emotion="pointing",
            allow_interaction=True,
            allow_scroll=True,
            hide_next_button=True,
            target_widget_names=["UmapHistoryCombo"],
            validator=NewRunSelectedValidator(),
            on_success_step_id="cm_p04_choose",
        ),
        VerificationStep(
            id="cm_p04_choose",
            text=(
                "Set **Algorithm** to **PhenoGraph**. PI and CD45 should still be "
                "unchecked in the channel list."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            allow_scroll=True,
            hide_next_button=True,
            target_widget_names=["ClusteringMethodCombo", "UmapChannelList"],
            validator=AllOf(
                ClusteringMethodValidator("phenograph"), UmapChannelExcludedValidator(*EXCLUDED)
            ),
            on_success_step_id="cm_p05_settings",
            failure_hint="Pick PhenoGraph under Algorithm, then uncheck only PI and CD45.",
        ),
        InfoStep(
            id="cm_p05_settings",
            text=(
                "PhenoGraph's settings ⚙️<br><br>"
                "**Neighbours (k)** 30 is PhenoGraph's default: how many similar "
                "cells each cell is linked to.<br>"
                "**Resolution** 1.0: higher gives more, smaller clusters. You can "
                "change it after the run.<br>"
                "**Minimum cluster size** 10: smaller clusters become outliers.<br><br>"
                "Leave them all. Every cell is used, as with FlowSOM."
            ),
            cyto_emotion="talking",
            allow_interaction=True,
            allow_scroll=True,
            target_widget_names=["PhenographParams"],
            next_step_id="cm_p06_run",
        ),
        VerificationStep(
            id="cm_p06_run",
            text=(
                "Name the run, e.g. **Sample C PhenoGraph**, and click "
                "**🧬 Run Analysis**. Linking 200,000 cells takes about 15 seconds."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            allow_scroll=True,
            hide_next_button=True,
            target_widget_names=["UmapRunNameInput", "RunAnalysisButton"],
            validator=PhenographResultsReadyValidator(on_found=_fill_first_run),
            on_success_step_id="cm_p07_reveal",
        ),
        _pg_reveal_step,
        VerificationStep(
            id="cm_p08_colour_b220",
            text="Open **Colour by** above the graph and pick **B220**.",
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["PhenographColorCombo"],
            validator=PhenographColorValidator(
                "B220",
                on_found=lambda graph: setattr(_pg_b220_step, "text", _pg_b220_text(graph)),
            ),
            on_success_step_id="cm_p09_b220_read",
        ),
        _pg_b220_step,
        _pg_apart_step,
        QuestionStep(
            id="cm_p11_apart_question",
            text=(
                "The clusters standing apart are **B220+** and **CD3+**: a B-cell "
                "marker and a T-cell marker on the same cells. What are they?"
            ),
            question_id="cm_pg_apart",
            choices=[
                AnswerChoice(
                    "A new kind of cell",
                    feedback="Possible, but nothing here shows it. A rare, odd phenotype needs checking before it's named.",
                ),
                AnswerChoice(
                    "Doublets: a B cell and a T cell stuck together",
                    feedback=(
                        "A real possibility: two cells passing the laser together look "
                        "like this. But these files have no FSC-H or FSC-W, so you can't "
                        "gate single cells to check. Don't assume it."
                    ),
                ),
                AnswerChoice(
                    "You can't tell from these markers yet",
                    correct=True,
                ),
            ],
            explanation=(
                "Doublets are a good suspect, and a singlet gate (FSC-H against "
                "FSC-A) would test it on data that has those channels. Until "
                "something tests it, a group that stands apart is a lead, not an answer."
            ),
            cyto_emotion="thinking",
            next_step_id="cm_p12_res_question",
        ),
        QuestionStep(
            id="cm_p12_res_question",
            text="What will lowering the **resolution** from 1.0 to 0.5 do?",
            question_id="cm_pg_resolution",
            choices=[
                AnswerChoice(
                    "Rerun the neighbours from scratch",
                    feedback="The links stay as they are. Only how finely they're divided changes, which is why it takes seconds.",
                ),
                AnswerChoice(
                    "Merge clusters into fewer, bigger ones",
                    correct=True,
                ),
                AnswerChoice(
                    "Split clusters into more, smaller ones",
                    feedback="That's a higher resolution. Lower divides the links more coarsely.",
                ),
            ],
            explanation=(
                "Resolution is PhenoGraph's k: it sets the grain, not the data. "
                "The links between cells stay the same."
            ),
            cyto_emotion="thinking",
            next_step_id="cm_p13_set_res",
        ),
        VerificationStep(
            id="cm_p13_set_res",
            text=(
                "Set **Resolution** above the graph to **0.5**. It re-clusters in a few seconds."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["PhenographResolutionSpin"],
            validator=PhenographResolutionValidator(
                0.5,
                on_found=lambda graph: setattr(_pg_res05_step, "text", _pg_res05_text(graph)),
            ),
            on_success_step_id="cm_p14_res05_read",
        ),
        _pg_res05_step,
        InfoStep(
            id="cm_p15_which_resolution",
            text=(
                "Which resolution is right? ⚖️<br><br>"
                "Neither: like FlowSOM's k and HDBSCAN's minimum cluster size, it "
                "picks the grain. Look for what holds across settings: a group "
                "that keeps standing apart, a population that stays one cluster.<br><br>"
                "Keep 0.5 for now. Next, the lens holds your gates up against "
                "both new runs."
            ),
            cyto_emotion="talking",
            next_step_id="cm_l01_tab",
        ),
        # ── The lens, against both ──────────────────────────────────────────────
        VerificationStep(
            id="cm_l01_tab",
            text="Click the **Sample Lens** tab at the top.",
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["MainTabBar"],
            validator=TabActiveValidator(MainTab.SAMPLE_LENS),
            on_success_step_id="cm_l02_sample",
        ),
        VerificationStep(
            id="cm_l02_sample",
            text="Choose **Sample C** in the **Sample** dropdown.",
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["SampleLensSampleCombo"],
            validator=AllOf(LensSampleValidator("sample c"), LensRunReadyValidator()),
            on_success_step_id="cm_l03_flowsom",
            failure_hint="Open the **Sample** dropdown at the top left and pick **Sample C**.",
        ),
        VerificationStep(
            id="cm_l03_flowsom",
            text="FlowSOM first. Pick your **FlowSOM** run in **Clustering run**.",
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["SampleLensRunCombo"],
            validator=LensRunMethodValidator("flowsom"),
            on_success_step_id="cm_l04_flowsom_read",
            failure_hint="Open **Clustering run** and pick the run with 'FlowSOM' in its name.",
        ),
        InfoStep(
            id="cm_l04_flowsom_read",
            text=(
                "Same lens, another method 🔍<br><br>"
                "Findings now name **metaclusters** and their phenotype, and the "
                "map is the FlowSOM tree, with a finding's nodes ringed.<br><br>"
                "FlowSOM always makes k groups, so the lens only calls it a merge "
                "when the phenotypes clearly differ, and groups findings that "
                "share a phenotype."
            ),
            cyto_emotion="talking",
            allow_interaction=True,
            target_widget_names=["SampleLensFindings", "SampleLensMap"],
            next_step_id="cm_l05_flowsom_k",
        ),
        VerificationStep(
            id="cm_l05_flowsom_k",
            text=(
                "You left this run at k = 5. Set **Metaclusters (k)** to **8** and "
                "watch the findings."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["SampleLensKSpin", "SampleLensFindings"],
            validator=LensKValidator(8),
            on_success_step_id="cm_l06_flowsom_findings",
        ),
        InfoStep(
            id="cm_l06_flowsom_findings",
            text=(
                "Why these findings? 🤔<br><br>"
                "Your gates didn't change. Most of these come from how FlowSOM works:<br>"
                "• **No noise.** HDBSCAN leaves in-between cells out; FlowSOM puts "
                "every cell in a metacluster. A gate that skips a population's sparse "
                "edge then looks like a cut, keeping 75–90%.<br>"
                "• **The proposed gates** (the *Cluster* ones from Course 5) were "
                "fitted to UMAP's cluster, so FlowSOM's borders won't match them.<br>"
                "• **Few, broad groups.** At low k a big metacluster's edge spills into "
                "a small gate such as DN."
            ),
            cyto_emotion="thinking",
            allow_interaction=True,
            target_widget_names=["SampleLensFindings"],
            next_step_id="cm_l07_agreement",
        ),
        InfoStep(
            id="cm_l07_agreement",
            text=(
                "The grey line 🤝<br><br>"
                "Under each finding, the lens says whether your **other runs** of "
                "these cells report the same thing: *Also found by …* or *Only "
                "this run finds it*.<br><br>"
                "Cluster numbers mean nothing across runs, so it matches what "
                "findings say: the same kind of finding on the same gate, or, for "
                "missed cells, mostly the same cells."
            ),
            cyto_emotion="talking",
            allow_interaction=True,
            target_widget_names=["SampleLensFindings"],
            next_step_id="cm_l08_phenograph",
        ),
        VerificationStep(
            id="cm_l08_phenograph",
            text="Now pick your **PhenoGraph** run in **Clustering run**.",
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["SampleLensRunCombo"],
            validator=AllOf(
                LensRunMethodValidator("phenograph"),
                LensAgreementValidator(
                    on_found=lambda pairs: setattr(
                        _pg_findings_step, "text", _pg_findings_text(pairs)
                    )
                ),
            ),
            on_success_step_id="cm_l09_pg_findings",
            failure_hint="Open **Clustering run** and pick the run with 'PhenoGraph' in its name.",
        ),
        _pg_findings_step,
        InfoStep(
            id="cm_l10_cuts",
            text=(
                "The cuts ✂️<br><br>"
                "A cut's detail says how much of the cluster the gate keeps. "
                "**80–90%** is a gate edge in a cluster's sparse tail: PhenoGraph, "
                "like FlowSOM, puts nearly every cell in a cluster, where HDBSCAN "
                "would call the tail noise.<br><br>"
                "Read those as *this edge sits in a gradient*, not *this gate is "
                "wrong*. Click one to see its cells ringed on the map."
            ),
            cyto_emotion="talking",
            allow_interaction=True,
            target_widget_names=["SampleLensFindings", "SampleLensMap"],
            next_step_id="cm_l11_dn",
        ),
        QuestionStep(
            id="cm_l11_dn",
            text=(
                "FlowSOM and PhenoGraph both say **DN holds two clusters**, and the "
                "bigger one is **CD3−**. DN sits inside T-cells. What's the most "
                "likely story?"
            ),
            question_id="cm_dn_story",
            choices=[
                AnswerChoice(
                    "DN is a new kind of CD3− T cell",
                    feedback="T cells carry CD3. A CD3− cluster inside a T-cell gate points at the gate first.",
                ),
                AnswerChoice(
                    "The T-cells gate's lower CD3 edge reaches into the CD3− cells next door",
                    correct=True,
                ),
                AnswerChoice(
                    "Both methods are wrong",
                    feedback="Two methods that work differently agree. That's when a finding deserves a look.",
                ),
            ],
            explanation=(
                "Most of DN's cells belong to the CD3− cluster and are dimmer for "
                "CD3 than other T cells: that population's dim edge crosses the "
                "T-cells gate and lands in DN. Some may be real, but DN's number "
                "mostly reflects where the T-cells edge sits."
            ),
            cyto_emotion="thinking",
            allow_interaction=True,
            target_widget_names=["SampleLensFindings"],
            next_step_id="cm_l12_dp",
        ),
        QuestionStep(
            id="cm_l12_dp",
            text=(
                "Only PhenoGraph says **DP holds two clusters**: the second is the "
                "**B220+ CD4+ CD3+ CD8+** group that stood apart in the graph. What "
                "do you do with it?"
            ),
            question_id="cm_dp_only_one",
            choices=[
                AnswerChoice(
                    "Gate it out of DP: they're doublets",
                    feedback="Maybe they are, but nothing here proves it, and these files can't be checked for singlets.",
                ),
                AnswerChoice(
                    "Ignore it: only one method reports it",
                    feedback=(
                        "One method is a reason for caution, not for ignoring it. Small, "
                        "distinct groups are what PhenoGraph finds best."
                    ),
                ),
                AnswerChoice(
                    "Note it, and check it another way before changing a gate",
                    correct=True,
                ),
            ],
            explanation=(
                "A finding one method reports is a lead, not a verdict. Here the "
                "check would be a singlet gate on data that has FSC-H, or a "
                "closer look at those cells. Until then, DP's number carries a caveat."
            ),
            cyto_emotion="thinking",
            next_step_id="cm_l13_res10",
        ),
        VerificationStep(
            id="cm_l13_res10",
            text=(
                "Back to the finer grain: set the lens's **Resolution** to **1.0** "
                "and watch the findings."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["SampleLensResolutionSpin", "SampleLensFindings"],
            validator=LensResolutionValidator(
                1.0, on_found=lambda lens: setattr(_pg_res10_step, "text", _pg_res10_text(lens))
            ),
            on_success_step_id="cm_l14_res10_read",
        ),
        _pg_res10_step,
        InfoStep(
            id="cm_l15_weigh",
            text=(
                "Which findings to trust ⚖️<br><br>"
                "• **Shared** by methods that work differently, and holding across "
                "settings: about your gates. Look at it (DN).<br>"
                "• **One method, one setting:** about the method. Set it aside.<br>"
                "• **One method, but steady and distinct:** a lead. Note it and "
                "check it another way (DP).<br><br>"
                "No method is the truth, the lens included. The gates are your call."
            ),
            cyto_emotion="thinking",
            next_step_id="cm_s90_prediction_back",
        ),
        # ── Wrap-up ─────────────────────────────────────────────────────────────
        InfoStep(
            id="cm_s90_prediction_back",
            text=(
                "Your prediction 🔮<br><br>"
                "At the start you predicted: **{answer:cm_methods_agree}**.<br><br>"
                "They agreed on some findings and not others. Where HDBSCAN set "
                "in-between cells aside, FlowSOM and PhenoGraph put them in "
                "clusters, so they saw edges UMAP didn't, and the agreement line "
                "sorted the shared findings from the method's own."
            ),
            cyto_emotion="happy",
            next_step_id="cm_s91_save",
        ),
        VerificationStep(
            id="cm_s91_save",
            text=(
                "Course 7 reports numbers from these gates. Save your progress, "
                "with both new runs.<br><br>"
                "Click the **⚠️ Save Workspace** button (highlighted) at the top right."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["WorkspaceSaveButton"],
            validator=WorkflowSavedValidator(),
            on_success_step_id="cm_s92_graduation",
            failure_hint="Click **⚠️ Save Workspace**, give it a name, and click Save to finish.",
        ),
        InfoStep(
            # The true end of the course: no next_step_id, so the Academy
            # awards the badge when the learner clicks Next.
            id="cm_s92_graduation",
            text=(
                "Your workspace is updated!<br><br>Course 6 is complete — you can "
                "now get a **Second Opinion** on any gate! 🏆<br><br>"
                "In Course 7 you'll report the numbers your gates give."
            ),
            cyto_emotion="cheering",
            cyto_animation="cheering",
        ),
    ],
)
