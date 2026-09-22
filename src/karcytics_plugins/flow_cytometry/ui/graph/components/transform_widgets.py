"""Transform widgets — AxisTransformPanel for scaling UI."""

from __future__ import annotations

from collections.abc import Callable

from karcytics_sdk.plugin.theme_fallback import Colors
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QDoubleValidator
from PyQt6.QtWidgets import (
    QButtonGroup,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from karcytics_plugins.flow_cytometry.analysis.scaling import AxisScale
from karcytics_plugins.flow_cytometry.analysis.transforms import TransformType
from karcytics_plugins.flow_cytometry.ui.widgets.styled_combo import FlowComboBox


class AxisTransformPanel(QWidget):
    """Panel for adjusting a single axis's scale and limits.

    Signals:
        scale_changed: Emitted whenever a setting is changed.
    """

    scale_changed = pyqtSignal()

    def __init__(
        self,
        axis_name: str,
        current_scale: AxisScale,
        auto_range_callback: Callable[[float | None], tuple[float, float]],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._axis_name = axis_name
        self._scale = current_scale.copy()
        self._auto_range_callback = auto_range_callback

        self._updating_ui = False

        # Debounce: only fire scale_changed after 150ms of no slider activity.
        # This prevents a full canvas redraw on every individual slider tick.
        self._change_timer = QTimer(self)
        self._change_timer.setSingleShot(True)
        self._change_timer.setInterval(150)
        self._change_timer.timeout.connect(self.scale_changed)

        self._themed_buttons: list[QPushButton] = []
        self._section_labels: list[QLabel] = []
        self._separators: list[QWidget] = []

        self._setup_ui()
        self._load_from_scale()

    @property
    def scale(self) -> AxisScale:
        return self._scale

    def _setup_ui(self) -> None:  # noqa: PLR0915
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(16)

        # ── Scale Type ────────────────────────────────────────────────
        type_group_box = QWidget()
        type_layout = QVBoxLayout(type_group_box)
        type_layout.setContentsMargins(0, 0, 0, 0)

        lbl_type = QLabel("Scale Type")
        lbl_type.setStyleSheet(f"color: {Colors.FG_SECONDARY}; font-weight: bold;")
        self._section_labels.append(lbl_type)
        type_layout.addWidget(lbl_type)

        self._type_group = QButtonGroup(self)

        hbox_type = QHBoxLayout()
        self._rb_lin = QRadioButton("Linear")
        self._rb_log = QRadioButton("Log")
        self._rb_biex = QRadioButton("Biexponential")

        self._type_group.addButton(self._rb_lin, 0)
        self._type_group.addButton(self._rb_log, 1)
        self._type_group.addButton(self._rb_biex, 2)

        hbox_type.addWidget(self._rb_lin)
        hbox_type.addWidget(self._rb_log)
        hbox_type.addWidget(self._rb_biex)
        type_layout.addLayout(hbox_type)

        self._type_group.idClicked.connect(self._on_type_changed)
        layout.addWidget(type_group_box)

        self._add_separator(layout)

        # ── Range Limits ──────────────────────────────────────────────
        range_box = QWidget()
        range_layout = QVBoxLayout(range_box)
        range_layout.setContentsMargins(0, 0, 0, 0)

        hbox_range_header = QHBoxLayout()
        lbl_range = QLabel("Display Range")
        lbl_range.setStyleSheet(f"color: {Colors.FG_SECONDARY}; font-weight: bold;")
        self._section_labels.append(lbl_range)
        hbox_range_header.addWidget(lbl_range)

        self._btn_auto = QPushButton("Auto-Range")
        self._style_button(self._btn_auto)
        self._btn_auto.clicked.connect(self._on_auto_range)
        hbox_range_header.addWidget(self._btn_auto, alignment=Qt.AlignmentFlag.AlignRight)
        range_layout.addLayout(hbox_range_header)

        grid_range = QGridLayout()

        # Min
        grid_range.addWidget(QLabel("Min:"), 0, 0)
        self._min_input = QLineEdit()
        self._min_input.setValidator(QDoubleValidator())
        self._min_input.textChanged.connect(self._on_limits_changed)
        grid_range.addWidget(self._min_input, 0, 1)

        btn_min_down = QPushButton("−")
        btn_min_up = QPushButton("+")
        self._style_button(btn_min_down)
        self._style_button(btn_min_up)
        btn_min_down.setFixedSize(24, 24)
        btn_min_up.setFixedSize(24, 24)
        btn_min_down.clicked.connect(lambda: self._adjust_limit("min", -1))
        btn_min_up.clicked.connect(lambda: self._adjust_limit("min", 1))
        grid_range.addWidget(btn_min_down, 0, 2)
        grid_range.addWidget(btn_min_up, 0, 3)

        # Max
        grid_range.addWidget(QLabel("Max:"), 1, 0)
        self._max_input = QLineEdit()
        self._max_input.setValidator(QDoubleValidator())
        self._max_input.textChanged.connect(self._on_limits_changed)
        grid_range.addWidget(self._max_input, 1, 1)

        btn_max_down = QPushButton("−")
        btn_max_up = QPushButton("+")
        self._style_button(btn_max_down)
        self._style_button(btn_max_up)
        btn_max_down.setFixedSize(24, 24)
        btn_max_up.setFixedSize(24, 24)
        btn_max_down.clicked.connect(lambda: self._adjust_limit("max", -1))
        btn_max_up.clicked.connect(lambda: self._adjust_limit("max", 1))
        grid_range.addWidget(btn_max_down, 1, 2)
        grid_range.addWidget(btn_max_up, 1, 3)

        # Outlier percentile
        grid_range.addWidget(QLabel("Outliers:"), 2, 0)
        self._outlier_combo = FlowComboBox()
        self._outlier_combo.addItems(["0%", "0.01%", "0.1% (Def)", "0.5%", "1%", "2%", "5%"])
        self._outlier_combo.currentIndexChanged.connect(self._on_outlier_changed)
        grid_range.addWidget(self._outlier_combo, 2, 1, 1, 3)

        range_layout.addLayout(grid_range)
        layout.addWidget(range_box)

        self._add_separator(layout)

        # ── Biexponential Parameters (Logicle) ────────────────────────
        self._logicle_box = QWidget()
        logicle_layout = QVBoxLayout(self._logicle_box)
        logicle_layout.setContentsMargins(0, 0, 0, 0)

        lbl_logicle = QLabel("Biexponential (Logicle) Parameters")
        lbl_logicle.setStyleSheet(f"color: {Colors.FG_SECONDARY}; font-weight: bold;")
        self._section_labels.append(lbl_logicle)
        logicle_layout.addWidget(lbl_logicle)

        # Short explainer
        self._lbl_hint = QLabel(
            "T: instrument max value (sets positive ceiling)\n"
            "W: linearization width around 0 (compress/expand near-zero)\n"
            "M: total positive decades shown (e.g. 4.5 = up to ~10⁴·⁵)\n"
            "A: extra negative decades (0 = no negatives shown)"
        )
        self._style_hint_label(self._lbl_hint)
        self._lbl_hint.setWordWrap(True)
        logicle_layout.addWidget(self._lbl_hint)

        form_logicle = QFormLayout()
        form_logicle.setContentsMargins(0, 8, 0, 0)

        # Top (T)
        self._top_input = QLineEdit()
        self._top_input.setValidator(QDoubleValidator())
        self._top_input.setToolTip(
            "T — Instrument maximum value.\n"
            "Typical values: 262144 (18-bit), 1048576 (20-bit).\n"
            "Auto-Range will set this from the data."
        )
        self._top_input.textChanged.connect(self._on_logicle_changed)
        form_logicle.addRow("Top (T):", self._top_input)

        # Width Basis (W) slider
        self._slider_w, self._lbl_w = self._add_slider_row(
            form_logicle,
            "Width (W):",
            0,
            50,
            self._on_w_slider,
            tooltip="W — Width of the linear region around 0.\n"
            "Higher = more events near 0 shown in linear scale.\n"
            "Typical: 1.0. Try 1.5–2.0 if events cluster at 0.",
        )

        # Positive Decades (M) slider
        self._slider_m, self._lbl_m = self._add_slider_row(
            form_logicle,
            "Decades (M):",
            20,
            60,
            self._on_m_slider,
            tooltip="M — Total positive decades displayed.\n"
            "4.5 = shows up to ~10^4.5 on the positive side.\n"
            "Typical: 4.5. Use 5.0 for very bright populations.",
        )

        # Extra Negative Decades (A) slider
        self._slider_a, self._lbl_a = self._add_slider_row(
            form_logicle,
            "Neg. Decades (A):",
            0,
            30,
            self._on_a_slider,
            tooltip="A — Additional decades shown BELOW zero.\n"
            "0 = axis starts at 0 (no negative events shown).\n"
            "Set to 0.5–1.0 to display over-compensated negative events.",
        )

        # Reset defaults button
        btn_reset = QPushButton("Reset to Defaults")
        self._style_button(btn_reset)
        btn_reset.setToolTip("Restore W=1.0, M=4.5, A=0.0 (standard logicle defaults)")
        btn_reset.clicked.connect(self._on_reset_logicle_defaults)
        form_logicle.addRow("", btn_reset)

        logicle_layout.addLayout(form_logicle)
        layout.addWidget(self._logicle_box)

        layout.addStretch()

    def _add_slider_row(  # noqa: PLR0913
        self,
        form: QFormLayout,
        label: str,
        min_val: int,
        max_val: int,
        callback,
        tooltip: str = "",
    ) -> tuple[QSlider, QLabel]:
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setMinimum(min_val)
        slider.setMaximum(max_val)
        slider.valueChanged.connect(callback)
        if tooltip:
            slider.setToolTip(tooltip)

        val_label = QLabel("0.0")
        val_label.setFixedWidth(30)

        hbox = QHBoxLayout()
        hbox.addWidget(slider)
        hbox.addWidget(val_label)

        form.addRow(label, hbox)
        return slider, val_label

    def _add_separator(self, layout: QVBoxLayout) -> None:
        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {Colors.BORDER};")
        self._separators.append(sep)
        layout.addWidget(sep)

    def _style_button(self, btn: QPushButton) -> None:
        btn.setStyleSheet(
            f"QPushButton {{ background: {Colors.BG_MEDIUM}; color: {Colors.FG_PRIMARY};"
            f" border: 1px solid {Colors.BORDER}; border-radius: 4px;"
            f" padding: 4px 8px; }}"
            f"QPushButton:hover {{ background: {Colors.ACCENT_PRIMARY}; color: {Colors.BG_DARKEST}; }}"
        )
        if btn not in self._themed_buttons:
            self._themed_buttons.append(btn)

    def _style_hint_label(self, lbl: QLabel) -> None:
        lbl.setStyleSheet(
            f"color: {Colors.FG_DISABLED}; font-size: 10px; "
            f"background: {Colors.BG_DARKEST}; padding: 4px; border-radius: 4px;"
        )

    # ── Theme ─────────────────────────────────────────────────────────

    def _apply_theme_styles(self) -> None:
        """Re-apply Colors-derived QSS baked in at construction time.

        The workspace's TransformDialog always rebuilds this panel fresh
        (so it's never stale), but a caller that constructs it once and
        reuses it (e.g. the Comparisons tab's embedded copy) needs to call
        this on every theme change to avoid frozen colors.
        """
        for btn in self._themed_buttons:
            self._style_button(btn)
        for lbl in self._section_labels:
            lbl.setStyleSheet(f"color: {Colors.FG_SECONDARY}; font-weight: bold;")
        self._style_hint_label(self._lbl_hint)
        for sep in self._separators:
            sep.setStyleSheet(f"background: {Colors.BORDER};")

    # ── State Sync ────────────────────────────────────────────────────

    def _load_from_scale(self) -> None:
        self._updating_ui = True

        # Use string matching to avoid Enum identity issues from plugin module paths
        tt_val = getattr(
            self._scale.transform_type, "value", str(self._scale.transform_type)
        ).lower()
        idx = {
            "linear": 0,
            "log": 1,
            "biexponential": 2,
        }.get(tt_val, 0)

        btn = self._type_group.button(idx)
        if btn:
            btn.setChecked(True)

        if self._scale.min_val is not None:
            self._min_input.setText(f"{self._scale.min_val:.1f}")
        else:
            self._min_input.setText("")

        if self._scale.max_val is not None:
            self._max_input.setText(f"{self._scale.max_val:.1f}")
        else:
            self._max_input.setText("")

        self._top_input.setText(str(self._scale.logicle_t))

        self._slider_w.setValue(int(self._scale.logicle_w * 10))
        self._lbl_w.setText(f"{self._scale.logicle_w:.1f}")

        self._slider_m.setValue(int(self._scale.logicle_m * 10))
        self._lbl_m.setText(f"{self._scale.logicle_m:.1f}")

        self._slider_a.setValue(int(self._scale.logicle_a * 10))
        self._lbl_a.setText(f"{self._scale.logicle_a:.1f}")

        # Outlier combo
        percentiles = [0.0, 0.01, 0.1, 0.5, 1.0, 2.0, 5.0]
        try:
            # Find closest match if not exact
            best_idx = 2  # default 0.1%
            min_diff = 100.0
            for i, p in enumerate(percentiles):
                diff = abs(p - self._scale.outlier_percentile)
                if diff < min_diff:
                    min_diff = diff
                    best_idx = i
            self._outlier_combo.setCurrentIndex(best_idx)
        except Exception:
            self._outlier_combo.setCurrentIndex(2)

        self._logicle_box.setVisible(self._scale.transform_type == TransformType.BIEXPONENTIAL)

        self._updating_ui = False

    def _emit_change(self) -> None:
        """Schedule a debounced scale_changed emission."""
        if not self._updating_ui:
            # Restart the 150ms debounce window on every change
            self._change_timer.start()

    # ── Event Handlers ────────────────────────────────────────────────

    def _on_type_changed(self, btn_id: int) -> None:
        types = {
            0: TransformType.LINEAR,
            1: TransformType.LOG,
            2: TransformType.BIEXPONENTIAL,
        }
        self._scale.transform_type = types[btn_id]
        self._logicle_box.setVisible(btn_id == 2)  # noqa: PLR2004
        self._emit_change()

    def _on_auto_range(self) -> None:
        rng = self._auto_range_callback(self._scale.outlier_percentile)
        if rng:
            self._scale.min_val = rng[0]
            self._scale.max_val = rng[1]

            self._load_from_scale()
            # Auto-range fires immediately (deliberate user action, not slider drag)
            self._change_timer.stop()
            if not self._updating_ui:
                self.scale_changed.emit()

    def _on_limits_changed(self) -> None:
        if self._updating_ui:
            return

        t_min = self._min_input.text()
        t_max = self._max_input.text()

        try:
            new_min = float(t_min) if t_min else None
            new_max = float(t_max) if t_max else None
        except ValueError:
            return

        # Don't apply partial or invalid ranges (prevents auto-range resets and crashes)
        if new_min is None or new_max is None or new_min >= new_max:
            return

        self._scale.min_val = new_min
        self._scale.max_val = new_max
        self._emit_change()

    def _adjust_limit(self, limit_type: str, direction: int) -> None:
        if self._scale.min_val is None or self._scale.max_val is None:
            self._on_auto_range()
            return

        current_range = self._scale.max_val - self._scale.min_val
        if current_range <= 0:
            return

        factor = 0.1 * direction
        delta = current_range * factor

        new_min = self._scale.min_val
        new_max = self._scale.max_val

        if limit_type == "min":
            new_min += delta
        else:
            new_max += delta

        if new_min >= new_max:
            return

        self._scale.min_val = new_min
        self._scale.max_val = new_max

        self._load_from_scale()
        self._emit_change()

    def _on_logicle_changed(self) -> None:
        if self._updating_ui:
            return
        t_val = self._top_input.text()
        try:
            self._scale.logicle_t = float(t_val)
            self._emit_change()
        except ValueError:
            pass

    def _on_w_slider(self, val: int) -> None:
        float_val = val / 10.0
        self._lbl_w.setText(f"{float_val:.1f}")
        if not self._updating_ui:
            self._scale.logicle_w = float_val
            self._emit_change()

    def _on_m_slider(self, val: int) -> None:
        float_val = val / 10.0
        self._lbl_m.setText(f"{float_val:.1f}")
        if not self._updating_ui:
            self._scale.logicle_m = float_val
            self._emit_change()

    def _on_a_slider(self, val: int) -> None:
        float_val = val / 10.0
        self._lbl_a.setText(f"{float_val:.1f}")
        if not self._updating_ui:
            self._scale.logicle_a = float_val
            self._emit_change()

    def _on_outlier_changed(self, index: int) -> None:
        if self._updating_ui:
            return
        percentiles = [0.0, 0.01, 0.1, 0.5, 1.0, 2.0, 5.0]
        if 0 <= index < len(percentiles):
            self._scale.outlier_percentile = percentiles[index]
            # Changing outliers should trigger a re-calculation of the auto-range
            self._on_auto_range()

    def _on_reset_logicle_defaults(self) -> None:
        """Reset W, M, A to standard logicle defaults."""
        self._scale.logicle_w = 1.0
        self._scale.logicle_m = 4.5
        self._scale.logicle_a = 0.0
        self._load_from_scale()
        self._change_timer.stop()
        if not self._updating_ui:
            self.scale_changed.emit()
