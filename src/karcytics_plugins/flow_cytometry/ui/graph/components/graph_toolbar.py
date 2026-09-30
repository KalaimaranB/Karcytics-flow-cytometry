"""Graph Toolbar — Navigation and breadcrumbs for GraphWindow."""

from __future__ import annotations

from karcytics_sdk.plugin.theme_fallback import Fonts, theme_manager
from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QWidget


class ElidedLabel(QLabel):
    """A QLabel that elides its text in the middle when space is constrained."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._full_text = ""
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(30)

    def setText(self, text: str | None) -> None:
        self._full_text = text or ""
        self._update_elided_text()

    def text(self) -> str:
        return self._full_text

    def minimumSizeHint(self) -> QSize:
        return QSize(30, super().minimumSizeHint().height())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_elided_text()

    def _update_elided_text(self) -> None:
        # Subtract ~20px to account for the left and right padding from the stylesheet
        available_width = self.width() - 20
        if available_width > 0:
            fm = self.fontMetrics()
            elided = fm.elidedText(self._full_text, Qt.TextElideMode.ElideMiddle, available_width)
            super().setText(elided)
        else:
            super().setText("")


class GraphToolbar(QWidget):
    """Navigation and breadcrumbs for GraphWindow."""

    navigation_requested = pyqtSignal(str)  # "next_sample", "prev_sample", "parent_gate"

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Prev / Next sample arrows
        self._btn_prev = QPushButton("◀ Prev Sample")
        self._btn_next = QPushButton("Next Sample ▶")
        for btn in (self._btn_prev, self._btn_next):
            btn.setFixedHeight(24)
            self._style_btn(btn)
            layout.addWidget(btn)

        self._btn_prev.clicked.connect(lambda: self.navigation_requested.emit("prev_sample"))
        self._btn_next.clicked.connect(lambda: self.navigation_requested.emit("next_sample"))

        layout.addSpacing(16)

        # Up to parent button
        self._btn_parent = QPushButton("↑ Parent Gate")
        self._btn_parent.setFixedHeight(24)
        self._style_btn(self._btn_parent)
        self._btn_parent.setVisible(False)
        self._btn_parent.clicked.connect(lambda: self.navigation_requested.emit("parent_gate"))
        layout.addWidget(self._btn_parent)

        self._breadcrumb = ElidedLabel()
        theme_manager.apply_style(
            self._breadcrumb,
            f"color: {{FG_SECONDARY}}; font-size: {Fonts.SIZE_SMALL}px;"
            " background: {BG_DARK}; padding: 4px 8px;"
            " border-radius: 4px;",
        )
        layout.addWidget(self._breadcrumb)
        layout.addStretch()

    def _style_btn(self, btn: QPushButton) -> None:
        theme_manager.apply_style(
            btn,
            "QPushButton { background: {BG_MEDIUM};"
            " color: {FG_PRIMARY}; border: 1px solid {BORDER};"
            " border-radius: 3px; font-size: 11px; font-weight: 600; padding: 2px 8px; }"
            "QPushButton:hover { background: {BG_DARK};"
            " color: {ACCENT_PRIMARY}; }",
        )

    def set_parent_button_visible(self, visible: bool) -> None:
        self._btn_parent.setVisible(visible)

    def set_breadcrumb_text(self, text: str) -> None:
        self._breadcrumb.setText(text)
