"""Centralized checkbox/tickbox theming.

Every checkable control in the Statistics and Comparisons tabs (plain
QCheckBox settings, checkable QListWidget sample rows, checkable QTreeWidget
population rows) previously styled only the text colour/font-size and left
the checkbox glyph itself unstyled (plain OS default), independently
duplicated per file. Qt supports skinning the glyph itself via
``::indicator`` QSS pseudo-elements on any of these widget types, so one
shared stylesheet fragment is enough to make every tickbox in both tabs look
and behave identically — no custom paint delegate needed.
"""

from __future__ import annotations

from karcytics_sdk.plugin.theme_fallback import Colors, Fonts


def _get_theme_tokens():
    return Colors, Fonts


def checkbox_qss() -> str:
    """Themed QSS for every tickbox idiom used across the two tabs.

    Covers plain ``QCheckBox`` widgets (options panels, the Statistics
    checkbox list) and the native item checkboxes of ``QListWidget``/
    ``QTreeWidget`` (sample checklists, population trees). Callers append
    this to whatever container stylesheet they already build, e.g.::

        widget.setStyleSheet(f"QListWidget {{ ... }}" + checkbox_qss())
    """
    Colors, Fonts = _get_theme_tokens()
    indicator_selectors = "QCheckBox::indicator, QListWidget::indicator, QTreeWidget::indicator"
    return (
        f"QCheckBox {{ color: {Colors.FG_PRIMARY}; font-size: {Fonts.SIZE_SMALL}px; spacing: 6px; }}"
        f"{indicator_selectors} {{"
        f" width: 14px; height: 14px; border-radius: 3px;"
        f" border: 1px solid {Colors.BORDER}; background: {Colors.BG_MEDIUM}; }}"
        f"QCheckBox::indicator:hover, QListWidget::indicator:hover, QTreeWidget::indicator:hover {{"
        f" border: 1px solid {Colors.ACCENT_PRIMARY}; }}"
        f"QCheckBox::indicator:checked, QListWidget::indicator:checked, QTreeWidget::indicator:checked {{"
        f" background: {Colors.ACCENT_PRIMARY}; border: 1px solid {Colors.ACCENT_PRIMARY}; }}"
        f"QCheckBox::indicator:disabled, QListWidget::indicator:disabled, QTreeWidget::indicator:disabled {{"
        f" border: 1px solid {Colors.FG_DISABLED}; background: {Colors.BG_DARKEST}; }}"
    )
