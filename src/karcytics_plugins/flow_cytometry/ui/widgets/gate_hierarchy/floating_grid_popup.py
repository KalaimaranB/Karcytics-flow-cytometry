"""FloatingGridPopup — shared chrome for a floating population×sample grid.

Extracted from `AllSamplesPopup` (the read-only Quick-Stats popup) so a
second, *interactive* grid popup (the population selection picker used by
Statistics/Comparisons) doesn't duplicate its ~250 lines of shell: title
bar, close button, Escape-to-close, frozen-left branch-label column +
scrollable-right cell columns with synced vertical scrolling, trigger-
relative positioning, and dark theme styling. Only the *cell content*
differs between consumers (a painted heatmap percentage vs. a checkable
toggle) — that's the one piece left to each subclass, via `_populate_grid()`'s
`cell_factory` callback.

`BranchLabel` (the ├─/└─ tree-connector + colored-dot + name row label,
originally `_BranchLabel` in `all_samples_popup.py`) lives here too and is
reused as-is by both popups — it renders a `PopulationRow`
(`analysis/population_matching.py`) regardless of which popup built it.
"""

from __future__ import annotations

from collections.abc import Callable

from karcytics_sdk.plugin.theme_fallback import Colors
from PyQt6.QtCore import QEvent, QPoint, QRect, Qt, QTimer
from PyQt6.QtGui import QFont, QFontMetrics, QKeyEvent, QMouseEvent, QResizeEvent
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizeGrip,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from karcytics_plugins.flow_cytometry.analysis.population_matching import PopulationRow

_PALETTE_HEX = [
    "#7c4dff",  # 0 purple
    "#00bcd4",  # 1 teal
    "#42a5f5",  # 2 blue
    "#ffa726",  # 3 orange
    "#ef5350",  # 4 pink
    "#66bb6a",  # 5 green
]


class BranchLabel(QWidget):
    """Draws the tree-branch connector + coloured dot + population name."""

    _DOT_SIZE = 8

    def __init__(
        self,
        row: PopulationRow,
        on_clicked: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._row = row
        self._on_clicked = on_clicked
        self.setFixedHeight(30)
        self.setMinimumWidth(160)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        if on_clicked is not None:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setToolTip("Click to toggle for every sample")

    def mousePressEvent(self, event: QMouseEvent | None) -> None:  # noqa: N802
        if self._on_clicked is not None:
            self._on_clicked()
        elif event is not None:
            super().mousePressEvent(event)

    def paintEvent(self, _event) -> None:  # noqa: N802
        from PyQt6.QtGui import QColor, QPainter

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        palette_hex = (
            _PALETTE_HEX[self._row.color_index % len(_PALETTE_HEX)]
            if 0 <= self._row.color_index < len(_PALETTE_HEX)
            else "#8b949e"
        )
        dot_color = QColor(palette_hex)
        branch_color = QColor("#2a4a5a")
        text_color = QColor("#e6edf3")

        branch = self._row.branch_str
        font = QFont("Courier New, monospace", 9)
        painter.setFont(font)
        painter.setPen(branch_color)
        fm = QFontMetrics(font)
        branch_w = fm.horizontalAdvance(branch)
        y_center = self.height() // 2
        painter.drawText(4, y_center + fm.ascent() // 2, branch)

        dot_x = 4 + branch_w + 4
        painter.setBrush(dot_color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(dot_x, y_center - self._DOT_SIZE // 2, self._DOT_SIZE, self._DOT_SIZE)

        name_font = QFont("Inter, sans-serif", 10)
        painter.setFont(name_font)
        painter.setPen(text_color)
        fm2 = QFontMetrics(name_font)
        name_x = dot_x + self._DOT_SIZE + 6
        available = self.width() - name_x - 4
        name = fm2.elidedText(self._row.name, Qt.TextElideMode.ElideRight, available)
        painter.drawText(name_x, y_center + fm2.ascent() // 2, name)

        painter.end()


class FloatingGridPopup(QFrame):
    """Floating, frameless popup: title bar + frozen-left branch-label
    column + scrollable-right cell-column grid with synced vertical
    scrolling, always dismissed via Escape or its own × button, and
    optionally also by a click (or tab switch) anywhere outside it.

    Subclasses call `_populate_grid()` from their own rebuild/refresh method
    to (re)build the grid content, and may override `_build_toolbar()` to
    add a row of controls (search box, All/None buttons, ...) between the
    title bar and the grid.

    The grid area itself is a 2×2 freeze-pane layout, same idea as a
    spreadsheet: sample-name column headers stay pinned across the top,
    branch-label rows stay pinned down the left, and only the cell body
    (bottom-right quadrant) scrolls in both directions — the header row
    tracks the body's horizontal scroll, the branch-label column tracks its
    vertical scroll, exactly like the existing left-column freeze.
    """

    _FROZEN_COL_WIDTH = 240
    _HEADER_HEIGHT = 28

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        object_name: str = "",
        title_text: str = "",
        size: tuple[int, int] = (640, 460),
        dismiss_on_outside_click: bool = False,
    ) -> None:
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        if object_name:
            self.setObjectName(object_name)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.resize(*size)
        self.setMinimumSize(360, 260)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._title_text = title_text
        self._dismiss_on_outside_click = dismiss_on_outside_click
        self._drag_offset: QPoint | None = None
        self._setup_chrome()

    # ── Outside-click dismissal ──────────────────────────────────────

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if self._dismiss_on_outside_click:
            app = QApplication.instance()
            if app is not None:
                app.installEventFilter(self)

    def hideEvent(self, event) -> None:  # noqa: N802
        super().hideEvent(event)
        if self._dismiss_on_outside_click:
            app = QApplication.instance()
            if app is not None:
                app.removeEventFilter(self)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if (
            self._dismiss_on_outside_click
            and event is not None
            and event.type() == QEvent.Type.MouseButtonPress
        ):
            global_pos = event.globalPosition().toPoint()
            if not self.frameGeometry().contains(global_pos):
                # See _build_close_button: deferred to dodge the macOS
                # cursor-image crash from hiding this Tool window
                # mid-native-event.
                QTimer.singleShot(0, self.hide)
        return super().eventFilter(obj, event)

    # ── Public API ────────────────────────────────────────────────────

    def show_near(self, trigger: QWidget) -> None:
        """Position below `trigger` (shifted to stay on-screen) and show."""
        global_bottom_left = trigger.mapToGlobal(QPoint(0, trigger.height() + 4))
        screen = QApplication.primaryScreen()
        if not screen:
            return
        screen_rect: QRect = screen.availableGeometry()

        x = global_bottom_left.x()
        y = global_bottom_left.y()
        if x + self.width() > screen_rect.right():
            x = screen_rect.right() - self.width() - 8
        if y + self.height() > screen_rect.bottom():
            y = global_bottom_left.y() - trigger.height() - self.height() - 4

        self.move(x, y)
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus()

    # ── UI ────────────────────────────────────────────────────────────

    def _build_close_button(self) -> QLabel:
        btn = QLabel("×")
        btn.setFixedSize(20, 20)
        btn.setAlignment(Qt.AlignmentFlag.AlignCenter)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        # Deferred, not a direct self.hide(): this button (and the title bar
        # and size grip) carry a custom cursor shape. Hiding this top-level
        # Tool window synchronously, from inside the mouse-press event it's
        # still dispatching, races macOS's native cursor-image recompute for
        # whatever's now under the pointer and can crash the whole process
        # (EXC_BREAKPOINT in QImage::toCGImage/CGImageCreate). Deferring by
        # one event-loop tick lets that native dispatch finish first.
        btn.mousePressEvent = lambda _e: QTimer.singleShot(0, self.hide)  # type: ignore[method-assign, assignment]
        self._btn_close = btn
        return btn

    def _build_title_bar(self) -> QWidget:
        self._title_bar = QWidget()
        self._title_bar.setFixedHeight(38)
        # Not SizeAllCursor: macOS/AppKit has no native cursor for it, so Qt
        # has to synthesize a bitmap image and convert it via
        # QImage::toCGImage() every time the pointer crosses this widget's
        # bounds — and that conversion is what's been crashing the whole
        # process (EXC_BREAKPOINT in CGImageCreate), just from hovering,
        # with no click required. OpenHandCursor still reads as "draggable"
        # and has a real NSCursor behind it.
        self._title_bar.setCursor(Qt.CursorShape.OpenHandCursor)
        title_layout = QHBoxLayout(self._title_bar)
        title_layout.setContentsMargins(14, 0, 14, 0)

        self._title_lbl = QLabel(self._title_text)
        # Transparent to mouse events so a press/drag anywhere on the title
        # bar — including on the label text itself — reaches the title
        # bar's own drag handlers below rather than being consumed here.
        self._title_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        title_layout.addWidget(self._title_lbl)
        title_layout.addStretch()

        self._esc_lbl = QLabel("Esc to close")
        self._esc_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        title_layout.addWidget(self._esc_lbl)

        title_layout.addSpacing(8)
        title_layout.addWidget(self._build_close_button())

        self._title_bar.mousePressEvent = self._on_title_bar_press  # type: ignore[method-assign, assignment]
        self._title_bar.mouseMoveEvent = self._on_title_bar_move  # type: ignore[method-assign, assignment]
        self._title_bar.mouseReleaseEvent = self._on_title_bar_release  # type: ignore[method-assign, assignment]
        return self._title_bar

    def _on_title_bar_press(self, event: QMouseEvent | None) -> None:
        if event is not None and event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.pos()

    def _on_title_bar_move(self, event: QMouseEvent | None) -> None:
        if (
            event is not None
            and (event.buttons() & Qt.MouseButton.LeftButton)
            and self._drag_offset is not None
        ):
            self.move(event.globalPosition().toPoint() - self._drag_offset)

    def _on_title_bar_release(self, _event: QMouseEvent | None) -> None:
        self._drag_offset = None

    def _build_toolbar(self) -> QWidget | None:
        """Optional row of controls between the title bar and the grid
        (e.g. a search box, All/None buttons). None by default.
        """
        return None

    def _setup_chrome(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._build_title_bar())

        toolbar = self._build_toolbar()
        if toolbar is not None:
            outer.addWidget(toolbar)

        self._split_widget = QWidget()
        self._split_outer = QVBoxLayout(self._split_widget)
        self._split_outer.setContentsMargins(0, 0, 0, 0)
        self._split_outer.setSpacing(0)
        outer.addWidget(self._split_widget, stretch=1)

        self._split_outer.addWidget(self._build_header_row())
        self._split_outer.addWidget(self._build_body_row(), stretch=1)

        frozen_vsb = self._frozen_scroll.verticalScrollBar()
        main_vsb = self._scroll.verticalScrollBar()
        if frozen_vsb and main_vsb:
            frozen_vsb.valueChanged.connect(main_vsb.setValue)
            main_vsb.valueChanged.connect(frozen_vsb.setValue)

        header_hsb = self._header_scroll.horizontalScrollBar()
        main_hsb = self._scroll.horizontalScrollBar()
        if header_hsb and main_hsb:
            main_hsb.valueChanged.connect(header_hsb.setValue)
            header_hsb.valueChanged.connect(main_hsb.setValue)

        self._size_grip = QSizeGrip(self)
        self._size_grip.setFixedSize(16, 16)
        # Not SizeFDiagCursor, and not just leaving QSizeGrip's own default
        # either: same non-native, synthesized-bitmap cursor as the title
        # bar above (Qt's QSizeGrip sets this same shape internally by
        # default, so a bare setCursor(...) here doesn't help). Forcing the
        # native ArrowCursor trades the diagonal-resize hint for actually
        # not crashing; the grip still resizes the popup either way.
        self._size_grip.setCursor(Qt.CursorShape.ArrowCursor)
        self._size_grip.raise_()

        self._apply_theme_styles()

    def _build_header_row(self) -> QWidget:
        """Blank corner + horizontally-scrolling sample-name headers, pinned
        above the scrollable cell body.
        """
        top_row = QWidget()
        top_row_layout = QHBoxLayout(top_row)
        top_row_layout.setContentsMargins(0, 0, 0, 0)
        top_row_layout.setSpacing(0)

        self._corner = QWidget()
        self._corner.setFixedSize(self._FROZEN_COL_WIDTH, self._HEADER_HEIGHT)
        top_row_layout.addWidget(self._corner)

        self._header_scroll = QScrollArea()
        self._header_scroll.setWidgetResizable(True)
        self._header_scroll.setFixedHeight(self._HEADER_HEIGHT)
        self._header_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._header_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._header_content = QWidget()
        self._header_grid = QGridLayout(self._header_content)
        # Left/right margins mirror `_grid`'s (6, 12) so cell columns below
        # line up exactly under their header above; spacing must match too.
        self._header_grid.setContentsMargins(6, 0, 12, 0)
        self._header_grid.setSpacing(3)
        self._header_scroll.setWidget(self._header_content)

        top_row_layout.addWidget(self._header_scroll, stretch=1)
        return top_row

    def _build_body_row(self) -> QWidget:
        """Frozen branch-label column + scrollable cell body."""
        bottom_row = QWidget()
        self._split_layout = QHBoxLayout(bottom_row)
        self._split_layout.setContentsMargins(0, 0, 0, 0)
        self._split_layout.setSpacing(0)

        self._frozen_scroll = QScrollArea()
        self._frozen_scroll.setWidgetResizable(True)
        self._frozen_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._frozen_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._frozen_scroll.setFixedWidth(self._FROZEN_COL_WIDTH)

        self._frozen_content = QWidget()
        self._frozen_grid = QGridLayout(self._frozen_content)
        self._frozen_grid.setContentsMargins(12, 12, 6, 12)
        self._frozen_grid.setSpacing(3)
        self._frozen_scroll.setWidget(self._frozen_content)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)

        self._content = QWidget()
        self._grid = QGridLayout(self._content)
        self._grid.setContentsMargins(6, 12, 12, 12)
        self._grid.setSpacing(3)
        self._scroll.setWidget(self._content)

        self._split_layout.addWidget(self._frozen_scroll)
        self._split_layout.addWidget(self._scroll, stretch=1)
        return bottom_row

    def resizeEvent(self, event: QResizeEvent | None) -> None:  # noqa: N802
        super().resizeEvent(event)
        if hasattr(self, "_size_grip"):
            self._size_grip.move(
                self.width() - self._size_grip.width() - 2,
                self.height() - self._size_grip.height() - 2,
            )
            self._size_grip.raise_()

    def _apply_theme_styles(self) -> None:
        self.setStyleSheet(f"""
            {type(self).__name__} {{
                background: {Colors.BG_DARKEST};
                border: 1px solid {Colors.BORDER};
                border-radius: 10px;
            }}
        """)
        self._title_bar.setStyleSheet(
            f"background: {Colors.BG_DARK}; border-bottom: 1px solid {Colors.BORDER};"
            " border-top-left-radius: 10px; border-top-right-radius: 10px;"
        )
        self._title_lbl.setStyleSheet(
            f"color: {Colors.FG_PRIMARY}; font-size: 12px; font-weight: 600;"
            " background: transparent;"
        )
        self._esc_lbl.setStyleSheet(
            f"color: {Colors.FG_DISABLED}; font-size: 10px; background: transparent;"
        )
        self._btn_close.setStyleSheet(
            f"color: {Colors.FG_SECONDARY}; font-size: 15px; font-weight: bold;"
            " background: transparent; border-radius: 4px;"
        )
        self._scroll.setStyleSheet(
            f"QScrollArea {{ background: transparent; border: none; }}"
            f"QScrollBar:vertical {{ background: {Colors.BG_DARK}; width: 6px; border-radius: 3px; }}"
            f"QScrollBar::handle:vertical {{ background: {Colors.BORDER}; border-radius: 3px; }}"
            f"QScrollBar:horizontal {{ background: {Colors.BG_DARK}; height: 6px; border-radius: 3px; }}"
            f"QScrollBar::handle:horizontal {{ background: {Colors.BORDER}; border-radius: 3px; }}"
        )
        self._frozen_scroll.setStyleSheet(
            f"QScrollArea {{ background: transparent; border: none; border-right: 1px solid {Colors.BORDER}; }}"
            f"QScrollBar:vertical {{ width: 0px; }}"
            f"QScrollBar:horizontal {{ height: 0px; }}"
        )
        self._header_scroll.setStyleSheet(
            f"QScrollArea {{ background: transparent; border: none; border-bottom: 1px solid {Colors.BORDER}; }}"
            f"QScrollBar:vertical {{ height: 0px; }}"
            f"QScrollBar:horizontal {{ height: 0px; }}"
        )
        self._corner.setStyleSheet(
            f"background: {Colors.BG_DARKEST}; border-right: 1px solid {Colors.BORDER};"
            f" border-bottom: 1px solid {Colors.BORDER};"
        )
        self._content.setStyleSheet(f"background: {Colors.BG_DARKEST};")
        self._frozen_content.setStyleSheet(f"background: {Colors.BG_DARKEST};")
        self._header_content.setStyleSheet(f"background: {Colors.BG_DARKEST};")
        self._size_grip.setStyleSheet(f"background: transparent; color: {Colors.FG_DISABLED};")

    def _populate_grid(  # noqa: PLR0913
        self,
        rows: list[PopulationRow],
        sample_ids: list[str],
        display_names: dict[str, str],
        cell_factory: Callable[[PopulationRow, str, int], QWidget],
        *,
        row_click_factory: Callable[[PopulationRow], Callable[[], None] | None] | None = None,
        on_header_clicked: Callable[[str], None] | None = None,
        highlighted_sample_ids: set[str] | None = None,
        empty_message: str = "No data.",
    ) -> None:
        """(Re)build the grid from `rows` × `sample_ids`.

        `cell_factory(row, sample_id, col_width)` builds one cell widget.
        `row_click_factory(row)`, if given, returns an optional click
        handler for that row's `BranchLabel` (None = not clickable).
        `on_header_clicked(sample_id)`, if given, is wired to each column
        header's click. `highlighted_sample_ids`, if given (even as an empty
        set), marks this as a "pick one active sample" context: headers get
        an accent-filled pill treatment when the sample is in the set, a
        muted one otherwise, and the tooltip explains the click switches the
        active sample instead of just naming it.
        """
        for grid in (self._grid, self._frozen_grid, self._header_grid):
            while grid.count():
                item = grid.takeAt(0)
                if item:
                    w = item.widget()
                    if w:
                        w.deleteLater()
            for c in range(grid.columnCount()):
                grid.setColumnStretch(c, 0)
            for r in range(grid.rowCount()):
                grid.setRowStretch(r, 0)

        if not rows:
            empty = QLabel(empty_message)
            empty.setStyleSheet(
                f"color: {Colors.FG_DISABLED}; font-size: 11px; background: transparent;"
            )
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._grid.addWidget(empty, 0, 0)
            return

        n_samples = len(sample_ids)

        hdr_font = QFont("Inter, sans-serif", 10)
        hdr_font.setWeight(QFont.Weight.DemiBold)
        fm = QFontMetrics(hdr_font)
        col_w = max(
            64,
            max((fm.horizontalAdvance(display_names.get(sid, sid)) + 16) for sid in sample_ids)
            if sample_ids
            else 64,
        )

        self._frozen_grid.setColumnStretch(0, 1)
        self._grid.setColumnStretch(n_samples, 0)
        self._header_grid.setColumnStretch(n_samples, 0)

        for col_i, sid in enumerate(sample_ids):
            name = display_names.get(sid, sid)
            header = QLabel(name)
            header.setAlignment(Qt.AlignmentFlag.AlignCenter)
            header.setFixedWidth(col_w)
            header.setFixedHeight(self._HEADER_HEIGHT)
            if highlighted_sample_ids is not None and sid in highlighted_sample_ids:
                header.setStyleSheet(
                    f"color: {Colors.BG_DARKEST}; font-size: 10px; font-weight: 700;"
                    f" background: {Colors.ACCENT_PRIMARY}; border-radius: 4px; padding: 1px 4px;"
                )
                header.setToolTip(f"{name} — active sample. Click another sample to switch.")
            else:
                header.setStyleSheet(
                    f"color: {Colors.FG_SECONDARY}; font-size: 10px; font-weight: 600;"
                    " background: transparent;"
                )
                header.setToolTip(
                    f"Click to switch to {name}" if highlighted_sample_ids is not None else name
                )
            if on_header_clicked is not None:
                header.setCursor(Qt.CursorShape.PointingHandCursor)
                _sid = sid

                def _make_press_handler(s: str) -> Callable[[QMouseEvent | None], None]:
                    def _handler(ev: QMouseEvent | None) -> None:
                        on_header_clicked(s)

                    return _handler

                header.mousePressEvent = _make_press_handler(_sid)  # type: ignore[method-assign, assignment]
            self._header_grid.addWidget(header, 0, col_i)

        for row_i, row in enumerate(rows):
            on_click = row_click_factory(row) if row_click_factory is not None else None
            branch_widget = BranchLabel(row, on_clicked=on_click)
            self._frozen_grid.addWidget(
                branch_widget,
                row_i,
                0,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            )

            for col_i, sid in enumerate(sample_ids):
                cell = cell_factory(row, sid, col_w)
                self._grid.addWidget(cell, row_i, col_i, Qt.AlignmentFlag.AlignCenter)

        last_row = len(rows)
        self._frozen_grid.setRowStretch(last_row, 1)
        self._grid.setRowStretch(last_row, 1)

    # ── Dismiss logic ─────────────────────────────────────────────────

    def keyPressEvent(self, event: QKeyEvent | None) -> None:  # noqa: N802
        if event is None:
            return
        if event.key() == Qt.Key.Key_Escape:
            # See _build_close_button: deferred to dodge the macOS cursor-
            # image crash from hiding this Tool window mid-native-event.
            QTimer.singleShot(0, self.hide)
        else:
            super().keyPressEvent(event)
