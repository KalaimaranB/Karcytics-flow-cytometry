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

Course 3 does no new gating. Part 1 validates the gating tree Course 2
built, then hands the user to unsupervised Population Analysis
(UMAP + HDBSCAN) on Sample C (the confirmed Spleen), walking every run
parameter with real justification, the live animation, the Plot Gallery,
and the Interactive Map. Part 2 continues straight on: export the real
B-cell HDBSCAN cluster as a gate-tree population, cross-check it against
the manual "B-cells" gate via a Pipeline AND node, then tour Statistics
and Comparisons using those populations as real evidence. This is still
not the true end of Course 3 — it ends on a soft "more soon" note rather
than a full graduation, so no completion/badge fires. See the closing
step's docstring-style comment for how that's guaranteed.
"""

from karcytics_sdk.plugin.tutorial_models import (
    Course,
    InfoStep,
    InteractionStep,
    VerificationStep,
)

from ..analysis.statistics import StatType
from .validators import (
    ClusterResultsTabActiveValidator,
    ComparisonPlotTypeValidator,
    Course2GatingCompleteValidator,
    ExactSampleOpenValidator,
    GateExistsValidator,
    LogicGateExistsValidator,
    LogicNodeStatsReadyValidator,
    PipelineOrientationValidator,
    PopulationsCheckedValidator,
    StatsChartTypeValidator,
    StatsCheckedValidator,
    TabActiveValidator,
    UmapBestBCellClusterValidator,
    UmapChannelExcludedValidator,
    UmapGateSelectedValidator,
    UmapHdbscanEnabledValidator,
    UmapMarkerColoredValidator,
    UmapResultsReadyValidator,
    UmapRunNameProvidedValidator,
    UmapSampleSelectedValidator,
    UmapSubsampleValueValidator,
)

# ==============================================================================
# Course 3 — Population Analysis
# No new gating. Part 1: validates Course 2's tree, walks unsupervised
# UMAP + HDBSCAN clustering on Sample C end to end. Part 2: export the real
# B-cell cluster, cross-check it against the manual gate via a Pipeline AND
# node, then tour Statistics and Comparisons using both as real evidence.
# ==============================================================================

# Held as a module-level variable for the same reason course1.py's
# _provisioning_step is: its validator calls back into
# _best_bcell_step.text = ... on every poll, so the bubble names the real,
# freshly-computed cluster ID for THIS run instead of a hardcoded guess —
# cluster ID numbering isn't stable run-to-run even though the clustering
# itself is (fixed seed/params).
_best_bcell_step: VerificationStep = VerificationStep(
    id="c3_s42_select_bcell_cluster",
    text="Scanning your run's real numbers...",
    cyto_emotion="scanning",
    hide_next_button=True,
    allow_interaction=True,
    target_widget_names=["UmapExportPopulationsPanel"],
    validator=UmapBestBCellClusterValidator(
        on_progress=lambda text: setattr(_best_bcell_step, "text", text),
        marker_label_substr="b220",
        expected_name="UMAP B Cells",
    ),
    on_success_step_id="c3_s43_create_populations",
)

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
            allow_scroll=True,
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
            allow_scroll=True,
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
            allow_scroll=True,
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
        InfoStep(
            id="c3_s13_run_name",
            text=(
                "Give this run a name — anything memorable works, e.g. "
                "'Sample C Overview'. Click **Next →** once you've typed it in."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            allow_scroll=True,
            target_widget_names=["UmapRunNameInput"],
            next_step_id="c3_s13b_verify_run_name",
        ),
        VerificationStep(
            id="c3_s13b_verify_run_name",
            text="Checking run name...",
            cyto_emotion="scanning",
            hide_next_button=True,
            validator=UmapRunNameProvidedValidator(),
            on_success_step_id="c3_s14_neighbors",
            on_fail_step_id="c3_s13_run_name",
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
            allow_interaction=True,
            allow_scroll=True,
            target_widget_names=["UmapNeighborsGroup"],
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
            allow_interaction=True,
            allow_scroll=True,
            target_widget_names=["UmapMinDistGroup"],
            next_step_id="c3_s16_subsample",
        ),
        # ── Subsample = 25% ──────────────────────────────────────────────────────
        VerificationStep(
            id="c3_s16_subsample",
            text="Set **Subsample Events** to 25%.",
            cyto_emotion="pointing",
            allow_interaction=True,
            allow_scroll=True,
            hide_next_button=True,
            target_widget_names=["UmapSubsampleGroup"],
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
            allow_interaction=True,
            allow_scroll=True,
            target_widget_names=["UmapMetricGroup"],
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
            allow_interaction=True,
            allow_scroll=True,
            target_widget_names=["UmapSeedGroup"],
            next_step_id="c3_s20_hdbscan",
        ),
        # ── Enable HDBSCAN ───────────────────────────────────────────────────────
        VerificationStep(
            id="c3_s20_hdbscan",
            text="Check 'Run HDBSCAN Auto-Clustering'.",
            cyto_emotion="pointing",
            allow_interaction=True,
            allow_scroll=True,
            hide_next_button=True,
            target_widget_names=["UmapHdbscanGroup"],
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
            allow_interaction=True,
            allow_scroll=True,
            target_widget_names=["UmapMinClusterGroup"],
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
            target_widget_name="ClusterResultsTabBar",
            target_widget_names=["ClusterResultsTabBar"],
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
            target_widget_name="ClusterResultsTabBar",
            target_widget_names=["ClusterResultsTabBar"],
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
            target_widget_names=["UmapInteractiveMapCanvas"],
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
            next_step_id="c3_s34_verify_marker",
        ),
        # ══════════════════════════════════════════════════════════════════════
        # Course 3 — Part 2 — Export the B-cell cluster, cross-check it via a
        # Pipeline AND node, then tour Statistics and Comparisons with both
        # populations as real evidence.
        # ══════════════════════════════════════════════════════════════════════
        VerificationStep(
            id="c3_s34_verify_marker",
            text="Checking the marker dropdown...",
            cyto_emotion="scanning",
            hide_next_button=True,
            validator=UmapMarkerColoredValidator("FITC"),
            on_success_step_id="c3_s35_marker_why",
        ),
        InfoStep(
            id="c3_s35_marker_why",
            text=(
                "That's not decoration 🔬<br><br>"
                "That large lit-up island is real B220 signal — the same "
                "channel you excluded from the UMAP run itself, so this is "
                "an independent confirmation, not something UMAP was ever "
                "told to look for."
            ),
            cyto_emotion="happy",
            next_step_id="c3_s36_switch_pop_stats",
        ),
        # ── Switch to Population Statistics sub-tab ──────────────────────────────
        InteractionStep(
            id="c3_s36_switch_pop_stats",
            text="Click the 'Population Statistics' tab (highlighted).",
            cyto_emotion="pointing",
            target_widget_name="ClusterResultsTabBar",
            target_widget_names=["ClusterResultsTabBar"],
            event_trigger="currentChanged",
            next_step_id="c3_s37_verify_pop_stats",
        ),
        VerificationStep(
            id="c3_s37_verify_pop_stats",
            text="Checking tab...",
            cyto_emotion="scanning",
            hide_next_button=True,
            validator=ClusterResultsTabActiveValidator("Population Statistics"),
            on_success_step_id="c3_s38_cluster_table",
            on_fail_step_id="c3_s37b_wrong_tab",
        ),
        InteractionStep(
            id="c3_s37b_wrong_tab",
            text="Oops! Click the 'Population Statistics' tab to proceed.",
            cyto_emotion="surprised",
            target_widget_name="ClusterResultsTabBar",
            target_widget_names=["ClusterResultsTabBar"],
            event_trigger="currentChanged",
            next_step_id="c3_s37_verify_pop_stats",
        ),
        # ── Explain the 3 plots ──────────────────────────────────────────────────
        InfoStep(
            id="c3_s38_cluster_table",
            text=(
                "Cluster Statistics 📋<br><br>"
                "One row per cluster HDBSCAN found — its cell count and its "
                "% of the total. This is the same count you'd get by hand-gating, "
                "just produced without you drawing a single gate."
            ),
            cyto_emotion="talking",
            allow_interaction=True,
            target_widget_names=["UmapStatsPlotsPanel"],
            next_step_id="c3_s39_heatmap_table",
        ),
        InfoStep(
            id="c3_s39_heatmap_table",
            text=(
                "Marker Expression Heatmap 🌡️<br><br>"
                "One row per cluster, one column per marker — brighter red "
                "means higher expression. This is the **median** expression "
                "per marker per cluster, not the mean, which is exactly why "
                "it's the more outlier-robust number to trust for identifying "
                "which cluster is which population."
            ),
            cyto_emotion="talking",
            allow_interaction=True,
            target_widget_names=["UmapStatsPlotsPanel"],
            next_step_id="c3_s40_expression_profiles",
        ),
        InfoStep(
            id="c3_s40_expression_profiles",
            text=(
                "Expression Profiles 📊<br><br>"
                "The same heatmap numbers, redrawn as a 100%-stacked bar per "
                "cluster — easier to compare a cluster's whole marker "
                "*profile* at a glance than reading numbers cell by cell."
            ),
            cyto_emotion="happy",
            allow_interaction=True,
            target_widget_names=["UmapStatsPlotsPanel"],
            next_step_id="c3_s41_noise_cluster",
        ),
        InfoStep(
            id="c3_s41_noise_cluster",
            text=(
                "One cluster doesn't count 🚫<br><br>"
                "**Cluster ID -1** is HDBSCAN's noise bucket — cells it "
                "couldn't confidently assign to any real, dense population. "
                "It'll show up in every table here, but it's never a "
                "candidate for anything you export downstream."
            ),
            cyto_emotion="thinking",
            next_step_id="c3_s42_select_bcell_cluster",
        ),
        # ── Dynamically identify and export the B-cell cluster ──────────────────
        _best_bcell_step,
        InteractionStep(
            id="c3_s43_create_populations",
            text="Click '➕ Create Populations' (highlighted).",
            target_widget_name="CreatePopulationsButton",
            target_widget_names=["CreatePopulationsButton"],
            event_trigger="clicked",
            cyto_emotion="pointing",
            next_step_id="c3_s44_create_populations_why",
        ),
        InfoStep(
            id="c3_s44_create_populations_why",
            text=(
                "That just built two real, permanent nodes 🌳<br><br>"
                "A **UMAP Reduction** node now sits under Leukocytes, and "
                "**UMAP B Cells** sits under that — a genuine gate-tree "
                "population, exportable, chartable, and comparable exactly "
                "like the ones you drew by hand in Course 2."
            ),
            cyto_emotion="happy",
            next_step_id="c3_s45_verify_bcell_node",
        ),
        VerificationStep(
            id="c3_s45_verify_bcell_node",
            text="Checking your new population...",
            cyto_emotion="scanning",
            hide_next_button=True,
            validator=GateExistsValidator("UMAP B Cells"),
            on_success_step_id="c3_s46_switch_pipeline",
        ),
        # ── Switch to Pipeline ────────────────────────────────────────────────────
        InteractionStep(
            id="c3_s46_switch_pipeline",
            text="Click the 'Pipeline' tab at the top.",
            cyto_emotion="pointing",
            target_widget_name="MainTabBar",
            target_widget_names=["MainTabBar"],
            event_trigger="currentChanged",
            next_step_id="c3_s47_verify_pipeline_tab",
        ),
        VerificationStep(
            id="c3_s47_verify_pipeline_tab",
            text="Checking tab...",
            cyto_emotion="scanning",
            hide_next_button=True,
            validator=TabActiveValidator(3),
            on_success_step_id="c3_s48_verify_sample_c",
            on_fail_step_id="c3_s47b_wrong_tab",
        ),
        InteractionStep(
            id="c3_s47b_wrong_tab",
            text="Oops! Click the 'Pipeline' tab to proceed.",
            cyto_emotion="surprised",
            target_widget_name="MainTabBar",
            target_widget_names=["MainTabBar"],
            event_trigger="currentChanged",
            next_step_id="c3_s47_verify_pipeline_tab",
        ),
        VerificationStep(
            id="c3_s48_verify_sample_c",
            text="Confirming Sample C is still the active pipeline...",
            cyto_emotion="scanning",
            hide_next_button=True,
            validator=ExactSampleOpenValidator("Sample C"),
            on_success_step_id="c3_s49_switch_horizontal",
            on_fail_step_id="c3_s48b_wrong_sample",
        ),
        InfoStep(
            id="c3_s48b_wrong_sample",
            text=(
                "Wrong sample 🔍<br><br>"
                "This pipeline needs to be **Sample C**'s — use the sample "
                "dropdown in the Pipeline toolbar to switch back, then I'll "
                "continue automatically."
            ),
            cyto_emotion="surprised",
            allow_interaction=True,
            next_step_id="c3_s48_verify_sample_c",
        ),
        # ── Horizontal layout ─────────────────────────────────────────────────────
        VerificationStep(
            id="c3_s49_switch_horizontal",
            text="Set the pipeline layout to **Horizontal** (highlighted).",
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["PipelineOrientationCombo"],
            validator=PipelineOrientationValidator("horizontal"),
            on_success_step_id="c3_s50_spotlight_trio_1",
        ),
        # ── Spotlight the Leukocytes / UMAP Reduction / UMAP B Cells trio ───────
        InfoStep(
            id="c3_s50_spotlight_trio_1",
            text=(
                "Here's what 'Create Populations' actually built 🔦<br><br>"
                "**Leukocytes** → **UMAP Reduction** → **UMAP B Cells** — the "
                "exact trio highlighted here. UMAP Reduction is just a "
                "container for whatever you exported; UMAP B Cells is the "
                "real population, hanging off it as a child."
            ),
            cyto_emotion="talking",
            allow_interaction=True,
            metadata={
                "pipeline_highlight_node_names": ["Leukocytes", "UMAP Reduction", "UMAP B Cells"]
            },
            next_step_id="c3_s51_spotlight_trio_2",
        ),
        InfoStep(
            id="c3_s51_spotlight_trio_2",
            text=(
                "Two very different '% of parent's ⚖️<br><br>"
                "**UMAP Reduction** shows roughly the subsample percentage "
                "you set earlier as its % of parent — that's a **random** "
                "25%, not a judged cut. Compare that to **Leukocytes**' own "
                "% of parent, back in Course 1 — a carefully drawn boundary, "
                "not a random sample. Same phrase, two completely different "
                "meanings depending on which node it's attached to."
            ),
            cyto_emotion="thinking",
            allow_interaction=True,
            metadata={
                "pipeline_highlight_node_names": ["Leukocytes", "UMAP Reduction", "UMAP B Cells"]
            },
            next_step_id="c3_s52_add_and_node",
        ),
        # ── Add the AND node ──────────────────────────────────────────────────────
        InteractionStep(
            id="c3_s52_add_and_node",
            text="Click '+ AND' (highlighted) to create a new logic node.",
            target_widget_name="AddAndGateButton",
            event_trigger="clicked",
            cyto_emotion="pointing",
            next_step_id="c3_s53_drag_and_node",
        ),
        InfoStep(
            id="c3_s53_drag_and_node",
            text=(
                "Drag it out of the way 🖐️<br><br>"
                "The new AND node has no parents yet, so it lands wherever "
                "the auto-layout puts it — possibly right on top of another "
                "node. Drag it out to the far right of the canvas, clear of "
                "everything else, before wiring it up."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            target_widget_names=["PipelineCanvas"],
            next_step_id="c3_s54_wire_and",
        ),
        VerificationStep(
            id="c3_s54_wire_and",
            text=(
                "Drag a connection from **UMAP B Cells** into the new AND "
                "node, then drag another from your manual **B-cells** node "
                "into it too."
            ),
            cyto_emotion="thinking",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["PipelineCanvas"],
            validator=LogicGateExistsValidator("AND", ["b-cells", "umap b cells"]),
            on_success_step_id="c3_s55_wait_and_stats",
        ),
        VerificationStep(
            id="c3_s55_wait_and_stats",
            text="Crunching the real overlap between both methods...",
            cyto_emotion="scanning",
            hide_next_button=True,
            validator=LogicNodeStatsReadyValidator("AND", ["b-cells", "umap b cells"]),
            on_success_step_id="c3_s56_explain_and_stats",
        ),
        InfoStep(
            id="c3_s56_explain_and_stats",
            text=(
                "Read the AND node's real numbers 🔢<br><br>"
                "Its event count should sit close to your **entire UMAP B "
                "Cells** count — nearly all of them really do fall inside "
                "the hand-gated B-cells boundary too. But as a % of your "
                "**total** B-cells, it'll only cover a modest slice.<br><br>"
                "That gap isn't disagreement between the two methods — it's "
                "simply that UMAP only ever saw a **25% subsample** of the "
                "data to begin with. Two independent methods, real numbers, "
                "a real, explainable gap."
            ),
            cyto_emotion="happy",
            next_step_id="c3_s57_switch_statistics",
        ),
        # ── Statistics tab ────────────────────────────────────────────────────────
        InteractionStep(
            id="c3_s57_switch_statistics",
            text="Click the 'Statistics' tab at the top.",
            cyto_emotion="pointing",
            target_widget_name="MainTabBar",
            target_widget_names=["MainTabBar"],
            event_trigger="currentChanged",
            next_step_id="c3_s58_verify_stats_tab",
        ),
        VerificationStep(
            id="c3_s58_verify_stats_tab",
            text="Checking tab...",
            cyto_emotion="scanning",
            hide_next_button=True,
            validator=TabActiveValidator(4),
            on_success_step_id="c3_s59_stats_theory",
            on_fail_step_id="c3_s58b_wrong_tab",
        ),
        InteractionStep(
            id="c3_s58b_wrong_tab",
            text="Oops! Click the 'Statistics' tab to proceed.",
            cyto_emotion="surprised",
            target_widget_name="MainTabBar",
            target_widget_names=["MainTabBar"],
            event_trigger="currentChanged",
            next_step_id="c3_s58_verify_stats_tab",
        ),
        InfoStep(
            id="c3_s59_stats_theory",
            text=(
                "Choosing the right statistic 📊<br><br>"
                "• % Parent — fraction of the immediate parent gate.<br>"
                "• % Total — fraction of ALL events in the tube. The number "
                "to use when comparing a population's true abundance.<br>"
                "• Median / MFI — the standard, outlier-robust measure of "
                "fluorescence intensity. Avoid the arithmetic Mean on "
                "log-scaled fluorescence data.<br>"
                "• CV (Coefficient of Variation) — how tight or spread-out "
                "a peak is. High CV = broad, messy population."
            ),
            cyto_emotion="talking",
            next_step_id="c3_s60_select_pops",
        ),
        VerificationStep(
            id="c3_s60_select_pops",
            text=(
                "In the sidebar, check at least your manual **B-cells** "
                "population and your new **UMAP B Cells** population — feel "
                "free to add others too (like the AND node's population)."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            validator=PopulationsCheckedValidator(
                "_statistics_explorer", "b-cells", "umap b cells"
            ),
            on_success_step_id="c3_s61_select_stats",
        ),
        VerificationStep(
            id="c3_s61_select_stats",
            text="Check at least **% Total** and **CV** in the stat picker.",
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            validator=StatsCheckedValidator(StatType.PERCENT_TOTAL, StatType.CV),
            on_success_step_id="c3_s62_read_table",
        ),
        InfoStep(
            id="c3_s62_read_table",
            text=(
                "Read the table 🔍<br><br>"
                "% Total tells you how the two B-cell populations' real "
                "abundance compares; CV tells you which one is the tighter, "
                "cleaner peak. Two independent methods, both showing up as "
                "real numbers side by side."
            ),
            cyto_emotion="thinking",
            next_step_id="c3_s63_chart_toggle",
        ),
        InteractionStep(
            id="c3_s63_chart_toggle",
            text="Click '📈 Chart' (highlighted) to switch from table to chart view.",
            target_widget_name="StatsChartMode",
            event_trigger="clicked",
            cyto_emotion="pointing",
            next_step_id="c3_s64_grouped_bar",
        ),
        VerificationStep(
            id="c3_s64_grouped_bar",
            text="From the chart-type dropdown, select 'Grouped Bar'.",
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["StatsChartTypeCombo"],
            validator=StatsChartTypeValidator("grouped bar"),
            on_success_step_id="c3_s65_grouped_bar_read",
        ),
        InfoStep(
            id="c3_s65_grouped_bar_read",
            text=(
                "Good for a handful of populations side by side — "
                "bars are easy to compare at a glance, up until the labels "
                "start getting crowded."
            ),
            cyto_emotion="happy",
            next_step_id="c3_s66_horizontal_bar",
        ),
        VerificationStep(
            id="c3_s66_horizontal_bar",
            text="Now switch to 'Horizontal Bar'.",
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["StatsChartTypeCombo"],
            validator=StatsChartTypeValidator("horizontal bar"),
            on_success_step_id="c3_s67_horizontal_bar_read",
        ),
        InfoStep(
            id="c3_s67_horizontal_bar_read",
            text=(
                "Same chart, rotated 🔄<br><br>"
                "Long population names (like 'UMAP B Cells') read much more "
                "easily here than rotated along a vertical axis — reach for "
                "this whenever your labels are the crowded part."
            ),
            cyto_emotion="talking",
            next_step_id="c3_s68_heatmap",
        ),
        VerificationStep(
            id="c3_s68_heatmap",
            text="Now switch to 'Heatmap'.",
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["StatsChartTypeCombo"],
            validator=StatsChartTypeValidator("heatmap"),
            on_success_step_id="c3_s69_heatmap_read",
        ),
        InfoStep(
            id="c3_s69_heatmap_read",
            text=(
                "One-glance comparison 🗺️<br><br>"
                "Every population × every stat you picked, all at once — "
                "the fastest way to scan for anything unexpected across a "
                "wide comparison."
            ),
            cyto_emotion="happy",
            next_step_id="c3_s70_switch_comparisons",
        ),
        # ── Comparisons tab ───────────────────────────────────────────────────────
        InteractionStep(
            id="c3_s70_switch_comparisons",
            text="Click the 'Comparisons' tab at the top.",
            cyto_emotion="pointing",
            target_widget_name="MainTabBar",
            target_widget_names=["MainTabBar"],
            event_trigger="currentChanged",
            next_step_id="c3_s71_verify_comparisons_tab",
        ),
        VerificationStep(
            id="c3_s71_verify_comparisons_tab",
            text="Checking tab...",
            cyto_emotion="scanning",
            hide_next_button=True,
            validator=TabActiveValidator(7),
            on_success_step_id="c3_s72_comparisons_intro",
            on_fail_step_id="c3_s71b_wrong_tab",
        ),
        InteractionStep(
            id="c3_s71b_wrong_tab",
            text="Oops! Click the 'Comparisons' tab to proceed.",
            cyto_emotion="surprised",
            target_widget_name="MainTabBar",
            target_widget_names=["MainTabBar"],
            event_trigger="currentChanged",
            next_step_id="c3_s71_verify_comparisons_tab",
        ),
        InfoStep(
            id="c3_s72_comparisons_intro",
            text=(
                "5 ways to compare 🎨<br><br>"
                "This tab has 5 dedicated chart types — let's walk all of "
                "them, using your manual **B-cells** and new **UMAP B "
                "Cells** populations as the running example."
            ),
            cyto_emotion="talking",
            target_widget_names=["ComparisonsPlotTypeCombo"],
            next_step_id="c3_s73_violin",
        ),
        VerificationStep(
            id="c3_s73_violin",
            text="Select '🎻 Violin Plot'.",
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["ComparisonsPlotTypeCombo"],
            validator=ComparisonPlotTypeValidator("violin"),
            on_success_step_id="c3_s74_violin_info",
        ),
        InfoStep(
            id="c3_s74_violin_info",
            text=(
                "Wide violin = many cells at that intensity. Your two "
                "B-cell populations should look like close, largely "
                "overlapping shapes."
            ),
            cyto_emotion="happy",
            next_step_id="c3_s75_channel_heatmap",
        ),
        VerificationStep(
            id="c3_s75_channel_heatmap",
            text="Select '🗺️ Channel Heatmap'.",
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["ComparisonsPlotTypeCombo"],
            validator=ComparisonPlotTypeValidator("channel heatmap"),
            on_success_step_id="c3_s76_channel_heatmap_info",
        ),
        InfoStep(
            id="c3_s76_channel_heatmap_info",
            text=(
                "Both B-cell rows should light up for B220 the same way — "
                "one glance, same conclusion as the AND node's numbers."
            ),
            cyto_emotion="talking",
            next_step_id="c3_s77_radar",
        ),
        VerificationStep(
            id="c3_s77_radar",
            text="Select '🕷️ Radar Chart'.",
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["ComparisonsPlotTypeCombo"],
            validator=ComparisonPlotTypeValidator("radar"),
            on_success_step_id="c3_s78_radar_info",
        ),
        InfoStep(
            id="c3_s78_radar_info",
            text=(
                "Two nearly-identical polygons here is exactly the visual "
                "version of 'these two methods agree.'"
            ),
            cyto_emotion="happy",
            next_step_id="c3_s79_histogram",
        ),
        VerificationStep(
            id="c3_s79_histogram",
            text="Select '📊 Histogram Overlay'.",
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["ComparisonsPlotTypeCombo"],
            validator=ComparisonPlotTypeValidator("histogram overlay"),
            on_success_step_id="c3_s80_histogram_info",
        ),
        InfoStep(
            id="c3_s80_histogram_info",
            text=(
                "Two closely-stacked peaks on B220 — the same story again, from yet another angle."
            ),
            cyto_emotion="thinking",
            next_step_id="c3_s81_pseudocolor",
        ),
        VerificationStep(
            id="c3_s81_pseudocolor",
            text="Select '🌈 Pseudocolor Overlay' — new since you last saw this tab.",
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["ComparisonsPlotTypeCombo"],
            validator=ComparisonPlotTypeValidator("pseudocolor overlay"),
            on_success_step_id="c3_s82_pseudocolor_info",
        ),
        InfoStep(
            id="c3_s82_pseudocolor_info",
            text=(
                "A different kind of comparison 🌈<br><br>"
                "This one skips channel expression entirely — it overlays "
                "population *shapes* on one sample, side by side. Good for "
                "sanity-checking that your manual and UMAP-derived B-cells "
                "actually occupy the same region on a real 2D plot, not "
                "just matching numbers."
            ),
            cyto_emotion="happy",
            next_step_id="c3_s83_part2_close",
        ),
        # ── Close (soft-stop, Part 2) ─────────────────────────────────────────────
        InfoStep(
            # Still not the true end of Course 3 — same self-loop idiom as
            # Part 1's own soft-stop (see AcademyManager.next_step(): a
            # next_step_id of None/"__complete__" is what triggers
            # complete_course() and awards badge_reward, so a plain
            # terminal InfoStep's visible "Next →" button would otherwise
            # complete the course and prematurely award "Population
            # Analyst" the instant it's clicked). Deliberately does NOT set
            # manual_dismiss_bubble — that hides Cyto AND the bubble with no
            # way to bring them back for a step type with no other
            # advance mechanism, which is exactly the dead end Part 1's own
            # testing caught. When the next part is written, repoint this
            # next_step_id at the first new step and move badge_reward to
            # the true final step.
            id="c3_s83_part2_close",
            text=(
                "Nicely done! 🎉<br><br>"
                "You've exported a real population from unsupervised "
                "clustering, cross-checked it against your own hand-gating "
                "with a Pipeline AND node, and read the agreement out in "
                "both the Statistics and Comparisons tabs."
                "<br><br>Course 3 will be complete soon!"
            ),
            cyto_emotion="cheering",
            cyto_animation="cheering",
            allow_interaction=True,
            next_step_id="c3_s83_part2_close",
        ),
    ],
)
