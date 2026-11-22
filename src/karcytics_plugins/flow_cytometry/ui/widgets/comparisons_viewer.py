"""ComparisonsViewer — full-screen cross-sample comparison plot workspace.

Follows the same architecture as StatisticsExplorer and PopulationAnalysisViewer:
  - Fixed-width scrollable left sidebar for controls
  - Right workspace with toolbar, progress bar, and matplotlib canvas

SOLID design:
  SRP: this widget assembles Qt layout and wires signals only.
       Rendering is delegated to IPlotRenderer subclasses.
       Data extraction is delegated to ComparisonsDataExtractor.
  OCP: new plot types are added to PLOT_REGISTRY — zero changes here.
  LSP: any IPlotRenderer / IOptionsPanel subclass can be swapped in.
  ISP: depends on narrow IPlotRenderer.render() and IOptionsPanel.get_config().
  DIP: depends on abstractions (IPlotRenderer, FlowState), not concrete renderers.
"""

from __future__ import annotations

import logging

from karcytics_sdk.plugin import BioSectionLabel
from karcytics_sdk.plugin.components import (
    BioComboBox,
    BioHelpButton,
    PrimaryButton,
    SecondaryButton,
)
from karcytics_sdk.plugin.dialogs import get_save_path
from karcytics_sdk.plugin.rendering.lock import MPL_RASTER_LOCK
from karcytics_sdk.plugin.runtime_services import diagnostics
from karcytics_sdk.plugin.theme_fallback import Colors, theme_manager
from matplotlib.figure import Figure
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.ui.widgets.selection.selector_panel import (
    SampleAndPopulationSelector,
)

from ...analysis.comparison_data import ComparisonsDataExtractor
from ..academy_context import ComparisonsSnapshot, PopulationPicks
from .comparisons.channel_picker import ChannelPicker
from .comparisons.options.base import IOptionsPanel
from .comparisons.options_stack import DynamicStackedWidget
from .comparisons.plot_spec import ChannelMode, PlotType, PlotTypeSpec, PopulationMode, SampleMode
from .comparisons.registry import PLOT_REGISTRY
from .figure_view import FigureView

logger = logging.getLogger(__name__)

_SIDEBAR_WIDTH = 370
_EXPORT_DPI = 300


class ComparisonsViewer(QWidget):
    """Cross-sample comparison plot workspace.

    Provides 5 plot types for comparing samples and populations:
    Violin, Channel Heatmap, Radar/Spider, Histogram Overlay,
    Pseudocolor Overlay. Each plot type's sample/population/channel
    constraints and kwargs-building live in one PlotTypeSpec
    (comparisons/plot_spec.py, comparisons/registry.py) — this widget applies
    those constraints generically rather than special-casing plot types.

    Parameters
    ----------
    state:
        Shared FlowState — read-only access for data extraction.
    gate_coordinator:
        Optional coordinator (not used for rendering, but kept for API parity
        with StatisticsExplorer and PopulationAnalysisViewer).
    parent:
        Qt parent widget.
    """

    def __init__(
        self,
        state: FlowState,
        gate_coordinator=None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._state = state
        self._gate_coordinator = gate_coordinator
        self._extractor = ComparisonsDataExtractor()
        # Exports that actually succeeded ("plot"); read by the Academy's
        # export checklist (ExportDoneValidator).
        self.completed_exports: set[str] = set()

        # Build one options panel per plot type (instantiated once, reused)
        self._options_panels: dict[PlotType, IOptionsPanel] = {}

        # The plot type the last successful Generate Plot rendered (see
        # _on_generate), which can differ from the combo's current value.
        # ComparisonsPlotGeneratedValidator reads this, so a tutorial step
        # keeps failing until Generate is clicked for the new selection.
        self._last_generated_plot_type: PlotType | None = None
        self._pending_plot_type: PlotType | None = None

        self._setup_ui()
        self.refresh_samples()

    @property
    def _current_figure(self) -> Figure | None:
        """The plot on screen."""
        return self._plot.figure

    # ── UI Construction ──────────────────────────────────────────────────────

    def _setup_ui(self) -> None:  # noqa: PLR0915
        theme_manager.apply_style(self, "background-color: {BG_DARKEST};")
        main = QHBoxLayout(self)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)

        # ── Left Sidebar ─────────────────────────────────────────────────────
        sidebar = QWidget()
        sidebar.setObjectName("cmp_sidebar")
        sidebar.setFixedWidth(_SIDEBAR_WIDTH)
        theme_manager.apply_style(
            sidebar, "background-color: {BG_DARKEST}; border-right: 1px solid {BORDER};"
        )
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("background: transparent; border: none;")

        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(16, 16, 12, 16)
        cl.setSpacing(14)

        # 1. Plot type selector
        pt_hdr = QHBoxLayout()
        pt_hdr.addWidget(BioSectionLabel("Plot Type"))
        self._plot_help_btn = BioHelpButton()
        pt_hdr.addWidget(self._plot_help_btn)
        pt_hdr.addStretch()
        cl.addLayout(pt_hdr)

        self._plot_type_combo = BioComboBox()
        self._plot_type_combo.setObjectName("ComparisonsPlotTypeCombo")
        for plot_type, spec in PLOT_REGISTRY.items():
            self._plot_type_combo.addItem(spec.label, plot_type.value)
        self._plot_type_combo.currentIndexChanged.connect(self._on_plot_type_changed)
        cl.addWidget(self._plot_type_combo)

        # 2 & 3. Samples + Populations (shared selector). The constructor's
        # mode args are just the initial state — _on_plot_type_changed(0),
        # called at the end of _setup_ui(), applies the real PlotTypeSpec.
        self._selector = SampleAndPopulationSelector(
            multi_population=self._current_spec().population_mode == PopulationMode.MULTI,
            population_help_text=(
                "Select which gated populations to compare. Click 'Edit Population "
                "Selection' to open the picker.\n\n"
                "• For Violin and FMO: one population per sample is used.\n"
                "• For Radar, Heatmap, and Histogram Overlay: each checked population "
                "becomes a separate row/trace."
            ),
        )
        self._selector.selectionChanged.connect(self._on_selection_changed)
        self._selector.population_edit_button.setObjectName("ComparisonsPopulationPickerButton")
        cl.addWidget(self._selector)

        # 4. Channels (hidden for plot types that take none)
        self._channels = ChannelPicker()
        cl.addWidget(self._channels)

        # 5. Per-plot options (DynamicStackedWidget — height dynamically follows current panel)
        opts_hdr = QHBoxLayout()
        opts_hdr.addWidget(BioSectionLabel("Plot Options"))
        opts_hdr.addStretch()
        cl.addLayout(opts_hdr)

        self._options_stack = DynamicStackedWidget()
        self._options_stack.setObjectName("ComparisonsOptionsPanel")
        for plot_type, spec in PLOT_REGISTRY.items():
            panel = spec.options_panel_cls()
            panel.bind_state(self._state)
            self._options_panels[plot_type] = panel
            self._options_stack.addWidget(panel)
        cl.addWidget(self._options_stack)

        # 6. Generate button
        self._generate_btn = PrimaryButton("🔬 Generate Plot")
        self._generate_btn.setObjectName("ComparisonsGenerateButton")
        self._generate_btn.clicked.connect(self._on_generate)
        cl.addWidget(self._generate_btn)

        cl.addStretch()
        scroll.setWidget(content)
        sidebar_layout.addWidget(scroll)
        main.addWidget(sidebar)

        # ── Right Workspace ──────────────────────────────────────────────────
        right = QWidget()
        right.setObjectName("cmp_right")
        theme_manager.apply_style(right, "background-color: {BG_DARK};")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(16, 12, 16, 16)
        right_layout.setSpacing(10)

        # Toolbar
        toolbar = QHBoxLayout()
        self._status_lbl = QLabel("Select samples and click Generate Plot.")
        theme_manager.apply_style(self._status_lbl, "color: {FG_SECONDARY}; font-size: 12px;")
        toolbar.addWidget(self._status_lbl)
        toolbar.addStretch()

        self._export_btn = SecondaryButton("📸 Export")
        self._export_btn.setObjectName("ComparisonsExportButton")
        self._export_btn.setToolTip("Save the current plot as PNG, PDF, or SVG")
        self._export_btn.setEnabled(False)
        self._export_btn.clicked.connect(self._on_export)
        toolbar.addWidget(self._export_btn)

        right_layout.addLayout(toolbar)

        # Progress bar
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 0)
        self._progress_bar.setFixedHeight(4)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.hide()
        right_layout.addWidget(self._progress_bar)

        # Display stack: 0=placeholder, 1=canvas
        self._display_stack = QStackedWidget()
        self._display_stack.setObjectName("ComparisonsPlotDisplay")
        self._display_stack.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

        # Placeholder
        placeholder = QWidget()
        ph_layout = QVBoxLayout(placeholder)
        ph_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ph_icon = QLabel("📊")
        ph_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ph_icon.setStyleSheet("font-size: 52px;")
        ph_layout.addWidget(ph_icon)
        self._ph_lbl = QLabel(
            "Select samples, populations and a plot type\nthen click Generate Plot."
        )
        self._ph_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        theme_manager.apply_style(self._ph_lbl, "color: {FG_SECONDARY}; font-size: 14px;")
        ph_layout.addWidget(self._ph_lbl)
        self._display_stack.addWidget(placeholder)

        # The plot, drawn off the GUI thread at its own size (a big heatmap scrolls).
        self._plot = FigureView(natural_size=True)
        self._plot.figure_shown.connect(self._on_render_done)
        self._plot.render_failed.connect(self._on_render_error)
        self._canvas_scroll = QScrollArea()
        self._canvas_scroll.setWidgetResizable(True)
        self._canvas_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._canvas_scroll.setStyleSheet("background: transparent; border: none;")
        self._canvas_scroll.setWidget(self._plot)
        self._display_stack.addWidget(self._canvas_scroll)

        right_layout.addWidget(self._display_stack, stretch=1)
        main.addWidget(right, stretch=1)

        self._on_plot_type_changed(0)

    # ── Public API ───────────────────────────────────────────────────────────

    def refresh_samples(self) -> None:
        """Repopulate sample list from the current experiment state."""
        self._selector.refresh(self._state.data.experiment.samples)
        # selectionChanged (emitted by refresh()) already triggers
        # _on_selection_changed -> _refresh_channels()/_refresh_fmo_options().

    # ── Signals ──────────────────────────────────────────────────────────────

    def _on_plot_type_changed(self, index: int) -> None:
        """SRP: swap options panel + update help text + apply this plot
        type's sample/population/channel constraints (PlotTypeSpec).
        """
        spec = self._current_spec()
        self._options_stack.setCurrentIndex(index)

        self._plot_help_btn.setHelpText(spec.help_body, spec.help_title)

        self._channels.set_mode(spec.channel_mode)

        # Apply this plot type's sample/population constraints: force a
        # single checked sample (radio) when the renderer only supports one,
        # and switch the population selector between grouped multi-select
        # and the flat per-sample radio mode.
        self._selector.set_sample_mode(spec.sample_mode == SampleMode.SINGLE)
        self._selector.set_multi_population(spec.population_mode == PopulationMode.MULTI)
        self._refresh_channels()
        self._refresh_pseudocolor_overlay_options()

    def _on_selection_changed(self) -> None:
        self._refresh_channels()
        self._refresh_pseudocolor_overlay_options()

    def _on_generate(self) -> None:
        """Validate inputs, extract data, spawn worker."""
        if self._plot.is_rendering():
            return

        plot_type = self.current_plot_type()
        spec = PLOT_REGISTRY[plot_type]
        panel = self._options_panels[plot_type]
        config = panel.get_config()

        sample_ids = self._selector.get_checked_sample_ids()
        pop_pairs = self._selector.get_checked_populations()
        channel_keys = self._channels.checked() if spec.channel_mode != ChannelMode.NONE else []

        # Validate. Every plot type requires at least one population
        # (PlotTypeSpec.population_mode is always ONE_PER_SAMPLE or MULTI,
        # never "none") — checked here generically so an empty selection
        # can't silently fall through to a builder that treats "no
        # population" as "All Events" (e.g. Violin) and plots that instead
        # without telling the user nothing was actually selected.
        if not sample_ids:
            self._status_lbl.setText("⚠ No samples selected.")
            return
        if not pop_pairs:
            self._status_lbl.setText("⚠ No populations selected.")
            return

        try:
            render_kwargs = spec.build_kwargs(
                self._state, self._extractor, config, sample_ids, pop_pairs, channel_keys
            )
        except ValueError as e:
            self._status_lbl.setText(f"⚠ {e}")
            return

        # Inject theme colors (DIP: renderers don't import Qt/theme). Uses
        # setdefault rather than update() so a plot type whose kwargs builder
        # already set one of these (e.g. Pseudocolor Overlay, which needs a
        # fixed white background + jet-safe palette instead of the app's
        # dark/light theme — see build_pseudocolor_overlay_kwargs) keeps its
        # own value instead of being overwritten.
        for key, value in {
            "bg_color": Colors.BG_DARKEST,
            "fg_color": Colors.FG_PRIMARY,
            "border_color": Colors.BORDER,
            "accent_color": Colors.ACCENT_PRIMARY,
            "palette": Colors.CHART_COLORS,
        }.items():
            render_kwargs.setdefault(key, value)

        self._pending_plot_type = plot_type
        self._plot.draw(spec.renderer_cls(), render_kwargs)

        self._generate_btn.setEnabled(False)
        self._progress_bar.show()
        self._status_lbl.setText("⏳ Rendering…")

    def _on_render_done(self, _figure: Figure) -> None:
        self._generate_btn.setEnabled(True)
        self._progress_bar.hide()
        self._display_stack.setCurrentWidget(self._canvas_scroll)
        self._export_btn.setEnabled(True)
        self._last_generated_plot_type = self._pending_plot_type
        self._status_lbl.setText("✓ Plot ready. Use Export to save.")

    def _on_render_error(self, msg: str) -> None:
        self._generate_btn.setEnabled(True)
        self._progress_bar.hide()
        self._status_lbl.setText(f"❌ Error: {msg}")

    def _on_export(self) -> None:
        figure = self._current_figure
        if figure is None:
            return
        path = get_save_path(
            self,
            "Export Plot",
            "comparison.png",
            "PNG Image (*.png);;PDF Document (*.pdf);;SVG Vector (*.svg)",
        )
        if not path:
            return
        try:
            with MPL_RASTER_LOCK:  # savefig rasterizes through the shared Agg backend
                figure.savefig(path, dpi=_EXPORT_DPI, bbox_inches="tight")
        except Exception as exc:  # noqa: BLE001 - reported as a diagnostic, not a crash
            logger.exception("Comparisons plot export failed")
            self._status_lbl.setText(f"❌ Export failed: {exc}")
            diagnostics.report_error("Comparisons plot export failed", exception=exc, fatal=False)
            return
        self._status_lbl.setText(f"✓ Exported to {path}")
        self.completed_exports.add("plot")

    # ── Data helpers ─────────────────────────────────────────────────────────

    def current_plot_type(self) -> PlotType:
        """The id of the plot type selected in the combo."""
        return PlotType(self._plot_type_combo.currentData())

    def _current_spec(self) -> PlotTypeSpec:
        return PLOT_REGISTRY[self.current_plot_type()]

    def academy_snapshot(self) -> ComparisonsSnapshot:
        overlay = self._options_panels.get(PlotType.HISTOGRAM_OVERLAY)
        return ComparisonsSnapshot(
            PopulationPicks.of(self._selector),
            self._last_generated_plot_type,
            overlay.get_config()["layout"] if overlay is not None else "",
            tuple(self._channels.checked()),
        )

    def refresh_channels(self) -> None:
        """Rebuild the channel list (e.g. after derived parameters change)."""
        self._refresh_channels()

    def _refresh_channels(self) -> None:
        sample_ids = self._selector.get_checked_sample_ids()
        sample = self._state.data.experiment.samples.get(sample_ids[0]) if sample_ids else None
        self._channels.refresh(sample.fcs_data if sample is not None else None)

    def _refresh_pseudocolor_overlay_options(self) -> None:
        """Populate the Pseudocolor Overlay panel's X/Y channel combos from
        the first checked sample (it's a single-sample plot type, like FMO).
        """
        panel = self._options_panels.get(PlotType.PSEUDOCOLOR_OVERLAY)
        if panel is None:
            return
        sample_ids = self._selector.get_checked_sample_ids()
        if not sample_ids:
            return
        channels = self._extractor.get_channel_list(self._state, sample_ids[0])
        panel.populate_channels(channels, sample_id=sample_ids[0])

    # ── Theme ────────────────────────────────────────────────────────────────

    def _apply_theme_styles(self) -> None:
        """MainPanel calls this on a theme change: the stylesheets set by hand, and the plot."""
        self._channels.apply_theme()
        for panel in self._options_panels.values():
            panel.apply_theme()
        if self._current_figure is not None:
            self._on_generate()  # its colours are drawn into the figure
