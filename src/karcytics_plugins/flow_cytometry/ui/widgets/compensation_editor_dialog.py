from __future__ import annotations

import typing

import numpy as np
from matplotlib.figure import Figure
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from karcytics_plugins.flow_cytometry.ui.graph._mpl_compat import (
    LockedFigureCanvas as FigureCanvasQTAgg,  # thread-safe vs RenderTask's Agg rasterization
)

if typing.TYPE_CHECKING:
    from karcytics_plugins.flow_cytometry.analysis.state import FlowState

from karcytics_sdk.plugin.components import repopulate_combo
from karcytics_sdk.plugin.theme_fallback import Colors

from karcytics_plugins.flow_cytometry.analysis.compensation import CompensationMatrix
from karcytics_plugins.flow_cytometry.ui.widgets.styled_combo import FlowComboBox


class CompensationEditorDialog(QDialog):
    """Dialog for fine-tuning and verifying compensation matrix."""

    def __init__(self, state: FlowState, parent=None):
        super().__init__(parent)
        self._state = state
        self.setWindowTitle("Spillover Matrix Editor")
        self.resize(1100, 700)

        self._temp_matrix: CompensationMatrix | None = None
        if self._state.data.compensation:
            # Deep copy to avoid mutating the state until applied
            d = self._state.data.compensation.to_dict()
            self._temp_matrix = CompensationMatrix.from_dict(d)

        self._active_sample_id: str | None = None
        for s_id, s in self._state.data.experiment.samples.items():
            if s.fcs_data is not None:
                self._active_sample_id = s_id
                break

        self._setup_ui()
        self._populate_matrix()
        self._update_plots()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter)

        # ── Left side: Matrix Editor ──
        left_widget = QSplitter(Qt.Orientation.Vertical)

        # Matrix Table
        self._table = QTableWidget()
        self._table.itemChanged.connect(self._on_cell_changed)
        self._table.setStyleSheet(
            f"background-color: {Colors.BG_DARKEST}; color: {Colors.FG_PRIMARY};"
        )
        left_widget.addWidget(self._table)

        splitter.addWidget(left_widget)

        # ── Right side: Visualization ──
        right_widget = QSplitter(Qt.Orientation.Vertical)

        # Controls
        controls_layout = QHBoxLayout()
        controls_layout.addWidget(QLabel("X Channel:"))
        self._x_combo = FlowComboBox()
        self._x_combo.currentIndexChanged.connect(self._update_plots)
        controls_layout.addWidget(self._x_combo)

        controls_layout.addWidget(QLabel("Y Channel:"))
        self._y_combo = FlowComboBox()
        self._y_combo.currentIndexChanged.connect(self._update_plots)
        controls_layout.addWidget(self._y_combo)
        controls_layout.addStretch()

        controls_widget = QSplitter(Qt.Orientation.Horizontal)
        controls_widget.setLayout(controls_layout)
        right_widget.addWidget(controls_widget)

        # Plot Canvas
        self._fig = Figure(figsize=(8, 4), facecolor=Colors.BG_DARKEST)
        self._canvas = FigureCanvasQTAgg(self._fig)
        self._ax_uncomp = self._fig.add_subplot(121)
        self._ax_comp = self._fig.add_subplot(122)
        right_widget.addWidget(self._canvas)

        splitter.addWidget(right_widget)
        splitter.setSizes([450, 650])

        # ── Bottom Buttons ──
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)

        btn_apply = QPushButton("Apply to Workspace")
        btn_apply.setStyleSheet(
            f"background: {Colors.ACCENT_PRIMARY}; color: {Colors.FG_PRIMARY}; font-weight: bold;"
        )
        btn_apply.clicked.connect(self._on_apply)
        btn_layout.addWidget(btn_apply)

        layout.addLayout(btn_layout)

    def _populate_matrix(self) -> None:
        self._table.blockSignals(True)
        if not self._temp_matrix:
            self._table.clear()
            self._table.setRowCount(0)
            self._table.setColumnCount(0)
            self._table.blockSignals(False)
            return

        channels = self._temp_matrix.channel_names
        n = len(channels)
        self._table.setRowCount(n)
        self._table.setColumnCount(n)
        self._table.setHorizontalHeaderLabels(channels)
        self._table.setVerticalHeaderLabels(channels)

        items = [(ch, ch) for ch in channels]
        first = channels[0] if channels else None
        repopulate_combo(self._x_combo, items, restore_data=first)
        repopulate_combo(
            self._y_combo,
            items,
            restore_data=channels[1] if n >= 2 else first,  # noqa: PLR2004
        )

        for i in range(n):
            for j in range(n):
                val = self._temp_matrix.matrix[i, j]
                item = QTableWidgetItem(f"{val:.4f}")
                if i == j:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    item.setBackground(QColor(Colors.BG_DARK))
                self._table.setItem(i, j, item)
        self._table.blockSignals(False)

    def _on_cell_changed(self, item: QTableWidgetItem) -> None:
        if not self._temp_matrix:
            return

        row = item.row()
        col = item.column()
        try:
            val = float(item.text())
            # Recreate matrix because we can't mutate the cached inverse easily
            m = self._temp_matrix.matrix.copy()
            m[row, col] = val
            self._temp_matrix = CompensationMatrix(
                matrix=m, channel_names=self._temp_matrix.channel_names
            )
            self._update_plots()
        except ValueError:
            pass  # Ignore invalid input

    def _update_plots(self) -> None:
        if not self._temp_matrix or not self._active_sample_id:
            return

        sample = self._state.data.experiment.samples.get(self._active_sample_id)
        if not sample or sample.fcs_data is None:
            return

        x_ch = self._x_combo.currentText()
        y_ch = self._y_combo.currentText()

        if not x_ch or not y_ch:
            return

        # Get raw data
        raw_events = getattr(sample.fcs_data, "raw_events", sample.fcs_data.events)
        if raw_events is None or x_ch not in raw_events.columns or y_ch not in raw_events.columns:
            return

        # Downsample for preview performance
        n_events = len(raw_events)
        if n_events > 10000:  # noqa: PLR2004
            # stable_subsample_mask, not Generator.choice — stable under
            # small population-size differences (see its docstring).
            from karcytics_plugins.flow_cytometry.analysis.rendering import stable_subsample_mask

            mask = stable_subsample_mask(n_events, 10000)
            df_raw = raw_events[mask].copy()
        else:
            df_raw = raw_events.copy()

        # Apply temporary compensation
        # To avoid altering the global state, we do it inline here for the sample data
        channels = self._temp_matrix.channel_names
        present = [ch for ch in channels if ch in df_raw.columns]
        if present:
            c_idx = [channels.index(ch) for ch in present]
            sub_matrix = self._temp_matrix.inverse[np.ix_(c_idx, c_idx)]
            raw_vals = df_raw[present].values
            comp_vals = raw_vals @ sub_matrix
            df_comp = df_raw.copy()
            df_comp[present] = comp_vals
        else:
            df_comp = df_raw

        self._ax_uncomp.clear()
        self._ax_comp.clear()

        # Plot uncompensated
        x_raw = df_raw[x_ch].values
        y_raw = df_raw[y_ch].values
        self._ax_uncomp.scatter(
            x_raw, y_raw, s=3, alpha=0.4, c=Colors.ACCENT_PRIMARY, edgecolors="none"
        )
        self._ax_uncomp.set_title("Uncompensated")
        self._ax_uncomp.set_xlabel(x_ch)
        self._ax_uncomp.set_ylabel(y_ch)

        # Plot compensated
        x_comp = df_comp[x_ch].values
        y_comp = df_comp[y_ch].values
        self._ax_comp.scatter(
            x_comp, y_comp, s=3, alpha=0.4, c=Colors.ACCENT_PRIMARY, edgecolors="none"
        )
        self._ax_comp.set_title("Compensated")
        self._ax_comp.set_xlabel(x_ch)

        # Apply symlog scale to better view flow data
        for ax in (self._ax_uncomp, self._ax_comp):
            ax.set_xscale("symlog", linthresh=100)
            ax.set_yscale("symlog", linthresh=100)
            ax.tick_params(colors=Colors.FG_PRIMARY)
            ax.xaxis.label.set_color(Colors.FG_PRIMARY)
            ax.yaxis.label.set_color(Colors.FG_PRIMARY)
            ax.title.set_color(Colors.FG_PRIMARY)
            for spine in ax.spines.values():
                spine.set_color(Colors.BORDER)

        self._fig.tight_layout()
        self._canvas.draw_idle()

    def _on_apply(self) -> None:
        if self._temp_matrix:
            self._state.data.compensation = self._temp_matrix
            self.accept()
        else:
            self.reject()
