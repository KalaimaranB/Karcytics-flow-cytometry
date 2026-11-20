"""A clustering run's Population Statistics tab: tables, expression chart, export list."""

from __future__ import annotations

from functools import partial
from typing import Any

import pandas as pd
from karcytics_sdk.plugin.components import (
    BioCaptionLabel,
    BioLineEdit,
    BioScrollArea,
    BioSplitter,
    BioTableWidget,
    PrimaryButton,
    SecondaryButton,
    SubtitleLabel,
)
from karcytics_sdk.plugin.dialogs import show_info
from karcytics_sdk.plugin.theme_fallback import Colors, get_contrast_text_color, theme_manager
from matplotlib.figure import Figure
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...analysis import events
from ...analysis.clustering import ClusteringMethod
from ...analysis.clustering.result_tables import (
    ExportPicks,
    drawn_populations,
    export_populations,
    heatmap_table,
    run_array,
    stacked_profiles,
    statistics_table,
)
from ...analysis.services import experiment_edits
from ..graph.figure_renderer import FigureRenderWorker
from .cluster_scatter_draw import cluster_rgb
from .copyable import CopyableCanvas
from .expression_profile_renderer import ExpressionProfileRenderer

_ROW_HEIGHT_PX = 30
_HEADER_HEIGHT_PX = 40
_DRAWN_COLOR_OFFSET = 100  # drawn populations take palette colours past the clusters'


def _qcolor(rgb: tuple[float, float, float]) -> QColor:
    return QColor(int(rgb[0] * 255), int(rgb[1] * 255), int(rgb[2] * 255))


def _heat_color(fraction: float) -> QColor:
    """Low values dark blue through black to high values red (``fraction`` in 0..1)."""
    if fraction < 0.5:  # noqa: PLR2004 - the scale's midpoint
        return QColor(0, 0, int((1.0 - fraction * 2) * 150))
    return QColor(int((fraction - 0.5) * 2 * 200), 0, 0)


def _sized_table(rows: int, headers: list[str]) -> QTableWidget:
    """A read-only table showing every row, so the page scrolls instead of the table."""
    table = BioTableWidget(rows, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
    table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    table.setMinimumHeight(_HEADER_HEIGHT_PX + rows * _ROW_HEIGHT_PX)
    return table


def _cell(text: str, background: QColor | None = None) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
    if background is not None:
        item.setBackground(background)
        item.setForeground(QColor(get_contrast_text_color(background.name())))
    return item


class ClusterStatisticsTab(QWidget):
    """Statistics and marker tables with an expression chart, beside the export list."""

    results_modified = Signal()

    def __init__(
        self,
        run: dict[str, Any],
        method: ClusteringMethod,
        state: Any | None,
        gate_coordinator: Any | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._run = run
        self._state = state
        self._gate_coordinator = gate_coordinator
        self._heatmap: pd.DataFrame | None = None
        self._worker: FigureRenderWorker | None = None
        self._chart_layout = QVBoxLayout()
        self._method = method
        has_ids = "clusters" in run and len(run["clusters"])
        self._lowest_id = int(run_array(run, "clusters").min()) if has_ids else 0

        stats = statistics_table(run)
        splitter = BioSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_tables(stats))
        self._export = PopulationExportList(run, method, stats, self)
        self._export.create_requested.connect(self.create_populations)
        self._export.results_modified.connect(self.results_modified)
        splitter.addWidget(self._export)
        splitter.setSizes([700, 300])
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)
        self._render_chart()

    def cluster_rows(self) -> dict[Any, tuple[bool, str]]:
        """Each cluster's export row: (ticked, name)."""
        return self._export.cluster_rows()

    def _build_tables(self, stats: pd.DataFrame | None) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(16)
        if stats is not None:
            layout.addWidget(SubtitleLabel("Cluster Statistics"))
            layout.addWidget(self._statistics_table(stats))
        self._heatmap = heatmap_table(self._run)
        if self._heatmap is not None:
            layout.addWidget(SubtitleLabel("Marker Expression Heatmap"))
            layout.addWidget(self._heatmap_table(self._heatmap))
            layout.addWidget(SubtitleLabel("Expression Profiles"))
            layout.addLayout(self._chart_layout)
        layout.addStretch()
        scroll = BioScrollArea()
        scroll.setObjectName("UmapStatsPlotsPanel")
        scroll.setWidget(page)
        return scroll

    def _row_color(self, cluster_id: Any, row: int) -> QColor:
        try:
            return _qcolor(cluster_rgb(int(cluster_id), self._lowest_id))
        except ValueError:  # a drawn population ("Custom 2")
            return _qcolor(cluster_rgb(_DRAWN_COLOR_OFFSET + row, 0))

    def _statistics_table(self, stats: pd.DataFrame) -> QTableWidget:
        table = _sized_table(len(stats), [str(c) for c in stats.columns])
        header = table.horizontalHeader()
        if header is not None:
            header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for i, (cluster_id, count, pct) in enumerate(stats.itertuples(index=False, name=None)):
            table.setItem(i, 0, _cell(str(cluster_id), self._row_color(cluster_id, i)))
            table.setItem(i, 1, _cell(str(count)))
            table.setItem(i, 2, _cell(f"{pct:.2f}%"))
        return table

    def _heatmap_table(self, heatmap: pd.DataFrame) -> QTableWidget:
        table = _sized_table(len(heatmap), ["Cluster ID", *map(str, heatmap.columns)])
        values = heatmap.to_numpy(dtype=float)
        low = values.min() if values.size else 0.0
        span = (values.max() - low) if values.size and values.max() > low else 1.0
        for i, cluster_id in enumerate(heatmap.index):
            table.setItem(i, 0, _cell(str(cluster_id), self._row_color(cluster_id, i)))
            for j, value in enumerate(values[i]):
                table.setItem(i, j + 1, _cell(f"{value:.2f}", _heat_color((value - low) / span)))
        table.resizeColumnsToContents()
        return table

    # ── Expression chart (rendered off the GUI thread) ──────────────────

    def _render_chart(self) -> None:
        if self._heatmap is None or (self._worker is not None and self._worker.isRunning()):
            return
        self._show_in_chart_slot(BioCaptionLabel("Rendering…"))
        worker = FigureRenderWorker(
            ExpressionProfileRenderer(),
            {
                "profiles": stacked_profiles(self._heatmap),
                "cluster_labels": list(self._heatmap.index),
                "marker_labels": [str(c) for c in self._heatmap.columns],
                "background": Colors.BG_DARK,
                "panel": Colors.BG_MEDIUM,
                "foreground": Colors.FG_PRIMARY,
                "secondary": Colors.FG_SECONDARY,
                "border": Colors.BORDER,
            },
            self,
        )
        worker.finished_ok.connect(self._on_chart_rendered)
        worker.finished_err.connect(self._on_chart_failed)
        # Qt aborts if a running QThread is destroyed with its parent: wait it out.
        self.destroyed.connect(lambda *_: worker.stop_and_wait())
        self._worker = worker
        worker.start()

    def _on_chart_rendered(self, figure: Figure) -> None:
        canvas = CopyableCanvas(figure)
        canvas.setMinimumHeight(300)
        self._show_in_chart_slot(canvas)

    def _on_chart_failed(self, message: str) -> None:
        self._show_in_chart_slot(BioCaptionLabel(f"The chart could not be drawn: {message}"))

    def _show_in_chart_slot(self, widget: QWidget) -> None:
        while (item := self._chart_layout.takeAt(0)) is not None:
            if (old := item.widget()) is not None:
                old.deleteLater()
        self._chart_layout.addWidget(widget)

    def _apply_theme_styles(self) -> None:
        self._render_chart()  # its colours are baked into the figure

    # ── Export ───────────────────────────────────────────────────────────

    def create_populations(self) -> None:
        """Add the ticked clusters to the gate tree, as one undo step."""
        if self._state is None:
            return
        created = export_populations(self._run, self._state.data.experiment, self._export.picks())
        if created is None:
            return
        sample_id = self._run["sample_id"]
        if self._gate_coordinator is not None:
            self._gate_coordinator.recompute_all_stats(sample_id)
        name = self._method.name
        # GATE_CREATED drives the usual refreshes and joins the same undo step.
        experiment_edits.announce(
            f"Export {name} Clusters", (events.GATE_CREATED, {"sample_id": sample_id})
        )
        show_info(
            self,
            "Populations Created",
            f"Successfully exported {created} {name} clusters to the Pipeline.",
        )


class PopulationExportList(QWidget):
    """A ticked, nameable row per cluster and drawn population, and Create Populations."""

    create_requested = Signal()
    results_modified = Signal()

    def __init__(
        self,
        run: dict[str, Any],
        method: ClusteringMethod,
        stats: pd.DataFrame | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("UmapExportPopulationsPanel")
        self._method = method
        self._run = run
        self._cluster_rows: dict[Any, tuple[QCheckBox, BioLineEdit]] = {}
        self._drawn_rows: list[tuple[Any, QCheckBox, BioLineEdit]] = []  # (mask, …)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 8, 8, 8)
        layout.addWidget(SubtitleLabel("Export Populations"))
        layout.addLayout(self._select_buttons())

        rows = QWidget()
        theme_manager.apply_style(rows, "QCheckBox { color: {FG_SECONDARY}; }")
        self._rows_layout = QVBoxLayout(rows)
        self._rows_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._add_cluster_rows(stats)
        self._add_drawn_rows()
        scroll = BioScrollArea()
        scroll.setWidget(rows)
        layout.addWidget(scroll, stretch=1)

        create = PrimaryButton("➕ Create Populations")
        create.setObjectName("CreatePopulationsButton")
        create.clicked.connect(self.create_requested)
        layout.addWidget(create)

    def cluster_rows(self) -> dict[Any, tuple[bool, str]]:
        return {
            cid: (box.isChecked(), edit.text()) for cid, (box, edit) in self._cluster_rows.items()
        }

    def picks(self) -> ExportPicks:
        return ExportPicks(
            clusters={
                cid: edit.text()
                for cid, (box, edit) in self._cluster_rows.items()
                if box.isChecked()
            },
            drawn=[(mask, edit.text()) for mask, box, edit in self._drawn_rows if box.isChecked()],
        )

    def _select_buttons(self) -> QHBoxLayout:
        row = QHBoxLayout()
        for label, ticked, name in (
            ("All", True, "ExportPopulationsSelectAllButton"),
            ("None", False, "ExportPopulationsSelectNoneButton"),
        ):
            button = SecondaryButton(label)
            button.setObjectName(name)
            button.clicked.connect(lambda _=False, t=ticked: self._tick_all(t))
            row.addWidget(button)
        row.addStretch()
        return row

    def _tick_all(self, ticked: bool) -> None:
        boxes = [box for box, _edit in self._cluster_rows.values()]
        boxes += [box for _mask, box, _edit in self._drawn_rows]
        for box in boxes:
            box.setChecked(ticked)

    def _add_row(
        self, label: str, name: str, count: int, pct: float
    ) -> tuple[QCheckBox, BioLineEdit]:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        box = QCheckBox(label)
        box.setChecked(True)
        edit = BioLineEdit()
        edit.setText(name)
        edit.setPlaceholderText("Population Name")
        edit.editingFinished.connect(self.results_modified)
        layout.addWidget(box)
        layout.addWidget(edit, stretch=1)
        layout.addWidget(BioCaptionLabel(f"{count} events ({pct:.1f}%)"))
        self._rows_layout.addWidget(row)
        return box, edit

    def _add_cluster_rows(self, stats: pd.DataFrame | None) -> None:
        if stats is None:
            return
        names = self._run.setdefault("cluster_names", {})
        for cluster_id, count, pct in stats.itertuples(index=False, name=None):
            if str(cluster_id).startswith("Custom "):
                continue  # listed below, from the drawn populations themselves
            name = names.get(str(cluster_id), self._method.cluster_name(cluster_id))
            box, edit = self._add_row(f"ID {cluster_id}", name, int(count), float(pct))
            edit.textChanged.connect(partial(names.__setitem__, str(cluster_id)))
            self._cluster_rows[cluster_id] = (box, edit)

    def _add_drawn_rows(self) -> None:
        n_events = len(run_array(self._run, "embedding"))
        stored = self._run.get("custom_clusters", [])
        for drawn in drawn_populations(self._run):
            count = int(drawn.mask.sum())
            box, edit = self._add_row(
                f"Custom {drawn.number}", drawn.name, count, count / n_events * 100
            )
            entry = stored[drawn.number - 1]
            edit.textChanged.connect(partial(entry.__setitem__, "name"))
            self._drawn_rows.append((drawn.mask, box, edit))
