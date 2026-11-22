"""A stacked widget as tall as its current page, not its tallest (the options panels)."""

from __future__ import annotations

from PySide6.QtWidgets import QSizePolicy, QStackedWidget, QWidget


class DynamicStackedWidget(QStackedWidget):
    """QStackedWidget whose height dynamically matches only the current active widget."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.currentChanged.connect(self._on_current_changed)

    def addWidget(self, widget: QWidget) -> int:  # noqa: N802 - Qt override
        idx = super().addWidget(widget)
        if idx != self.currentIndex():
            widget.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        else:
            widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        return idx

    def _on_current_changed(self, index: int) -> None:
        for i in range(self.count()):
            w = self.widget(i)
            if w is not None:
                if i == index:
                    w.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
                else:
                    w.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.updateGeometry()

    def sizeHint(self):
        w = self.currentWidget()
        return w.sizeHint() if w is not None else super().sizeHint()

    def minimumSizeHint(self):
        w = self.currentWidget()
        return w.minimumSizeHint() if w is not None else super().minimumSizeHint()
