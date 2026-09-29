from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QComboBox, QListView


def _get_theme_tokens():
    from karcytics_sdk.plugin.theme_fallback import Colors, Fonts

    return Colors, Fonts


def _get_contrast_text_color():
    from karcytics_sdk.plugin.theme_fallback import get_contrast_text_color

    return get_contrast_text_color


class FlowComboBox(QComboBox):
    """A combo box that prevents text truncation.

    Automatically expands its dropdown menu to fit wide contents
    and disables Ellipsis truncation.
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        # Completely prevents the combobox from shrinking and hiding text in the collapsed state
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)

        view = QListView()
        view.setTextElideMode(Qt.TextElideMode.ElideNone)
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setView(view)

        self._apply_theme_styles()

    def _apply_theme_styles(self) -> None:
        """Dynamically refresh colors based on current theme."""
        Colors, Fonts = _get_theme_tokens()
        selection_text_color = _get_contrast_text_color()(Colors.ACCENT_PRIMARY)
        self.setStyleSheet(
            f"QComboBox {{ background: {Colors.BG_MEDIUM};"
            f" color: {Colors.FG_PRIMARY}; border: 1px solid {Colors.BORDER};"
            f" border-radius: 4px; padding: 4px 8px;"
            f" font-size: {Fonts.SIZE_SMALL}px; }}"
            f"QComboBox::drop-down {{ border-left: 1px solid {Colors.BORDER}; }}"
            f"QComboBox QAbstractItemView {{ min-width: 200px; padding: 4px; background: {Colors.BG_DARKEST}; color: {Colors.FG_PRIMARY}; selection-background-color: {Colors.ACCENT_PRIMARY}; selection-color: {selection_text_color}; border: 1px solid {Colors.BORDER}; outline: none; }}"
            f"QComboBox QAbstractItemView::item {{ color: {Colors.FG_PRIMARY}; min-height: 24px; padding: 2px 4px; }}"
            f"QComboBox QAbstractItemView::item:hover {{ background-color: {Colors.BG_MEDIUM}; color: {Colors.FG_PRIMARY}; }}"
            f"QComboBox QAbstractItemView::item:selected {{ background-color: {Colors.ACCENT_PRIMARY}; color: {selection_text_color}; }}"
        )

    def showPopup(self):
        """Dynamically ensure the popup list fits all text before showing."""
        width = self.width()
        font_metrics = self.fontMetrics()
        for i in range(self.count()):
            text_width = font_metrics.horizontalAdvance(self.itemText(i)) + 30
            width = max(width, text_width)
        self.view().setMinimumWidth(width)
        super().showPopup()
