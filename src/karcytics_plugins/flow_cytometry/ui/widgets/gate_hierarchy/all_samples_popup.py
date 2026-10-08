"""AllSamplesPopup — floating heatmap panel showing all samples × populations.

Single Responsibility: render the cross-sample heatmap. The popup shell
(title bar, close button, Escape-to-close, frozen-branch-label column +
scrollable heat-cell columns, positioning, theming) lives in
`FloatingGridPopup` and is shared with the interactive population selection
popup (`ui/widgets/selection/population_selection_popup.py`) — this class
only supplies the heatmap-specific pieces: the model, the legend, and the
painted `_HeatCell`.

Opens as an application-level floating QFrame, not a modal dialog. Dismissed
only by pressing Escape or clicking its own × button — deliberately NOT by
clicking elsewhere, so it can stay open while the rest of the app is used
(e.g. scrolling other panels, or a tutorial step reading it alongside other
widgets) without vanishing the moment something else is clicked.
"""

from __future__ import annotations

from karcytics_sdk.plugin.theme_fallback import Colors
from PyQt6.QtCore import QRect, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QWidget

from .all_samples_model import AllSamplesModel, PopulationRow
from .floating_grid_popup import _PALETTE_HEX, FloatingGridPopup

_HEAT_TEXT_COLOR = "#e6edf3"


def _saturate(hex_color: str, pct: float) -> str:
    """Darken a colour proportionally to low event percentage."""
    c = QColor(hex_color)
    h, s, v, a = c.getHsvF()

    _h = h if h is not None else 0.0
    _s = s if s is not None else 0.0
    _v = v if v is not None else 0.0
    _a = a if a is not None else 1.0

    new_v = max(0.18, _v * (0.35 + 0.65 * pct / 100.0))
    new_s = max(0.2, _s * (0.35 + 0.65 * pct / 100.0))
    c.setHsvF(_h, new_s, new_v, _a)
    return c.name()


class AllSamplesPopup(FloatingGridPopup):
    """Floating popup showing the full cross-sample heatmap with tree branches.

    Usage::
        popup = AllSamplesPopup(parent_widget)
        popup.show_near(trigger_button, state, reference_sample_id)
    """

    sample_selected = pyqtSignal(str)  # Emitted when a column header is clicked

    def __init__(self, parent: QWidget | None = None) -> None:
        self._model = AllSamplesModel()
        super().__init__(
            parent,
            object_name="AllSamplesOverviewPopup",
            title_text="⊞  All Samples — Population Overview",
        )

    # ── Public API ────────────────────────────────────────────────────

    def show_near(  # type: ignore[override]
        self,
        trigger: QWidget,
        state,
        reference_sample_id: str,
    ) -> None:
        """Rebuild content and show the popup anchored below the trigger widget.

        Args:
            trigger:             Button or widget that was clicked.
            state:               FlowState — read-only.
            reference_sample_id: Sample whose gate tree defines row order.
        """
        self._model.build(state, reference_sample_id)
        self._rebuild_grid()
        super().show_near(trigger)

    # ── UI ────────────────────────────────────────────────────────────

    def _build_toolbar(self) -> QWidget | None:
        legend = QWidget()
        self._legend = legend
        legend.setFixedHeight(28)
        legend_layout = QHBoxLayout(legend)
        legend_layout.setContentsMargins(14, 0, 14, 0)
        legend_layout.setSpacing(16)

        # (dot, the theme colour it takes) and the labels, styled in _apply_theme_styles.
        self._legend_dots: list[tuple[QLabel, str]] = []
        self._legend_labels: list[QLabel] = []
        for dot_token, label_text in [
            ("ACCENT_PRIMARY", "Gated"),
            ("FG_DISABLED", "Not applied"),
            ("BORDER", "0 events"),
        ]:
            dot = QLabel("●")
            lbl = QLabel(label_text)
            self._legend_dots.append((dot, dot_token))
            self._legend_labels.append(lbl)
            legend_layout.addWidget(dot)
            legend_layout.addWidget(lbl)

        legend_layout.addStretch()
        return legend

    def _apply_theme_styles(self) -> None:
        super()._apply_theme_styles()
        if hasattr(self, "_legend"):
            self._legend.setStyleSheet(
                f"background: {Colors.BG_DARK}; border-top: 1px solid {Colors.BORDER};"
            )
            for dot, token in self._legend_dots:
                dot.setStyleSheet(
                    f"color: {getattr(Colors, token)}; font-size: 10px; background: transparent;"
                )
            for lbl in self._legend_labels:
                lbl.setStyleSheet(
                    f"color: {Colors.FG_SECONDARY}; font-size: 10px; background: transparent;"
                )

    def _rebuild_grid(self) -> None:
        """Clear and repopulate the grid from the current model."""
        self._populate_grid(
            self._model.rows,
            self._model.sample_ids,
            self._model.sample_display_names,
            cell_factory=lambda row, sid, col_w: _HeatCell(
                row.color_index, row.cells.get(sid), col_w
            ),
            on_header_clicked=self.sample_selected.emit,
            empty_message="No gates found on the reference sample.",
        )


class _HeatCell(QWidget):
    """One heatmap cell: coloured block with percentage text."""

    def __init__(
        self,
        color_index: int,
        value: float | None,
        col_width: int = 64,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._color_index = color_index
        self._value = value
        self.setFixedSize(col_width, 30)

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self._value is None:
            # Not applied
            fill = QColor(Colors.BG_MEDIUM)
            text_color = QColor(Colors.FG_DISABLED)
            label = "—"
        elif self._value == 0.0:
            fill = QColor(Colors.BG_DARK)
            text_color = QColor(Colors.FG_DISABLED)
            label = "0%"
        else:
            base = _PALETTE_HEX[self._color_index % len(_PALETTE_HEX)]
            fill = QColor(_saturate(base, self._value))
            # The fill is the population's own colour in every theme.
            text_color = QColor(_HEAT_TEXT_COLOR)
            label = f"{self._value:.1f}%"

        path = QPainterPath()
        path.addRoundedRect(QRectF(1, 1, self.width() - 2, self.height() - 2), 4, 4)
        painter.fillPath(path, fill)

        font = QFont("Inter, sans-serif", 9)
        painter.setFont(font)
        painter.setPen(text_color)
        painter.drawText(
            QRect(0, 0, self.width(), self.height()),
            Qt.AlignmentFlag.AlignCenter,
            label,
        )
        painter.end()


__all__ = ["AllSamplesPopup", "PopulationRow"]
