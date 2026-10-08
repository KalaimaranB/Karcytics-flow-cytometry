"""Transform and scaling dialog.

Allows the user to adjust axis limits and transformation parameters
(Linear, Log, Biexponential/Logicle) interactively.
"""

from __future__ import annotations

from collections.abc import Callable

from karcytics_sdk.plugin import get_logger
from karcytics_sdk.plugin.theme_fallback import Colors, Fonts
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from karcytics_plugins.flow_cytometry.analysis.scaling import AxisScale

from .components.transform_widgets import AxisTransformPanel

logger = get_logger(__name__, "flow_cytometry")


class TransformDialog(QDialog):
    """Dialog housing multi-axis scaling configuration panels.

    Signals:
        scale_changed(str, AxisScale): emitted when either axis is modified locally.
        apply_to_all_requested(str, AxisScale): emitted when user hits Apply to All perfectly.
    """

    scale_changed = Signal(str, object)  # axis: 'x' or 'y', AxisScale
    apply_to_all_requested = Signal(str, object)  # axis: 'x' or 'y', AxisScale

    def __init__(  # noqa: PLR0913
        self,
        x_name: str,
        y_name: str,
        x_scale: AxisScale,
        y_scale: AxisScale,
        auto_range_x_callback: Callable[[], tuple[float, float]],
        auto_range_y_callback: Callable[[], tuple[float, float]],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Axis Scaling & Transforms")
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowStaysOnTopHint)
        self.setModal(False)
        self.resize(380, 520)
        self.setStyleSheet(
            f"QDialog {{ background: {Colors.BG_DARKEST}; }}"
            f"QTabWidget::pane {{ border: 1px solid {Colors.BORDER}; background: {Colors.BG_DARK}; border-radius: 4px; }}"
            f"QTabBar::tab {{ background: {Colors.BG_MEDIUM}; color: {Colors.FG_SECONDARY}; padding: 6px 12px; }}"
            f"QTabBar::tab:selected {{ background: {Colors.BG_DARK}; color: {Colors.FG_PRIMARY}; border-top: 2px solid {Colors.ACCENT_PRIMARY}; }}"
        )

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        self._tabs = QTabWidget()

        self._x_panel = AxisTransformPanel(x_name, x_scale, auto_range_x_callback, self)  # type: ignore
        self._y_panel = AxisTransformPanel(y_name, y_scale, auto_range_y_callback, self)  # type: ignore

        self._x_panel.scale_changed.connect(
            lambda: self.scale_changed.emit("x", self._x_panel.scale)
        )
        self._y_panel.scale_changed.connect(
            lambda: self.scale_changed.emit("y", self._y_panel.scale)
        )

        self._tabs.addTab(self._x_panel, f"X-Axis: {x_name}")
        self._tabs.addTab(self._y_panel, f"Y-Axis: {y_name}")
        layout.addWidget(self._tabs)

        # ── Apply to All ──────────────────────────────────────────────
        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {Colors.BORDER};")
        layout.addWidget(sep)

        lbl_hint = QLabel(
            "Scale settings are synchronized natively.\n"
            "Changes immediately affect all samples mapping this channel."
        )
        lbl_hint.setStyleSheet(
            f"color: {Colors.FG_DISABLED}; font-size: {Fonts.SIZE_SMALL}px; font-style: italic;"
        )
        lbl_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_hint.setWordWrap(True)
        layout.addWidget(lbl_hint)

    @property
    def x_scale(self) -> AxisScale:
        return self._x_panel.scale

    @property
    def y_scale(self) -> AxisScale:
        return self._y_panel.scale
