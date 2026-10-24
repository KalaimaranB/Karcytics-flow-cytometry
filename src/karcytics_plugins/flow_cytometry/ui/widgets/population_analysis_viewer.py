"""Population Analysis Viewer — set up and view clustering runs (UMAP + HDBSCAN, FlowSOM, PhenoGraph)."""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd
from karcytics_sdk.plugin import BioSectionLabel
from karcytics_sdk.plugin.components import (
    BioComboBox,
    PrimaryButton,
    SecondaryButton,
    repopulate_combo,
)
from karcytics_sdk.plugin.managed_task import FunctionalTask
from karcytics_sdk.plugin.runtime_services import task_scheduler
from karcytics_sdk.plugin.theme_fallback import Colors
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from karcytics_plugins.flow_cytometry.analysis.animation.alignment import align_to_frame
from karcytics_plugins.flow_cytometry.analysis.animation.animation_prep import (
    UmapAnimationDataPrep,
)
from karcytics_plugins.flow_cytometry.analysis.clustering import (
    UMAP_HDBSCAN,
    method_of,
)
from karcytics_plugins.flow_cytometry.analysis.population_service import population_events
from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.ui.services.umap_service import (
    FlowsomParams,
    PhenographParams,
    UmapParams,
    UmapService,
)

from ...analysis.fcs_io import get_fluorescence_channels
from ...analysis.services import experiment_edits
from ..academy_context import PopulationAnalysisSnapshot
from .cluster_results_panel import ClusterResultsPanel
from .clustering_setup import ClusteringSetup
from .umap_animator_widget import UmapAnimatorWidget, build_umap_animation_frames

logger = logging.getLogger(__name__)

# What a UMAP run stores of the settings it ran with.
_UMAP_SETTINGS = (
    "name",
    "run_hdbscan",
    "percentage",
    "n_neighbors",
    "min_dist",
    "metric",
    "random_seed",
    "min_cluster_size",
    "hdbscan_space",
)
# The display stack's pages.
_PLACEHOLDER, _RESULTS, _ANIMATION = 0, 1, 2


def _prepare_animation(
    events: Any, channels: list[str], state: FlowState, params: UmapParams, fps: int
) -> dict[str, Any]:
    """Background: the animation's quick subsample UMAP and its ~750 frames.

    The frames are built here too: on the GUI thread they froze the app after
    a quick UMAP run.
    """
    prep = UmapAnimationDataPrep(n_neighbors=params.n_neighbors, random_seed=params.random_seed)
    if not prep.prepare(events, channels, state, params.target_sample_id, min_dist=params.min_dist):
        return {"success": False}
    frames, colors = build_umap_animation_frames(prep, fps=fps)
    return {"success": True, "prep": prep, "frames": frames, "colors": colors}


class PopulationAnalysisViewer(QWidget):
    """Component that plots the UMAP embedding and exposes configurations."""

    def __init__(
        self,
        state: FlowState,
        umap_service: UmapService,
        gate_coordinator=None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._last_prep_data: Any = None  # the UMAP run's animation frames, once prepared
        self._state = state
        self._umap_service = umap_service
        self._gate_coordinator = gate_coordinator
        self._is_animation_playing = False
        self._is_analysis_running = False

        self._last_results: dict[str, Any] | None = None
        self._pending_umap: UmapParams | None = None  # waits for its animation's frames

        self._setup_ui()
        self._apply_theme_styles()
        self.refresh_samples()

    def _setup_ui(self) -> None:
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        main_layout.addWidget(self._build_sidebar())
        main_layout.addWidget(self._build_display(), stretch=1)

    def _build_sidebar(self) -> QWidget:
        """The run's settings, the Run/Cancel buttons and the run history."""
        sidebar = self._sidebar = QWidget()
        sidebar.setObjectName("left_sidebar")
        sidebar.setFixedWidth(320)
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setStyleSheet("background: transparent; border: none;")
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.addWidget(scroll_area)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)
        scroll_area.setWidget(content)
        self._setup = ClusteringSetup(self._state)
        self._setup.target_changed.connect(self.refresh_history)
        self._setup.method_changed.connect(self._on_method_changed)
        layout.addWidget(self._setup)
        layout.addSpacing(20)
        self._add_run_section(layout)
        layout.addStretch()
        return sidebar

    def _add_run_section(self, layout: QVBoxLayout) -> None:
        """Run / Cancel, and the history of past runs."""
        self._run_btn = PrimaryButton("🧬 Run Analysis")
        self._run_btn.setObjectName("RunAnalysisButton")
        self._run_btn.clicked.connect(self.start_analysis)
        layout.addWidget(self._run_btn)
        self._cancel_btn = SecondaryButton("⏹ Cancel")
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.clicked.connect(self._umap_service.cancel)
        layout.addWidget(self._cancel_btn)
        layout.addSpacing(20)

        layout.addWidget(BioSectionLabel("History"))
        self._history_combo = BioComboBox()
        self._history_combo.setObjectName("UmapHistoryCombo")
        self._history_combo.addItem("[ New Run ]", None)
        self._history_combo.currentIndexChanged.connect(self._on_history_changed)
        layout.addWidget(self._history_combo)
        self._run_details_lbl = QLabel("Select a past run to view details.")
        self._run_details_lbl.setWordWrap(True)
        layout.addWidget(self._run_details_lbl)
        self._delete_run_btn = SecondaryButton("🗑️ Delete Run")
        self._delete_run_btn.setEnabled(False)
        self._delete_run_btn.clicked.connect(self._on_delete_run_clicked)
        layout.addWidget(self._delete_run_btn)

    def _build_display(self) -> QWidget:
        """Status and progress over a stack: placeholder, results, UMAP animation."""
        panel = self._display_panel = QWidget()
        panel.setObjectName("right_panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        toolbar = QHBoxLayout()
        self._status_lbl = QLabel("Ready")
        toolbar.addWidget(self._status_lbl)
        toolbar.addStretch()
        self._replay_anim_btn = SecondaryButton("▶ Replay Animation")
        self._replay_anim_btn.setEnabled(False)
        self._replay_anim_btn.clicked.connect(self._play_animation)
        toolbar.addWidget(self._replay_anim_btn)
        layout.addLayout(toolbar)

        self._progress_bar = QProgressBar()  # shown while a run computes
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setTextVisible(True)
        self._progress_bar.hide()
        layout.addWidget(self._progress_bar)

        self._display_stack = QStackedWidget()
        self._display_stack.setObjectName("display_stack")
        self._placeholder_panel = QWidget()
        self._placeholder_panel.setObjectName("placeholder_panel")
        placeholder_layout = QVBoxLayout(self._placeholder_panel)
        placeholder_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder_lbl = QLabel("Configure a run in the left panel to begin.")
        self._placeholder_lbl.setObjectName("placeholder_lbl")
        placeholder_layout.addWidget(self._placeholder_lbl)
        self._results_panel = QWidget()  # replaced by a ClusterResultsPanel per run
        self._animator = UmapAnimatorWidget()
        self._animator.animation_finished.connect(self._on_animation_finished)
        self._display_stack.addWidget(self._placeholder_panel)  # _PLACEHOLDER
        self._display_stack.addWidget(self._results_panel)  # _RESULTS
        self._display_stack.addWidget(self._animator)  # _ANIMATION
        layout.addWidget(self._display_stack, stretch=1)
        return panel

    def _apply_theme_styles(self) -> None:
        self.setStyleSheet(f"background-color: {Colors.BG_DARKEST};")
        sidebar_qss = (
            f"background-color: {Colors.BG_DARKEST}; border-right: 1px solid {Colors.BORDER};"
        )
        self._sidebar.setStyleSheet(sidebar_qss)
        self._display_panel.setStyleSheet(f"background-color: {Colors.BG_DARK};")
        self._display_stack.setStyleSheet(f"""
            #display_stack {{ background-color: {Colors.BG_DARKEST}; border-radius: 8px; }}
            #placeholder_panel {{ background-color: {Colors.BG_DARKEST}; border-radius: 8px; }}
        """)
        self._placeholder_lbl.setStyleSheet(f"color: {Colors.FG_SECONDARY}; font-size: 14px;")
        self._status_lbl.setStyleSheet(
            f"color: {Colors.FG_SECONDARY}; font-size: 12px; font-weight: bold;"
        )
        self._run_details_lbl.setStyleSheet(f"color: {Colors.FG_SECONDARY}; font-size: 11px;")
        self._progress_bar.setStyleSheet(f"""
            QProgressBar {{
                border: 1px solid {Colors.BORDER};
                border-radius: 4px;
                text-align: center;
                background-color: {Colors.BG_DARKER};
                color: {Colors.FG_PRIMARY};
            }}
            QProgressBar::chunk {{
                background-color: {Colors.DNA_PRIMARY};
                border-radius: 3px;
            }}
        """)
        self._setup._apply_theme_styles()
        self._animator._apply_theme_styles()

    def academy_snapshot(self) -> PopulationAnalysisSnapshot:
        panel = self._results_panel
        return PopulationAnalysisSnapshot(
            **self._setup.academy_fields(),
            new_run_selected=self._history_combo.currentData() is None,
            is_running=self._is_analysis_running,
            is_animating=self._is_animation_playing,
            has_results=self._last_results is not None,
            results=panel.academy_snapshot() if isinstance(panel, ClusterResultsPanel) else None,
        )

    def _on_method_changed(self) -> None:
        self._replay_anim_btn.setVisible(self._setup.method is UMAP_HDBSCAN)  # UMAP's animation

    def _set_read_only(self, read_only: bool) -> None:
        """A stored run is shown read-only; [ New Run ] edits the form again."""
        if read_only:
            self._setup.set_read_only(True)
        else:
            self._setup.start_new_run()
        self._run_btn.setEnabled(not read_only)
        self._run_btn.setVisible(not read_only)
        self._cancel_btn.setVisible(not read_only)

    def set_running(self, running: bool) -> None:
        """Toggle button enabled states during running tasks."""
        self._run_btn.setEnabled(not running)
        self._cancel_btn.setEnabled(running)
        self._setup.set_busy(running)
        self._history_combo.setEnabled(not running)

        if running:
            self._delete_run_btn.setEnabled(False)
        else:
            has_run = self._history_combo.itemData(self._history_combo.currentIndex()) is not None
            self._delete_run_btn.setEnabled(has_run)

    def refresh_samples(self) -> None:
        """Re-lists the samples (and the chosen sample's populations and runs)."""
        self._setup.refresh_samples()
        self.refresh_history()

    def _purify_state(self) -> None:
        """Recursively cleans up umap_results structure while keeping numpy arrays intact.

        This prevents PySide6 / Qt C++ from converting 100k+ element lists into
        QVariantList strings on stdout/stderr, which causes massive console dumps
        and main thread UI freezes.
        """

        def _purify(obj):
            if isinstance(obj, dict):
                for k, v in list(obj.items()):
                    obj[k] = _purify(v)
            elif isinstance(obj, list):
                if len(obj) > 100 and not isinstance(obj[0], (dict, list)):  # noqa: PLR2004
                    return obj
                for i in range(len(obj)):
                    obj[i] = _purify(obj[i])
            elif isinstance(obj, pd.DataFrame):
                return obj.to_dict(orient="split")
            return obj

        if self._state and hasattr(self._state.data, "umap_results"):
            _purify(self._state.data.umap_results)

    def show_run(self, sample_id: str, gate_id: str | None, run_index: int) -> None:
        """Shows a stored run: picks its sample, gate and history entry, then displays it."""
        self._setup.select(sample_id, gate_id)
        self.refresh_history()
        self._history_combo.blockSignals(True)
        index = self._history_combo.findData(run_index)
        if index >= 0:
            self._history_combo.setCurrentIndex(index)
        self._history_combo.blockSignals(False)
        if index >= 0:
            self._on_history_changed(index)

    def refresh_history(self) -> None:
        """Populate the history combo with past runs for current sample and gate."""
        self._purify_state()

        prev_run_idx = self._history_combo.currentData()
        items: list[tuple[str, int | None]] = [("[ New Run ]", None)]

        if self._setup.sample_id:
            for i, run in enumerate(self._runs(), 1):
                name = run.get("name")
                method = method_of(run)
                if method.recuttable:
                    label = f"{i}. {name or 'Run'} · {method.name} {method.setting_text(run)}"
                elif name:
                    label = f"{i}. {name}"
                else:
                    n = run.get("n_neighbors", 15)
                    md = run.get("min_dist", 0.1)
                    label = f"Run {i} (n={n}, md={md})"
                items.append((label, i - 1))

        repopulate_combo(self._history_combo, items, restore_data=prev_run_idx)
        self._update_delete_button_state()

    def _update_delete_button_state(self) -> None:
        has_run = self._history_combo.itemData(self._history_combo.currentIndex()) is not None
        self._delete_run_btn.setEnabled(has_run)

    def _restore_fields_from_run(self, run_data: dict) -> None:
        """Shows a stored run's settings (without rebuilding its results panel)."""
        self._last_results = run_data
        self._set_read_only(True)
        self._run_details_lbl.setVisible(False)
        self._setup.show_run(run_data)

    def _on_history_changed(self, index: int) -> None:
        self._update_delete_button_state()
        run_idx = self._history_combo.itemData(index)

        if run_idx is None:
            self._set_read_only(False)
            self._display_stack.setCurrentIndex(_PLACEHOLDER)
            self._last_results = None
            self._animator.stop()
            self._replay_anim_btn.setEnabled(False)
            self._run_details_lbl.setText("Configure a new run above to begin.")
            self._run_details_lbl.setVisible(True)
            return

        runs = self._runs()
        if not (0 <= run_idx < len(runs)):
            return
        self._restore_fields_from_run(runs[run_idx])
        self._show_results(runs[run_idx])

    def _runs(self) -> list[dict[str, Any]]:
        """The stored runs of the chosen sample and population."""
        sample_id = self._setup.sample_id
        if not sample_id:
            return []
        key = experiment_edits.runs_key(sample_id, self._setup.gate_id)
        return self._state.data.umap_results.get(key, [])

    def _show_results(self, run: dict[str, Any]) -> None:
        """Replaces the results page with `run`'s (its plots take seconds to build)."""
        self._display_stack.removeWidget(self._results_panel)
        self._results_panel.deleteLater()
        self._results_panel = self._make_results_panel(run)
        self._display_stack.insertWidget(_RESULTS, self._results_panel)
        self._animator.stop()
        self._display_stack.setCurrentIndex(_RESULTS)
        self._replay_anim_btn.setEnabled(method_of(run) is UMAP_HDBSCAN)

    def _on_results_modified(self) -> None:
        # Cluster names / custom clusters live inside the run's result dict,
        # which undo snapshots only reference by id: saved, not undoable.
        experiment_edits.announce_unsaved_change()
        self._history_combo.blockSignals(True)  # a re-cut k shows in the run's label
        self.refresh_history()
        self._history_combo.blockSignals(False)

    def _on_delete_run_clicked(self) -> None:
        run_idx = self._history_combo.currentData()
        sample_id = self._setup.sample_id
        if run_idx is None or not sample_id:
            return
        key = experiment_edits.runs_key(sample_id, self._setup.gate_id)
        experiment_edits.delete_umap_run(self._state, key, run_idx)  # an undoable edit
        self.refresh_history()
        # refresh_history() blocks signals: show the next run or [ New Run ] by hand.
        self._on_history_changed(self._history_combo.currentIndex())

    def start_analysis(self) -> None:
        try:
            params = self._setup.request()
        except ValueError as e:
            self._on_analysis_error(str(e))
            return
        if params is None:  # no sample
            return
        self._is_analysis_running = True
        self._is_animation_playing = False
        if not isinstance(params, UmapParams):
            self._start_without_animation(params)
            return

        self._progress_bar.setRange(0, 0)
        self._progress_bar.show()

        self.set_running(True)
        node_id = params.target_node_id
        gate_hint = f" (gate: {node_id[:8]}\u2026)" if node_id else " (all events)"
        self._status_lbl.setText(f"Running analysis{gate_hint}...")

        sample = self._state.data.experiment.samples.get(params.target_sample_id)
        if sample is None or sample.fcs_data is None:
            self._display_stack.setCurrentIndex(_PLACEHOLDER)
            self._run_umap(params)
            return
        # A quick UMAP of a subsample animates while the full run computes.
        gate_node = sample.gate_tree.find_node_by_id(node_id) if node_id else None
        events = population_events(self._state.data.experiment, sample, gate_node)
        channels = get_fluorescence_channels(sample.fcs_data)
        self._animator.show_loading()
        self._display_stack.setCurrentIndex(_ANIMATION)
        self._pending_umap = params
        state, fps = self._state, self._animator.fps
        task = FunctionalTask(
            lambda: _prepare_animation(events, channels, state, params, fps), name="UMAP Prep"
        )
        worker = task_scheduler.submit(task, None)
        worker.finished.connect(self._on_animation_prepared)
        worker.error.connect(self._on_animation_prep_error)

    def _on_animation_prepared(self, results: dict) -> None:
        params, self._pending_umap = self._pending_umap, None
        if params is None:
            return
        if results.get("success"):
            self._last_prep_data = results["prep"]
            if results["frames"]:
                self._animator.apply_precomputed_frames(results["frames"], results["colors"])
            else:  # the prep lacked the arrays to build frames from in the background
                self._animator.prepare_animation(self._last_prep_data)
            self._is_animation_playing = True
            self._display_stack.setCurrentIndex(_ANIMATION)
            self._animator.start()
        else:
            logger.warning("Prep failed — skipping animation, proceeding to UMAP only.")
            self._display_stack.setCurrentIndex(_PLACEHOLDER)
        self._run_umap(params)

    def _on_animation_prep_error(self, err: str) -> None:
        self._pending_umap = None
        self._display_stack.setCurrentIndex(_PLACEHOLDER)
        self._on_analysis_error(f"Animation prep failed: {err}")

    def _run_umap(self, params: UmapParams) -> None:
        self._umap_service.run_analysis(
            params=params,
            on_done=lambda results: self._on_analysis_done(results, params=params),
            on_error_cb=self._on_analysis_error,
            on_progress=self._progress_bar.setValue,
        )

    def _start_without_animation(self, params: FlowsomParams | PhenographParams) -> None:
        """FlowSOM and PhenoGraph: no UMAP animation, just progress."""
        name = "FlowSOM" if isinstance(params, FlowsomParams) else "PhenoGraph"
        self._last_prep_data = None  # no UMAP animation to align with
        self._animator.stop()
        self._display_stack.setCurrentIndex(_PLACEHOLDER)
        self._placeholder_lbl.setText(f"Running {name} on {params.n_events:,} events…")
        self._progress_bar.setValue(0)
        self._progress_bar.show()
        self.set_running(True)
        if isinstance(params, FlowsomParams):
            self._progress_bar.setRange(0, 100)
            self._status_lbl.setText("Running FlowSOM...")
            self._umap_service.run_flowsom(
                params, self._on_analysis_done, self._on_analysis_error, self._progress_bar.setValue
            )
        else:
            self._progress_bar.setRange(0, 0)  # the daemon reports no progress: busy bar
            self._status_lbl.setText("Running PhenoGraph (neighbours, then clusters)...")
            self._umap_service.run_phenograph(
                params, self._on_analysis_done, self._on_analysis_error
            )

    def _make_results_panel(self, results: dict[str, Any]) -> ClusterResultsPanel:
        panel = ClusterResultsPanel(
            results,
            state=self._state,
            gate_coordinator=self._gate_coordinator,
        )
        panel.results_modified.connect(self._on_results_modified)
        panel.recluster_requested.connect(self._on_recluster_requested)
        return panel

    def _on_recluster_requested(self, resolution: float) -> None:
        """Re-cluster the PhenoGraph run on screen; the panel shows the result."""
        panel = self._results_panel
        run = getattr(panel, "_results", None)
        if run is None or not isinstance(panel, ClusterResultsPanel):
            return
        self._umap_service.recluster_phenograph(
            run,
            resolution,
            on_done=lambda arrays: self._finish_recluster(panel, arrays),
            on_error_cb=lambda err: self._finish_recluster(panel, {"error": err}),
        )

    def _finish_recluster(self, panel: ClusterResultsPanel, arrays: dict[str, Any]) -> None:
        if panel is self._results_panel:  # still the run on screen
            panel.apply_recluster(arrays)

    def _on_analysis_done(  # noqa: PLR0912, PLR0915
        self, results: dict[str, Any], params: UmapParams | None = None
    ) -> None:
        self._progress_bar.setRange(0, 100)
        self._progress_bar.hide()
        self._is_analysis_running = False

        if "error" in results:
            self.set_running(False)
            self._status_lbl.setText("Error computing analysis.")
            self._on_analysis_error(results["error"])
            return

        self._status_lbl.setText(f"Completed — {results['n_events']:,} events")

        embedding = results.get("embedding")
        if embedding is not None and method_of(results) is UMAP_HDBSCAN:
            if isinstance(embedding, list):
                embedding = np.array(embedding)

            if self._last_prep_data and self._last_prep_data.final_2d is not None:
                embedding = align_to_frame(embedding, self._last_prep_data.final_2d)

            # Check for NaNs/Infs that could crash downstream logic
            if not np.isfinite(embedding).all():
                logger.warning(
                    "UMAP embedding contains non-finite values (NaN/Inf). Resetting to zeros."
                )
                embedding = np.nan_to_num(embedding)

            # Store back as a list so it can be JSON serialized when history is saved
            if hasattr(embedding, "tolist"):
                results["embedding"] = embedding.tolist()

        # Keep numeric arrays in numpy format to avoid PySide6 / Qt C++ QVariant list console dumping.
        for key in ["intensities", "indices", "clusters", "embedding"]:
            if key in results and isinstance(results[key], list):
                results[key] = np.array(results[key])

        if params:  # a UMAP run records the settings it ran with
            results.update({key: getattr(params, key) for key in _UMAP_SETTINGS})

        self._last_results = results

        experiment_edits.add_umap_run(self._state, results)

        # The results panel is built in _check_transition_to_results(), not here:
        # its plots take seconds and would freeze the running animation.

        self._replay_anim_btn.setEnabled(method_of(results) is UMAP_HDBSCAN)
        self._placeholder_lbl.setText("Configure a run in the left panel to begin.")
        self._check_transition_to_results()

    def _check_transition_to_results(self) -> None:
        """Shows a finished run once both it and its animation are done."""
        if self._is_animation_playing or self._is_analysis_running or not self._last_results:
            return
        run = self._last_results
        # Built only now: the results' plots block the GUI thread for seconds.
        self._show_results(run)
        self.set_running(False)
        self._history_combo.blockSignals(True)  # the panel is built: just select its entry
        self.refresh_history()
        final_index = max(self._history_combo.count() - 1, 0)
        self._history_combo.setCurrentIndex(final_index)
        self._history_combo.blockSignals(False)
        run_idx = self._history_combo.itemData(final_index)
        runs = self._runs()
        if run_idx is not None and 0 <= run_idx < len(runs):
            self._restore_fields_from_run(runs[run_idx])
        self._update_delete_button_state()

    def _on_animation_finished(self) -> None:
        self._is_animation_playing = False
        self._check_transition_to_results()

    def _play_animation(self) -> None:
        self._is_animation_playing = True
        if not self._last_prep_data:
            return
        if hasattr(self._animator, "_anim_frame_counter"):
            self._animator._anim_frame_counter = 0
        self._display_stack.setCurrentIndex(_ANIMATION)
        self._animator.prepare_animation(self._last_prep_data)
        self._animator.start()

    def _on_analysis_error(self, error_msg: str) -> None:
        self._progress_bar.setRange(0, 100)
        self._progress_bar.hide()
        self.set_running(False)
        self._status_lbl.setText(f"Error: {error_msg}")
        self._run_details_lbl.setVisible(True)
        self._run_details_lbl.setText(f"Analysis Failed:\n{error_msg}")
        self._display_stack.setCurrentIndex(_PLACEHOLDER)
