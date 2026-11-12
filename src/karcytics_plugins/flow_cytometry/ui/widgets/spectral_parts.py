"""Parts of the Spectral viewer: its drop target, toggle buttons and FPbase citation.

Every spectrum in the viewer comes from FPbase's public GraphQL API (see
analysis/biology_services.py), so the source and its paper are shown under
both sub-tabs, one click away.
"""

from __future__ import annotations

from collections.abc import Callable

from karcytics_sdk.plugin.components import BioHelpButton, BioToggleButton
from karcytics_sdk.plugin.theme_fallback import Colors, Fonts, theme_manager
from PySide6.QtCore import Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QListWidget, QVBoxLayout, QWidget

CITATION_NAME = "SpectralCitation"  # the Academy spotlights it by this name


def fpbase_citation_html(link_color: str) -> str:
    link = f"style='color: {link_color};'"
    return (
        f"Spectra: <a {link} href='https://www.fpbase.org'>FPbase</a>, an open, "
        "community-maintained database. Lambert TJ. FPbase: a community-editable "
        "fluorescent protein database. <i>Nature Methods</i> 16, 277–278 (2019). "
        f"<a {link} href='https://doi.org/10.1038/s41592-019-0352-8'>"
        "doi:10.1038/s41592-019-0352-8</a>"
    )


class CitationLabel(QLabel):
    """The citation, with working links, in the theme's colors."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName(CITATION_NAME)
        self.setWordWrap(True)
        self.setOpenExternalLinks(True)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        theme_manager.apply_style(
            self,
            f"color: {{FG_SECONDARY}}; font-size: {Fonts.SIZE_SMALL}px; padding: 4px 16px 8px 16px;",
        )
        self.restyle()

    def restyle(self) -> None:
        """Re-color the links (their color is in the text, not the stylesheet)."""
        self.setText(fpbase_citation_html(Colors.ACCENT_PRIMARY))


class DropCanvas(QFrame):
    """Transparent frame around the plot; takes items dragged from ``source``."""

    def __init__(
        self,
        source: QListWidget,
        on_drop: Callable[[str, str], None],  # (item data, item text)
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._source = source
        self._on_drop = on_drop
        self.setAcceptDrops(True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.canvas_layout = lay

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802 - Qt override
        if event.source() is self._source:
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802 - Qt override
        if event.source() is self._source:
            item = self._source.currentItem()
            if item:
                self._on_drop(item.data(Qt.ItemDataRole.UserRole), item.text())
            event.acceptProposedAction()


class HelpToggleButton(BioToggleButton):
    """A toggle button with a help icon at its right end."""

    def __init__(self, label: str, help_text: str) -> None:
        super().__init__(label)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 8, 0)
        help_btn = BioHelpButton(self)
        help_btn.setHelpText(help_text)
        # Left-aligned, padded so the text never runs under the right-aligned help icon.
        self.custom_css_overrides = "text-align: left; padding-left: 12px; padding-right: 36px;"
        self._apply_theme_styles()  # so the override takes effect at once
        lay.addWidget(
            help_btn, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )


def toggle_button(label: str, active: bool, help_text: str | None = None) -> BioToggleButton:
    """A toggle button, with a help icon when ``help_text`` is given."""
    btn = HelpToggleButton(label, help_text) if help_text else BioToggleButton(label)
    btn.setChecked(active)
    btn.setMinimumWidth(160)
    return btn
