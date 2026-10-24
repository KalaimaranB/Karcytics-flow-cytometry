"""The panel skeleton's own styles, and the pass that restyles every child on a theme change."""

from __future__ import annotations

from karcytics_sdk.plugin.theme_fallback import Colors, Fonts
from PySide6.QtWidgets import QWidget


def palette_key() -> tuple[str, ...]:
    """The colours the skeleton uses; unchanged means a restyle has nothing to do."""
    return (
        Colors.BG_DARKEST,
        Colors.BG_DARK,
        Colors.BG_MEDIUM,
        Colors.FG_PRIMARY,
        Colors.FG_SECONDARY,
        Colors.ACCENT_PRIMARY,
        Colors.BORDER,
    )


def tab_bar_qss() -> str:
    return (
        f"QTabBar {{ background: {Colors.BG_DARKEST}; border: none; }}"
        f"QTabBar::tab {{ background: {Colors.BG_DARK}; color: {Colors.FG_SECONDARY}; "
        "padding: 10px 20px; border: none; border-bottom: 2px solid transparent; "
        f"font-size: {Fonts.SIZE_SMALL}px; font-weight: 600; }}"
        f"QTabBar::tab:selected {{ color: {Colors.ACCENT_PRIMARY}; "
        f"border-bottom: 2px solid {Colors.ACCENT_PRIMARY}; background: {Colors.BG_DARKEST}; }}"
        f"QTabBar::tab:hover {{ color: {Colors.FG_PRIMARY}; background: {Colors.BG_MEDIUM}; }}"
    )


def ribbon_stack_qss() -> str:
    return f"background: {Colors.BG_DARK}; border-bottom: 1px solid {Colors.BORDER};"


def restyle_children(root: QWidget, keep: tuple[QWidget, ...]) -> None:
    """Asks every child under `root` to restyle itself for the new palette.

    A child with no theme hook gets its own stylesheet re-set, so one written
    with the old colours is re-polished; `keep` (already styled) is left alone.
    """
    for child in root.findChildren(QWidget):
        # karcytics: allow KS342 - _apply_theme_styles is the SDK widgets' theme hook
        hook = getattr(child, "_apply_theme_styles", None)
        restyle = hook or getattr(child, "refresh_styles", None)
        if restyle is not None:
            restyle()
        elif child.styleSheet() and child not in keep:
            child.setStyleSheet(child.styleSheet())
        child.update()
