"""The Comparisons tab's channel checklist: one channel or several, as the plot type needs.

Single-channel plot types (Violin, FMO) keep exactly one channel checked and
also offer derived parameters; multi-channel ones (Heatmap, Radar) offer the
raw fluorescence channels with All / None. Switching between the two starts
from a clean slate: a lone channel checked for a violin would leave a radar
under its minimum without saying so.
"""

from __future__ import annotations

from typing import Any

from karcytics_sdk.plugin import BioSectionLabel
from karcytics_sdk.plugin.components import BioHelpButton, BioListWidget, SecondaryButton
from karcytics_sdk.plugin.theme_fallback import Colors
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QHBoxLayout, QListWidgetItem, QVBoxLayout, QWidget

from ....analysis.fcs_io import (
    derived_labels_of,
    get_channel_marker_label,
    get_fluorescence_channels,
)
from ..checkbox_style import checkbox_qss
from .plot_spec import ChannelMode

_MAX_LIST_HEIGHT = 180
_MIN_ROW_HEIGHT = 24
_HELP = {
    ChannelMode.MULTI: (
        "Channels",
        "Select multiple channels. Each channel becomes one column (heatmap) or one spoke "
        "(radar). Choose channels relevant to the populations you are comparing.",
    ),
    ChannelMode.SINGLE: (
        "Channel",
        "Select a single channel to compare across samples. For example, choose CD3 to "
        "compare T-cell expression, or CD19 for B cells.",
    ),
}
_MINI_BUTTON = "QPushButton { padding: 3px 10px; min-height: 26px; }"


class ChannelPicker(QWidget):
    """Checkable channels for the current plot type (hidden when it takes none)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ComparisonsChannelSection")  # Academy steps point at it
        self._mode = ChannelMode.MULTI
        self._listed_mode: ChannelMode | None = None  # the mode the list was last filled for

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        header = QHBoxLayout()
        header.addWidget(BioSectionLabel("Channels"))
        self._help_btn = BioHelpButton()
        header.addWidget(self._help_btn)
        header.addStretch()
        layout.addLayout(header)

        self._list = BioListWidget()
        self._list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setMaximumHeight(_MAX_LIST_HEIGHT)
        self._list.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self._list)

        buttons = QHBoxLayout()
        self._all_btn = SecondaryButton("All")
        self._none_btn = SecondaryButton("None")
        self._all_btn.clicked.connect(lambda: self._check_all(True))
        self._none_btn.clicked.connect(lambda: self._check_all(False))
        for button in (self._all_btn, self._none_btn):
            button.setStyleSheet(_MINI_BUTTON)
            buttons.addWidget(button)
        buttons.addStretch()
        layout.addLayout(buttons)
        self.apply_theme()

    def set_mode(self, mode: ChannelMode) -> None:
        """Follow the plot type's channel mode (call ``refresh`` after)."""
        self._mode = mode
        self.setVisible(mode != ChannelMode.NONE)
        if mode == ChannelMode.NONE:
            return
        title, body = _HELP[mode]
        self._help_btn.setHelpText(body, title)
        # All / None mean nothing when one channel is checked at a time.
        self._all_btn.setVisible(mode == ChannelMode.MULTI)
        self._none_btn.setVisible(mode == ChannelMode.MULTI)

    def refresh(self, fcs_data: Any | None) -> None:
        """List ``fcs_data``'s channels (None: none), keeping the checks if the mode is unchanged.

        A fresh list, or a new mode, starts with every channel checked (one, in
        single-channel mode).
        """
        keep = self.checked() if self._mode == self._listed_mode else []
        self._listed_mode = self._mode
        self._list.blockSignals(True)
        self._list.clear()
        for label, key in self._channels(fcs_data):
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, key)
            item.setForeground(QColor(Colors.FG_PRIMARY))
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            checked = key in keep or not keep
            item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
            self._list.addItem(item)
        rows = self._list.count()
        row_height = max(_MIN_ROW_HEIGHT, self._list.sizeHintForRow(0) if rows else 0)
        self._list.setFixedHeight(min(_MAX_LIST_HEIGHT, rows * row_height + 4))
        if self._mode == ChannelMode.SINGLE:
            self._keep_one_checked()
        self._list.blockSignals(False)

    def checked(self) -> list[str]:
        """The checked channels' keys, in list order."""
        return [item.data(Qt.ItemDataRole.UserRole) for item in self._items() if _is_checked(item)]

    def apply_theme(self) -> None:
        self._list.setStyleSheet(
            f"QListWidget {{ background: {Colors.BG_DARKEST}; border: 1px solid {Colors.BORDER};"
            f" border-radius: 4px; color: {Colors.FG_PRIMARY}; }}"
            f"QListWidget::item {{ color: {Colors.FG_PRIMARY}; padding: 2px 4px; }}"
            f"QListWidget::item:hover {{ background: {Colors.BG_DARK}; color: {Colors.FG_PRIMARY}; }}"
            f"QListWidget::item:selected {{ background: {Colors.BG_MEDIUM};"
            f" color: {Colors.FG_PRIMARY}; }}" + checkbox_qss()
        )
        for item in self._items():
            item.setForeground(QColor(Colors.FG_PRIMARY))

    def _channels(self, fcs_data: Any | None) -> list[tuple[str, str]]:
        if fcs_data is None:
            return []
        channels = get_fluorescence_channels(fcs_data)
        if self._mode == ChannelMode.SINGLE:
            # A derived parameter (a ratio...) makes sense on its own axis, not
            # beside raw intensities in a heatmap or radar.
            derived = derived_labels_of(fcs_data)
            channels += [ch for ch in fcs_data.channels if ch in derived]
        return [(get_channel_marker_label(fcs_data, ch), ch) for ch in channels]

    def _items(self) -> list[QListWidgetItem]:
        return [item for i in range(self._list.count()) if (item := self._list.item(i))]

    def _check_all(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        self._list.blockSignals(True)
        for item in self._items():
            item.setCheckState(state)
        self._list.blockSignals(False)

    def _keep_one_checked(self) -> None:
        """The first checked channel stays checked (the first channel, if none is)."""
        items = self._items()
        first = next((item for item in items if _is_checked(item)), items[0] if items else None)
        for item in items:
            item.setCheckState(Qt.CheckState.Checked if item is first else Qt.CheckState.Unchecked)

    def _on_item_changed(self, item: QListWidgetItem) -> None:
        """In single-channel mode, checking a channel unchecks the rest."""
        if self._mode != ChannelMode.SINGLE or not _is_checked(item):
            return
        self._list.blockSignals(True)
        for other in self._items():
            if other is not item:
                other.setCheckState(Qt.CheckState.Unchecked)
        self._list.blockSignals(False)


def _is_checked(item: QListWidgetItem) -> bool:
    return item.checkState() == Qt.CheckState.Checked
