"""Render Settings Dialog — tabbed, per-mode scientist-friendly settings.

Each tab hosts an independent panel class from ``render_panels/``.
This dialog is purely a coordinator — all business logic lives in the panels.
"""

from __future__ import annotations

from typing import Any

from karcytics_sdk.plugin import get_logger
from karcytics_sdk.plugin.theme_fallback import theme_manager
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from karcytics_plugins.flow_cytometry.analysis.config import RenderConfig
from karcytics_plugins.flow_cytometry.analysis.state import FlowState

from .flow_canvas import DisplayMode
from .render_panels import (
    ContourSettingsPanel,
    DotPlotSettingsPanel,
    HistogramSettingsPanel,
    PseudocolorSettingsPanel,
)

logger = get_logger(__name__, "flow_cytometry")

# Map DisplayMode → tab index (must match addTab order below)
_MODE_TAB = {
    DisplayMode.PSEUDOCOLOR: 0,
    DisplayMode.DOT_PLOT: 1,
    DisplayMode.HISTOGRAM: 2,
    DisplayMode.CONTOUR: 3,
}


def _scrollable(panel: QWidget) -> QScrollArea:
    """Wrap a panel in a scroll area so it works on small screens."""
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setFrameShape(QScrollArea.Shape.NoFrame)
    theme_manager.apply_style(sa, "background: {BG_DARKEST};")
    sa.setWidget(panel)
    return sa


class RenderSettingsDialog(QDialog):
    """Context-sensitive rendering settings dialog.

    Shows only the settings relevant to the currently active plot type
    (e.g., Pseudocolor, Dot Plot, etc.) to keep the UI clean and scientist-friendly.
    """

    settings_applied = pyqtSignal(RenderConfig)

    def __init__(self, state: FlowState, parent: QWidget | None = None):
        super().__init__(parent)
        self._state = state
        self._cfg = RenderConfig.from_dict(state.view.render_config.to_dict())

        # Determine current sample event count for adaptive caps
        self._sample_n = self._get_sample_event_count()

        # Determine active mode
        self._active_mode = self._get_active_mode()

        self.setWindowTitle(f"{self._active_mode.value} Settings")
        self.setMinimumWidth(440)
        self.setMinimumHeight(650)
        self.setModal(False)  # Modeless — user can interact with plot while tweaking
        theme_manager.apply_style(self, "background: {BG_DARKEST}; color: {FG_PRIMARY};")

        self._active_panel: Any | None = None
        self._setup_ui()

    # ── Setup ─────────────────────────────────────────────────────────

    def _get_active_mode(self) -> DisplayMode:
        """Map the string state to the DisplayMode enum."""
        try:
            mode_str = self._state.view.active_plot_type
            for mode in DisplayMode:
                if mode.value.lower() == mode_str.lower():
                    return mode
        except Exception:
            pass
        return DisplayMode.PSEUDOCOLOR

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 12)

        # Header
        header = QLabel(f"  {self._active_mode.value} Settings")
        theme_manager.apply_style(
            header,
            "font-size: 15px; font-weight: 700; color: {FG_PRIMARY};"
            " background: {BG_DARK}; padding: 14px 16px;"
            " border-bottom: 1px solid {BORDER};",
        )
        root.addWidget(header)

        sub = QLabel("  Changes apply globally to all open plots")
        theme_manager.apply_style(
            sub,
            "font-size: 11px; color: {FG_SECONDARY};"
            " background: {BG_DARK}; padding: 4px 16px 10px 16px;"
            " border-bottom: 1px solid {BORDER};",
        )
        root.addWidget(sub)

        # Instantiate only the active panel
        mode = self._active_mode
        if mode == DisplayMode.PSEUDOCOLOR:
            self._active_panel = PseudocolorSettingsPanel(self._cfg.pseudocolor, self._sample_n)
        elif mode == DisplayMode.DOT_PLOT:
            self._active_panel = DotPlotSettingsPanel(self._cfg.dot_plot, self._sample_n)
        elif mode in (DisplayMode.HISTOGRAM, DisplayMode.CDF):
            self._active_panel = HistogramSettingsPanel(self._cfg.histogram)
        elif mode == DisplayMode.CONTOUR:
            self._active_panel = ContourSettingsPanel(self._cfg.contour)
        else:
            # Fallback to Pseudocolor if something goes wrong
            self._active_panel = PseudocolorSettingsPanel(self._cfg.pseudocolor, self._sample_n)

        # Wrap in scroll area
        root.addWidget(_scrollable(self._active_panel), stretch=1)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(12, 8, 12, 0)

        self._btn_reset = QPushButton("Reset to Defaults")
        self._btn_reset.setToolTip("Reset settings to factory defaults.")
        self._btn_reset.setFixedHeight(30)
        theme_manager.apply_style(self._btn_reset, self._flat_btn_style())
        self._btn_reset.clicked.connect(self._reset_current_panel)

        self._btn_apply = QPushButton("Apply")
        self._btn_apply.setFixedHeight(30)
        theme_manager.apply_style(
            self._btn_apply,
            "QPushButton { background: {ACCENT_PRIMARY}; color: {BG_DARKEST};"
            " border: none; border-radius: 4px; font-size: 12px; font-weight: 700;"
            " padding: 2px 20px; }",
        )
        self._btn_apply.clicked.connect(self._apply)

        self._btn_close = QPushButton("Close")
        self._btn_close.setFixedHeight(30)
        theme_manager.apply_style(self._btn_close, self._flat_btn_style())
        self._btn_close.clicked.connect(self.accept)

        btn_row.addWidget(self._btn_reset)
        btn_row.addStretch()
        btn_row.addWidget(self._btn_close)
        btn_row.addWidget(self._btn_apply)
        root.addLayout(btn_row)

    # ── Helpers ───────────────────────────────────────────────────────

    def _get_sample_event_count(self) -> int:
        """Return the event count of the active sample, or max of any sample."""
        try:
            # Try current sample first
            sid = self._state.view.current_sample_id
            if sid:
                sample = self._state.data.experiment.samples.get(sid)
                if sample and sample.fcs_data and sample.fcs_data.events is not None:
                    return len(sample.fcs_data.events)

            # Fallback: check all loaded samples and take the max
            counts = [
                len(s.fcs_data.events)
                for s in self._state.data.experiment.samples.values()
                if s.fcs_data and s.fcs_data.events is not None
            ]
            if counts:
                return max(counts)
        except Exception:
            pass
        return 100_000

    def _flat_btn_style(self) -> str:
        # Return a theme_manager template string, not a pre-baked f-string.
        return (
            "QPushButton { background: {BG_MEDIUM}; color: {FG_PRIMARY};"
            " border: 1px solid {BORDER}; border-radius: 4px; font-size: 12px;"
            " font-weight: 600; padding: 2px 14px; }"
            "QPushButton:hover { color: {ACCENT_PRIMARY}; }"
        )

    def _reset_current_panel(self) -> None:
        """Reset the active panel to its dataclass defaults."""
        defaults = RenderConfig()
        mode = self._active_mode
        if mode == DisplayMode.PSEUDOCOLOR:
            assert self._active_panel is not None
            self._active_panel.set_config(defaults.pseudocolor)
        elif mode == DisplayMode.DOT_PLOT:
            assert self._active_panel is not None
            self._active_panel.set_config(defaults.dot_plot)
        elif mode in (DisplayMode.HISTOGRAM, DisplayMode.CDF):
            assert self._active_panel is not None
            self._active_panel.set_config(defaults.histogram)
        elif mode == DisplayMode.CONTOUR:
            assert self._active_panel is not None
            self._active_panel.set_config(defaults.contour)

    def _apply(self) -> None:
        """Collect configs from the active panel and emit."""
        mode = self._active_mode
        if mode == DisplayMode.PSEUDOCOLOR:
            assert self._cfg is not None
            self._cfg.pseudocolor = self._active_panel.get_config()  # type: ignore
        elif mode == DisplayMode.DOT_PLOT:
            assert self._cfg is not None
            self._cfg.dot_plot = self._active_panel.get_config()  # type: ignore
        elif mode in (DisplayMode.HISTOGRAM, DisplayMode.CDF):
            assert self._cfg is not None
            self._cfg.histogram = self._active_panel.get_config()  # type: ignore
        elif mode == DisplayMode.CONTOUR:
            assert self._cfg is not None
            self._cfg.contour = self._active_panel.get_config()  # type: ignore

        logger.info(f"RenderSettingsDialog: applying config for {mode.value}")
        self.settings_applied.emit(self._cfg)
