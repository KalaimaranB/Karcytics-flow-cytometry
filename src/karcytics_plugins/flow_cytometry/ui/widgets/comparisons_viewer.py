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
from typing import TYPE_CHECKING

from karcytics_sdk.plugin.components import (
    BioComboBox,
    BioHelpButton,
    BioListWidget,
    PrimaryButton,
    SecondaryButton,
)
from karcytics_sdk.plugin.rendering.lock import MPL_RASTER_LOCK
from karcytics_sdk.plugin.theme_fallback import Colors, theme_manager
from matplotlib.figure import Figure
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidgetItem,
    QProgressBar,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.ui.graph._mpl_compat import (
    LockedFigureCanvas as FigureCanvasQTAgg,  # thread-safe vs RenderTask's Agg rasterization
)
from karcytics_plugins.flow_cytometry.ui.widgets.checkbox_style import checkbox_qss
from karcytics_plugins.flow_cytometry.ui.widgets.selection.selector_panel import (
    SampleAndPopulationSelector,
)

from .comparisons.data_extractor import ComparisonsDataExtractor
from .comparisons.plot_spec import ChannelMode, PlotTypeSpec, PopulationMode, SampleMode
from .comparisons.registry import PLOT_REGISTRY
from .comparisons.worker import ComparisonsWorker

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class DynamicStackedWidget(QStackedWidget):
    """QStackedWidget whose height dynamically matches only the current active widget."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.currentChanged.connect(self._on_current_changed)

    def addWidget(self, widget: QWidget | None) -> int:
        idx = super().addWidget(widget)
        if widget is not None:
            if idx != self.currentIndex():
                widget.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
            else:
                widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        return idx

    def _on_current_changed(self, index: int) -> None:
        for i in range(self.count()):
            w = self.widget(i)
            if w is not None:
                if i == index:
                    w.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
                else:
                    w.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.updateGeometry()

    def sizeHint(self):
        w = self.currentWidget()
        return w.sizeHint() if w is not None else super().sizeHint()

    def minimumSizeHint(self):
        w = self.currentWidget()
        return w.minimumSizeHint() if w is not None else super().minimumSizeHint()


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
        self._worker: ComparisonsWorker | None = None
        self._current_figure: Figure | None = None
        self._canvas_widget: FigureCanvasQTAgg | None = None

        # Build one options panel per plot type (instantiated once, reused)
        self._options_panels: dict[str, object] = {}

        # Tracks the previous plot type's ChannelMode so _refresh_channels()
        # can tell "still multi-channel, keep my checks" apart from "just
        # switched from single- to multi-channel mode, my one checked channel
        # isn't enough for this plot type anymore — reset to a full default."
        self._last_channel_mode: ChannelMode | None = None

        self._setup_ui()
        self.refresh_samples()

        theme_manager.theme_changed.connect(self._apply_theme_styles)
        self.destroyed.connect(self._cleanup)

    def _cleanup(self) -> None:
        """Disconnect from theme_manager so a destroyed Qt widget isn't
        invoked by a later theme change (RuntimeError: wrapped C/C++ object
        has been deleted), and block on any in-flight render so its worker
        thread can't be torn down mid-run (Qt aborts if a QThread is
        destroyed while still running). This widget is tab-embedded, not a
        window, so `closeEvent` never fires here -- `destroyed` (connected
        above) is the one teardown hook Qt guarantees for it.
        """
        if self._worker is not None:
            self._worker.stop_and_wait()
        try:
            theme_manager.theme_changed.disconnect(self._apply_theme_styles)
        except (TypeError, RuntimeError):
            pass

    # ── UI Construction ──────────────────────────────────────────────────────

    def _setup_ui(self) -> None:  # noqa: PLR0915
        main = QHBoxLayout(self)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)

        # ── Left Sidebar ─────────────────────────────────────────────────────
        sidebar = QWidget()
        sidebar.setObjectName("cmp_sidebar")
        sidebar.setFixedWidth(370)
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
        pt_hdr.addWidget(self._section_label("Plot Type"))
        self._plot_help_btn = BioHelpButton()
        pt_hdr.addWidget(self._plot_help_btn)
        pt_hdr.addStretch()
        cl.addLayout(pt_hdr)

        self._plot_type_combo = BioComboBox()
        self._plot_type_combo.setObjectName("ComparisonsPlotTypeCombo")
        for name in PLOT_REGISTRY:
            self._plot_type_combo.addItem(name)
        self._plot_type_combo.currentIndexChanged.connect(self._on_plot_type_changed)
        cl.addWidget(self._plot_type_combo)

        # 2 & 3. Samples + Populations (shared selector). The constructor's
        # mode args are just the initial state — _on_plot_type_changed(0),
        # called at the end of _setup_ui(), applies the real PlotTypeSpec.
        self._selector = SampleAndPopulationSelector(
            multi_population=self._current_spec().population_mode == PopulationMode.MULTI,
            sample_help_text=(
                "Check which samples to include in the comparison plot. "
                "Each checked sample appears as a separate group or data series."
            ),
            population_help_text=(
                "Select which gated populations to compare. 'Shared Populations' are "
                "present under the same name in every checked sample (the usual result "
                "of group gate propagation); 'Sample-Specific' lists anything that "
                "doesn't match across all checked samples.\n\n"
                "• For Violin and FMO: one population per sample is used.\n"
                "• For Radar, Heatmap, and Histogram Overlay: each checked population "
                "becomes a separate row/trace."
            ),
        )
        self._selector.selectionChanged.connect(self._on_selection_changed)
        cl.addWidget(self._selector)

        _mini = "QPushButton { padding: 3px 10px; min-height: 26px; }"

        # 4. Channels (hidden for plot types that manage their own channel selection)
        self._channel_section = QWidget()
        csl = QVBoxLayout(self._channel_section)
        csl.setContentsMargins(0, 0, 0, 0)
        csl.setSpacing(6)

        ch_hdr = QHBoxLayout()
        self._channel_section_label = self._section_label("Channels")
        ch_hdr.addWidget(self._channel_section_label)
        self._ch_help_btn = BioHelpButton()
        ch_hdr.addWidget(self._ch_help_btn)
        ch_hdr.addStretch()
        csl.addLayout(ch_hdr)

        self._channel_list = BioListWidget()
        self._channel_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._channel_list.setMaximumHeight(180)
        csl.addWidget(self._channel_list)

        ch_btns = QHBoxLayout()
        self._btn_all_ch = SecondaryButton("All")
        self._btn_all_ch.setStyleSheet(_mini)
        self._btn_all_ch.clicked.connect(lambda: self._check_all_list(self._channel_list, True))
        self._btn_none_ch = SecondaryButton("None")
        self._btn_none_ch.setStyleSheet(_mini)
        self._btn_none_ch.clicked.connect(lambda: self._check_all_list(self._channel_list, False))
        ch_btns.addWidget(self._btn_all_ch)
        ch_btns.addWidget(self._btn_none_ch)
        ch_btns.addStretch()
        csl.addLayout(ch_btns)

        cl.addWidget(self._channel_section)

        # 5. Per-plot options (DynamicStackedWidget — height dynamically follows current panel)
        opts_hdr = QHBoxLayout()
        opts_hdr.addWidget(self._section_label("Plot Options"))
        opts_hdr.addStretch()
        cl.addLayout(opts_hdr)

        self._options_stack = DynamicStackedWidget()
        for name, spec in PLOT_REGISTRY.items():
            panel = spec.options_panel_cls()
            panel.bind_state(self._state)
            self._options_panels[name] = panel
            self._options_stack.addWidget(panel)
        cl.addWidget(self._options_stack)

        # 6. Generate button
        self._generate_btn = PrimaryButton("🔬 Generate Plot")
        self._generate_btn.clicked.connect(self._on_generate)
        cl.addWidget(self._generate_btn)

        cl.addStretch()
        scroll.setWidget(content)
        sidebar_layout.addWidget(scroll)
        main.addWidget(sidebar)

        # ── Right Workspace ──────────────────────────────────────────────────
        right = QWidget()
        right.setObjectName("cmp_right")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(16, 12, 16, 16)
        right_layout.setSpacing(10)

        # Toolbar
        toolbar = QHBoxLayout()
        self._status_lbl = QLabel("Select samples and click Generate Plot.")
        self._status_lbl.setStyleSheet(f"color: {Colors.FG_SECONDARY}; font-size: 12px;")
        toolbar.addWidget(self._status_lbl)
        toolbar.addStretch()

        self._export_btn = SecondaryButton("📸 Export")
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
        self._ph_lbl.setStyleSheet(f"color: {Colors.FG_SECONDARY}; font-size: 14px;")
        ph_layout.addWidget(self._ph_lbl)
        self._display_stack.addWidget(placeholder)

        # Canvas placeholder (replaced when a figure is produced)
        self._canvas_scroll = QScrollArea()
        self._canvas_scroll.setWidgetResizable(True)
        self._canvas_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._canvas_scroll.setStyleSheet("background: transparent; border: none;")

        self._canvas_container = QWidget()
        canvas_container_layout = QVBoxLayout(self._canvas_container)
        canvas_container_layout.setContentsMargins(0, 0, 0, 0)
        canvas_container_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._canvas_scroll.setWidget(self._canvas_container)
        self._display_stack.addWidget(self._canvas_scroll)

        right_layout.addWidget(self._display_stack, stretch=1)
        main.addWidget(right, stretch=1)

        # Apply initial styles and trigger first plot-type switch
        self._apply_theme_styles()
        self._on_plot_type_changed(0)

    def _section_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"color: {Colors.FG_SECONDARY}; font-weight: bold; font-size: 11px;"
            " text-transform: uppercase; letter-spacing: 0.5px;"
        )
        return lbl

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
        plot_name = self._plot_type_combo.currentText()
        if not plot_name or plot_name not in PLOT_REGISTRY:
            return
        spec = PLOT_REGISTRY[plot_name]
        self._options_stack.setCurrentIndex(index)

        self._plot_help_btn.setHelpText(spec.help_body, spec.help_title)

        # Show/hide channel list
        no_channels = spec.channel_mode == ChannelMode.NONE
        self._channel_section.setVisible(not no_channels)

        # Update channel help text based on mode
        multi_ch = spec.channel_mode == ChannelMode.MULTI
        if multi_ch:
            self._ch_help_btn.setHelpText(
                "Select multiple channels. Each channel becomes one column (heatmap) "
                "or one spoke (radar). Choose channels relevant to the populations you are comparing.",
                "Channels",
            )
        else:
            self._ch_help_btn.setHelpText(
                "Select a single channel to compare across samples. "
                "For example, choose CD3 to compare T-cell expression, or CD19 for B cells.",
                "Channel",
            )

        # Enforce single-channel selection for violin/FMO
        if not multi_ch and not no_channels:
            self._enforce_single_channel_selection()

        # "All"/"None" only make sense when more than one channel can be
        # checked — hide them in single-channel mode instead of leaving a
        # control visible that silently does nothing useful.
        self._btn_all_ch.setVisible(multi_ch)
        self._btn_none_ch.setVisible(multi_ch)

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
        if self._worker and self._worker.isRunning():
            return

        plot_name = self._plot_type_combo.currentText()
        spec = PLOT_REGISTRY[plot_name]
        panel = self._options_panels[plot_name]
        config = panel.get_config()  # type: ignore

        sample_ids = self._selector.get_checked_sample_ids()
        pop_pairs = self._selector.get_checked_populations()
        channel_keys = self._get_checked_channels() if spec.channel_mode != ChannelMode.NONE else []

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

        renderer = spec.renderer_cls()
        self._worker = ComparisonsWorker(renderer, render_kwargs, self)
        self._worker.finished_ok.connect(self._on_render_done)
        self._worker.finished_err.connect(self._on_render_error)
        self._worker.start()

        self._generate_btn.setEnabled(False)
        self._progress_bar.show()
        self._status_lbl.setText("⏳ Rendering…")

    def _on_render_done(self, fig: Figure) -> None:
        """Replace canvas with the new figure."""
        self._current_figure = fig
        self._generate_btn.setEnabled(True)
        self._progress_bar.hide()

        # Remove old canvas. NOTE: `if container_layout:` is a trap here — a
        # QLayout's truthiness in PyQt6 follows __len__()/count(), not
        # identity, so an *empty* layout (the container's own layout on the
        # very first render, and on every render after since nothing was
        # ever actually added) is falsy even though it's a perfectly valid
        # object. That silently skipped addWidget() below on every single
        # Generate Plot click — the figure always rendered correctly
        # (Export/Download worked, since those read self._current_figure
        # directly, bypassing the widget tree entirely) but the canvas was
        # never parented into anything, so it stayed invisible. Must check
        # `is not None` explicitly.
        container_layout = self._canvas_container.layout()
        if container_layout is not None:
            while container_layout.count():
                item = container_layout.takeAt(0)
                if item:
                    w_widget = item.widget()
                    if w_widget:
                        w_widget.deleteLater()

        canvas = FigureCanvasQTAgg(fig)

        # Ignore wheel events on the canvas so they propagate up to the QScrollArea
        canvas.wheelEvent = lambda event: event.ignore()  # type: ignore[method-assign]

        canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        canvas.setStyleSheet("background-color: transparent; border: none;")

        w = int(fig.get_figwidth() * fig.dpi)
        h = int(fig.get_figheight() * fig.dpi)
        canvas.setMinimumSize(w, h)

        if container_layout is not None:
            container_layout.addWidget(canvas)
        self._canvas_widget = canvas

        self._display_stack.setCurrentIndex(1)
        self._export_btn.setEnabled(True)
        self._worker = None

        # matplotlib's Qt backend only performs a canvas's first real draw
        # from a resizeEvent-triggered draw_idle() (FigureCanvasQT.__init__
        # starts with _draw_pending=False — there's no draw scheduled at
        # construction time). A canvas built fresh here and dropped into an
        # *already-visible* container (unlike e.g. StatisticsExplorer's
        # canvas, which is built once before the window is first shown and
        # so rides the normal show/resize sequence) can end up with
        # _draw_idle() firing before layout has assigned it a real size —
        # that guards on width()<=0/height()<=0 and gives up permanently,
        # since nothing else ever calls draw_idle() again. The figure was
        # fully rendered (Export/Download worked), it just never made it to
        # screen. Force one explicit, synchronous draw() here — unlike
        # draw_idle() it has no size guard — so the canvas is guaranteed to
        # actually paint regardless of that timing race.
        #
        # Deliberately not silent: if this raises, the status label must say
        # so rather than claim "Plot ready" over a canvas that never
        # actually painted — that mismatch (status says ready, screen stays
        # blank) is exactly the symptom reported, so a swallowed exception
        # here would hide the real cause instead of surfacing it.
        try:
            canvas.draw()
        except Exception as e:
            logger.exception("ComparisonsViewer: canvas.draw() failed after Generate Plot")
            self._status_lbl.setText(f"⚠ Plot rendered but failed to display: {e}")
            return

        self._status_lbl.setText("✓ Plot ready. Use Export to save.")

    def _on_render_error(self, msg: str) -> None:
        self._generate_btn.setEnabled(True)
        self._progress_bar.hide()
        self._status_lbl.setText(f"❌ Error: {msg}")
        logger.error("ComparisonsViewer render error: %s", msg)
        self._worker = None

    def _on_export(self) -> None:
        if not self._current_figure:
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Plot",
            "",
            "PNG Image (*.png);;PDF Document (*.pdf);;SVG Vector (*.svg)",
        )
        if path:
            # savefig() triggers a full Agg rasterization pass — must hold
            # MPL_RASTER_LOCK or this can race a ComparisonsWorker/RenderTask
            # drawing a different Figure on a background thread and corrupt
            # matplotlib's shared C-level state.
            with MPL_RASTER_LOCK:
                self._current_figure.savefig(path, dpi=300, bbox_inches="tight")
            self._status_lbl.setText(f"✓ Exported to {path}")

    # ── Data helpers ─────────────────────────────────────────────────────────

    def _current_spec(self) -> PlotTypeSpec:
        return PLOT_REGISTRY[self._plot_type_combo.currentText()]

    def _is_multi_channel_mode(self) -> bool:
        return self._current_spec().channel_mode == ChannelMode.MULTI

    def _get_checked_channels(self) -> list[str]:
        result = []
        for i in range(self._channel_list.count()):
            item = self._channel_list.item(i)
            if item and item.checkState() == Qt.CheckState.Checked:
                result.append(item.data(Qt.ItemDataRole.UserRole))
        return result

    def _check_all_list(self, lst: BioListWidget, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        lst.blockSignals(True)
        is_channel_list = lst is self._channel_list
        for i in range(lst.count()):
            item = lst.item(i)
            if not item:
                continue
            # In single-channel mode, only check the first item when "All" is pressed
            if is_channel_list and not self._is_multi_channel_mode() and checked:
                item.setCheckState(Qt.CheckState.Checked if i == 0 else Qt.CheckState.Unchecked)
            else:
                item.setCheckState(state)
        lst.blockSignals(False)

    def _enforce_single_channel_selection(self) -> None:
        """Ensure only one channel is checked in single-channel plot modes."""
        self._channel_list.blockSignals(True)
        found_checked = False
        for i in range(self._channel_list.count()):
            item = self._channel_list.item(i)
            if item and item.checkState() == Qt.CheckState.Checked:
                if found_checked:
                    item.setCheckState(Qt.CheckState.Unchecked)
                else:
                    found_checked = True
        # If nothing is checked, check the first item
        if not found_checked and self._channel_list.count() > 0:
            first = self._channel_list.item(0)
            if first:
                first.setCheckState(Qt.CheckState.Checked)
        self._channel_list.blockSignals(False)

    def _refresh_channels(self) -> None:
        spec = self._current_spec()
        # A channel checked under single-channel mode isn't a meaningful
        # "keep this" signal once the plot type switches to multi-channel
        # (or vice versa) — carrying it forward could leave a multi-channel
        # plot type (e.g. Radar, which needs >=3) with only one checked
        # channel and no way to tell from the UI that it's now invalid. On a
        # mode change, start from a clean slate instead of the stale checks.
        mode_changed = spec.channel_mode != self._last_channel_mode
        self._last_channel_mode = spec.channel_mode

        prev_checked = set()
        if not mode_changed:
            for i in range(self._channel_list.count()):
                item = self._channel_list.item(i)
                if item and item.checkState() == Qt.CheckState.Checked:
                    prev_checked.add(item.data(Qt.ItemDataRole.UserRole))

        self._channel_list.blockSignals(True)
        self._channel_list.clear()
        no_channels_mode = spec.channel_mode == ChannelMode.NONE

        sample_ids = self._selector.get_checked_sample_ids()
        if not sample_ids:
            self._channel_list.blockSignals(False)
            return

        channels = []
        sample = self._state.data.experiment.samples.get(sample_ids[0])
        if sample and sample.fcs_data:
            from karcytics_plugins.flow_cytometry.analysis.fcs_io import (
                get_channel_marker_label,
                get_fluorescence_channels,
            )

            fluo_channels = get_fluorescence_channels(sample.fcs_data)
            channels = [(get_channel_marker_label(sample.fcs_data, ch), ch) for ch in fluo_channels]

        for label, key in channels:
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, key)
            from PyQt6.QtGui import QColor

            item.setForeground(QColor(Colors.FG_PRIMARY))
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked
                if (key in prev_checked or not prev_checked)
                else Qt.CheckState.Unchecked
            )
            self._channel_list.addItem(item)

        row_h = self._channel_list.sizeHintForRow(0) if self._channel_list.count() > 0 else 24
        self._channel_list.setFixedHeight(min(180, self._channel_list.count() * max(24, row_h) + 4))

        # In single-channel mode, enforce only one item is checked after populating
        if not self._is_multi_channel_mode() and not no_channels_mode:
            self._enforce_single_channel_selection()

        self._channel_list.blockSignals(False)

        # Wire channel single-select enforcement
        try:
            self._channel_list.itemChanged.disconnect(self._on_channel_item_changed)
        except TypeError:
            pass
        if not self._is_multi_channel_mode():
            self._channel_list.itemChanged.connect(self._on_channel_item_changed)

    def _on_channel_item_changed(self, item: QListWidgetItem) -> None:
        """Single-channel enforcement: when a channel is checked, uncheck all others."""
        if item.checkState() != Qt.CheckState.Checked:
            return
        self._channel_list.blockSignals(True)
        for i in range(self._channel_list.count()):
            ch_item = self._channel_list.item(i)
            if ch_item and ch_item is not item:
                ch_item.setCheckState(Qt.CheckState.Unchecked)
        self._channel_list.blockSignals(False)

    def _refresh_pseudocolor_overlay_options(self) -> None:
        """Populate the Pseudocolor Overlay panel's X/Y channel combos from
        the first checked sample (it's a single-sample plot type, like FMO).
        """
        panel = self._options_panels.get("🌈  Pseudocolor Overlay")
        if not panel or not hasattr(panel, "populate_channels"):
            return
        sample_ids = self._selector.get_checked_sample_ids()
        if not sample_ids:
            return
        channels = self._extractor.get_channel_list(self._state, sample_ids[0])
        panel.populate_channels(channels, sample_id=sample_ids[0])

    # ── Theme ────────────────────────────────────────────────────────────────

    def _apply_theme_styles(self) -> None:  # noqa: PLR0912
        self.setStyleSheet(f"background-color: {Colors.BG_DARKEST};")

        sidebar = self.findChild(QWidget, "cmp_sidebar")
        if sidebar:
            sidebar.setStyleSheet(
                f"background-color: {Colors.BG_DARKEST}; border-right: 1px solid {Colors.BORDER};"
            )
        right = self.findChild(QWidget, "cmp_right")
        if right:
            right.setStyleSheet(f"background-color: {Colors.BG_DARK};")

        if hasattr(self, "_plot_type_combo") and hasattr(
            self._plot_type_combo, "_apply_theme_styles"
        ):
            self._plot_type_combo._apply_theme_styles()

        from PyQt6.QtGui import QColor

        fg_color = QColor(Colors.FG_PRIMARY)

        # Note: the sample checklist and population tree (self._selector) theme
        # themselves independently via their own theme_manager subscription —
        # see ui/widgets/selection/.
        if self._channel_list:
            self._channel_list.setStyleSheet(
                f"QListWidget {{ background: {Colors.BG_DARKEST}; border: 1px solid {Colors.BORDER};"
                f" border-radius: 4px; color: {Colors.FG_PRIMARY}; }}"
                f"QListWidget::item {{ color: {Colors.FG_PRIMARY}; padding: 2px 4px; }}"
                f"QListWidget::item:hover {{ background: {Colors.BG_DARK}; color: {Colors.FG_PRIMARY}; }}"
                f"QListWidget::item:selected {{ background: {Colors.BG_MEDIUM}; color: {Colors.FG_PRIMARY}; }}"
                + checkbox_qss()
            )
            for i in range(self._channel_list.count()):
                item = self._channel_list.item(i)
                if item is not None:
                    item.setForeground(fg_color)

        self._status_lbl.setStyleSheet(f"color: {Colors.FG_SECONDARY}; font-size: 12px;")
        self._ph_lbl.setStyleSheet(f"color: {Colors.FG_SECONDARY}; font-size: 14px;")

        # Re-theme all options panels and their dropdowns
        color_dict = {
            "fg_primary": Colors.FG_PRIMARY,
            "fg_secondary": Colors.FG_SECONDARY,
            "bg_dark": Colors.BG_DARK,
            "bg_darkest": Colors.BG_DARKEST,
            "border": Colors.BORDER,
            "accent": Colors.ACCENT_PRIMARY,
        }
        for panel in self._options_panels.values():
            if hasattr(panel, "apply_theme"):
                panel.apply_theme(color_dict)
            if hasattr(panel, "_apply_theme_styles"):
                panel._apply_theme_styles()
            for combo in panel.findChildren(QWidget):  # type: ignore
                if hasattr(combo, "_apply_theme_styles"):
                    combo._apply_theme_styles()

        # Re-render current plot with new theme colours
        if self._current_figure is not None:
            self._on_generate()
