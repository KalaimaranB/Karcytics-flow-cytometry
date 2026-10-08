"""PropagationToggle — a pill-shaped ON/OFF toggle widget.

Single Responsibility: render and emit the toggle state.
No knowledge of what propagation means — it just signals.
"""

from __future__ import annotations

from karcytics_sdk.plugin.theme_fallback import Colors
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget


class PropagationToggle(QWidget):
    """Pill-shaped AUTO-PROPAGATE toggle.

    Signals:
        propagation_mode_changed(bool): Emitted whenever the toggle flips.
            True  = propagation ON (default).
            False = propagation OFF.
    """

    propagation_mode_changed = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._enabled = True
        self._setup_ui()

    # ── Properties ────────────────────────────────────────────────────

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    # ── UI ────────────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(6)

        self._label = QLabel("AUTO-PROPAGATE")
        self._label.setStyleSheet(
            f"color: {Colors.FG_SECONDARY}; font-size: 10px; font-weight: 600;"
            " letter-spacing: 0.5px; background: transparent;"
        )

        self._pill = QPushButton()
        self._pill.setCheckable(True)
        self._pill.setChecked(True)
        self._pill.setFixedSize(42, 22)
        self._pill.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pill.clicked.connect(self._on_clicked)
        self._refresh_pill_style()

        layout.addWidget(self._label)
        layout.addStretch()
        layout.addWidget(self._pill)

    def _on_clicked(self) -> None:
        self._enabled = self._pill.isChecked()
        self._refresh_pill_style()
        self.propagation_mode_changed.emit(self._enabled)

    def _refresh_pill_style(self) -> None:
        if self._enabled:
            self._pill.setStyleSheet(f"""
                QPushButton {{
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                        stop:0 {Colors.ACCENT_PRIMARY}, stop:1 {Colors.ACCENT_PRIMARY_PRESSED});
                    border-radius: 11px;
                    border: none;
                }}
                QPushButton::indicator {{ width: 0px; }}
            """)
            self._label.setStyleSheet(
                f"color: {Colors.ACCENT_PRIMARY}; font-size: 10px; font-weight: 600;"
                " letter-spacing: 0.5px; background: transparent;"
            )
        else:
            self._pill.setStyleSheet(f"""
                QPushButton {{
                    background: {Colors.BG_MEDIUM};
                    border-radius: 11px;
                    border: 1px solid {Colors.BORDER};
                }}
                QPushButton::indicator {{ width: 0px; }}
            """)
            self._label.setStyleSheet(
                f"color: {Colors.FG_SECONDARY}; font-size: 10px; font-weight: 600;"
                " letter-spacing: 0.5px; background: transparent;"
            )

    def _apply_theme_styles(self) -> None:
        """Dynamically refresh colors when theme changes."""
        self._refresh_pill_style()
