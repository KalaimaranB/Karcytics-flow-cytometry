"""Population Analysis Viewer — UI component for visualizing and configuring dimensionality reduction (UMAP)."""

from __future__ import annotations

import logging
from typing import Any

import scipy.spatial
from karcytics_sdk.plugin.components import (
    BioComboBox,
    BioHelpButton,
    BioLineEdit,
    BioListWidget,
    BioSpinBox,
    PrimaryButton,
    SecondaryButton,
)
from karcytics_sdk.plugin.theme_fallback import Colors
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIntValidator
from PyQt6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidgetItem,
    QProgressBar,
    QScrollArea,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from karcytics_plugins.flow_cytometry.analysis.animation.animation_prep import (
    UmapAnimationDataPrep,
)
from karcytics_plugins.flow_cytometry.analysis.services.umap_service import (
    UmapParams,
    UmapService,
)
from karcytics_plugins.flow_cytometry.analysis.state import FlowState

from .checkbox_style import checkbox_qss
from .cluster_results_panel import ClusterResultsPanel
from .umap_animator_widget import UmapAnimatorWidget

logger = logging.getLogger(__name__)


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
        self._state = state
        self._umap_service = umap_service
        self._gate_coordinator = gate_coordinator
        self._total_events = 0
        self._is_animation_playing = False
        self._is_analysis_running = False
        self._params_read_only: bool = False

        self._last_results: dict[str, Any] | None = None
        self._kdtree: scipy.spatial.KDTree | None = None

        self._colorbar = None
        self._scatter = None

        self._setup_ui()
        self._apply_theme_styles()
        self.refresh_samples()

    def _section_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"color: {Colors.FG_SECONDARY}; font-weight: bold; font-size: 11px; text-transform: uppercase;"
        )
        return lbl

    def _setup_ui(self) -> None:  # noqa: PLR0915
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── Left Control Panel (Scrollable) ──
        left_sidebar = QWidget()
        left_sidebar.setObjectName("left_sidebar")
        left_sidebar.setFixedWidth(320)
        left_layout = QVBoxLayout(left_sidebar)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setStyleSheet("background: transparent; border: none;")

        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(16, 16, 16, 16)
        scroll_layout.setSpacing(16)

        # 1. Target Data
        scroll_layout.addWidget(self._section_label("Target Data"))

        self._algo_combo = BioComboBox()
        self._algo_combo.addItem("UMAP", "umap")
        algo_layout = QHBoxLayout()
        algo_layout.addWidget(QLabel("Algorithm:"))
        algo_help = BioHelpButton()
        algo_help.setHelpText(
            "UMAP (Uniform Manifold Approximation and Projection) is a dimension reduction technique that can be used for visualisation similarly to t-SNE, but also for general non-linear dimension reduction.",
            "Algorithm",
        )
        algo_layout.addWidget(algo_help)
        algo_layout.addStretch()
        scroll_layout.addLayout(algo_layout)
        scroll_layout.addWidget(self._algo_combo)

        self._sample_combo = BioComboBox()
        self._sample_combo.setObjectName("UmapSampleCombo")
        self._sample_combo.currentIndexChanged.connect(self._on_sample_combo_changed)
        sample_layout = QHBoxLayout()
        sample_layout.addWidget(QLabel("Sample:"))
        sample_help = BioHelpButton()
        sample_help.setHelpText(
            "Select the flow cytometry sample to run the analysis on. UMAP will reduce the dimensionality of the single-cell events within this sample.",
            "Sample",
        )
        sample_layout.addWidget(sample_help)
        sample_layout.addStretch()
        scroll_layout.addLayout(sample_layout)
        scroll_layout.addWidget(self._sample_combo)

        self._gate_combo = BioComboBox()
        self._gate_combo.setObjectName("UmapGateCombo")
        self._gate_combo.currentIndexChanged.connect(self._on_gate_combo_changed)
        gate_layout = QHBoxLayout()
        gate_layout.addWidget(QLabel("Population (Gate):"))
        gate_help = BioHelpButton()
        gate_help.setHelpText(
            "Select a specific gated population to run the analysis on. It is highly recommended to run UMAP on pre-gated populations (e.g. Live, Singlets) to exclude debris and dead cells which can negatively distort the projection.",
            "Population (Gate)",
        )
        gate_layout.addWidget(gate_help)
        gate_layout.addStretch()
        scroll_layout.addLayout(gate_layout)
        scroll_layout.addWidget(self._gate_combo)

        # Channels Selection
        channel_layout = QHBoxLayout()
        channels_lbl = QLabel("Select Channels:")
        channels_lbl.setStyleSheet(f"color: {Colors.FG_PRIMARY}; font-size: 11px;")
        channel_layout.addWidget(channels_lbl)
        channels_help = BioHelpButton()
        channels_help.setHelpText(
            "Select the fluorescence parameters to include in the dimensionality reduction. You should UNCHECK channels that were already used for gating upstream (like Viability/Live-Dead dyes or Scatter parameters) as they do not provide useful variance for sub-population clustering.",
            "Channels",
        )
        channel_layout.addWidget(channels_help)
        channel_layout.addStretch()
        scroll_layout.addLayout(channel_layout)

        self._channel_list = BioListWidget()
        self._channel_list.setObjectName("UmapChannelList")
        self._channel_list.setMaximumHeight(150)
        scroll_layout.addWidget(self._channel_list)

        scroll_layout.addSpacing(10)

        # 2. Configuration
        scroll_layout.addWidget(self._section_label("Configuration"))

        # Run Name
        name_lbl = QLabel("Run Name:")
        name_lbl.setStyleSheet(f"color: {Colors.FG_PRIMARY}; font-size: 11px;")
        scroll_layout.addWidget(name_lbl)
        self._run_name_input = BioLineEdit("")
        self._run_name_input.setObjectName("UmapRunNameInput")
        self._run_name_input.setPlaceholderText("e.g., Global Overview")
        scroll_layout.addWidget(self._run_name_input)

        # n_neighbors
        n_neigh_lbl_layout = QHBoxLayout()
        n_neigh_title = QLabel("Neighbors:")
        n_neigh_title.setStyleSheet(f"color: {Colors.FG_PRIMARY}; font-size: 11px;")
        n_neigh_title.setToolTip("Number of nearest neighbors used in manifold approximation.")

        n_neigh_help = BioHelpButton()
        n_neigh_help.setHelpText(
            "Higher values (e.g., 30-50) preserve more global structure. Lower values (e.g., 5-15) focus on finer local clusters.",
            "Neighbors",
        )

        self._n_neigh_val_lbl = QLabel("15")
        self._n_neigh_val_lbl.setStyleSheet(
            f"color: {Colors.DNA_PRIMARY}; font-weight: bold; font-size: 11px;"
        )
        n_neigh_lbl_layout.addWidget(n_neigh_title)
        n_neigh_lbl_layout.addWidget(n_neigh_help)
        n_neigh_lbl_layout.addStretch()
        n_neigh_lbl_layout.addWidget(self._n_neigh_val_lbl)

        self._n_neigh_slider = QSlider(Qt.Orientation.Horizontal)
        self._n_neigh_slider.setObjectName("UmapNeighborsSlider")
        self._n_neigh_slider.setRange(5, 50)
        self._n_neigh_slider.setValue(15)
        self._n_neigh_slider.setToolTip(
            "Higher = more global structure. Lower = finer local clusters."
        )
        self._n_neigh_slider.valueChanged.connect(
            lambda val: self._n_neigh_val_lbl.setText(str(val))
        )

        # Groups the title/value row + slider under one objectName so a
        # tutorial step can spotlight the whole parameter — label, live
        # value, and control together — as a single region, rather than
        # just the bare slider (which gave no visual link to its own label
        # and could scroll out of view independently of it).
        n_neigh_group = QWidget()
        n_neigh_group.setObjectName("UmapNeighborsGroup")
        n_neigh_group_layout = QVBoxLayout(n_neigh_group)
        n_neigh_group_layout.setContentsMargins(0, 0, 0, 0)
        n_neigh_group_layout.addLayout(n_neigh_lbl_layout)
        n_neigh_group_layout.addWidget(self._n_neigh_slider)
        scroll_layout.addWidget(n_neigh_group)

        # min_dist
        min_dist_lbl_layout = QHBoxLayout()
        min_dist_title = QLabel("Min Distance:")
        min_dist_title.setStyleSheet(f"color: {Colors.FG_PRIMARY}; font-size: 11px;")
        min_dist_title.setToolTip(
            "Minimum distance apart that points are allowed to be in the low dimensional representation."
        )

        min_dist_help = BioHelpButton()
        min_dist_help.setHelpText(
            "Controls how tightly UMAP packs points together. \n\nLower values (0.0 - 0.1) pack points densely, useful for identifying highly similar cell subtypes or resolving rare populations. \n\nHigher values (0.3 - 0.5) spread points out, preserving broader topological relationships across major cell lineages (e.g. T-cells vs B-cells).",
            "Minimum Distance",
        )

        self._min_dist_val_lbl = QLabel("0.10")
        self._min_dist_val_lbl.setStyleSheet(
            f"color: {Colors.DNA_PRIMARY}; font-weight: bold; font-size: 11px;"
        )
        min_dist_lbl_layout.addWidget(min_dist_title)
        min_dist_lbl_layout.addWidget(min_dist_help)
        min_dist_lbl_layout.addStretch()
        min_dist_lbl_layout.addWidget(self._min_dist_val_lbl)

        self._min_dist_slider = QSlider(Qt.Orientation.Horizontal)
        self._min_dist_slider.setObjectName("UmapMinDistSlider")
        self._min_dist_slider.setRange(1, 50)  # Represents 0.01 to 0.50
        self._min_dist_slider.setValue(10)
        self._min_dist_slider.setToolTip("Lower = tighter packed islands.")
        self._min_dist_slider.valueChanged.connect(
            lambda val: self._min_dist_val_lbl.setText(f"{val / 100:.2f}")
        )

        # See the Neighbors group above for why label + slider are grouped.
        min_dist_group = QWidget()
        min_dist_group.setObjectName("UmapMinDistGroup")
        min_dist_group_layout = QVBoxLayout(min_dist_group)
        min_dist_group_layout.setContentsMargins(0, 0, 0, 0)
        min_dist_group_layout.addLayout(min_dist_lbl_layout)
        min_dist_group_layout.addWidget(self._min_dist_slider)
        scroll_layout.addWidget(min_dist_group)

        # n_events
        n_events_lbl_layout = QHBoxLayout()
        self._n_events_title_lbl = QLabel("Subsample Events: 10% (0 events)")
        self._n_events_title_lbl.setStyleSheet(f"color: {Colors.FG_PRIMARY}; font-size: 11px;")
        self._n_events_title_lbl.setToolTip(
            "Randomly downsample the input events before running analysis."
        )

        n_events_help = BioHelpButton()
        n_events_help.setHelpText(
            "UMAP scales non-linearly. Running it on >1,000,000 events can be very slow. Subsampling 10-20% is typically enough to preserve cluster relationships while running much faster.",
            "Subsample Events",
        )

        n_events_lbl_layout.addWidget(self._n_events_title_lbl)
        n_events_lbl_layout.addWidget(n_events_help)
        n_events_lbl_layout.addStretch()

        self._n_events_slider = QSlider(Qt.Orientation.Horizontal)
        self._n_events_slider.setObjectName("UmapSubsampleSlider")
        self._n_events_slider.setRange(1, 100)
        self._n_events_slider.setValue(10)
        self._n_events_slider.setToolTip("Percentage of events to subsample. Max is all events.")
        self._n_events_slider.valueChanged.connect(self._on_subsample_changed)

        # See the Neighbors group above for why label + slider are grouped.
        n_events_group = QWidget()
        n_events_group.setObjectName("UmapSubsampleGroup")
        n_events_group_layout = QVBoxLayout(n_events_group)
        n_events_group_layout.setContentsMargins(0, 0, 0, 0)
        n_events_group_layout.addLayout(n_events_lbl_layout)
        n_events_group_layout.addWidget(self._n_events_slider)
        scroll_layout.addWidget(n_events_group)

        # Metric
        metric_lbl_layout = QHBoxLayout()
        metric_lbl = QLabel("Distance Metric:")
        metric_lbl.setStyleSheet(f"color: {Colors.FG_PRIMARY}; font-size: 11px;")

        metric_help = BioHelpButton()
        metric_help.setHelpText(
            "The mathematical method used to measure distance between cells in high-dimensional space.\n\n• Euclidean: Straight-line distance (default, good for general use)\n• Cosine: Measures angle instead of magnitude (good when absolute fluorescence intensity varies due to staining artifacts)\n• Manhattan: Grid-like distance (more robust to outliers)",
            "Distance Metric",
        )

        metric_lbl_layout.addWidget(metric_lbl)
        metric_lbl_layout.addWidget(metric_help)
        metric_lbl_layout.addStretch()

        self._metric_combo = BioComboBox()
        self._metric_combo.setObjectName("UmapMetricCombo")
        self._metric_combo.addItems(["euclidean", "cosine", "manhattan"])

        # See the Neighbors group above for why label + control are grouped.
        metric_group = QWidget()
        metric_group.setObjectName("UmapMetricGroup")
        metric_group_layout = QVBoxLayout(metric_group)
        metric_group_layout.setContentsMargins(0, 0, 0, 0)
        metric_group_layout.addLayout(metric_lbl_layout)
        metric_group_layout.addWidget(self._metric_combo)
        scroll_layout.addWidget(metric_group)

        # Random Seed
        seed_lbl_layout = QHBoxLayout()
        seed_lbl = QLabel("Random Seed:")
        seed_lbl.setStyleSheet(f"color: {Colors.FG_PRIMARY}; font-size: 11px;")

        seed_help = BioHelpButton()
        seed_help.setHelpText(
            "Controls the random number generator used by UMAP. Keeping this constant ensures the same data always produces the exact same layout. Change it to see different valid embedding variations.",
            "Random Seed",
        )

        seed_lbl_layout.addWidget(seed_lbl)
        seed_lbl_layout.addWidget(seed_help)
        seed_lbl_layout.addStretch()

        self._seed_input = BioLineEdit("42")
        self._seed_input.setObjectName("UmapSeedInput")
        self._seed_input.setValidator(QIntValidator(0, 999999))

        # See the Neighbors group above for why label + control are grouped.
        seed_group = QWidget()
        seed_group.setObjectName("UmapSeedGroup")
        seed_group_layout = QVBoxLayout(seed_group)
        seed_group_layout.setContentsMargins(0, 0, 0, 0)
        seed_group_layout.addLayout(seed_lbl_layout)
        seed_group_layout.addWidget(self._seed_input)
        scroll_layout.addWidget(seed_group)

        scroll_layout.addSpacing(10)

        # 3. Auto-Clustering
        scroll_layout.addWidget(self._section_label("Clustering"))

        clustering_lbl_layout = QHBoxLayout()
        self._run_hdbscan_cb = QCheckBox("Run HDBSCAN Auto-Clustering")
        self._run_hdbscan_cb.setObjectName("UmapHdbscanCheckbox")
        self._run_hdbscan_cb.setStyleSheet(checkbox_qss())
        self._run_hdbscan_cb.setToolTip("Perform automatic density-based clustering.")

        cluster_help = BioHelpButton()
        cluster_help.setHelpText(
            "Automatically clusters the high-dimensional biological data (not the 2D plot), producing statistically robust populations that you can use as downstream gates. Does not rely on the UMAP projection.",
            "HDBSCAN Auto-Clustering",
        )

        clustering_lbl_layout.addWidget(self._run_hdbscan_cb)
        clustering_lbl_layout.addWidget(cluster_help)
        clustering_lbl_layout.addStretch()

        # See the Neighbors group above for why the checkbox + help are
        # wrapped — lets a tutorial step spotlight this whole row as one
        # region instead of just the bare checkbox.
        hdbscan_group = QWidget()
        hdbscan_group.setObjectName("UmapHdbscanGroup")
        hdbscan_group_layout = QVBoxLayout(hdbscan_group)
        hdbscan_group_layout.setContentsMargins(0, 0, 0, 0)
        hdbscan_group_layout.addLayout(clustering_lbl_layout)
        scroll_layout.addWidget(hdbscan_group)

        min_cluster_layout = QHBoxLayout()
        min_cluster_layout.setContentsMargins(0, 0, 0, 0)
        self._min_cluster_size_box = BioSpinBox()
        self._min_cluster_size_box.setObjectName("UmapMinClusterSizeBox")
        self._min_cluster_size_box.setRange(2, 500)
        self._min_cluster_size_box.setValue(100)
        self._min_cluster_size_box.setPrefix("Min Cluster Size: ")

        self._min_cluster_help = BioHelpButton()
        self._min_cluster_help.setHelpText(
            "The minimum number of cells required to form a cluster. Larger values will merge smaller groups into bigger populations or label them as noise. Smaller values will detect rarer populations but may over-segment.",
            "Minimum Cluster Size",
        )

        min_cluster_layout.addWidget(self._min_cluster_size_box)
        min_cluster_layout.addWidget(self._min_cluster_help)
        min_cluster_layout.addStretch()

        self._min_cluster_container = QWidget()
        # Also serves as this parameter's spotlight target — the spin box's
        # own prefix ("Min Cluster Size: 100") already merges label + value
        # into one control, so this container just adds the help icon.
        self._min_cluster_container.setObjectName("UmapMinClusterGroup")
        self._min_cluster_container.setLayout(min_cluster_layout)
        self._min_cluster_container.setVisible(False)
        scroll_layout.addWidget(self._min_cluster_container)

        self._run_hdbscan_cb.toggled.connect(self._on_hdbscan_toggled)

        scroll_layout.addSpacing(20)

        # Run Buttons
        self._run_btn = PrimaryButton("🧬 Run Analysis")
        self._run_btn.setObjectName("RunAnalysisButton")
        self._run_btn.clicked.connect(self.start_analysis)
        scroll_layout.addWidget(self._run_btn)

        self._cancel_btn = SecondaryButton("⏹ Cancel")
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.clicked.connect(self._umap_service.cancel)
        scroll_layout.addWidget(self._cancel_btn)

        scroll_layout.addSpacing(20)

        # 4. History
        scroll_layout.addWidget(self._section_label("History"))

        self._history_combo = BioComboBox()
        self._history_combo.addItem("[ New Run ]", None)
        self._history_combo.currentIndexChanged.connect(self._on_history_changed)
        scroll_layout.addWidget(self._history_combo)

        self._run_details_lbl = QLabel("Select a past run to view details.")
        self._run_details_lbl.setWordWrap(True)
        self._run_details_lbl.setStyleSheet(f"color: {Colors.FG_SECONDARY}; font-size: 11px;")
        scroll_layout.addWidget(self._run_details_lbl)

        self._delete_run_btn = SecondaryButton("🗑️ Delete Run")
        self._delete_run_btn.setEnabled(False)
        self._delete_run_btn.clicked.connect(self._on_delete_run_clicked)
        scroll_layout.addWidget(self._delete_run_btn)

        scroll_layout.addStretch()

        scroll_area.setWidget(scroll_content)
        left_layout.addWidget(scroll_area)

        main_layout.addWidget(left_sidebar)

        # ── Right Workspace Panel ──
        right_panel = QWidget()
        right_panel.setObjectName("right_panel")
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(16, 16, 16, 16)
        right_layout.setSpacing(10)

        # Toolbar for right panel
        toolbar_layout = QHBoxLayout()
        self._status_lbl = QLabel("Ready")
        self._status_lbl.setStyleSheet(
            f"color: {Colors.FG_SECONDARY}; font-size: 12px; font-weight: bold;"
        )
        toolbar_layout.addWidget(self._status_lbl)
        toolbar_layout.addStretch()

        self._replay_anim_btn = SecondaryButton("▶ Replay Animation")
        self._replay_anim_btn.setEnabled(False)
        self._replay_anim_btn.clicked.connect(self._play_animation)
        toolbar_layout.addWidget(self._replay_anim_btn)

        right_layout.addLayout(toolbar_layout)

        # Progress bar (only visible during computation)
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setTextVisible(True)
        self._progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: {Colors.BG_DARKEST};
                color: {Colors.FG_PRIMARY};
                border: 1px solid {Colors.BORDER};
                border-radius: 4px;
                text-align: center;
            }}
            QProgressBar::chunk {{
                background-color: {Colors.ACCENT_PRIMARY};
                border-radius: 4px;
            }}
        """)
        self._progress_bar.hide()
        right_layout.addWidget(self._progress_bar)

        # Stacked display
        self._display_stack = QStackedWidget()

        # 0: Placeholder
        self._placeholder_panel = QWidget()
        self._placeholder_panel.setObjectName("placeholder_panel")
        placeholder_layout = QVBoxLayout(self._placeholder_panel)
        placeholder_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder_lbl = QLabel("Configure a run in the left panel to begin.")
        self._placeholder_lbl.setObjectName("placeholder_lbl")
        placeholder_layout.addWidget(self._placeholder_lbl)

        # 1: Results Panel (Instantiated after run)
        self._results_panel = QWidget()

        # 2: Animator
        self._animator = UmapAnimatorWidget()
        self._animator.animation_finished.connect(self._on_animation_finished)

        self._display_stack.addWidget(self._placeholder_panel)
        self._display_stack.addWidget(self._results_panel)
        self._display_stack.addWidget(self._animator)

        right_layout.addWidget(self._display_stack, stretch=1)

        main_layout.addWidget(right_panel, stretch=1)

    def _apply_theme_styles(self) -> None:  # noqa: PLR0912
        self.setStyleSheet(f"background-color: {Colors.BG_DARKEST};")

        left_sidebar = self.findChild(QWidget, "left_sidebar")
        if left_sidebar:
            left_sidebar.setStyleSheet(
                f"background-color: {Colors.BG_DARKEST}; border-right: 1px solid {Colors.BORDER};"
            )

        right_panel = self.findChild(QWidget, "right_panel")
        if right_panel:
            right_panel.setStyleSheet(f"background-color: {Colors.BG_DARK};")

        self._display_stack.setObjectName("display_stack")
        self._display_stack.setStyleSheet(f"""
            #display_stack {{ background-color: {Colors.BG_DARKEST}; border-radius: 8px; }}
            #placeholder_panel {{ background-color: {Colors.BG_DARKEST}; border-radius: 8px; }}
        """)

        # Re-theme all dropdowns and inputs
        for combo in (
            getattr(self, "_algo_combo", None),
            getattr(self, "_sample_combo", None),
            getattr(self, "_gate_combo", None),
            getattr(self, "_metric_combo", None),
            getattr(self, "_history_combo", None),
            getattr(self, "_n_events_combo", None),
        ):
            if combo and hasattr(combo, "_apply_theme_styles"):
                combo._apply_theme_styles()

        from PyQt6.QtGui import QColor

        fg_color = QColor(Colors.FG_PRIMARY)

        if hasattr(self, "_channel_list"):
            self._channel_list.setStyleSheet(
                f"QListWidget {{ background: {Colors.BG_DARKEST}; border: 1px solid {Colors.BORDER};"
                f" border-radius: 4px; color: {Colors.FG_PRIMARY}; }}"
                f"QListWidget::item {{ color: {Colors.FG_PRIMARY}; padding: 2px 4px; }}"
                f"QListWidget::item:hover {{ background: {Colors.BG_DARK}; color: {Colors.FG_PRIMARY}; }}"
                f"QListWidget::item:selected {{ background: {Colors.BG_MEDIUM}; color: {Colors.FG_PRIMARY}; }}"
            )
            for i in range(self._channel_list.count()):
                item = self._channel_list.item(i)
                if item:
                    item.setForeground(fg_color)

        for line_edit in (
            getattr(self, "_run_name_input", None),
            getattr(self, "_run_name_edit", None),
        ):
            if line_edit:
                if hasattr(line_edit, "_apply_theme_styles"):
                    line_edit._apply_theme_styles()
                else:
                    line_edit.setStyleSheet(
                        f"QLineEdit {{ background: {Colors.BG_MEDIUM}; color: {Colors.FG_PRIMARY};"
                        f" border: 1px solid {Colors.BORDER}; border-radius: 4px; padding: 4px 8px; }}"
                    )

        if hasattr(self, "_seed_spin"):
            if hasattr(self._seed_spin, "_apply_theme_styles"):
                self._seed_spin._apply_theme_styles()
            else:
                self._seed_spin.setStyleSheet(
                    f"QSpinBox {{ background: {Colors.BG_MEDIUM}; color: {Colors.FG_PRIMARY};"
                    f" border: 1px solid {Colors.BORDER}; border-radius: 4px; padding: 4px 8px; }}"
                )

        if hasattr(self, "_placeholder_lbl"):
            self._placeholder_lbl.setStyleSheet(f"color: {Colors.FG_SECONDARY}; font-size: 14px;")

        self._status_lbl.setStyleSheet(
            f"color: {Colors.FG_SECONDARY}; font-size: 12px; font-weight: bold;"
        )
        self._run_details_lbl.setStyleSheet(f"color: {Colors.FG_SECONDARY}; font-size: 11px;")

        self._n_neigh_val_lbl.setStyleSheet(
            f"color: {Colors.DNA_PRIMARY}; font-weight: bold; font-size: 11px;"
        )
        self._min_dist_val_lbl.setStyleSheet(
            f"color: {Colors.DNA_PRIMARY}; font-weight: bold; font-size: 11px;"
        )
        if hasattr(self, "_n_events_title_lbl"):
            self._n_events_title_lbl.setStyleSheet(f"color: {Colors.FG_PRIMARY}; font-size: 11px;")

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

        self._run_hdbscan_cb.setStyleSheet(checkbox_qss())

        for lbl in self.findChildren(QLabel):
            text = lbl.text()
            if text in {"Target Data", "Configuration", "Run History"}:
                lbl.setStyleSheet(
                    f"color: {Colors.FG_SECONDARY}; font-weight: bold; font-size: 11px; text-transform: uppercase;"
                )
            elif (
                text.endswith(":")
                or text.startswith("Subsample Events")
                or text
                in [
                    "Select a past run to view details.",
                    "Ready",
                    "Configure a run in the left panel to begin.",
                ]
            ):
                lbl.setStyleSheet(f"color: {Colors.FG_PRIMARY}; font-size: 11px;")

        if hasattr(self._animator, "_apply_theme_styles"):
            self._animator._apply_theme_styles()

        if hasattr(self, "_cluster_panel") and self._cluster_panel:
            if hasattr(self._cluster_panel, "_apply_theme_styles"):
                self._cluster_panel._apply_theme_styles()

    def _on_hdbscan_toggled(self, checked: bool) -> None:
        # In read-only (history) mode, silently revert any user click on the
        # checkbox. The checkbox is kept *enabled* so that macOS's native Aqua
        # style actually renders the checked indicator — disabled checkboxes on
        # macOS render as blank regardless of their logical check state.
        if self._params_read_only:
            self._run_hdbscan_cb.blockSignals(True)
            self._run_hdbscan_cb.setChecked(not checked)  # revert
            self._run_hdbscan_cb.blockSignals(False)
            return
        self._min_cluster_container.setVisible(checked)

    def _set_parameters_read_only(self, read_only: bool) -> None:
        self._params_read_only = read_only
        self._algo_combo.setEnabled(not read_only)
        self._run_name_input.setReadOnly(read_only)
        self._n_neigh_slider.setEnabled(not read_only)
        self._min_dist_slider.setEnabled(not read_only)
        self._n_events_slider.setEnabled(not read_only)
        self._metric_combo.setEnabled(not read_only)
        self._seed_input.setReadOnly(read_only)
        # NOTE: _run_hdbscan_cb is intentionally NOT disabled here.
        # On macOS, QCheckBox.setEnabled(False) causes the native Aqua style to
        # render the indicator as a blank box regardless of the check state.
        # Read-only enforcement for the checkbox is handled in _on_hdbscan_toggled.

        self._min_cluster_size_box.setEnabled(not read_only)
        self._min_cluster_container.setVisible(self._run_hdbscan_cb.isChecked())

        for i in range(self._channel_list.count()):
            item = self._channel_list.item(i)
            if item:
                if read_only:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
                else:
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)

        self._sample_combo.setEnabled(not read_only)
        self._gate_combo.setEnabled(not read_only)

        self._run_btn.setEnabled(not read_only)
        self._run_btn.setVisible(not read_only)
        self._cancel_btn.setVisible(not read_only)

    def set_running(self, running: bool) -> None:
        """Toggle button enabled states during running tasks."""
        self._run_btn.setEnabled(not running)
        self._cancel_btn.setEnabled(running)
        self._sample_combo.setEnabled(not running)
        self._gate_combo.setEnabled(not running)
        self._history_combo.setEnabled(not running)

        if running:
            self._delete_run_btn.setEnabled(False)
        else:
            has_run = self._history_combo.itemData(self._history_combo.currentIndex()) is not None
            self._delete_run_btn.setEnabled(has_run)

    def refresh_samples(self) -> None:
        """Populate the sample combobox with active experiment samples."""
        prev_sample = self._sample_combo.currentData()

        self._sample_combo.blockSignals(True)
        self._sample_combo.clear()

        for sample_id, sample in self._state.data.experiment.samples.items():
            self._sample_combo.addItem(sample.display_name, sample_id)

        target_sample = prev_sample or self._state.view.current_sample_id
        if target_sample:
            idx = self._sample_combo.findData(target_sample)
            if idx >= 0:
                self._sample_combo.setCurrentIndex(idx)

        self._sample_combo.blockSignals(False)

        self._refresh_gates()
        self.refresh_history()

        current_id = self._sample_combo.currentData()
        if (
            current_id
            and current_id != prev_sample
            or current_id
            and self._channel_list.count() == 0
        ):
            self._on_sample_changed_internal(current_id)

    def _refresh_gates(self) -> None:
        """Populate the gate combo with all named nodes in the selected sample's gate tree."""
        prev_gate = self._gate_combo.currentData()

        self._gate_combo.blockSignals(True)
        self._gate_combo.clear()
        self._gate_combo.addItem("⬡  All Events (no gate)", None)

        sample_id = self._sample_combo.currentData()
        if not sample_id:
            self._gate_combo.blockSignals(False)
            return

        sample = self._state.data.experiment.samples.get(sample_id)
        if not sample or sample.gate_tree is None:
            self._gate_combo.blockSignals(False)
            return

        def _add_nodes(node, depth: int = 0) -> None:
            if not node.is_root:
                indent = "  " * depth
                icon = "⊘ " if node.negated else "◆ "
                label = f"{indent}{icon}{node.name}"
                self._gate_combo.addItem(label, node.node_id)
            for child in node.children:
                # Unwired/under-wired logic nodes have no valid population yet —
                # not selectable, same as the gating hierarchy view.
                if getattr(child, "is_incomplete", False):
                    continue
                _add_nodes(child, depth + (0 if node.is_root else 1))

        _add_nodes(sample.gate_tree)

        if prev_gate is not None:
            idx = self._gate_combo.findData(prev_gate)
            if idx >= 0:
                self._gate_combo.setCurrentIndex(idx)

        self._gate_combo.blockSignals(False)

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
            elif type(obj).__name__ == "DataFrame":
                return obj.to_dict(orient="split")
            return obj

        if self._state and hasattr(self._state.data, "umap_results"):
            _purify(self._state.data.umap_results)

    def refresh_history(self) -> None:
        """Populate the history combo with past runs for current sample and gate."""
        self._purify_state()

        prev_run_idx = self._history_combo.currentData()

        self._history_combo.blockSignals(True)
        self._history_combo.clear()
        self._history_combo.addItem("[ New Run ]", None)

        sample_id = self._sample_combo.currentData()
        if not sample_id:
            self._history_combo.blockSignals(False)
            return

        node_id = self._gate_combo.currentData()
        key = f"{sample_id}::{node_id or 'root'}"
        runs = self._state.data.umap_results.get(key, [])

        idx_to_select = 0
        for i, run in enumerate(runs, 1):
            name = run.get("name")
            if name:
                label = f"{i}. {name}"
            else:
                n = run.get("n_neighbors", 15)
                md = run.get("min_dist", 0.1)
                label = f"Run {i} (n={n}, md={md})"
            self._history_combo.addItem(label, i - 1)
            if prev_run_idx is not None and prev_run_idx == (i - 1):
                idx_to_select = i

        self._history_combo.setCurrentIndex(idx_to_select)
        self._history_combo.blockSignals(False)
        self._update_delete_button_state()

    def _update_delete_button_state(self) -> None:
        has_run = self._history_combo.itemData(self._history_combo.currentIndex()) is not None
        self._delete_run_btn.setEnabled(has_run)

    def _on_sample_combo_changed(self, index: int) -> None:
        self._refresh_gates()
        self.refresh_history()
        sample_id = self._sample_combo.currentData()
        if sample_id:
            self._on_sample_changed_internal(sample_id)
            gate_id = self._gate_combo.currentData()
            self._on_gate_changed_internal(sample_id, gate_id)

    def _on_gate_combo_changed(self, index: int) -> None:
        self.refresh_history()
        sample_id = self._sample_combo.currentData()
        if sample_id:
            gate_id = self._gate_combo.currentData()
            self._on_gate_changed_internal(sample_id, gate_id)

    def _on_subsample_changed(self, value: int) -> None:
        num_events = int(self._total_events * (value / 100.0))
        self._n_events_title_lbl.setText(f"Subsample Events: {value}% ({num_events:,} events)")

    def _on_sample_changed_internal(self, sample_id: str) -> None:
        self._channel_list.clear()
        sample = self._state.data.experiment.samples.get(sample_id)
        if not sample or sample.fcs_data is None:
            return

        from ...analysis.fcs_io import (
            get_channel_marker_label,
            get_fluorescence_channels,
        )

        fluo_channels = get_fluorescence_channels(sample.fcs_data)

        for ch in fluo_channels:
            label = get_channel_marker_label(sample.fcs_data, ch)
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, ch)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            self._channel_list.addItem(item)

    def _on_gate_changed_internal(self, sample_id: str, gate_id: object) -> None:
        sample = self._state.data.experiment.samples.get(sample_id)
        if not sample or sample.fcs_data is None:
            self._total_events = 0
        elif gate_id and sample.gate_tree:
            gate_node = sample.gate_tree.find_node_by_id(gate_id)  # type: ignore
            if gate_node:
                df = gate_node.apply_hierarchy(sample.fcs_data.events)
                self._total_events = len(df)
            else:
                self._total_events = len(sample.fcs_data.events)  # type: ignore
        else:
            self._total_events = len(sample.fcs_data.events)  # type: ignore

        self._on_subsample_changed(self._n_events_slider.value())

    def _restore_fields_from_run(self, run_data: dict) -> None:
        """Sync all parameter widgets to values stored in a completed run dict.

        This is deliberately separate from panel-rebuilding so that callers
        (e.g. _check_transition_to_results) can restore UI state without
        triggering a redundant ClusterResultsPanel rebuild.
        """
        self._last_results = run_data

        # Freeze the UI first — on macOS/PyQt6, calling setEnabled(False) on a
        # QCheckBox AFTER setChecked(True) causes the native style to repaint
        # the indicator as visually unchecked even though isChecked() is True.
        # By disabling first and then setting values on the already-disabled
        # widgets we avoid that repaint artifact entirely.
        self._set_parameters_read_only(True)
        self._run_details_lbl.setVisible(False)

        if "name" in run_data and run_data["name"]:
            self._run_name_input.setText(run_data["name"])

        if "n_neighbors" in run_data:
            self._n_neigh_slider.setValue(run_data["n_neighbors"])

        if "min_dist" in run_data:
            self._min_dist_slider.setValue(int(run_data["min_dist"] * 100))

        if "percentage" in run_data:
            self._n_events_slider.setValue(int(run_data["percentage"]))

        if "metric" in run_data:
            idx = self._metric_combo.findText(run_data["metric"])
            if idx >= 0:
                self._metric_combo.setCurrentIndex(idx)

        if "random_seed" in run_data:
            self._seed_input.setText(str(run_data["random_seed"]))

        # For backwards compatibility: runs saved before "run_hdbscan" was
        # explicitly stored are treated as having run HDBSCAN when clusters exist.
        has_clusters = "clusters" in run_data
        run_hdbscan = bool(run_data.get("run_hdbscan", has_clusters))

        # Block the toggled signal so _on_hdbscan_toggled does not interfere
        # while the widget is already disabled (read-only mode).
        self._run_hdbscan_cb.blockSignals(True)
        self._run_hdbscan_cb.setChecked(run_hdbscan)
        self._run_hdbscan_cb.blockSignals(False)

        if "min_cluster_size" in run_data:
            self._min_cluster_size_box.setValue(int(run_data["min_cluster_size"]))

        used_channels = run_data.get("channels", [])
        if used_channels:
            for i in range(self._channel_list.count()):
                item = self._channel_list.item(i)
                if item:
                    ch = item.data(Qt.ItemDataRole.UserRole)
                    if ch in used_channels:
                        item.setCheckState(Qt.CheckState.Checked)
                    else:
                        item.setCheckState(Qt.CheckState.Unchecked)

    def _on_history_changed(self, index: int) -> None:
        self._update_delete_button_state()
        run_idx = self._history_combo.itemData(index)

        if run_idx is None:
            self._set_parameters_read_only(False)
            self._run_name_input.setText("")
            self._display_stack.setCurrentIndex(0)
            self._last_results = None
            self._animator.stop()
            self._replay_anim_btn.setEnabled(False)
            self._run_details_lbl.setText("Configure a new run above to begin.")
            self._run_details_lbl.setVisible(True)
            return

        sample_id = self._sample_combo.currentData()
        gate_id = self._gate_combo.currentData()
        key = f"{sample_id}::{gate_id or 'root'}"
        runs = self._state.data.umap_results.get(key, [])
        if not (0 <= run_idx < len(runs)):
            return

        run_data = runs[run_idx]
        self._restore_fields_from_run(run_data)

        self._display_stack.removeWidget(self._results_panel)
        self._results_panel.deleteLater()

        self._results_panel = ClusterResultsPanel(
            self._last_results,  # type: ignore
            state=self._state,
            gate_coordinator=self._gate_coordinator,
        )
        self._results_panel.results_modified.connect(self._on_results_modified)
        self._display_stack.insertWidget(1, self._results_panel)

        self._animator.stop()
        self._display_stack.setCurrentIndex(1)
        self._replay_anim_btn.setEnabled(True)

    def _on_results_modified(self) -> None:
        try:
            # Publish UMAP_COMPLETED so the undo history and dirty flag are updated
            from karcytics_sdk.plugin import CentralEventBus

            from ...analysis import events

            CentralEventBus.publish(events.UMAP_COMPLETED, {})
        except Exception:
            pass

    def _on_delete_run_clicked(self) -> None:
        idx = self._history_combo.currentIndex()
        if idx <= 0:
            return

        run_idx = self._history_combo.currentData()
        if run_idx is not None:
            sample_id = self._sample_combo.currentData()
            gate_id = self._gate_combo.currentData()
            key = f"{sample_id}::{gate_id or 'root'}"

            if key in self._state.data.umap_results:
                runs = self._state.data.umap_results[key]
                if 0 <= run_idx < len(runs):
                    runs.pop(run_idx)

            # Publish UMAP_COMPLETED so the undo history and dirty flag are updated
            from karcytics_sdk.plugin import CentralEventBus

            from ...analysis import events

            CentralEventBus.publish(events.UMAP_COMPLETED, {})

            # Immediately persist the deletion to disk so it survives project close/reopen.
            # CentralEventBus.publish() only updates the in-memory undo history; the
            # workflow file on disk is not updated until handle_update() is called.
            try:
                p = self.parentWidget()
                while p is not None and not hasattr(p, "_workspace_io_handler"):
                    p = p.parentWidget()
                if p is not None and hasattr(p, "_workspace_io_handler"):
                    p._workspace_io_handler.handle_update()
            except Exception:
                logger.warning(
                    "Could not auto-save after run deletion — save manually to persist.",
                    exc_info=True,
                )

            self.refresh_history()

            # refresh_history() blocks signals to prevent spurious updates, so we must manually
            # trigger the UI transition to either the next available run or the [ New Run ] screen.
            self._on_history_changed(self._history_combo.currentIndex())

    def start_analysis(self) -> None:  # noqa: PLR0915
        sample_id = self._sample_combo.currentData()
        node_id = self._gate_combo.currentData()
        if not sample_id:
            return

        self._is_analysis_running = True
        self._is_animation_playing = False

        selected_channels = []
        for i in range(self._channel_list.count()):
            item = self._channel_list.item(i)
            if item and item.checkState() == Qt.CheckState.Checked:
                selected_channels.append(item.data(Qt.ItemDataRole.UserRole))

        if not selected_channels:
            self._on_analysis_error(
                "No channels selected. Please select at least one channel for analysis."
            )
            return

        percentage = self._n_events_slider.value() / 100.0
        n_events_to_sample = int(self._total_events * percentage) if self._total_events > 0 else 0
        n_events_to_sample = (
            max(50, n_events_to_sample)
            if self._total_events > 50  # noqa: PLR2004
            else self._total_events
        )

        name = self._run_name_input.text().strip()
        if not name:
            self._on_analysis_error("Please provide a name for this run.")
            return

        params = UmapParams(
            target_sample_id=sample_id,
            target_node_id=node_id,
            name=name,
            percentage=float(self._n_events_slider.value()),
            n_neighbors=self._n_neigh_slider.value(),
            min_dist=(self._min_dist_slider.value() / 100.0),
            n_events=n_events_to_sample,
            metric=self._metric_combo.currentText(),
            random_seed=int(self._seed_input.text() or "42"),
            run_hdbscan=self._run_hdbscan_cb.isChecked(),
            hdbscan_space="high_dim",  # Hardcoded to biologically accurate high_dim
            min_cluster_size=self._min_cluster_size_box.value(),
            channels=selected_channels,
        )

        self._progress_bar.setRange(0, 0)
        self._progress_bar.show()

        self.set_running(True)
        gate_hint = f" (gate: {node_id[:8]}\u2026)" if node_id else " (all events)"
        self._status_lbl.setText(f"Running analysis{gate_hint}...")

        sample = self._state.data.experiment.samples.get(sample_id)
        if sample and sample.fcs_data is not None:
            from ...analysis.fcs_io import get_fluorescence_channels

            fluo_channels = get_fluorescence_channels(sample.fcs_data)

            events_df = sample.fcs_data.events
            if node_id and sample.gate_tree is not None:
                gate_node = sample.gate_tree.find_node_by_id(node_id)
                if gate_node is not None:
                    events_df = gate_node.apply_hierarchy(events_df)

            self._animator.show_loading()
            self._display_stack.setCurrentIndex(2)

            state_ref = self._state

            def _prep_task():
                logger.info("[ANIM-PREP] Starting UmapAnimationDataPrep in background thread")
                p = UmapAnimationDataPrep(
                    n_neighbors=params.n_neighbors,
                    random_seed=params.random_seed,
                )
                success = p.prepare(
                    events_df,
                    fluo_channels,
                    state_ref,
                    sample_id,
                    min_dist=params.min_dist,
                    color_marker_idx=0,
                )
                logger.info(f"[ANIM-PREP] prepare() returned success={success}")
                if not success:
                    return {"success": False, "prep": None}
                return {"success": True, "prep": p}

            def _on_prep_done(results: dict):
                try:
                    from PyQt6 import sip

                    if not sip.isdeleted(worker):
                        worker.finished.disconnect(_on_prep_done)
                        worker.error.disconnect(_on_prep_error)
                except Exception:
                    pass
                logger.info(
                    f"[ANIM-PREP] _on_prep_done called on main thread. success={results.get('success')}"
                )
                success = results.get("success", False)
                if success:
                    self._last_prep_data = results.get("prep")
                    logger.info("[ANIM-PREP] Calling prepare_animation() on main thread...")
                    self._animator.prepare_animation(self._last_prep_data)  # type: ignore
                    logger.info(
                        f"[ANIM-PREP] prepare_animation() done. {len(self._animator._frames)} frames built."
                    )
                    self._is_animation_playing = True
                    self._display_stack.setCurrentIndex(2)
                    self._animator.start()
                    logger.info("[ANIM-PREP] Animator started. Poll timer running.")
                else:
                    logger.warning(
                        "[ANIM-PREP] Prep failed — skipping animation, proceeding to UMAP only."
                    )
                    self._display_stack.setCurrentIndex(0)

                logger.info("[ANIM-PREP] Submitting full UMAP analysis task...")
                self._umap_service.run_analysis(
                    params=params,
                    on_done=lambda res: self._on_analysis_done(res, params=params),
                    on_error_cb=lambda err: self._on_analysis_error(err),
                    on_progress=self._progress_bar.setValue,
                )
                logger.info("[ANIM-PREP] Full UMAP task submitted.")

            def _on_prep_error(err: str):
                try:
                    from PyQt6 import sip

                    if not sip.isdeleted(worker):
                        worker.finished.disconnect(_on_prep_done)
                        worker.error.disconnect(_on_prep_error)
                except Exception:
                    pass
                self._display_stack.setCurrentIndex(0)
                self._on_analysis_error(f"Animation prep failed: {err}")

            from karcytics_sdk.plugin.managed_task import FunctionalTask
            from karcytics_sdk.plugin.runtime_services import task_scheduler

            task = FunctionalTask(_prep_task, name="UMAP Prep")
            worker = task_scheduler.submit(task, None)
            worker.finished.connect(_on_prep_done)
            worker.error.connect(_on_prep_error)

            return
        self._display_stack.setCurrentIndex(0)

        self._umap_service.run_analysis(
            params=params,
            on_done=lambda results: self._on_analysis_done(results, params=params),
            on_error_cb=lambda err: self._on_analysis_error(err),
            on_progress=self._progress_bar.setValue,
        )

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
        if embedding is not None:
            import numpy as np

            if isinstance(embedding, list):
                embedding = np.array(embedding)

            if (
                hasattr(self, "_last_prep_data")
                and self._last_prep_data
                and self._last_prep_data.final_2d is not None
            ):
                import scipy.linalg

                n_sub = len(self._last_prep_data.final_2d)
                if len(embedding) >= n_sub:
                    X_sub = embedding[:n_sub]
                    Y = self._last_prep_data.final_2d

                    X_mean = X_sub.mean(axis=0)
                    Y_mean = Y.mean(axis=0)
                    X_c = X_sub - X_mean
                    Y_c = Y - Y_mean

                    scale_X = np.linalg.norm(X_c)
                    scale_Y = np.linalg.norm(Y_c)

                    if scale_X > 0:
                        X_c = X_c / scale_X
                        Y_c = Y_c / scale_Y

                        try:
                            U, _, Vt = scipy.linalg.svd(X_c.T @ Y_c)
                            R = U @ Vt

                            embedding = embedding - X_mean
                            embedding = embedding / scale_X
                            embedding = embedding @ R
                            embedding = (embedding * scale_Y) + Y_mean
                        except Exception as e:
                            logger.warning(f"Failed to align embedding with animation frame: {e}")

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
                import numpy as np

                results[key] = np.array(results[key])

        if params:
            results["name"] = params.name
            results["run_hdbscan"] = params.run_hdbscan
            results["percentage"] = params.percentage
            results["n_neighbors"] = params.n_neighbors
            results["min_dist"] = params.min_dist
            results["metric"] = params.metric
            results["random_seed"] = params.random_seed
            results["min_cluster_size"] = params.min_cluster_size
            results["hdbscan_space"] = params.hdbscan_space

        self._last_results = results

        key = f"{results['sample_id']}::{results['node_id'] or 'root'}"
        if key not in self._state.data.umap_results:
            self._state.data.umap_results[key] = []
        self._state.data.umap_results[key].append(results)

        from karcytics_sdk.plugin import CentralEventBus

        from ...analysis import events

        CentralEventBus.publish(events.UMAP_COMPLETED, {})

        # We NO LONGER build the ClusterResultsPanel here, because building 10+ matplotlib
        # scatter plots takes 5-10 seconds and blocks the UI thread, which causes the
        # still-running UMAP animation to freeze jarringly.
        # Instead, we defer it to _check_transition_to_results().

        self._replay_anim_btn.setEnabled(True)
        self._check_transition_to_results()

    def _check_transition_to_results(self) -> None:
        logger.info(
            f"[TRANSITION] check_transition: anim_playing={self._is_animation_playing}, run={self._is_analysis_running}, results={self._last_results is not None}"
        )
        if self._is_animation_playing or self._is_analysis_running:
            return
        if self._last_results is not None:
            logger.info("[TRANSITION] Conditions met! Building results panel and switching.")

            # Now that animation is fully done, we can safely block the UI thread
            # for a few seconds to generate the matplotlib scatter plots.
            self._display_stack.removeWidget(self._results_panel)
            self._results_panel.deleteLater()

            self._results_panel = ClusterResultsPanel(
                self._last_results,
                state=self._state,
                gate_coordinator=self._gate_coordinator,
            )
            self._results_panel.results_modified.connect(self._on_results_modified)
            self._display_stack.insertWidget(1, self._results_panel)

            self._animator.stop()
            self._display_stack.setCurrentIndex(1)

            self.set_running(False)
            self._history_combo.blockSignals(True)
            self.refresh_history()
            final_index = self._history_combo.count() - 1 if self._history_combo.count() > 1 else 0
            self._history_combo.setCurrentIndex(final_index)
            self._history_combo.blockSignals(False)
            # Signals were blocked during setCurrentIndex so _on_history_changed never fired.
            # Call only the field-restoration helper — the panel was already built above.
            run_idx = self._history_combo.itemData(final_index)
            if run_idx is not None:
                sample_id = self._sample_combo.currentData()
                gate_id = self._gate_combo.currentData()
                key = f"{sample_id}::{gate_id or 'root'}"
                runs = self._state.data.umap_results.get(key, [])
                if 0 <= run_idx < len(runs):
                    self._restore_fields_from_run(runs[run_idx])

            self._replay_anim_btn.setEnabled(True)
            self._update_delete_button_state()

    def _on_animation_finished(self) -> None:
        logger.info("[TRANSITION] _on_animation_finished called.")
        self._is_animation_playing = False
        self._check_transition_to_results()

    def _play_animation(self) -> None:
        self._is_animation_playing = True
        if not hasattr(self, "_last_prep_data") or not self._last_prep_data:
            return
        if hasattr(self._animator, "_anim_frame_counter"):
            self._animator._anim_frame_counter = 0
        self._display_stack.setCurrentIndex(2)
        self._animator.prepare_animation(self._last_prep_data)
        self._animator.start()

    def _on_analysis_error(self, error_msg: str) -> None:
        self._progress_bar.setRange(0, 100)
        self._progress_bar.hide()
        self.set_running(False)
        self._status_lbl.setText(f"Error: {error_msg}")
        self._run_details_lbl.setVisible(True)
        self._run_details_lbl.setText(f"Analysis Failed:\n{error_msg}")
        self._display_stack.setCurrentIndex(0)
