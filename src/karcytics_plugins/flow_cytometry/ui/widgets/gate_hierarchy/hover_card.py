"""HoverCard — floating tooltip-style detail card for icicle blocks.

Single Responsibility: display gate statistics for a hovered IcicleRect.
Parented to the top-level window to escape sidebar clipping.
Auto-dismisses on mouse leave (handled by SampleViewWidget which calls hide()).
"""

from __future__ import annotations

from karcytics_sdk.plugin.theme_fallback import Colors, theme_manager
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QLabel,
    QWidget,
)

from .node_tree_engine import TreeNodeRect

# Palette mapping: must match IcicleLayoutEngine._DEPTH_COLORS index
_PALETTE = [
    "#7c4dff",  # 0 root — purple
    "#00bcd4",  # 1 — teal
    "#42a5f5",  # 2 — blue
    "#ffa726",  # 3 — orange
    "#ef5350",  # 4 — pink/red
    "#66bb6a",  # 5 — green
]


class HoverCard(QFrame):
    """Floating card that shows full stats for a hovered gate block.

    Create once, attach to the top-level window, then call show_for()
    whenever the hover target changes.
    """

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.ToolTip
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setFixedWidth(230)
        self._setup_ui()
        self.hide()

    # ── Public API ────────────────────────────────────────────────────

    def show_for(
        self,
        rect: TreeNodeRect,
        global_pos: QPoint,
        samples_gated: int = 0,
        total_samples: int = 0,
    ) -> None:
        """Populate and show the card near global_pos.

        Args:
            rect:            The IcicleRect being hovered.
            global_pos:      Global mouse/block position.
            samples_gated:   How many samples have this gate.
            total_samples:   Total number of samples.
        """
        color = (
            _PALETTE[rect.color_index]
            if 0 <= rect.color_index < len(_PALETTE)
            else Colors.FG_SECONDARY
        )

        # Title
        self._title.setText(rect.name)
        self._title.setStyleSheet(
            f"color: {color}; font-size: 12px; font-weight: 700; background: transparent;"
        )

        # Gate metadata
        if rect.gate_type:
            axes = f"{rect.x_param} · {rect.y_param}" if rect.x_param and rect.y_param else "—"
            self._gate_val.setText(rect.gate_type)
            self._axes_val.setText(axes)
            self._meta_frame.show()
        else:
            self._meta_frame.hide()

        # Stats
        self._events_val.setText(f"{rect.count:,}")
        self._pct_parent_val.setText(f"{rect.pct_parent:.1f}%")
        self._pct_total_val.setText(f"{rect.pct_total:.1f}%")

        # Cross-sample bar
        if total_samples > 0:
            filled = min(samples_gated, total_samples)
            dots = "▪" * filled + "░" * (total_samples - filled)
            self._samples_label.setText(f"{dots}  {samples_gated}/{total_samples} samples")
            self._samples_label.show()
        else:
            self._samples_label.hide()

        # Position: prefer above the cursor, shift left if near right edge
        pos = QPoint(global_pos.x() - 10, global_pos.y() - self.sizeHint().height() - 8)
        self.move(pos)
        self.adjustSize()
        self.show()
        self.raise_()

    # ── UI ────────────────────────────────────────────────────────────

    def _setup_ui(self) -> None:  # noqa: PLR0915
        theme_manager.apply_style(
            self,
            """
            HoverCard {
                background: {BG_MEDIUM};
                border: 1px solid {BORDER};
                border-radius: 8px;
            }
        """,
        )

        from PyQt6.QtWidgets import QVBoxLayout

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(6)

        # Title
        self._title = QLabel()
        self._title.setWordWrap(True)
        outer.addWidget(self._title)

        # Separator
        sep1 = QFrame()
        sep1.setFrameShape(QFrame.Shape.HLine)
        sep1.setStyleSheet(f"background: {Colors.BORDER}; max-height: 1px;")
        outer.addWidget(sep1)

        # Gate metadata (type + axes)
        self._meta_frame = QWidget()
        meta_layout = QGridLayout(self._meta_frame)
        meta_layout.setContentsMargins(0, 0, 0, 0)
        meta_layout.setSpacing(4)

        def _lbl(text: str, bold: bool = False) -> QLabel:
            lbl = QLabel(text)
            fw = "600" if bold else "400"
            lbl.setStyleSheet(
                f"color: {Colors.FG_SECONDARY}; font-size: 10px;"
                f" font-weight: {fw}; background: transparent;"
            )
            return lbl

        def _val(text: str = "") -> QLabel:
            lbl = QLabel(text)
            lbl.setStyleSheet(
                f"color: {Colors.FG_PRIMARY}; font-size: 11px;"
                " font-weight: 500; background: transparent;"
            )
            return lbl

        meta_layout.addWidget(_lbl("Gate"), 0, 0)
        self._gate_val = _val()
        meta_layout.addWidget(self._gate_val, 0, 1)

        meta_layout.addWidget(_lbl("Axes"), 1, 0)
        self._axes_val = _val()
        meta_layout.addWidget(self._axes_val, 1, 1)

        outer.addWidget(self._meta_frame)

        # Separator
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"background: {Colors.BORDER}; max-height: 1px;")
        outer.addWidget(sep2)

        # Stats grid
        stats = QWidget()
        stats_layout = QGridLayout(stats)
        stats_layout.setContentsMargins(0, 0, 0, 0)
        stats_layout.setSpacing(4)

        for col, header in enumerate(["Events", "%Parent", "%Total"]):
            h = _lbl(header, bold=True)
            h.setAlignment(Qt.AlignmentFlag.AlignCenter)
            stats_layout.addWidget(h, 0, col)

        self._events_val = _val()
        self._events_val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._pct_parent_val = _val()
        self._pct_parent_val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._pct_total_val = _val()
        self._pct_total_val.setAlignment(Qt.AlignmentFlag.AlignCenter)

        stats_layout.addWidget(self._events_val, 1, 0)
        stats_layout.addWidget(self._pct_parent_val, 1, 1)
        stats_layout.addWidget(self._pct_total_val, 1, 2)

        outer.addWidget(stats)

        # Cross-sample bar
        sep3 = QFrame()
        sep3.setFrameShape(QFrame.Shape.HLine)
        sep3.setStyleSheet(f"background: {Colors.BORDER}; max-height: 1px;")
        outer.addWidget(sep3)

        self._samples_label = QLabel()
        self._samples_label.setStyleSheet(
            f"color: {Colors.FG_SECONDARY}; font-size: 10px; background: transparent;"
        )
        outer.addWidget(self._samples_label)
