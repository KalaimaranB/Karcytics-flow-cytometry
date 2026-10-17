"""Small styled building blocks shared by the Sample Lens widgets.

Everything goes through ``theme_manager.apply_style`` so a theme switch
restyles it, the same way the SDK components restyle themselves.
"""

from __future__ import annotations

from karcytics_sdk.plugin.components import BioHelpButton
from karcytics_sdk.plugin.theme_fallback import Fonts, theme_manager
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QWidget

# Categorical colours for populations and clusters: readable on both themes.
PALETTE = (
    "#58a6ff",
    "#3fb950",
    "#d29922",
    "#f778ba",
    "#a371f7",
    "#f0883e",
    "#39c5cf",
    "#ff7b72",
    "#7ee787",
    "#e3b341",
)

# Pill tones → theme token for text and border.
_TONES = {
    "neutral": "FG_SECONDARY",
    "accent": "ACCENT_PRIMARY",
    "success": "ACCENT_SUCCESS",
    "warning": "ACCENT_WARNING",
}


def palette_color(i: int) -> str:
    return PALETTE[i % len(PALETTE)]


def section_header(text: str, help_text: str = "") -> QWidget:
    """An uppercase sidebar section title, with a (?) popup when ``help_text`` is given."""
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    label = QLabel(text.upper())
    theme_manager.apply_style(
        label, "color: {FG_SECONDARY}; font-weight: bold; font-size: 11px; letter-spacing: 0.5px;"
    )
    layout.addWidget(label)
    if help_text:
        help_btn = BioHelpButton()
        help_btn.setHelpText(help_text, text)
        layout.addWidget(help_btn)
    layout.addStretch()
    return row


def card(object_name: str, background: str = "BG_DARK") -> QFrame:
    """A rounded, bordered frame."""
    frame = QFrame()
    frame.setObjectName(object_name)
    theme_manager.apply_style(
        frame,
        f"QFrame#{object_name} {{ background: {{{background}}}; border: 1px solid {{BORDER}};"
        " border-radius: 10px; }",
    )
    return frame


class Pill(QLabel):
    """A small rounded status chip whose tone can change."""

    def __init__(self, text: str = "", tone: str = "neutral") -> None:
        super().__init__(text)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.set_tone(tone)

    def set_tone(self, tone: str) -> None:
        fg = _TONES[tone]
        theme_manager.apply_style(
            self,
            f"QLabel {{ color: {{{fg}}}; background: {{BG_MEDIUM}}; border: 1px solid {{{fg}}};"
            f" border-radius: 9px; padding: 2px 8px; font-size: {Fonts.SIZE_SMALL}px;"
            " font-weight: 600; }",
        )
