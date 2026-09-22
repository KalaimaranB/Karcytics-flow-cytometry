"""Cluster Results Panel — Dedicated UI for analyzing HDBSCAN UMAP clusters."""

from __future__ import annotations

from typing import Any

import matplotlib as mpl
import matplotlib.colors as mcolors
import numpy as np
from karcytics_sdk.plugin.theme_fallback import Colors, Fonts
from matplotlib.figure import Figure
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction, QColor
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from karcytics_plugins.flow_cytometry.ui.graph._mpl_compat import (
    LockedFigureCanvas as FigureCanvasQTAgg,  # thread-safe vs RenderTask's Agg rasterization
)


class CopyableCanvas(FigureCanvasQTAgg):
    """A Matplotlib canvas that supports right-click to copy to clipboard."""

    def __init__(self, figure):
        super().__init__(figure)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    def _show_context_menu(self, pos):
        menu = QMenu(self)
        copy_action = QAction("Copy Image to Clipboard", self)
        copy_action.triggered.connect(self._copy_to_clipboard)
        menu.addAction(copy_action)
        menu.exec(self.mapToGlobal(pos))

    def _copy_to_clipboard(self):
        pixmap = self.grab()
        QApplication.clipboard().setPixmap(pixmap)

    def wheelEvent(self, event):
        # Ignore wheel events so they propagate to the parent QScrollArea
        # allowing the user to scroll through the gallery while hovered over a plot
        event.ignore()


class HoverStatsWidget(QFrame):
    """Floating widget to display local neighborhood stats."""

    def __init__(self, channels: list[str], parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setObjectName("hover_stats")
        self.setStyleSheet(
            f"#hover_stats {{ background-color: {Colors.BG_DARKEST}; border: 1px solid {Colors.BORDER}; border-radius: 6px; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self._title = QLabel("Local Neighborhood")
        self._title.setStyleSheet(
            f"color: {Colors.FG_PRIMARY}; font-weight: bold; font-size: 12px;"
        )
        layout.addWidget(self._title)

        self._grid = QGridLayout()
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(6)

        self._bars = []
        for i, ch in enumerate(channels):
            lbl = QLabel(ch)
            lbl.setStyleSheet(f"color: {Colors.FG_SECONDARY}; font-size: 11px;")
            self._grid.addWidget(lbl, i, 0)

            bar_container = QFrame()
            bar_container.setFixedSize(120, 10)
            bar_container.setStyleSheet(
                f"background-color: {Colors.BG_LIGHT}; border-radius: 3px; border: none;"
            )

            bar_fill = QFrame(bar_container)
            bar_fill.setStyleSheet(
                f"background-color: {Colors.ACCENT_PRIMARY}; border-radius: 3px; border: none;"
            )
            bar_fill.setFixedSize(0, 10)

            self._grid.addWidget(bar_container, i, 1)
            self._bars.append(bar_fill)

        layout.addLayout(self._grid)
        self.hide()

    def update_stats(self, title_text: str, expressions: np.ndarray, max_vals: np.ndarray):
        self._title.setText(title_text)
        for i, val in enumerate(expressions):
            norm_val = min(1.0, max(0.0, val / max_vals[i])) if max_vals[i] > 0 else 0
            self._bars[i].setFixedSize(int(norm_val * 120), 10)


class ClusterResultsPanel(QWidget):
    """A multi-tabbed panel displaying UMAP plot gallery and statistical tables."""

    results_modified = pyqtSignal()

    def __init__(
        self,
        results: dict[str, Any],
        state: Any | None = None,
        gate_coordinator=None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._results = results
        self._state = state
        self._gate_coordinator = gate_coordinator
        self._poly_selector: Any | None = None
        self._custom_cluster_masks: list = []  # List of tuples (mask, row_widget_references)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._tabs = QTabWidget()
        self._tabs.setObjectName("ClusterResultsTabs")
        self._tabs.setStyleSheet(f"""
            QTabWidget {{ background: transparent; }}
            QTabWidget::pane {{ border: 1px solid {Colors.BORDER}; border-radius: 4px; background: {Colors.BG_DARK}; }}
            QTabBar::tab {{ background: {Colors.BG_MEDIUM}; color: {Colors.FG_SECONDARY}; padding: 8px 16px; border: 1px solid {Colors.BORDER}; border-bottom: none; border-top-left-radius: 4px; border-top-right-radius: 4px; margin-right: 2px; }}
            QTabBar::tab:selected {{ background: {Colors.BG_DARK}; color: {Colors.FG_PRIMARY}; font-weight: bold; border-bottom: 1px solid {Colors.BG_DARK}; }}
            QTabBar::tab:hover:!selected {{ background: {Colors.BG_LIGHT}; }}
        """)

        layout.addWidget(self._tabs)

        self._build_plot_gallery()

        if "clusters" in self._results:
            self._build_interactive_map_tab()
            self._build_unified_statistics_tab()

    def _apply_theme_styles(self) -> None:
        self._tabs.setStyleSheet(f"""
            QTabWidget {{ background: transparent; }}
            QTabWidget::pane {{ border: 1px solid {Colors.BORDER}; border-radius: 4px; background: {Colors.BG_DARK}; }}
            QTabBar::tab {{ background: {Colors.BG_MEDIUM}; color: {Colors.FG_SECONDARY}; padding: 8px 16px; border: 1px solid {Colors.BORDER}; border-bottom: none; border-top-left-radius: 4px; border-top-right-radius: 4px; margin-right: 2px; }}
            QTabBar::tab:selected {{ background: {Colors.BG_DARK}; color: {Colors.FG_PRIMARY}; font-weight: bold; border-bottom: 1px solid {Colors.BG_DARK}; }}
            QTabBar::tab:hover:!selected {{ background: {Colors.BG_LIGHT}; }}
        """)

        for canvas in self.findChildren(FigureCanvasQTAgg):
            if hasattr(canvas, "figure"):
                fig = canvas.figure
                fig.patch.set_facecolor(Colors.BG_DARK)
                if fig.axes:
                    for ax in fig.axes:
                        ax.set_facecolor(Colors.BG_DARK)
                        ax.tick_params(colors=Colors.FG_SECONDARY)
                        for spine in ("bottom", "left"):
                            if spine in ax.spines:
                                ax.spines[spine].set_color(Colors.BORDER)
                        if ax.title:
                            ax.title.set_color(Colors.FG_PRIMARY)
                        if ax.xaxis.label:
                            ax.xaxis.label.set_color(Colors.FG_SECONDARY)
                        if ax.yaxis.label:
                            ax.yaxis.label.set_color(Colors.FG_SECONDARY)
                canvas.draw_idle()

    def _create_plot(  # noqa: PLR0913
        self,
        embedding: np.ndarray,
        color_data: np.ndarray,
        title: str,
        cmap: str | mcolors.Colormap,
        norm=None,
        is_discrete=False,
        min_c=0,
        max_c=0,
    ) -> CopyableCanvas:
        fig = Figure(facecolor=Colors.BG_DARK, figsize=(5, 4))
        ax = fig.add_subplot(111)
        ax.set_facecolor(Colors.BG_DARK)
        ax.tick_params(colors=Colors.FG_SECONDARY, labelsize=7)
        for spine in ("bottom", "left"):
            ax.spines[spine].set_color(Colors.BORDER)
        for spine in ("top", "right"):
            ax.spines[spine].set_visible(False)

        ax.set_title(title, color=Colors.FG_PRIMARY, fontsize=10, fontweight="bold", pad=8)
        ax.set_aspect("equal", "datalim")

        scatter = ax.scatter(
            embedding[:, 0],
            embedding[:, 1],
            c=color_data,
            cmap=cmap,
            norm=norm,
            s=1.0,
            alpha=0.75,
            edgecolors="none",
        )

        cbar = fig.colorbar(scatter, ax=ax, fraction=0.046, pad=0.04)
        cbar.ax.yaxis.set_tick_params(colors=Colors.FG_SECONDARY, labelsize=7)
        cbar.outline.set_color(Colors.BORDER)  # type: ignore

        if is_discrete:
            cbar.set_ticks(np.arange(min_c, max_c + 1))  # type: ignore
            cbar.set_label("Cluster ID", color=Colors.FG_SECONDARY, fontsize=8)
        else:
            cbar.set_label("Intensity", color=Colors.FG_SECONDARY, fontsize=8)

        fig.tight_layout()
        canvas = CopyableCanvas(fig)
        canvas.setMinimumHeight(350)
        return canvas

    def _create_cluster_plot(self) -> CopyableCanvas | None:
        if "clusters" not in self._results:
            return None

        embedding = self._results["embedding"]
        if isinstance(embedding, list):
            embedding = np.array(embedding)

        clusters = self._results["clusters"]
        if isinstance(clusters, list):
            clusters = np.array(clusters)

        min_c = int(clusters.min())
        max_c = int(clusters.max())
        n_clusters = max_c - min_c + 1

        base_cmap = mpl.colormaps["tab20"]
        colors = [base_cmap(i % 20) for i in range(n_clusters)]
        cmap = mcolors.ListedColormap(colors)
        bounds = np.arange(min_c, max_c + 2) - 0.5
        norm = mcolors.BoundaryNorm(bounds, cmap.N)

        return self._create_plot(
            embedding,
            clusters,
            "Auto-Cluster ID",
            cmap,
            norm,
            True,
            min_c,
            max_c,  # type: ignore
        )

    def _build_plot_gallery(self) -> None:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        container = QWidget()
        container.setStyleSheet("background: transparent;")
        grid = QGridLayout(container)
        grid.setSpacing(16)

        embedding = self._results.get("embedding")
        intensities = self._results.get("intensities")
        if embedding is None or intensities is None:
            return

        if isinstance(embedding, list):
            embedding = np.array(embedding)
            self._results["embedding"] = embedding

        if isinstance(intensities, list):
            intensities = np.array(intensities)
            self._results["intensities"] = intensities

        channels = self._results["channels"]

        row, col = 0, 0
        max_cols = 2

        # 1. Plot Auto-Cluster ID first (if available)
        cluster_canvas = self._create_cluster_plot()
        if cluster_canvas:
            grid.addWidget(cluster_canvas, row, col)
            col += 1

        # 2. Plot all markers
        sample_id = self._results.get("sample_id")
        sample = (
            self._state.data.experiment.samples.get(sample_id)
            if self._state and sample_id
            else None
        )

        from ...analysis.fcs_io import get_channel_marker_label

        for i, ch in enumerate(channels):
            if col >= max_cols:
                col = 0
                row += 1

            title = ch
            if sample and sample.fcs_data:
                try:
                    title = get_channel_marker_label(sample.fcs_data, ch)
                except Exception:
                    pass

            norm = mcolors.Normalize(vmin=0, vmax=1)
            canvas = self._create_plot(embedding, intensities[:, i], title, "viridis", norm=norm)
            grid.addWidget(canvas, row, col)
            col += 1

        scroll.setWidget(container)
        self._tabs.addTab(scroll, "Plot Gallery")

    def _build_interactive_map_tab(self) -> None:
        import scipy.spatial
        from karcytics_sdk.plugin.components import BioComboBox, SecondaryButton
        from PyQt6.QtWidgets import QLabel, QStackedWidget

        container = QWidget()
        layout = QVBoxLayout(container)

        toolbar = QHBoxLayout()
        self._interactive_combo = BioComboBox()
        self._interactive_combo.setObjectName("UmapInteractiveMapCombo")
        self._interactive_combo.addItem("Auto-Cluster ID", "clusters")
        for ch in self._results.get("channels", []):
            self._interactive_combo.addItem(f"Marker: {ch}", ch)
        self._interactive_combo.currentIndexChanged.connect(self._on_interactive_combo_changed)
        toolbar.addWidget(self._interactive_combo)

        btn_draw = SecondaryButton("✏️ Draw Custom Population")
        btn_draw.clicked.connect(self._activate_polygon_drawer)
        toolbar.addWidget(btn_draw)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        self._interactive_stack = QStackedWidget()
        layout.addWidget(self._interactive_stack, stretch=1)

        self._interactive_info = QLabel("")
        self._interactive_info.setStyleSheet(f"color: {Colors.FG_SECONDARY};")
        layout.addWidget(self._interactive_info)

        self._tabs.addTab(container, "Interactive Map")

        embedding = self._results["embedding"]
        if isinstance(embedding, list):
            embedding = np.array(embedding)
        self._kdtree = scipy.spatial.KDTree(embedding)

        intensities = self._results["intensities"]
        if isinstance(intensities, list):
            intensities = np.array(intensities)
        self._max_intensities = np.percentile(intensities, 99, axis=0)

        sample_id = self._results.get("sample_id")
        self._state.data.experiment.samples.get(sample_id) if self._state and sample_id else None

        display_channels = []
        channels_list = self._results.get("channels", [])
        labels_list = self._results.get("channel_labels", [])
        for ch in channels_list:
            label = str(ch)
            idx = channels_list.index(label)
            if idx < len(labels_list):
                label = labels_list[idx]
            display_channels.append(label)

        self._hover_widget = HoverStatsWidget(display_channels, None)

        self._on_interactive_combo_changed(0)

    def _on_interactive_combo_changed(self, idx: int) -> None:
        while self._interactive_stack.count() > 0:
            widget = self._interactive_stack.widget(0)
            self._interactive_stack.removeWidget(widget)
            if widget:
                widget.deleteLater()

        data_key = self._interactive_combo.currentData()
        title = self._interactive_combo.currentText()

        embedding = self._results["embedding"]
        if isinstance(embedding, list):
            embedding = np.array(embedding)

        if data_key == "clusters":
            canvas = self._create_cluster_plot()
            if not canvas:
                return
        else:
            ch_idx = self._results["channels"].index(data_key)
            intensities = self._results["intensities"]
            if isinstance(intensities, list):
                intensities = np.array(intensities)
            norm = mcolors.Normalize(vmin=0, vmax=1)
            canvas = self._create_plot(
                embedding, intensities[:, ch_idx], title, "viridis", norm=norm
            )

        ax = canvas.figure.axes[0]
        from matplotlib.patches import Polygon

        if "custom_clusters" in self._results:
            for custom_data in self._results["custom_clusters"]:
                if "verts" in custom_data:
                    poly = Polygon(
                        custom_data["verts"],
                        closed=True,
                        fill=False,
                        edgecolor=Colors.ACCENT_PRIMARY,
                        linewidth=2,
                        linestyle="--",
                    )
                    ax.add_patch(poly)

        self._interactive_stack.addWidget(canvas)
        self._interactive_canvas = canvas

        self._hover_widget.setParent(canvas)
        canvas.mpl_connect("motion_notify_event", self._on_hover)

        self._interactive_info.setText(f"Displaying: {title} | Total events: {len(embedding)}")

    def _on_hover(self, event):  # noqa: PLR0912
        if not event.inaxes:
            if self._hover_widget.isVisible():
                self._hover_widget.hide()
            return

        gui_event = event.guiEvent
        if gui_event:
            pos = gui_event.pos()
            canvas_width = self._interactive_canvas.width()
            x_pos = pos.x() + 15
            if x_pos + self._hover_widget.width() > canvas_width:
                x_pos = pos.x() - self._hover_widget.width() - 15

            self._hover_widget.move(x_pos, pos.y() + 15)
            if not self._hover_widget.isVisible():
                self._hover_widget.show()
                self._hover_widget.raise_()

        if not hasattr(self, "_kdtree"):
            return

        # Find nearest 50 neighbors
        dists, inds = self._kdtree.query([event.xdata, event.ydata], k=50)

        xlim = self._interactive_canvas.figure.axes[0].get_xlim()
        ylim = self._interactive_canvas.figure.axes[0].get_ylim()
        range_span = max(abs(xlim[1] - xlim[0]), abs(ylim[1] - ylim[0]))
        if dists[0] > (range_span * 0.05):
            if self._hover_widget.isVisible():
                self._hover_widget.hide()
            return

        intensities = self._results["intensities"]
        if isinstance(intensities, list):
            intensities = np.array(intensities)

        local_expr = intensities[inds].mean(axis=0)

        title_text = "Local Neighborhood (n=50)"

        custom_name = None
        if "custom_clusters" in self._results:
            closest_pt = inds[0]
            for custom_data in reversed(self._results["custom_clusters"]):
                if closest_pt in custom_data.get("mask", []):
                    custom_name = custom_data["name"]
                    break

        if custom_name:
            title_text = f"Custom: {custom_name}"
        elif "clusters" in self._results:
            clusters = self._results["clusters"]
            if isinstance(clusters, list):
                clusters = np.array(clusters)
                self._results["clusters"] = clusters
            local_clusters = clusters[inds]
            vals, counts = np.unique(local_clusters, return_counts=True)
            dominant = vals[np.argmax(counts)]
            dominant_id = int(dominant)
            name = self._results.get("cluster_names", {}).get(
                str(dominant_id), f"Cluster {dominant_id}"
            )
            title_text = f"Dominant: {name}"

        self._hover_widget.update_stats(title_text, local_expr, self._max_intensities)

    def _refresh_statistics_tab(self) -> None:
        for i in range(self._tabs.count()):
            if self._tabs.tabText(i) == "Population Statistics":
                self._tabs.removeTab(i)
                break
        self._build_unified_statistics_tab()

    def _build_unified_statistics_tab(self) -> None:  # noqa: PLR0912, PLR0915
        self._custom_cluster_masks = []
        self._cluster_ui_elements: dict = {}
        from karcytics_sdk.plugin.components import BioLineEdit, PrimaryButton
        from PyQt6.QtWidgets import (
            QCheckBox,
            QLabel,
            QScrollArea,
            QSplitter,
            QVBoxLayout,
            QWidget,
        )

        splitter = QSplitter(Qt.Orientation.Horizontal)

        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        left_container = QWidget()
        left_layout = QVBoxLayout(left_container)
        left_layout.setContentsMargins(8, 8, 8, 8)
        left_layout.setSpacing(16)

        stats_data = self._results.get("cluster_stats")
        if stats_data is not None:
            stats_lbl = QLabel("Cluster Statistics")
            stats_lbl.setStyleSheet(
                f"color: {Colors.FG_PRIMARY}; font-weight: bold; font-size: 14px;"
            )
            left_layout.addWidget(stats_lbl)

            import pandas as pd

            if stats_data is not None:
                if isinstance(stats_data, dict):
                    stats_df = pd.DataFrame(
                        data=stats_data.get("data", []),
                        index=stats_data.get("index", []),
                        columns=stats_data.get("columns", []),
                    )
                else:
                    stats_df = stats_data.copy()
            else:
                stats_df = pd.DataFrame(columns=["Cluster ID", "Cell Count", "% of Total"])

            if "custom_clusters" in self._results:
                for custom_idx, custom_data in enumerate(self._results["custom_clusters"], 1):
                    indices = custom_data.get("mask", [])
                    if not indices:
                        continue

                    embedding = self._results["embedding"]
                    if isinstance(embedding, list):
                        embedding = np.array(embedding)
                        self._results["embedding"] = embedding

                    mask = np.zeros(len(embedding), dtype=bool)
                    mask[indices] = True
                    count = int(np.sum(mask))
                    if count > 0:
                        pct = (count / len(embedding)) * 100
                        stats_df.loc[len(stats_df)] = [
                            f"Custom {custom_idx}",
                            count,
                            pct,
                        ]

            table = QTableWidget(len(stats_df), len(stats_df.columns))
            table.setHorizontalHeaderLabels(stats_df.columns)
            hh = table.horizontalHeader()
            if hh:
                hh.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
            table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            table.setStyleSheet(
                f"QTableWidget {{ background: {Colors.BG_DARK}; color: {Colors.FG_PRIMARY}; gridline-color: {Colors.BORDER}; }} QHeaderView::section {{ background: {Colors.BG_MEDIUM}; color: {Colors.FG_PRIMARY}; font-weight: bold; border: 1px solid {Colors.BORDER}; padding: 4px; }}"
            )

            for i in range(len(stats_df)):
                cluster_id = stats_df.iloc[i, 0]
                try:
                    c_idx = int(cluster_id)
                except ValueError:
                    c_idx = 100 + i
                base_cmap = mpl.colormaps["tab20"]
                c = base_cmap(c_idx % 20)
                cluster_color = QColor(int(c[0] * 255), int(c[1] * 255), int(c[2] * 255))
                for j, col_name in enumerate(stats_df.columns):
                    val = stats_df.iloc[i, j]
                    item = QTableWidgetItem(f"{val:.2f}%" if col_name == "% of Total" else str(val))
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    if col_name == "Cluster ID":
                        item.setBackground(cluster_color)
                        item.setForeground(
                            QColor(255, 255, 255)
                            if (c[0] * 0.299 + c[1] * 0.587 + c[2] * 0.114) < 0.5  # noqa: PLR2004
                            else QColor(0, 0, 0)
                        )
                    table.setItem(i, j, item)

            table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            table.setMinimumHeight(40 + (table.rowCount() * 30))
            left_layout.addWidget(table)

        heatmap_data = self._results.get("marker_heatmap")
        if heatmap_data is not None or "custom_clusters" in self._results:
            hm_lbl = QLabel("Marker Expression Heatmap")
            hm_lbl.setStyleSheet(f"color: {Colors.FG_PRIMARY}; font-weight: bold; font-size: 14px;")
            left_layout.addWidget(hm_lbl)

            if heatmap_data is not None:
                if isinstance(heatmap_data, dict):
                    heatmap_df = pd.DataFrame(
                        data=heatmap_data.get("data", []),
                        index=heatmap_data.get("index", []),
                        columns=heatmap_data.get("columns", []),
                    )
                else:
                    heatmap_df = heatmap_data.copy()
            else:
                heatmap_df = pd.DataFrame(columns=self._results.get("channels", []))

            if "custom_clusters" in self._results:
                for custom_idx, custom_data in enumerate(self._results["custom_clusters"], 1):
                    indices = custom_data.get("mask", [])
                    if not indices:
                        continue

                    embedding = self._results["embedding"]
                    if isinstance(embedding, list):
                        embedding = np.array(embedding)
                        self._results["embedding"] = embedding

                    mask = np.zeros(len(embedding), dtype=bool)
                    mask[indices] = True
                    count = int(np.sum(mask))
                    if count > 0:
                        intensities = self._results["intensities"]
                        if isinstance(intensities, list):
                            intensities = np.array(intensities)
                            self._results["intensities"] = intensities
                        mean_expr = np.mean(intensities[mask], axis=0)
                        heatmap_df.loc[f"Custom {custom_idx}"] = mean_expr

            sample_id = self._results.get("sample_id")
            self._state.data.experiment.samples.get(
                sample_id
            ) if self._state and sample_id else None

            new_columns = []
            channels_list = self._results.get("channels", [])
            labels_list = self._results.get("channel_labels", [])
            for ch in heatmap_df.columns:
                label = str(ch)
                if label in channels_list:
                    idx = channels_list.index(label)
                    if idx < len(labels_list):
                        label = labels_list[idx]
                new_columns.append(label)
            heatmap_df.columns = new_columns

            hm_table = QTableWidget(len(heatmap_df), len(heatmap_df.columns) + 1)
            hm_table.setHorizontalHeaderLabels(["Cluster ID"] + list(heatmap_df.columns))
            hm_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            hm_table.setStyleSheet(
                f"QTableWidget {{ background: {Colors.BG_DARK}; color: {Colors.FG_PRIMARY}; gridline-color: {Colors.BORDER}; }} QHeaderView::section {{ background: {Colors.BG_MEDIUM}; color: {Colors.FG_PRIMARY}; font-weight: bold; border: 1px solid {Colors.BORDER}; padding: 4px; }}"
            )

            global_min = heatmap_df.values.min()
            global_max = heatmap_df.values.max()
            val_range = global_max - global_min if global_max > global_min else 1.0

            for i in range(len(heatmap_df)):
                cluster_id = heatmap_df.index[i]
                try:
                    c_idx = int(cluster_id)
                except ValueError:
                    c_idx = 100 + i
                base_cmap = mpl.colormaps["tab20"]
                c = base_cmap(c_idx % 20)
                cluster_color = QColor(int(c[0] * 255), int(c[1] * 255), int(c[2] * 255))
                id_item = QTableWidgetItem(str(cluster_id))
                id_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                id_item.setBackground(cluster_color)
                id_item.setForeground(
                    QColor(255, 255, 255)
                    if (c[0] * 0.299 + c[1] * 0.587 + c[2] * 0.114) < 0.5  # noqa: PLR2004
                    else QColor(0, 0, 0)
                )
                hm_table.setItem(i, 0, id_item)

                for j, col_name in enumerate(heatmap_df.columns):  # noqa: B007
                    val = heatmap_df.iloc[i, j]
                    norm = (val - global_min) / val_range
                    intensity = (
                        int((1.0 - (norm * 2)) * 150)
                        if norm < 0.5  # noqa: PLR2004
                        else int(((norm - 0.5) * 2) * 200)
                    )
                    bg_color = (
                        QColor(0, 0, intensity)
                        if norm < 0.5  # noqa: PLR2004
                        else QColor(intensity, 0, 0)
                    )
                    item = QTableWidgetItem(f"{val:.2f}")
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    item.setBackground(bg_color)
                    item.setForeground(QColor(255, 255, 255))
                    hm_table.setItem(i, j + 1, item)

            hm_table.resizeColumnsToContents()
            hm_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            hm_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            hm_table.setMinimumHeight(40 + (hm_table.rowCount() * 30))
            left_layout.addWidget(hm_table)

            vis_lbl = QLabel("Expression Profiles")
            vis_lbl.setStyleSheet(
                f"color: {Colors.FG_PRIMARY}; font-weight: bold; font-size: 14px;"
            )
            left_layout.addWidget(vis_lbl)

            fig = Figure(facecolor=Colors.BG_DARK, figsize=(6, 4))
            ax = fig.add_subplot(111)
            ax.set_facecolor(Colors.BG_DARK)
            ax.tick_params(colors=Colors.FG_SECONDARY, labelsize=8)
            for spine in ax.spines.values():
                spine.set_color(Colors.BORDER)
            n_clusters = len(heatmap_df)
            x = np.arange(n_clusters)

            data_values = heatmap_df.values.copy()
            if data_values.min() < 0:
                data_values = data_values - data_values.min()

            row_sums = data_values.sum(axis=1, keepdims=True)
            row_sums[row_sums == 0] = 1e-9
            normalized_data = (data_values / row_sums) * 100

            bottoms = np.zeros(n_clusters)
            marker_cmap = mpl.colormaps["tab20"]
            for j, col_name in enumerate(heatmap_df.columns):
                val = normalized_data[:, j]
                ax.bar(
                    x,
                    val,
                    width=0.7,
                    bottom=bottoms,
                    label=col_name,
                    color=marker_cmap(j % 20),
                )
                bottoms += val

            ax.set_xticks(x)
            ax.set_xticklabels(heatmap_df.index)
            ax.set_xlabel("Cluster ID", color=Colors.FG_PRIMARY, fontsize=9)
            ax.set_ylabel("Relative Expression (%)", color=Colors.FG_PRIMARY, fontsize=9)
            ax.set_title("100% Stacked Expression Profiles", color=Colors.FG_PRIMARY, fontsize=10)

            ax.legend(
                bbox_to_anchor=(1.02, 1),
                loc="upper left",
                fontsize=8,
                facecolor=Colors.BG_MEDIUM,
                edgecolor=Colors.BORDER,
                labelcolor=Colors.FG_PRIMARY,
            )
            fig.subplots_adjust(right=0.75, bottom=0.15)
            fig.tight_layout()

            vis_canvas = CopyableCanvas(fig)
            vis_canvas.setMinimumHeight(300)
            left_layout.addWidget(vis_canvas)

        left_scroll.setWidget(left_container)
        splitter.addWidget(left_scroll)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(16, 8, 8, 8)

        title = QLabel("Export Populations")
        title.setStyleSheet(f"color: {Colors.FG_PRIMARY}; font-weight: bold; font-size: 14px;")
        right_layout.addWidget(title)

        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        list_container = QWidget()
        self._list_layout = QVBoxLayout(list_container)
        self._list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._cluster_ui_elements = {}
        if stats_data is not None:
            for i in range(len(stats_df)):
                cluster_id = stats_df.iloc[i, 0]
                if str(cluster_id).startswith("Custom "):
                    continue
                count = int(stats_df.iloc[i, 1])
                pct = float(stats_df.iloc[i, 2])

                row_widget = QWidget()
                row_layout = QHBoxLayout(row_widget)
                row_layout.setContentsMargins(0, 0, 0, 0)

                checkbox = QCheckBox(f"ID {cluster_id}")
                checkbox.setStyleSheet(f"color: {Colors.FG_SECONDARY};")
                checkbox.setChecked(True)

                if "cluster_names" not in self._results:
                    self._results["cluster_names"] = {}
                saved_name = self._results["cluster_names"].get(
                    str(cluster_id), f"UMAP Cluster {cluster_id}"
                )

                name_edit = BioLineEdit()
                name_edit.setText(saved_name)
                name_edit.setPlaceholderText("Population Name")

                def make_text_handler(cid):
                    def on_text_changed(text):
                        self._results["cluster_names"][str(cid)] = text

                    return on_text_changed

                def make_edit_handler():
                    def on_editing_finished():
                        self.results_modified.emit()

                    return on_editing_finished

                name_edit.textChanged.connect(make_text_handler(cluster_id))
                name_edit.editingFinished.connect(make_edit_handler())

                info = QLabel(f"{count} events ({pct:.1f}%)")
                info.setStyleSheet(
                    f"color: {Colors.FG_SECONDARY}; font-size: {Fonts.SIZE_SMALL}px;"
                )

                row_layout.addWidget(checkbox)
                row_layout.addWidget(name_edit, stretch=1)
                row_layout.addWidget(info)

                self._list_layout.addWidget(row_widget)
                self._cluster_ui_elements[cluster_id] = (checkbox, name_edit)

        if "custom_clusters" in self._results:
            for custom_idx, custom_data in enumerate(self._results["custom_clusters"], 1):
                name = custom_data.get("name", f"Custom Cluster {custom_idx}")
                indices = custom_data.get("mask", [])

                mask = np.zeros(len(self._results["embedding"]), dtype=bool)
                mask[indices] = True

                count = int(np.sum(mask))
                if count == 0:
                    continue

                pct = (count / len(self._results["embedding"])) * 100

                row_widget = QWidget()
                row_layout = QHBoxLayout(row_widget)
                row_layout.setContentsMargins(0, 0, 0, 0)

                checkbox = QCheckBox(f"Custom {custom_idx}")
                checkbox.setStyleSheet(f"color: {Colors.FG_SECONDARY};")
                checkbox.setChecked(True)

                name_edit = BioLineEdit()
                name_edit.setText(name)
                name_edit.setPlaceholderText("Population Name")

                def make_custom_text_handler(idx):
                    def on_custom_text_changed(text):
                        self._results["custom_clusters"][idx]["name"] = text

                    return on_custom_text_changed

                def make_custom_edit_handler():
                    def on_custom_editing_finished():
                        self.results_modified.emit()

                    return on_custom_editing_finished

                name_edit.textChanged.connect(make_custom_text_handler(custom_idx - 1))
                name_edit.editingFinished.connect(make_custom_edit_handler())

                info = QLabel(f"{count} events ({pct:.1f}%)")
                info.setStyleSheet(
                    f"color: {Colors.FG_SECONDARY}; font-size: {Fonts.SIZE_SMALL}px;"
                )

                row_layout.addWidget(checkbox)
                row_layout.addWidget(name_edit, stretch=1)
                row_layout.addWidget(info)

                self._list_layout.addWidget(row_widget)
                self._custom_cluster_masks.append((mask, (checkbox, name_edit)))

        right_scroll.setWidget(list_container)
        right_layout.addWidget(right_scroll, stretch=1)

        btn_create = PrimaryButton("➕ Create Populations")
        btn_create.setObjectName("CreatePopulationsButton")
        btn_create.clicked.connect(self._create_populations)
        right_layout.addWidget(btn_create)

        splitter.addWidget(right_panel)
        splitter.setSizes([700, 300])

        self._tabs.addTab(splitter, "Population Statistics")

    def _create_populations(self) -> None:  # noqa: PLR0912
        if not self._state:
            return

        sample_id = self._results.get("sample_id")
        target_node_id = self._results.get("node_id")
        if not sample_id:
            return

        sample = self._state.data.experiment.samples.get(sample_id)
        if not sample or not sample.gate_tree:
            return

        target_node = (
            sample.gate_tree.find_node_by_id(target_node_id) if target_node_id else sample.gate_tree
        )
        if not target_node:
            return

        indices = self._results.get("indices", [])
        if len(indices) == 0:
            return

        import numpy as np

        if isinstance(indices, list):
            indices_arr = np.array(indices)
        else:
            indices_arr = indices

        from ...analysis.gating.subset import SubsetGate

        # Create UMAP parent node — mark it as a subset node, not a geometric gate node
        umap_parent = target_node.add_child(
            gate=SubsetGate(indices=[int(x) for x in indices_arr]),
            name="UMAP Reduction",
        )
        # Flag that this is a UMAP container — pipeline view will skip thumbnail
        umap_parent.is_umap_parent = True

        clusters = self._results.get("clusters")
        created_count = 0

        if clusters is not None:
            if isinstance(clusters, list):
                clusters = np.array(clusters)
            for cluster_id, (checkbox, name_edit) in self._cluster_ui_elements.items():
                if checkbox.isChecked():
                    name = name_edit.text() or f"Cluster {cluster_id}"
                    mask = clusters == cluster_id
                    cluster_indices = indices_arr[mask]

                    umap_parent.add_child(
                        gate=SubsetGate(indices=[int(x) for x in cluster_indices]),
                        name=name,
                    )
                    created_count += 1

        for mask, (checkbox, name_edit) in self._custom_cluster_masks:
            if checkbox.isChecked():
                name = name_edit.text() or "Custom Cluster"
                cluster_indices = indices_arr[mask]
                umap_parent.add_child(
                    gate=SubsetGate(indices=[int(x) for x in cluster_indices]),
                    name=name,
                )
                created_count += 1

        # Trigger stats recomputation so event/percentage counts appear correctly
        if self._gate_coordinator:
            self._gate_coordinator.recompute_all_stats(sample_id)

        from karcytics_sdk.plugin import CentralEventBus

        from ...analysis import events

        CentralEventBus.publish(events.GATE_CREATED, {"sample_id": sample_id})

        from karcytics_sdk.plugin.dialogs import show_info

        show_info(
            self,
            "Populations Created",
            f"Successfully exported {created_count} UMAP clusters to the Pipeline.",
        )

    def _activate_polygon_drawer(self) -> None:
        if not hasattr(self, "_interactive_canvas") or not self._interactive_canvas:
            return

        from matplotlib.widgets import PolygonSelector

        ax = self._interactive_canvas.figure.axes[0]

        from karcytics_sdk.plugin.dialogs import show_info

        show_info(
            self,
            "Draw Cluster",
            "Click on the UMAP plot to draw a polygon.\nDouble-click or press Enter to complete the shape.",
        )

        self._poly_selector = PolygonSelector(
            ax,
            self._on_polygon_drawn,  # type: ignore
            useblit=True,
            props=dict(color=Colors.ACCENT_PRIMARY, linestyle="-", linewidth=2, alpha=0.8),
        )

    def _on_polygon_drawn(self, verts) -> None:
        import numpy as np
        from matplotlib.path import Path
        from PyQt6.QtWidgets import QInputDialog

        if self._poly_selector:
            self._poly_selector.disconnect_events()
            self._poly_selector.set_visible(False)
            self._poly_selector = None

        path = Path(verts)
        embedding = self._results["embedding"]
        if isinstance(embedding, list):
            embedding = np.array(embedding)
            self._results["embedding"] = embedding
        mask = path.contains_points(embedding)

        count = int(np.sum(mask))
        if count == 0:
            return

        (count / len(embedding)) * 100

        if "custom_clusters" not in self._results:
            self._results["custom_clusters"] = []

        custom_idx = len(self._results["custom_clusters"]) + 1
        name, ok = QInputDialog.getText(
            self,
            "Name Population",
            "Enter a name for this custom population:",
            text=f"Custom Cluster {custom_idx}",
        )
        if not ok or not name.strip():
            return

        name = name.strip()

        indices = np.where(mask)[0].tolist()
        custom_data = {"name": name, "mask": indices, "verts": verts}
        self._results["custom_clusters"].append(custom_data)

        # Steal cells from auto-clusters
        if "clusters" in self._results:
            clusters = self._results["clusters"]
            if isinstance(clusters, list):
                clusters = np.array(clusters)
            clusters[mask] = -1
            self._results["clusters"] = clusters

            # Recompute stats
            import pandas as pd

            df_cluster = pd.DataFrame(
                self._results["intensities"], columns=self._results["channels"]
            )
            df_cluster["Cluster_ID"] = clusters

            # Drop the stolen cells (-1) from auto-cluster stats
            df_valid = df_cluster[df_cluster["Cluster_ID"] != -1]
            counts = df_valid["Cluster_ID"].value_counts().sort_index()
            percentages = (counts / len(df_cluster)) * 100
            stats_df = pd.DataFrame(
                {
                    "Cluster ID": counts.index,
                    "Cell Count": counts.values,
                    "% of Total": percentages.values,
                }
            )
            self._results["cluster_stats"] = stats_df.to_dict(orient="split")

            heatmap_df = df_valid.groupby("Cluster_ID").median()
            self._results["marker_heatmap"] = heatmap_df.to_dict(orient="split")

        ax = self._interactive_canvas.figure.axes[0]
        from matplotlib.patches import Polygon

        poly = Polygon(
            verts,
            closed=True,
            fill=False,
            edgecolor=Colors.ACCENT_PRIMARY,
            linewidth=2,
            linestyle="--",
        )
        ax.add_patch(poly)
        self._interactive_canvas.draw()

        self.results_modified.emit()
        self._refresh_statistics_tab()
