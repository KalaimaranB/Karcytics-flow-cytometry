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

Main tab bar order (0-indexed): Workspace, Compensation, Gating, Pipeline,
Statistics, Spectral, Population Analysis, Comparisons.

Panel reference (confirmed from the tutorial FCS file headers, $PnN/$PnS —
see course2.py's header for the full table):
  CD45 = APC-A          | pan-leukocyte gating channel
  PI   = PerCP-Cy5-5-A   | viability dye

Course 3 — Part 1 — does no new gating: it validates the gating tree
Course 2 built, then hands the user to unsupervised Population Analysis
(UMAP + HDBSCAN) on Sample C (the confirmed Spleen), walking every run
parameter with real justification, the live animation, the Plot Gallery,
and the Interactive Map. This is deliberately only the first half of the
eventual Course 3 — it ends on a soft "more soon" note rather than a full
graduation, so no completion/badge fires. See the closing step's
docstring-style comment for how that's guaranteed.
"""

from karcytics_sdk.plugin.tutorial_models import (
    Course,
    InfoStep,
    InteractionStep,
    VerificationStep,
)

from .validators import (
    ClusterResultsTabActiveValidator,
    Course2GatingCompleteValidator,
    TabActiveValidator,
    UmapChannelExcludedValidator,
    UmapGateSelectedValidator,
    UmapHdbscanEnabledValidator,
    UmapResultsReadyValidator,
    UmapRunNameProvidedValidator,
    UmapSampleSelectedValidator,
    UmapSubsampleValueValidator,
)

# ==============================================================================
# Course 3 (Part 1) — Population Analysis
# No new gating. Validates Course 2's tree, then walks unsupervised
# UMAP + HDBSCAN clustering on Sample C end to end.
# ==============================================================================

course_3_analysis = Course(
    id="flow_course_3_analysis",
    title="Population Analysis",
    description=(
        "Validate your Course 2 gating, then let UMAP and HDBSCAN independently "
        "cluster Sample C with zero manual gates — parameter by parameter, with "
        "the real animation and Interactive Map."
    ),
    estimated_minutes=30,
    badge_reward="Population Analyst",
    badge_icon="🧠",
    prerequisite_course_ids=["flow_course_2_gating"],
    steps=[
        InfoStep(
            id="c3_s00_intro",
            text=(
                "Welcome to Course 3! 🧠<br><br>"
                "Course 2 left you with a hand-drawn hierarchy — Leukocytes, "
                "T-cells, B-cells, and the CD4/CD8 subsets — across all three "
                "samples.<br><br>"
                "This course hands that same data to an algorithm that has "
                "never seen your gates, and lets it draw its own conclusions."
            ),
            cyto_emotion="happy",
            next_step_id="c3_s01_validate_gating",
        ),
        # ── Validate Course 2's gating tree ─────────────────────────────────────
        VerificationStep(
            id="c3_s01_validate_gating",
            text="Checking your gating tree from Course 2...",
            cyto_emotion="scanning",
            hide_next_button=True,
            validator=Course2GatingCompleteValidator(),
            on_success_step_id="c3_s02_pop_analysis_switch",
            on_fail_step_id="c3_s01b_incomplete_gating",
        ),
        InfoStep(
            id="c3_s01b_incomplete_gating",
            text=(
                "Missing a gate 🔍<br><br>"
                "Every sample needs **Leukocytes**, **T-cells**, and **B-cells** "
                "gated before Course 3 can continue — that's the foundation "
                "Course 2 built. Head back and finish that course first, then "
                "relaunch Course 3."
            ),
            cyto_emotion="thinking",
        ),
        # ── Switch to Population Analysis tab ───────────────────────────────────
        InteractionStep(
            id="c3_s02_pop_analysis_switch",
            text="Your gating tree checks out! Click the 'Population Analysis' tab at the top.",
            cyto_emotion="pointing",
            target_widget_name="MainTabBar",
            target_widget_names=["MainTabBar"],
            event_trigger="currentChanged",
            next_step_id="c3_s03_verify_pop_tab",
        ),
        VerificationStep(
            id="c3_s03_verify_pop_tab",
            text="Checking tab...",
            cyto_emotion="scanning",
            hide_next_button=True,
            validator=TabActiveValidator(6),
            on_success_step_id="c3_s04_umap_theory_1",
            on_fail_step_id="c3_s03b_wrong_tab",
        ),
        InteractionStep(
            id="c3_s03b_wrong_tab",
            text="Oops! Click the 'Population Analysis' tab to proceed.",
            cyto_emotion="surprised",
            target_widget_name="MainTabBar",
            target_widget_names=["MainTabBar"],
            event_trigger="currentChanged",
            next_step_id="c3_s03_verify_pop_tab",
        ),
        # ── UMAP theory ──────────────────────────────────────────────────────────
        InfoStep(
            id="c3_s04_umap_theory_1",
            text=(
                "Understanding UMAP 🧠<br><br>"
                "You have 6 fluorescence channels — every cell is a point in "
                "6-dimensional space. **UMAP** (Uniform Manifold Approximation "
                "and Projection) is a dimension-reduction technique: it flattens "
                "that 6D cloud down onto a 2D map you can actually look at, the "
                "same way t-SNE does, while trying much harder to preserve both "
                "local neighborhoods and the broader shape between them."
            ),
            cyto_emotion="thinking",
            next_step_id="c3_s05_umap_theory_2",
        ),
        InfoStep(
            id="c3_s05_umap_theory_2",
            text=(
                "Reading the result 🗺️<br><br>"
                "The **axes themselves have no biological meaning** — there's "
                "no 'CD3 axis'. What matters is which cells end up near each "
                "other. A tight cluster of points ('island') that stays "
                "together means UMAP found those cells similar across all 6 "
                "channels at once — often a real, biologically coherent "
                "population, discovered with no gates drawn by you at all."
            ),
            cyto_emotion="talking",
            next_step_id="c3_s06_video_rec",
        ),
        InfoStep(
            id="c3_s06_video_rec",
            text=(
                "Want the deeper dive? 🎥<br><br>"
                "StatQuest's walkthrough is the clearest explanation of how "
                "UMAP actually works under the hood, if you want more than "
                "the summary above:<br><br>"
                "[Watch: UMAP, Main Ideas!!! (StatQuest)](https://www.youtube.com/watch?v=m3s0Tgh8ofg)"
            ),
            cyto_emotion="happy",
            next_step_id="c3_s07_select_sample",
        ),
        # ── Select Sample C ──────────────────────────────────────────────────────
        VerificationStep(
            id="c3_s07_select_sample",
            text="In the sidebar, set **Sample** to 'Sample C'.",
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["UmapSampleCombo"],
            validator=UmapSampleSelectedValidator("sample c"),
            on_success_step_id="c3_s08_sample_why",
        ),
        InfoStep(
            id="c3_s08_sample_why",
            text=(
                "Why Sample C? 🧩<br><br>"
                "Course 2 confirmed Sample C is the **Spleen** — the one sample "
                "with mature T-cells *and* B-cells living side by side. That "
                "mix makes it the richest sample to hand to an unsupervised "
                "algorithm: there's more than one real population for it to "
                "actually have to separate."
            ),
            cyto_emotion="happy",
            next_step_id="c3_s09_select_gate",
        ),
        # ── Select the population gate ───────────────────────────────────────────
        VerificationStep(
            id="c3_s09_select_gate",
            text="Set **Population (Gate)** to 'Leukocytes'.",
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["UmapGateCombo"],
            validator=UmapGateSelectedValidator("leukocytes"),
            on_success_step_id="c3_s10_gate_why",
        ),
        InfoStep(
            id="c3_s10_gate_why",
            text=(
                "Why gate first? 🚫<br><br>"
                "It's tempting to run UMAP on 'All Events' — but debris and "
                "dead cells have no real biological identity, and UMAP will "
                "happily invent fake structure out of that noise. Feeding it "
                "the same **Leukocytes** gate you've used all along excludes "
                "exactly that noise, so every 'island' it finds is made of "
                "real, living, lineage-committed cells."
            ),
            cyto_emotion="thinking",
            next_step_id="c3_s11_exclude_channels",
        ),
        # ── Exclude PI and CD45 ───────────────────────────────────────────────────
        VerificationStep(
            id="c3_s11_exclude_channels",
            text=(
                "In the channel list, **uncheck PI and CD45** — leave every other channel checked."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["UmapChannelList"],
            validator=UmapChannelExcludedValidator("PerCP-Cy5-5-A", "APC-A"),
            on_success_step_id="c3_s12_exclude_why",
        ),
        InfoStep(
            id="c3_s12_exclude_why",
            text=(
                "Why exclude exactly these two? ✂️<br><br>"
                "**PI** is a viability dye — it already did its job separating "
                "live from dead cells before this gate even started; among "
                "surviving Leukocytes, it carries no further information.<br><br>"
                "**CD45** is the pan-leukocyte marker you gated on to define "
                "this very population — everyone left in the room is already "
                "CD45+, so it can't tell UMAP anything to discriminate between "
                "them. Including either channel just adds dead weight the "
                "algorithm has to wade through for nothing."
            ),
            cyto_emotion="talking",
            next_step_id="c3_s13_run_name",
        ),
        # ── Run name ─────────────────────────────────────────────────────────────
        VerificationStep(
            id="c3_s13_run_name",
            text="Give this run a name — anything memorable works, e.g. 'Sample C Overview'.",
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["UmapRunNameInput"],
            validator=UmapRunNameProvidedValidator(),
            on_success_step_id="c3_s14_neighbors",
        ),
        # ── Explain Neighbors + Min Distance ─────────────────────────────────────
        InfoStep(
            id="c3_s14_neighbors",
            text=(
                "Neighbors 🔗<br><br>"
                "This controls how many nearby cells UMAP looks at when "
                "deciding what 'close together' means. **Lower** values (5-15) "
                "chase fine, local detail — small, tight sub-populations. "
                "**Higher** values (30-50) smooth that out in favor of the big "
                "picture — how the major lineages relate to each other overall. "
                "There's no single right answer here; it's a genuine judgment "
                "call about what you're looking for."
            ),
            cyto_emotion="talking",
            target_widget_names=["UmapNeighborsSlider"],
            next_step_id="c3_s15_min_dist",
        ),
        InfoStep(
            id="c3_s15_min_dist",
            text=(
                "Min Distance 📏<br><br>"
                "This controls how tightly UMAP is allowed to pack points "
                "together in the final 2D layout. **Lower** values (0.0-0.1) "
                "pack points densely — good for spotting rare, highly similar "
                "subtypes. **Higher** values (0.3-0.5) spread everything out, "
                "which can make broad lineage relationships easier to read at "
                "a glance, at the cost of local detail."
            ),
            cyto_emotion="talking",
            target_widget_names=["UmapMinDistSlider"],
            next_step_id="c3_s16_subsample",
        ),
        # ── Subsample = 25% ──────────────────────────────────────────────────────
        VerificationStep(
            id="c3_s16_subsample",
            text="Set **Subsample Events** to 25%.",
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["UmapSubsampleSlider"],
            validator=UmapSubsampleValueValidator(25),
            on_success_step_id="c3_s17_subsample_why",
        ),
        InfoStep(
            id="c3_s17_subsample_why",
            text=(
                "Why not use every event? ⚡<br><br>"
                "UMAP scales non-linearly — running it on the full event count "
                "can be very slow for very little extra insight. **25%** keeps "
                "every real population statistically well represented while "
                "keeping the run fast enough to iterate on."
            ),
            cyto_emotion="happy",
            next_step_id="c3_s18_metric",
        ),
        # ── Explain Distance Metric + Seed ───────────────────────────────────────
        InfoStep(
            id="c3_s18_metric",
            text=(
                "Distance Metric 📐<br><br>"
                "This is how UMAP measures 'how different' two cells are. "
                "**Euclidean** (straight-line distance) is the sane default for "
                "general use. **Cosine** compares angle instead of magnitude — "
                "useful if absolute fluorescence intensity varies from staining "
                "artifacts rather than real biology. **Manhattan** is a "
                "grid-like distance, more robust to outliers. Euclidean is "
                "fine here — no need to change it."
            ),
            cyto_emotion="talking",
            target_widget_names=["UmapMetricCombo"],
            next_step_id="c3_s19_seed",
        ),
        InfoStep(
            id="c3_s19_seed",
            text=(
                "Random Seed 🎲<br><br>"
                "UMAP's optimization involves randomness, so the seed pins "
                "down exactly which random starting point it uses. Keep it "
                "constant (the default, 42) and the same data always produces "
                "the exact same layout — useful for reproducibility. Changing "
                "it gives you a different, equally valid embedding, which is "
                "sometimes worth doing just to sanity-check that a cluster you "
                "found is real and not a one-off artifact."
            ),
            cyto_emotion="talking",
            target_widget_names=["UmapSeedInput"],
            next_step_id="c3_s20_hdbscan",
        ),
        # ── Enable HDBSCAN ───────────────────────────────────────────────────────
        VerificationStep(
            id="c3_s20_hdbscan",
            text="Check 'Run HDBSCAN Auto-Clustering'.",
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["UmapHdbscanCheckbox"],
            validator=UmapHdbscanEnabledValidator(),
            on_success_step_id="c3_s21_hdbscan_why",
        ),
        InfoStep(
            id="c3_s21_hdbscan_why",
            text=(
                "Why bother, if UMAP already shows islands? 🔬<br><br>"
                "Because 'it looks like a cluster' isn't a measurement. "
                "**HDBSCAN** clusters the real, original 6-dimensional data — "
                "not the 2D picture UMAP draws — and groups cells by density "
                "with zero human input. It's a fully independent second "
                "opinion: if HDBSCAN's clusters line up with your manually "
                "drawn gates, that's genuine, quantitative confirmation, not "
                "just a plot that happened to look convincing."
            ),
            cyto_emotion="thinking",
            next_step_id="c3_s22_min_cluster",
        ),
        InfoStep(
            id="c3_s22_min_cluster",
            text=(
                "Minimum Cluster Size 🔢<br><br>"
                "This is the fewest cells HDBSCAN will accept as its own "
                "cluster — smaller groups get merged into a bigger neighbor "
                "or labeled noise. **100** is a solid default here: with "
                "Sample C's total event count, that's large enough to ignore "
                "stray noise, but small enough that a real minority "
                "population — like a smaller B-cell subset — won't get "
                "swallowed whole. Leave it as-is."
            ),
            cyto_emotion="talking",
            target_widget_names=["UmapMinClusterSizeBox"],
            next_step_id="c3_s23_run",
        ),
        # ── Run the analysis ─────────────────────────────────────────────────────
        InteractionStep(
            id="c3_s23_run",
            text="Everything's configured. Click '🧬 Run Analysis' (highlighted).",
            target_widget_name="RunAnalysisButton",
            target_widget_names=["RunAnalysisButton"],
            event_trigger="clicked",
            cyto_emotion="pointing",
            next_step_id="c3_s24_animation",
        ),
        # ── Animation ────────────────────────────────────────────────────────────
        InfoStep(
            id="c3_s24_animation",
            text=(
                "This animation is real 🎬<br><br>"
                "What you're watching isn't decorative — it's built from "
                "Sample C's actual high-dimensional marker data, run through "
                "the real UMAP algorithm, while the full analysis keeps "
                "computing underneath it. Watch for 5 phases: your cells "
                "appearing in high-dimensional marker space, a fuzzy "
                "neighbor graph connecting similar cells, an initial rough 2D "
                "layout, that layout settling under force-directed motion, and "
                "finally the finished manifold — the same 'islands' you're "
                "about to explore."
            ),
            cyto_emotion="happy",
            allow_interaction=True,
            manual_dismiss_bubble=True,
            next_step_id="c3_s25_wait_results",
        ),
        VerificationStep(
            id="c3_s25_wait_results",
            text="Crunching the real numbers underneath that animation...",
            cyto_emotion="scanning",
            hide_next_button=True,
            allow_interaction=True,
            validator=UmapResultsReadyValidator(),
            on_success_step_id="c3_s26_plot_gallery",
        ),
        # ── Plot Gallery walkthrough ─────────────────────────────────────────────
        InfoStep(
            id="c3_s26_plot_gallery",
            text=(
                "The Plot Gallery 🖼️<br><br>"
                "Results are in! Each tile here is the same UMAP layout, "
                "colored by one marker's expression. Find the **CD3** tile — "
                "that's your T-cell island lighting up — then find **B220**, "
                "and watch a completely different island light up instead."
            ),
            cyto_emotion="talking",
            allow_interaction=True,
            target_widget_names=["ClusterResultsTabs"],
            next_step_id="c3_s27_plot_gallery_cluster",
        ),
        InfoStep(
            id="c3_s27_plot_gallery_cluster",
            text=(
                "One more tile 🎯<br><br>"
                "If HDBSCAN found clusters, there's also an **Auto-Cluster "
                "ID** tile — every cell colored by which unsupervised cluster "
                "it landed in, with zero manual gates involved."
            ),
            cyto_emotion="happy",
            allow_interaction=True,
            target_widget_names=["ClusterResultsTabs"],
            next_step_id="c3_s28_switch_interactive",
        ),
        # ── Move to Interactive Map ──────────────────────────────────────────────
        InteractionStep(
            id="c3_s28_switch_interactive",
            text="Click the 'Interactive Map' tab (highlighted).",
            cyto_emotion="pointing",
            target_widget_name="ClusterResultsTabs",
            target_widget_names=["ClusterResultsTabs"],
            event_trigger="currentChanged",
            next_step_id="c3_s29_verify_interactive",
        ),
        VerificationStep(
            id="c3_s29_verify_interactive",
            text="Checking tab...",
            cyto_emotion="scanning",
            hide_next_button=True,
            validator=ClusterResultsTabActiveValidator("Interactive Map"),
            on_success_step_id="c3_s30_hover_explore",
            on_fail_step_id="c3_s29b_wrong_tab",
        ),
        InteractionStep(
            id="c3_s29b_wrong_tab",
            text="Oops! Click the 'Interactive Map' tab to proceed.",
            cyto_emotion="surprised",
            target_widget_name="ClusterResultsTabs",
            target_widget_names=["ClusterResultsTabs"],
            event_trigger="currentChanged",
            next_step_id="c3_s29_verify_interactive",
        ),
        # ── Encourage hover exploration ──────────────────────────────────────────
        InfoStep(
            id="c3_s30_hover_explore",
            text=(
                "Explore freely 🖱️<br><br>"
                "Move your cursor over any population on the map — a live "
                "panel will show you its local marker expression. Take a "
                "minute to hover around before continuing.<br><br>"
                "Keep in mind: this map reflects the **Leukocytes** gate and "
                "channel choices you made earlier. A different gating "
                "strategy upstream can lead to noticeably different clusters "
                "down here — this isn't the one true answer, it's *an* "
                "answer, shaped by the choices you made."
            ),
            cyto_emotion="talking",
            allow_interaction=True,
            manual_dismiss_bubble=True,
            next_step_id="c3_s31_axes_meaningless",
        ),
        # ── Axes have no meaning ─────────────────────────────────────────────────
        InfoStep(
            id="c3_s31_axes_meaningless",
            text=(
                "One more reminder ⚠️<br><br>"
                "The overall **shape** of this map, and where things sit on "
                "the x/y axes, carry no biological meaning by themselves — "
                "the axes aren't measuring anything. All that matters is "
                "which cells UMAP judged similar enough to sit close together."
            ),
            cyto_emotion="thinking",
            next_step_id="c3_s32_marker_dropdown",
        ),
        # ── Marker dropdown ──────────────────────────────────────────────────────
        InfoStep(
            id="c3_s32_marker_dropdown",
            text=(
                "Try a different lens 🔬<br><br>"
                "Use the dropdown above the map — it's currently showing "
                "**Auto-Cluster ID**. Switch it to the **FITC** marker (B220) "
                "and watch the B-cell population light up on the same map, "
                "no re-running required."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            target_widget_names=["UmapInteractiveMapCombo"],
            next_step_id="c3_s33_part1_close",
        ),
        # ── Close (soft-stop, Part 1 only) ───────────────────────────────────────
        InfoStep(
            # Deliberately NOT the true end of Course 3 yet — Part 2 (deeper
            # cluster export, stats, comparisons) is still to be written.
            # next_step_id below points BACK AT THIS SAME STEP (a self-loop),
            # the same idiom already used elsewhere in this file for
            # quiz-retry routing. AcademyManager.next_step() only calls
            # complete_course() (which marks the course finished and awards
            # badge_reward) when next_step_id is None/"__complete__" — a
            # plain terminal InfoStep's visible "Next →" button would
            # otherwise complete the course, and prematurely award the
            # "Population Analyst" badge, the instant it's clicked. The
            # self-loop means clicking Next just re-shows this same closing
            # message instead. When Part 2 is written, repoint this
            # next_step_id at the first new step and move badge_reward to
            # the true final step.
            id="c3_s33_part1_close",
            text=(
                "Nicely done! 🎉<br><br>"
                "You've validated your manual gating against a completely "
                "independent, unsupervised method — UMAP for structure, "
                "HDBSCAN for confirmation — on real data, start to finish."
                "<br><br>Course 3 will be complete soon!"
            ),
            cyto_emotion="cheering",
            cyto_animation="cheering",
            allow_interaction=True,
            manual_dismiss_bubble=True,
            next_step_id="c3_s33_part1_close",
        ),
    ],
)
