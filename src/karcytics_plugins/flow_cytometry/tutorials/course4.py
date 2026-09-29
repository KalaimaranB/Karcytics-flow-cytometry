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

Course 4 picks up where Course 3 left off: Course 3 ends with a real,
gate-tree population ("UMAP B Cells") exported from unsupervised
clustering and cross-checked against the hand-gated "B-cells" population
via a Pipeline AND node. Course 4 uses both of those as running evidence
through the **Statistics** tab (table + all three chart types) and the
**Comparisons** tab (all five chart types).

This is currently placeholder-sized content only — it ends on a soft
"more soon" note rather than a full graduation, so no completion/badge
fires yet. See the closing step's own comment for how that's guaranteed.
Expect this course to grow before it gets its own real ending.
"""

from karcytics_sdk.plugin.tutorial_models import (
    Course,
    InfoStep,
    InteractionStep,
    VerificationStep,
)

from ..analysis.statistics import StatType
from .validators import (
    ComparisonPlotTypeValidator,
    ComparisonsPlotGeneratedValidator,
    Course3AnalysisCompleteValidator,
    HistogramOverlayLayoutValidator,
    PopulationsCheckedValidator,
    StatsChartTypeValidator,
    StatsCheckedValidator,
    StatsResultsReadyValidator,
    TabActiveValidator,
    WorkflowSavedValidator,
)

course_4_reporting = Course(
    id="flow_course_4_reporting",
    title="Statistics & Comparisons",
    description=(
        "Use your Course 3 populations — the hand-gated B-cells and the "
        "UMAP-exported UMAP B Cells — as real evidence through the "
        "Statistics table/charts and every Comparisons chart type."
    ),
    estimated_minutes=30,
    badge_reward="Insight Reporter",
    badge_icon="📊",
    prerequisite_course_ids=["flow_course_3_analysis"],
    steps=[
        InfoStep(
            id="c4_s00_intro",
            text=(
                "Welcome to Course 4! 📊<br><br>"
                "Course 3 left you with two independent ways of finding "
                "B-cells — your own hand-gated **B-cells**, and the "
                "unsupervised **UMAP B Cells** — plus an AND node proving "
                "they largely agree. This course puts both to work: real "
                "numbers in the Statistics tab, real charts in Comparisons."
            ),
            cyto_emotion="happy",
            next_step_id="c4_s00b_objectives",
        ),
        InfoStep(
            id="c4_s00b_objectives",
            text=(
                "What you'll walk away with 🎯<br><br>"
                "By the end of this course, you'll be able to:<br>"
                "• Pick a lean, readable set of populations and statistics "
                "instead of a cramped table showing everything at once<br>"
                "• Read % Total, CV, and an estimate-scaled UMAP count "
                "correctly, and know which number to trust for a fair "
                "comparison<br>"
                "• Choose the right Statistics chart (Grouped Bar, "
                "Horizontal Bar, Heatmap) for a given number of "
                "populations and label lengths<br>"
                "• Choose the right Comparisons chart (Violin, Channel "
                "Heatmap, Radar, Histogram Overlay, Pseudocolor Overlay) "
                "for a given question about two populations"
            ),
            cyto_emotion="talking",
            next_step_id="c4_s01_validate_analysis",
        ),
        # ── Validate Course 3's analysis output ─────────────────────────────────
        VerificationStep(
            id="c4_s01_validate_analysis",
            text="Checking for your Course 3 analysis...",
            cyto_emotion="scanning",
            hide_next_button=True,
            validator=Course3AnalysisCompleteValidator(),
            on_success_step_id="c4_s02_switch_statistics",
            on_fail_step_id="c4_s01b_incomplete_analysis",
        ),
        InfoStep(
            # This step has allow_interaction unset (defaults False), so the
            # whole app stays blocked behind it — there's no way to actually
            # go finish Course 3 without leaving first. Looping back to the
            # validator (an earlier fix) just replayed this same dead end
            # forever. next_step_id="__abandon__" exits the tutorial cleanly
            # instead — no badge, no completion (see
            # AcademyManager.abandon_course()) — rather than either that
            # dead loop or falling into the "no next_id" branch, which would
            # have completed the course and awarded "Insight Reporter" for
            # reading one message.
            id="c4_s01b_incomplete_analysis",
            text=(
                "Missing your Course 3 export 🔍<br><br>"
                "Course 4 needs the **UMAP B Cells** population and the "
                "**AND** node cross-checking it against **B-cells** — both "
                "built in Course 3. Head back and finish that course first, "
                "then relaunch Course 4."
            ),
            cyto_emotion="thinking",
            next_step_id="__abandon__",
        ),
        # ── Statistics tab ────────────────────────────────────────────────────────
        InteractionStep(
            id="c4_s02_switch_statistics",
            text="Click the 'Statistics' tab at the top.",
            cyto_emotion="pointing",
            target_widget_name="MainTabBar",
            target_widget_names=["MainTabBar"],
            event_trigger="currentChanged",
            next_step_id="c4_s03_verify_stats_tab",
        ),
        VerificationStep(
            id="c4_s03_verify_stats_tab",
            text="Checking tab...",
            cyto_emotion="scanning",
            hide_next_button=True,
            validator=TabActiveValidator(4),
            on_success_step_id="c4_s04_stats_theory",
            on_fail_step_id="c4_s03b_wrong_tab",
        ),
        InteractionStep(
            id="c4_s03b_wrong_tab",
            text="Oops! Click the 'Statistics' tab to proceed.",
            cyto_emotion="surprised",
            target_widget_name="MainTabBar",
            target_widget_names=["MainTabBar"],
            event_trigger="currentChanged",
            next_step_id="c4_s03_verify_stats_tab",
        ),
        InfoStep(
            id="c4_s04_stats_theory",
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
            next_step_id="c4_s05_select_pops",
        ),
        VerificationStep(
            id="c4_s05_select_pops",
            text=(
                "Trim the population list 🎯<br><br>"
                "Click **Edit Population Selection** (highlighted) to open the "
                "picker — a grid of populations × samples you can drag to move "
                "and resize from its corner for more room. Every population "
                "starts checked by default — click **None** first, then check "
                "4 cells total:<br><br>"
                "• **B-cells** — one click on its row label checks your "
                "manual gate for Sample A, B, and C all at once (it "
                "propagated everywhere back in Course 2).<br>"
                "• **UMAP B Cells** — only exists on **Sample C**, where you "
                "built it; check just that one cell.<br><br>"
                "Heads up: UMAP only ever clustered a **25% subsample** of "
                "Sample C — once you compute, the table marks UMAP B Cells' "
                "Count and % Total with a trailing star because the app "
                "scales those back up to a fair estimate, rather than "
                "leaving them artificially low.<br><br>"
                "Once your 4 cells are checked, close the popup (✕, Esc, or "
                "click outside it) to continue."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["StatsPopulationPickerButton"],
            validator=PopulationsCheckedValidator(
                "_statistics_explorer",
                "b-cells",
                "umap b cells",
                max_checked=4,
                require_popup_closed=True,
            ),
            on_success_step_id="c4_s06_select_stats",
        ),
        VerificationStep(
            id="c4_s06_select_stats",
            text=(
                "Trim the stat list too ✂️<br><br>"
                "**Count**, **% Parent** and **MFI** are checked by default — "
                "uncheck those and check just **% Total** and **CV** instead. "
                "Same reasoning as the populations: only the few stats you "
                "actually want, or the chart gets cramped.<br><br>"
                "That **★** next to CV (and MFI) means it needs a fluorescence "
                "channel picked below before it can compute — a plain count "
                "like % Total doesn't need one, since it isn't measuring a "
                "specific marker's brightness."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["StatsCheckboxPanel"],
            validator=StatsCheckedValidator(StatType.PERCENT_TOTAL, StatType.CV, max_checked=2),
            on_success_step_id="c4_s06b_compute",
        ),
        InteractionStep(
            id="c4_s06b_compute",
            text="Click '📊 Compute Statistics' (highlighted) to actually generate the table.",
            target_widget_name="StatsComputeButton",
            event_trigger="clicked",
            cyto_emotion="pointing",
            allow_interaction=True,
            allow_scroll=True,
            next_step_id="c4_s06c_wait_compute",
        ),
        VerificationStep(
            id="c4_s06c_wait_compute",
            text="Computing your selected statistics...",
            cyto_emotion="scanning",
            hide_next_button=True,
            validator=StatsResultsReadyValidator(),
            on_success_step_id="c4_s07_read_table",
        ),
        InfoStep(
            id="c4_s07_read_table",
            text=(
                "Read the table 🔍<br><br>"
                "First, **B-cells' % Total** across Sample A, B, and C — "
                "near-zero in A, solid in B, solid in C, the same "
                "Thymus/Bone Marrow/Spleen story Course 2's mystery walked "
                "you through.<br><br>"
                "Then, on Sample C only: manual **B-cells** vs **UMAP B "
                "Cells**. UMAP B Cells' Count and % Total carry a trailing "
                "star marker — hover either cell for the exact subsample "
                "size. That marker means the raw number already got scaled "
                "back up from UMAP's subsample to estimate the full "
                "population, so it's the fair number to compare against "
                "manual B-cells, not a smaller, unscaled one. CV tells you "
                "which of the two is the tighter, cleaner peak."
            ),
            cyto_emotion="thinking",
            allow_interaction=True,
            target_widget_names=["StatsResultsTable"],
            next_step_id="c4_s08_chart_toggle",
        ),
        InteractionStep(
            id="c4_s08_chart_toggle",
            text="Click '📈 Chart' (highlighted) to switch from table to chart view.",
            target_widget_name="StatsChartMode",
            event_trigger="clicked",
            cyto_emotion="pointing",
            next_step_id="c4_s09_grouped_bar",
        ),
        VerificationStep(
            id="c4_s09_grouped_bar",
            text="From the chart-type dropdown, select 'Grouped Bar'.",
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["StatsChartTypeCombo"],
            validator=StatsChartTypeValidator("grouped bar"),
            on_success_step_id="c4_s10_grouped_bar_read",
        ),
        InfoStep(
            id="c4_s10_grouped_bar_read",
            text=(
                "Good for a handful of populations side by side — "
                "bars are easy to compare at a glance, up until the labels "
                "start getting crowded."
            ),
            cyto_emotion="happy",
            next_step_id="c4_s11_horizontal_bar",
        ),
        VerificationStep(
            id="c4_s11_horizontal_bar",
            text="Now switch to 'Horizontal Bar'.",
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["StatsChartTypeCombo"],
            validator=StatsChartTypeValidator("horizontal bar"),
            on_success_step_id="c4_s12_horizontal_bar_read",
        ),
        InfoStep(
            id="c4_s12_horizontal_bar_read",
            text=(
                "Same chart, rotated 🔄<br><br>"
                "Long population names (like 'UMAP B Cells') read much more "
                "easily here than rotated along a vertical axis — reach for "
                "this whenever your labels are the crowded part."
            ),
            cyto_emotion="talking",
            allow_interaction=True,
            target_widget_names=["StatsChartCanvas"],
            next_step_id="c4_s13_heatmap",
        ),
        VerificationStep(
            id="c4_s13_heatmap",
            text="Now switch to 'Heatmap'.",
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["StatsChartTypeCombo"],
            validator=StatsChartTypeValidator("heatmap"),
            on_success_step_id="c4_s14_heatmap_read",
        ),
        InfoStep(
            id="c4_s14_heatmap_read",
            text=(
                "One-glance comparison 🗺️<br><br>"
                "Every population × every stat you picked, all at once — "
                "B-cells spanning Sample A, B, and C right next to UMAP B "
                "Cells' single Sample C column, this is the fastest way to "
                "scan a wide comparison for anything unexpected."
            ),
            cyto_emotion="happy",
            allow_interaction=True,
            target_widget_names=["StatsChartCanvas"],
            next_step_id="c4_s14b_stats_recap",
        ),
        InfoStep(
            id="c4_s14b_stats_recap",
            text=(
                "What that whole chunk was for 📋<br><br>"
                "Trimming populations and stats, computing, then reading "
                "the same numbers as a table and three different charts — "
                "that was all one question: does manual **B-cells** agree "
                "with unsupervised **UMAP B Cells**? Every view said yes.<br><br>"
                "Comparisons is a different tool for the same question — "
                "instead of numbers in a table, it plots the underlying "
                "*distributions* and *shapes* side by side, five different "
                "ways. Same two populations, a more visual kind of proof."
            ),
            cyto_emotion="talking",
            next_step_id="c4_s15_switch_comparisons",
        ),
        # ── Comparisons tab ───────────────────────────────────────────────────────
        InteractionStep(
            id="c4_s15_switch_comparisons",
            text="Click the 'Comparisons' tab at the top.",
            cyto_emotion="pointing",
            target_widget_name="MainTabBar",
            target_widget_names=["MainTabBar"],
            event_trigger="currentChanged",
            next_step_id="c4_s16_verify_comparisons_tab",
        ),
        VerificationStep(
            id="c4_s16_verify_comparisons_tab",
            text="Checking tab...",
            cyto_emotion="scanning",
            hide_next_button=True,
            validator=TabActiveValidator(7),
            on_success_step_id="c4_s17_comparisons_intro",
            on_fail_step_id="c4_s16b_wrong_tab",
        ),
        InteractionStep(
            id="c4_s16b_wrong_tab",
            text="Oops! Click the 'Comparisons' tab to proceed.",
            cyto_emotion="surprised",
            target_widget_name="MainTabBar",
            target_widget_names=["MainTabBar"],
            event_trigger="currentChanged",
            next_step_id="c4_s16_verify_comparisons_tab",
        ),
        InfoStep(
            id="c4_s17_comparisons_intro",
            text=(
                "5 ways to compare 🎨<br><br>"
                "This tab has 5 dedicated chart types — let's walk all of "
                "them, using your manual **B-cells** and new **UMAP B "
                "Cells** populations as the running example."
            ),
            cyto_emotion="talking",
            next_step_id="c4_s17b_select_pops",
        ),
        VerificationStep(
            id="c4_s17b_select_pops",
            text=(
                "Pick your population here too 🎯<br><br>"
                "This tab has its own population picker, separate from the "
                "one on the Statistics tab. Click **Edit Population "
                "Selection** (highlighted) and check **B-cells** — one "
                "click on its row label checks Sample A, B, and C all at "
                "once.<br><br>"
                "Violin (the first chart type below) only allows one "
                "population per sample, so this is the one to use for it. "
                "A later step brings **UMAP B Cells** into the mix once "
                "you reach a chart type that can show more than one "
                "population per sample. Close the popup (✕, Esc, or click "
                "outside it) once you're done."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["ComparisonsPopulationPickerButton"],
            validator=PopulationsCheckedValidator(
                "_comparisons_viewer",
                "b-cells",
                max_checked=3,
                require_popup_closed=True,
            ),
            on_success_step_id="c4_s18_violin",
        ),
        VerificationStep(
            id="c4_s18_violin",
            text="Select '🎻 Violin Plot'.",
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["ComparisonsPlotTypeCombo"],
            validator=ComparisonPlotTypeValidator("violin"),
            on_success_step_id="c4_s18a_violin_options",
        ),
        InfoStep(
            id="c4_s18a_violin_options",
            text=(
                "Before you generate: what these settings do 🎛️<br><br>"
                "• **Orientation** — vertical or horizontal violins.<br>"
                "• **Axis Range** — clips the axis to a percentile so a few "
                "bright outliers don't squash the rest of the distribution "
                "into a sliver near zero. Leave at 100 for the full range.<br>"
                "• **Show box plot overlay** — draws median/IQR whiskers "
                "inside each violin.<br>"
                "• **Show individual data points** — overlays up to 500 raw "
                "events per sample as dots."
            ),
            cyto_emotion="talking",
            allow_interaction=True,
            target_widget_names=["ComparisonsOptionsPanel"],
            next_step_id="c4_s18b_violin_generate",
        ),
        InteractionStep(
            id="c4_s18b_violin_generate",
            text="Click '🔬 Generate Plot' (highlighted) to render it with the settings from the last step.",
            target_widget_name="ComparisonsGenerateButton",
            event_trigger="clicked",
            cyto_emotion="pointing",
            allow_interaction=True,
            allow_scroll=True,
            next_step_id="c4_s18c_violin_wait",
        ),
        VerificationStep(
            id="c4_s18c_violin_wait",
            text="Rendering the violin plot...",
            cyto_emotion="scanning",
            hide_next_button=True,
            validator=ComparisonsPlotGeneratedValidator("violin"),
            on_success_step_id="c4_s19_violin_info",
        ),
        InfoStep(
            id="c4_s19_violin_info",
            text=(
                "Wide violin = many cells at that intensity. Three organs, "
                "one population — the same Thymus/Bone Marrow/Spleen "
                "B-cell story as the table, now as shape instead of a "
                "percentage."
            ),
            cyto_emotion="happy",
            allow_interaction=True,
            target_widget_names=["ComparisonsPlotDisplay"],
            next_step_id="c4_s20_channel_heatmap",
        ),
        VerificationStep(
            id="c4_s20_channel_heatmap",
            text="Select '🗺️ Channel Heatmap'.",
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["ComparisonsPlotTypeCombo"],
            validator=ComparisonPlotTypeValidator("channel heatmap"),
            on_success_step_id="c4_s20a_add_umap_pop",
        ),
        VerificationStep(
            id="c4_s20a_add_umap_pop",
            text=(
                "Bring in UMAP B Cells 🎯<br><br>"
                "Heatmap (and every chart type from here on) can show more "
                "than one population per sample, unlike Violin. Open "
                "**Edit Population Selection** (highlighted) again and "
                "also check **UMAP B Cells** for Sample C — leave your "
                "existing B-cells checks alone, just add this one. Now you "
                "have both methods side by side: the real comparison this "
                "whole course has been building to.<br><br>"
                "Close the popup once you're done."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["ComparisonsPopulationPickerButton"],
            validator=PopulationsCheckedValidator(
                "_comparisons_viewer",
                "b-cells",
                "umap b cells",
                max_checked=4,
                require_popup_closed=True,
            ),
            on_success_step_id="c4_s20a1_heatmap_channels",
        ),
        InfoStep(
            id="c4_s20a1_heatmap_channels",
            text=(
                "About that Channels list 📡<br><br>"
                "Violin only ever used one channel, so switching here reset "
                "the checklist back to **everything checked** — channel "
                "checks only carry over between chart types that share the "
                "same single-vs-multi channel mode, never across a mode "
                "change. Leave everything checked, or trim to just the "
                "channels you care about (e.g. B220) for a cleaner grid."
            ),
            cyto_emotion="talking",
            allow_interaction=True,
            target_widget_names=["ComparisonsChannelSection"],
            next_step_id="c4_s20b_channel_heatmap_generate",
        ),
        InteractionStep(
            id="c4_s20b_channel_heatmap_generate",
            text="Click '🔬 Generate Plot' (highlighted) to render it.",
            target_widget_name="ComparisonsGenerateButton",
            event_trigger="clicked",
            cyto_emotion="pointing",
            allow_interaction=True,
            allow_scroll=True,
            next_step_id="c4_s20c_channel_heatmap_wait",
        ),
        VerificationStep(
            id="c4_s20c_channel_heatmap_wait",
            text="Rendering the channel heatmap...",
            cyto_emotion="scanning",
            hide_next_button=True,
            validator=ComparisonsPlotGeneratedValidator("channel heatmap"),
            on_success_step_id="c4_s21_channel_heatmap_info",
        ),
        InfoStep(
            id="c4_s21_channel_heatmap_info",
            text=(
                "Both B-cell rows should light up for B220 the same way — "
                "one glance, same conclusion as the AND node's numbers."
            ),
            cyto_emotion="talking",
            allow_interaction=True,
            target_widget_names=["ComparisonsPlotDisplay"],
            next_step_id="c4_s22_radar",
        ),
        VerificationStep(
            id="c4_s22_radar",
            text="Select '🕷️ Radar Chart'.",
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["ComparisonsPlotTypeCombo"],
            validator=ComparisonPlotTypeValidator("radar"),
            on_success_step_id="c4_s22a_radar_channels",
        ),
        InfoStep(
            id="c4_s22a_radar_channels",
            text=(
                "This time the Channels list didn't reset 🔄<br><br>"
                "Channel Heatmap and Radar are both multi-channel — since "
                "the mode didn't change, whatever you left checked on the "
                "heatmap carried straight over. That's the flip side of "
                "the reset you just saw: it only happens when the mode "
                "itself changes, single ↔ multi, not on every chart-type "
                "switch."
            ),
            cyto_emotion="talking",
            allow_interaction=True,
            target_widget_names=["ComparisonsChannelSection"],
            next_step_id="c4_s22b_radar_generate",
        ),
        InteractionStep(
            id="c4_s22b_radar_generate",
            text="Click '🔬 Generate Plot' (highlighted) to render it.",
            target_widget_name="ComparisonsGenerateButton",
            event_trigger="clicked",
            cyto_emotion="pointing",
            allow_interaction=True,
            allow_scroll=True,
            next_step_id="c4_s22c_radar_wait",
        ),
        VerificationStep(
            id="c4_s22c_radar_wait",
            text="Rendering the radar chart...",
            cyto_emotion="scanning",
            hide_next_button=True,
            validator=ComparisonsPlotGeneratedValidator("radar"),
            on_success_step_id="c4_s23_radar_info",
        ),
        InfoStep(
            id="c4_s23_radar_info",
            text=(
                "Reading a radar chart 🕷️<br><br>"
                "Each spoke is one channel; each coloured polygon is one "
                "population. A point pulled out toward the edge means "
                "**high** on that channel, relative to the highest value "
                "seen among the populations plotted here — spokes are "
                "scaled per-channel, not on one shared axis, so compare "
                "shapes between populations, not one spoke's raw distance "
                "against another spoke's.<br><br>"
                "Two nearly-identical polygons here is exactly the visual "
                "version of 'these two methods agree.'"
            ),
            cyto_emotion="happy",
            allow_interaction=True,
            target_widget_names=["ComparisonsPlotDisplay"],
            next_step_id="c4_s24_histogram",
        ),
        VerificationStep(
            id="c4_s24_histogram",
            text="Select '📊 Histogram Overlay'.",
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["ComparisonsPlotTypeCombo"],
            validator=ComparisonPlotTypeValidator("histogram overlay"),
            on_success_step_id="c4_s24a_histogram_settings",
        ),
        InfoStep(
            id="c4_s24a_histogram_settings",
            text=(
                "What these settings do 🎛️<br><br>"
                "• **Layout** — Ridge (the default, also called 'waterfall') "
                "stacks each population in its own row; Overlay draws them "
                "all on one shared axis instead.<br>"
                "• **Smooth curve (KDE)** — a smooth density estimate "
                "instead of raw histogram bars.<br>"
                "• **Normalise to peak** — scales each curve so its own "
                "peak hits 1.0, so a small population stays visible next "
                "to a big one. Turn off to compare absolute event counts.<br>"
                "• **X-axis scale** — Linear, Log₁₀, or Biexponential.<br><br>"
                "And the Channels list reset again — Radar was "
                "multi-channel, Histogram is back to single-channel mode, "
                "so pick just B220."
            ),
            cyto_emotion="talking",
            allow_interaction=True,
            target_widget_names=["ComparisonsOptionsPanel", "ComparisonsChannelSection"],
            next_step_id="c4_s24a2_histogram_layout",
        ),
        VerificationStep(
            id="c4_s24a2_histogram_layout",
            text=(
                "Try switching off Ridge (waterfall) mode 🔀<br><br>"
                "From the **Layout** dropdown (highlighted), pick "
                "**'Overlay (all on one axis)'** instead of the default "
                "Ridge."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["ComparisonsOptionsPanel"],
            validator=HistogramOverlayLayoutValidator("overlay"),
            on_success_step_id="c4_s24b_histogram_generate",
        ),
        InteractionStep(
            id="c4_s24b_histogram_generate",
            text="Click '🔬 Generate Plot' (highlighted) to render it with Overlay mode.",
            target_widget_name="ComparisonsGenerateButton",
            event_trigger="clicked",
            cyto_emotion="pointing",
            allow_interaction=True,
            allow_scroll=True,
            next_step_id="c4_s24c_histogram_wait",
        ),
        VerificationStep(
            id="c4_s24c_histogram_wait",
            text="Rendering the histogram overlay...",
            cyto_emotion="scanning",
            hide_next_button=True,
            validator=ComparisonsPlotGeneratedValidator("histogram overlay"),
            on_success_step_id="c4_s25_histogram_info",
        ),
        InfoStep(
            id="c4_s25_histogram_info",
            text=(
                "Two closely-stacked peaks on B220 — the same story again, from yet another angle."
            ),
            cyto_emotion="thinking",
            allow_interaction=True,
            target_widget_names=["ComparisonsPlotDisplay"],
            next_step_id="c4_s26_pseudocolor",
        ),
        VerificationStep(
            id="c4_s26_pseudocolor",
            text="Select '🌈 Pseudocolor Overlay' — new since you last saw this tab.",
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["ComparisonsPlotTypeCombo"],
            validator=ComparisonPlotTypeValidator("pseudocolor overlay"),
            on_success_step_id="c4_s26b_pseudocolor_generate",
        ),
        InteractionStep(
            id="c4_s26b_pseudocolor_generate",
            text="Click '🔬 Generate Plot' (highlighted) to render it.",
            target_widget_name="ComparisonsGenerateButton",
            event_trigger="clicked",
            cyto_emotion="pointing",
            allow_interaction=True,
            allow_scroll=True,
            next_step_id="c4_s26c_pseudocolor_wait",
        ),
        VerificationStep(
            id="c4_s26c_pseudocolor_wait",
            text="Rendering the pseudocolor overlay...",
            cyto_emotion="scanning",
            hide_next_button=True,
            validator=ComparisonsPlotGeneratedValidator("pseudocolor overlay"),
            on_success_step_id="c4_s27_pseudocolor_info",
        ),
        InfoStep(
            id="c4_s27_pseudocolor_info",
            text=(
                "A different kind of comparison 🌈<br><br>"
                "This one skips channel expression entirely — no shared "
                "Channels list at all this time, because it isn't "
                "comparing a marker's intensity. It overlays population "
                "*shapes* on one sample, side by side, using its own X/Y "
                "Axis Channel pickers in **Plot Options** instead. Good "
                "for sanity-checking that your manual and UMAP-derived "
                "B-cells actually occupy the same region on a real 2D "
                "plot, not just matching numbers."
            ),
            cyto_emotion="happy",
            allow_interaction=True,
            target_widget_names=["ComparisonsPlotDisplay"],
            next_step_id="c4_s27b_export_intro",
        ),
        # ── Take it with you (export) ────────────────────────────────────────────
        InfoStep(
            id="c4_s27b_export_intro",
            text=(
                "Take it with you 📤<br><br>"
                "Every table and chart you've built this course can leave "
                "the app with you — CSV data, clipboard data, or an image "
                "file. Both tabs have their own export buttons; let's use "
                "them. Back to Statistics first."
            ),
            cyto_emotion="talking",
            next_step_id="c4_s27c_switch_stats",
        ),
        InteractionStep(
            id="c4_s27c_switch_stats",
            text="Click the 'Statistics' tab at the top.",
            cyto_emotion="pointing",
            target_widget_name="MainTabBar",
            target_widget_names=["MainTabBar"],
            event_trigger="currentChanged",
            next_step_id="c4_s27d_verify_stats_tab",
        ),
        VerificationStep(
            id="c4_s27d_verify_stats_tab",
            text="Checking tab...",
            cyto_emotion="scanning",
            hide_next_button=True,
            validator=TabActiveValidator(4),
            on_success_step_id="c4_s27e_export_csv",
            on_fail_step_id="c4_s27db_wrong_tab",
        ),
        InteractionStep(
            id="c4_s27db_wrong_tab",
            text="Oops! Click the 'Statistics' tab to proceed.",
            cyto_emotion="surprised",
            target_widget_name="MainTabBar",
            target_widget_names=["MainTabBar"],
            event_trigger="currentChanged",
            next_step_id="c4_s27d_verify_stats_tab",
        ),
        InteractionStep(
            id="c4_s27e_export_csv",
            text=(
                "Click '📤 Export CSV' (highlighted) and save your table — "
                "every row and column you computed, ready to open in a "
                "spreadsheet or attach to a report."
            ),
            target_widget_name="StatsExportButton",
            event_trigger="clicked",
            cyto_emotion="pointing",
            allow_interaction=True,
            allow_scroll=True,
            next_step_id="c4_s27f_copy_all",
        ),
        InteractionStep(
            id="c4_s27f_copy_all",
            text=(
                "'📋 Copy All' (highlighted) is the faster version of the "
                "same thing — same data, straight to your clipboard, no "
                "file dialog. Click it now."
            ),
            target_widget_name="StatsCopyAllButton",
            event_trigger="clicked",
            cyto_emotion="pointing",
            allow_interaction=True,
            allow_scroll=True,
            next_step_id="c4_s27g_export_stats_plot",
        ),
        InteractionStep(
            id="c4_s27g_export_stats_plot",
            text=(
                "You're still in Chart view from earlier, so there's a "
                "third option here too: click '📸 Export' (highlighted) to "
                "save the chart itself as an image file."
            ),
            target_widget_name="StatsExportPlotButton",
            event_trigger="clicked",
            cyto_emotion="pointing",
            allow_interaction=True,
            allow_scroll=True,
            next_step_id="c4_s27h_switch_comparisons_again",
        ),
        InteractionStep(
            id="c4_s27h_switch_comparisons_again",
            text="One more — click the 'Comparisons' tab at the top.",
            cyto_emotion="pointing",
            target_widget_name="MainTabBar",
            target_widget_names=["MainTabBar"],
            event_trigger="currentChanged",
            next_step_id="c4_s27i_verify_comparisons_tab",
        ),
        VerificationStep(
            id="c4_s27i_verify_comparisons_tab",
            text="Checking tab...",
            cyto_emotion="scanning",
            hide_next_button=True,
            validator=TabActiveValidator(7),
            on_success_step_id="c4_s27j_export_comparisons_plot",
            on_fail_step_id="c4_s27ib_wrong_tab",
        ),
        InteractionStep(
            id="c4_s27ib_wrong_tab",
            text="Oops! Click the 'Comparisons' tab to proceed.",
            cyto_emotion="surprised",
            target_widget_name="MainTabBar",
            target_widget_names=["MainTabBar"],
            event_trigger="currentChanged",
            next_step_id="c4_s27i_verify_comparisons_tab",
        ),
        InteractionStep(
            id="c4_s27j_export_comparisons_plot",
            text=(
                "This tab's own '📸 Export' (highlighted) saves whatever "
                "plot is currently on screen — your Pseudocolor Overlay — "
                "as PNG, PDF, or SVG. Click it now."
            ),
            target_widget_name="ComparisonsExportButton",
            event_trigger="clicked",
            cyto_emotion="pointing",
            allow_interaction=True,
            allow_scroll=True,
            next_step_id="c4_s27k_save_workspace",
        ),
        # ── Save workspace + real completion ─────────────────────────────────────
        VerificationStep(
            id="c4_s27k_save_workspace",
            text=(
                "Last step: save your progress. Click the **⚠️ Save "
                "Workspace** button (highlighted) at the top right."
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            hide_next_button=True,
            target_widget_names=["WorkspaceSaveButton"],
            validator=WorkflowSavedValidator(),
            on_success_step_id="c4_s27z_graduation",
            failure_hint="Click **⚠️ Save Workspace**, give it a name, and click Save to finish.",
        ),
        InfoStep(
            # The true end of Course 4 — no next_step_id, so
            # AcademyManager.next_step() treats this as course completion
            # and awards badge_reward ("Insight Reporter") the moment the
            # user clicks Next. Matches Course 3's own ending convention
            # (c3_s58_graduation): a real save-workspace step immediately
            # before it, then a plain graduation message with no further
            # step to loop back to.
            id="c4_s27z_graduation",
            text=(
                "Your workspace is updated!<br><br>Course 4 is complete — "
                "you're officially an **Insight Reporter**! 🏆<br><br>"
                "You've read the real agreement between your two B-cell "
                "methods across a full statistics table, three chart "
                "types, all five Comparisons chart types, and exported "
                "every piece of it."
            ),
            cyto_emotion="cheering",
            cyto_animation="cheering",
        ),
    ],
)
