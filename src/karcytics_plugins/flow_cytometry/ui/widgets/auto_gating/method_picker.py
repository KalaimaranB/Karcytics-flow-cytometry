"""The methods as cards, one chosen at a time. Built from ``PICKABLE``."""

from __future__ import annotations

from karcytics_sdk.plugin.theme_fallback import Fonts, theme_manager
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from ....analysis.autogate import MethodInfo
from ....analysis.autogate.models import PCA, PICKABLE

_ON = (
    "QFrame#{name} {{ background: {{BG_MEDIUM}}; border: 1px solid {{ACCENT_PRIMARY}};"
    " border-radius: 8px; }}"
)
_OFF = (
    "QFrame#{name} {{ background: {{BG_DARK}}; border: 1px solid {{BORDER}}; border-radius: 8px; }}"
    " QFrame#{name}:hover {{ border: 1px solid {{FG_SECONDARY}}; }}"
)


class _MethodCard(QFrame):
    clicked = Signal()

    def __init__(self, info: MethodInfo) -> None:
        super().__init__()
        self.info = info
        self.setObjectName(f"AutoGateMethod_{info.key}")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(info.name)
        self.setAccessibleDescription(info.blurb)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(3)
        title = QLabel(info.name)
        theme_manager.apply_style(
            title,
            f"color: {{FG_PRIMARY}}; font-weight: bold; font-size: {Fonts.SIZE_NORMAL}px;"
            " background: transparent; border: none;",
        )
        blurb = QLabel(info.blurb)
        blurb.setWordWrap(True)
        theme_manager.apply_style(
            blurb,
            f"color: {{FG_SECONDARY}}; font-size: {Fonts.SIZE_SMALL}px; background: transparent; border: none;",
        )
        layout.addWidget(title)
        layout.addWidget(blurb)
        self.set_on(False)

    def set_on(self, on: bool) -> None:
        template = _ON if on else _OFF
        theme_manager.apply_style(self, template.format(name=self.objectName()))

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt override
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.clicked.emit()
            return
        super().keyPressEvent(event)


class MethodPicker(QWidget):
    method_changed = Signal(str)  # method key

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self._cards = [_MethodCard(info) for info in PICKABLE]
        for card in self._cards:
            card.clicked.connect(self._on_card_clicked)
            layout.addWidget(card)
        self._key = ""
        self.set_method(PCA.key)

    def method_key(self) -> str:
        return self._key

    def set_method(self, key: str) -> None:
        if key == self._key:
            return
        self._key = key
        for card in self._cards:
            card.set_on(card.info.key == key)
        self.method_changed.emit(key)

    def _on_card_clicked(self) -> None:
        card = self.sender()
        if isinstance(card, _MethodCard):
            self.set_method(card.info.key)
