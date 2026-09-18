"""Educational tab for teaching compensation interactively.

Seven slides, each requiring a genuine action (measure, predict, correct,
gate, or reason through a control-design question) rather than a
click-near-the-right-spot guess. Quantitative values (spillover %, slopes,
the final matrix) are computed for real from whichever dyes the student
loaded, via ``analysis.spectral_math`` — not hardcoded — so the numbers are
real evidence, not a script.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from karcytics_sdk.plugin.components import BioCaptionLabel, PrimaryButton, SecondaryButton
from karcytics_sdk.plugin.theme_fallback import Colors
from matplotlib import patches
from matplotlib.figure import Figure
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from karcytics_plugins.flow_cytometry.analysis.spectral_math import spectral_overlap_pct
from karcytics_plugins.flow_cytometry.ui.graph._mpl_compat import (
    LockedFigureCanvas as FigureCanvasQTAgg,  # thread-safe vs RenderTask's Agg rasterization
)

if TYPE_CHECKING:
    from .spectral_viewer import SpectralViewer

# ── Pure data/math helpers (no Qt, no matplotlib — easy to reason about & test) ──

_PCT_TOLERANCE = 4.0  # percentage points allowed off in a typed/measured spillover answer
_SLOPE_TOLERANCE = 0.08  # allowed slope error when reading the ruler
_MIN_RUN = 1e-6  # avoids divide-by-zero when the ruler's two points share an x
_MIN_RULER_RUN = 150.0  # endpoints closer than this in x make a very noise-sensitive reading


def best_overlap_pairs(fluors: dict) -> list[tuple[str, str, float]]:
    """Real overlap % (highest first) for every pair of loaded dyes with EM data."""
    names = [n for n, d in fluors.items() if "em_data" in d]
    pairs = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            pct = spectral_overlap_pct(
                np.asarray(fluors[names[i]]["em_data"], dtype=float),
                np.asarray(fluors[names[j]]["em_data"], dtype=float),
            )
            pairs.append((names[i], names[j], pct))
    pairs.sort(key=lambda p: p[2], reverse=True)
    return pairs


def leaked_single_stain(pct: float, seed: int, n: int = 200) -> tuple[np.ndarray, np.ndarray]:
    """A single-stain population slanting upward by the real spillover slope."""
    rng = np.random.default_rng(seed)
    slope = pct / 100.0
    x = rng.normal(800, 70, n)
    y = x * slope + rng.normal(0, 18, n)
    return x, y


def compensated_scene(seed: int) -> dict[str, np.ndarray]:
    """A background + two single-positives + one double-positive population,
    already corrected (used for both 'before/after' comparisons and gating).
    """
    rng = np.random.default_rng(seed)
    return {
        "bg_x": rng.normal(100, 30, 200),
        "bg_y": rng.normal(100, 30, 200),
        "p1_x": rng.normal(600, 80, 200),
        "p1_y": rng.normal(100, 30, 200),
        "p2_x": rng.normal(100, 30, 200),
        "p2_y": rng.normal(600, 80, 200),
        "dp_x": rng.normal(600, 80, 100),
        "dp_y": rng.normal(600, 80, 100),
    }


def uncompensated_scene(pct: float, seed: int) -> dict[str, np.ndarray]:
    """The same scene as ``compensated_scene`` but with real spillover slant applied."""
    rng = np.random.default_rng(seed)
    slope = pct / 100.0
    p1x = rng.normal(600, 80, 200)
    p2y = rng.normal(600, 80, 200)
    return {
        "bg_x": rng.normal(100, 30, 200),
        "bg_y": rng.normal(100, 30, 200),
        "p1_x": p1x,
        "p1_y": p1x * slope + rng.normal(0, 25, 200),
        "p2_x": p2y * slope + rng.normal(0, 25, 200),
        "p2_y": p2y,
        "dp_x": rng.normal(750, 80, 100),
        "dp_y": rng.normal(750, 80, 100),
    }


def rise_run_slope(x0: float, y0: float, x1: float, y1: float) -> tuple[float, float, float]:
    rise = y1 - y0
    run = x1 - x0
    slope = rise / run if abs(run) > _MIN_RUN else float("inf")
    return rise, run, slope


def point_in_rect(px: float, py: float, x0: float, y0: float, x1: float, y1: float) -> bool:
    xmin, xmax = sorted((x0, x1))
    ymin, ymax = sorted((y0, y1))
    return xmin <= px <= xmax and ymin <= py <= ymax


class SpectralLearningTab(QWidget):
    """Educational tab for teaching compensation interactively."""

    def __init__(self, viewer: SpectralViewer, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._viewer = viewer
        self._current_step = 0
        self._max_steps = 7
        self._completed_steps: set[int] = set()
        self._drag_state: str | None = None
        self._pair_cache: list[tuple[str, str, float]] | None = None

        # Slide 1 (physics) two-phase progress + wrong-guess hint, shown in
        # the HTML panel (not the canvas — matplotlib text left there would
        # pile up click after click)
        self._slide1_filter_done = False
        self._slide1_pair_done = False
        self._slide1_wrong_hint: str | None = None

        # Slide 2 (unstained control) predict-first micro-question
        # _slide2_wrong_hint persists across re-renders (unlike appending to
        # the HTML browser which resets on every update_view call).
        self._slide2_wrong_hint: str | None = None

        self._slide2_predicted = False

        # Slide 3 ruler state
        self._ruler_points: list[tuple[float, float]] = []
        self._ruler_ok = False
        self._ruler_hint: str | None = None

        # Slide 4 predict+slider state. _corrected_scatter is the live
        # artist the slider drags in place — see _on_slider_moved.
        self._predicted_point: tuple[float, float] | None = None
        self._slider_pct = 0.0
        self._corrected_scatter = None
        self._active_leak_x = 0.0
        self._active_leak_pct = 0.0

        # Slide 6 gate-drag state
        self._gate_rect: patches.Rectangle | None = None
        self._gate_start: tuple[float, float] | None = None

        # Slide 7 (building the compensation matrix) reasoning-task state
        self._slide7_mc_correct = False
        self._slide7_mc_hint: str | None = None
        self._slide7_count_correct = False

        self._animation_timer = QTimer()
        self._animation_timer.timeout.connect(self._animate_step)
        self._anim_progress = 0.0
        self._is_animating = False
        self._anim_prediction: tuple[float, float] | None = None

        self._setup_ui()
        self._apply_theme_styles()

    # ── setup ──────────────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(16)

        header = QHBoxLayout()
        self._step_label = BioCaptionLabel("Step 1")
        header.addWidget(self._step_label)
        header.addStretch()

        self._btn_prev = SecondaryButton("← Previous")
        self._btn_prev.clicked.connect(self._prev_step)
        header.addWidget(self._btn_prev)

        self._btn_next = PrimaryButton("Next Step →")
        self._btn_next.clicked.connect(self._next_step)
        header.addWidget(self._btn_next)

        root.addLayout(header)

        content = QHBoxLayout()

        left_panel = QVBoxLayout()
        self._explanation = QTextBrowser()
        self._explanation.setMinimumWidth(350)
        self._explanation.setMaximumWidth(450)
        self._explanation.setOpenLinks(False)
        self._explanation.anchorClicked.connect(self._on_html_link_clicked)
        left_panel.addWidget(self._explanation, stretch=1)

        self._readout_label = QLabel()
        self._readout_label.setWordWrap(True)
        left_panel.addWidget(self._readout_label)

        self._interactive_container = QWidget()
        self._interactive_layout = QHBoxLayout(self._interactive_container)
        self._interactive_layout.setContentsMargins(0, 0, 0, 0)
        left_panel.addWidget(self._interactive_container)

        content.addLayout(left_panel)

        self._figure = Figure(facecolor=Colors.BG_DARK)
        self._canvas = FigureCanvasQTAgg(self._figure)
        self._ax = self._figure.add_subplot(111)
        self._style_axes()

        self._canvas_wrapper = QWidget()
        canvas_layout = QVBoxLayout(self._canvas_wrapper)
        canvas_layout.setContentsMargins(0, 0, 0, 0)
        canvas_layout.addWidget(self._canvas)

        self._canvas.mpl_connect("button_press_event", self._on_canvas_click)
        self._canvas.mpl_connect("motion_notify_event", self._on_canvas_mouse_move)
        self._canvas.mpl_connect("button_release_event", self._on_canvas_mouse_release)

        content.addWidget(self._canvas_wrapper, stretch=1)
        root.addLayout(content, stretch=1)

    def _style_axes(self):
        self._figure.patch.set_facecolor(Colors.BG_DARK)
        self._ax.set_facecolor(Colors.BG_DARK)
        self._ax.tick_params(colors=Colors.FG_SECONDARY, labelsize=9)
        for spine in ("bottom", "left"):
            self._ax.spines[spine].set_color(Colors.BORDER)
        for spine in ("top", "right"):
            self._ax.spines[spine].set_visible(False)

    def _apply_theme_styles(self):
        self._step_label.setStyleSheet(
            f"color: {Colors.FG_PRIMARY}; font-size: 16px; font-weight: bold;"
        )
        self._explanation.setStyleSheet(
            f"background: {Colors.BG_DARK}; color: {Colors.FG_PRIMARY}; border: 1px solid {Colors.BORDER}; border-radius: 6px; padding: 12px; font-size: 14px;"
        )
        self._readout_label.setStyleSheet(
            f"color: {Colors.FG_PRIMARY}; font-family: monospace; font-size: 13px;"
        )
        if hasattr(self, "_canvas_wrapper"):
            self._canvas_wrapper.setStyleSheet(
                f"border: 1px solid {Colors.BORDER}; border-radius: 6px;"
            )
        self.update_view()

    def _clear_interactive_widgets(self):
        # _add_slider/_add_answer_input nest their controls in a QHBoxLayout
        # (`addLayout`, not `addWidget`) — a shallow widget-only sweep leaves
        # those rows behind, so every re-render stacked a fresh slider/input
        # on top of the last. Clear recursively instead.
        self._clear_layout(self._interactive_layout)
        self._readout_label.setText("")

    def _clear_layout(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                continue
            child_layout = item.layout()
            if child_layout is not None:
                self._clear_layout(child_layout)

    # ── navigation ─────────────────────────────────────────────────────────

    def _prev_step(self):
        if self._current_step > 0:
            self._current_step -= 1
            self.update_view()

    def _next_step(self):
        if self._current_step < self._max_steps - 1:
            self._current_step += 1
            self.update_view()

    def showEvent(self, event):
        super().showEvent(event)
        self.update_view()

    def _set_axes_labels(self, x_label, y_label):
        self._ax.set_xlabel(f"{x_label}", color=Colors.FG_SECONDARY, fontsize=10)
        self._ax.set_ylabel(f"{y_label}", color=Colors.FG_SECONDARY, fontsize=10)

    def _pairs(self) -> list[tuple[str, str, float]]:
        if self._pair_cache is None:
            self._pair_cache = best_overlap_pairs(self._viewer._active_fluors)
        return self._pair_cache

    def _teaching_pair(self) -> tuple[str, str, float]:
        return self._pairs()[0]

    def _complete_step(self):
        if self._current_step not in self._completed_steps:
            self._completed_steps.add(self._current_step)
            can_advance = self._current_step < self._max_steps - 1
            self._btn_next.setEnabled(can_advance)
            self._canvas.draw()

    def _defer(self, callback) -> None:
        """Runs `callback` on the next event-loop tick instead of inline.

        Required whenever a widget's own signal handler (button click,
        slider release) needs to rebuild `_interactive_layout` — that
        destroys the very widget whose event is still being processed by Qt
        further up the call stack. Deleting a widget mid-event synchronously
        is a real segfault, not just a misbehavior; deferring lets Qt finish
        unwinding that widget's own event first.
        """
        QTimer.singleShot(0, callback)

    # ── render dispatch ────────────────────────────────────────────────────

    def update_view(self, from_animation=False):
        fluors = self._viewer._active_fluors
        self._btn_prev.setEnabled(self._current_step > 0)
        can_advance = (self._current_step in self._completed_steps) and (
            self._current_step < self._max_steps - 1
        )
        self._btn_next.setEnabled(can_advance)
        self._clear_interactive_widgets()
        self._ax.clear()
        self._style_axes()
        if not from_animation:
            self._animation_timer.stop()
            self._is_animating = False

        if not fluors or len(fluors) < 2:  # noqa: PLR2004
            self._step_label.setText("Waiting for Selection...")
            self._explanation.setHtml(
                "<h3>Need at least 2 dyes</h3><p>Load a few fluorophores in the Analysis tab first — spillover only exists between at least two dyes.</p>"
            )
            self._ax.text(
                0.5,
                0.5,
                "Add fluorophores to begin",
                ha="center",
                va="center",
                color=Colors.FG_DISABLED,
                transform=self._ax.transAxes,
                fontsize=12,
            )
            self._ax.set_xlim(0, 1)
            self._ax.set_ylim(0, 1)
            self._canvas.draw()
            return

        slide_funcs = [
            self._render_slide_1_physics,
            self._render_slide_2_unstained,
            self._render_slide_3_ruler,
            self._render_slide_4_predict_correct,
            self._render_slide_5_compensate_all,
            self._render_slide_6_gate,
            self._render_slide_7_matrix,
        ]
        slide_funcs[self._current_step](fluors)
        self._figure.tight_layout(pad=1.0)
        self._canvas.draw()

    # ==========================================================================
    # SLIDE 1: The Physics of Overlap
    # ==========================================================================
    def _render_slide_1_physics(self, fluors):
        self._step_label.setText("Step 1: The Physics of Overlap")
        dye_a, dye_b, _pct = self._teaching_pair()
        phase_a_done = 0 in self._completed_steps or self._slide1_filter_ok()
        pair_found = self._slide1_pair_done

        self._explanation.setHtml(self._slide1_html(fluors, dye_a, dye_b, phase_a_done, pair_found))
        self._ax.set_title("Real Emission Spectra", color=Colors.FG_PRIMARY, pad=15)
        self._set_axes_labels("Wavelength (nm)", "Normalized Intensity")

        x_grid = np.linspace(350, 800, 451)
        target_peak_x = self._slide1_plot_curves(fluors, dye_a, dye_b, x_grid)
        self._slide1_render_filter(phase_a_done, target_peak_x)
        self._target_peak_x = target_peak_x
        self._slide1_correct_dye = dye_b

        if phase_a_done and not pair_found:
            self._slide1_render_markers(dye_a, target_peak_x, x_grid)

        self._ax.set_xlim(350, 800)
        self._ax.set_ylim(0, 1.1)

    def _slide1_html(self, fluors, dye_a, dye_b, phase_a_done, pair_found) -> str:
        label_a = fluors[dye_a].get("display_label", dye_a)
        label_b = fluors[dye_b].get("display_label", dye_b)
        html = """
        <h3 style="color: #58a6ff;">Detectors, Filters, and Broad Curves</h3>
        <p>A flow cytometer uses detectors covered by colored glass filters to "see" light —
        each filter only passes a narrow range of wavelengths through to its detector.</p>
        <p>But a fluorescent dye doesn't glow at one exact wavelength. It emits across a
        broad, hill-shaped range spanning 100nm or more. Detectors sit under the peak of one
        dye's hill, but that hill's shoulders still spill into neighboring detectors — two
        dyes with peaks 50nm apart can still overlap by 20-30% or more.</p>
        <p>Below are the real emission curves for every dye you loaded. Use the legend to
        identify each dye by colour.</p>
        """
        if not phase_a_done:
            html += (
                f"<p style='color: #3fb950; font-weight: bold;'>Action Required: See the "
                f"<b>◀ drag ▶</b> Detector Filter band on the plot. Click and drag it onto "
                f"the peak of <b>{label_a}</b>'s curve, then release.</p>"
            )
        elif not pair_found:
            html += (
                f"<p style='color: #3fb950; font-weight: bold;'>Action Required: The filter "
                f"is now sitting on {label_a}'s detector. Click on whichever OTHER curve is "
                "still riding highest inside the shaded band — that dye leaks into this "
                "detector the most.</p>"
            )
            if self._slide1_wrong_hint:
                html += f"<p style='color: #ff7b72;'>{self._slide1_wrong_hint}</p>"
        else:
            html += f"<p style='color: #3fb950; font-weight: bold;'>Correct! {label_b} leaks the most into {label_a}'s detector — that's exactly the pair spillover will hit hardest.</p>"
        return html

    def _slide1_plot_curves(self, fluors, dye_a, dye_b, x_grid) -> float:
        self._slide1_curves = {}
        target_peak_x = 500.0
        for name, data in fluors.items():
            if "em_data" not in data:
                continue
            color = data.get("color", "#aaaaaa")
            label = data.get("display_label", name)
            arr = np.array(data["em_data"], dtype=float)
            x, y = arr[:, 0], arr[:, 1]
            peak = np.max(y)
            if peak > 0:
                y = y / peak
            y_grid = np.interp(x_grid, x, y, left=0.0, right=0.0)
            self._slide1_curves[name] = y_grid
            lw = 3 if name in (dye_a, dye_b) else 1.5
            alpha = 0.9 if name in (dye_a, dye_b) else 0.5
            self._ax.plot(x_grid, y_grid, color=color, lw=lw, alpha=alpha, label=label)
            if name == dye_a:
                target_peak_x = float(x_grid[np.argmax(y_grid)])
        self._ax.legend(
            facecolor=Colors.BG_DARKEST,
            edgecolor=Colors.BORDER,
            labelcolor=Colors.FG_PRIMARY,
            fontsize=8,
            loc="upper left",
        )
        return target_peak_x

    def _slide1_render_filter(self, phase_a_done: bool, target_peak_x: float) -> None:
        init_val = getattr(self, "_filter_center", None)
        # Default to mid-wavelength (575 nm) so the filter is visually centred
        # and clearly separate from the plot edge on first load.
        if init_val is None or not phase_a_done:
            init_val = 575.0
        self._filter_center = init_val if not phase_a_done else target_peak_x
        self._filter_width = 30
        fc = "#3fb950" if phase_a_done else "#8b949e"
        self._filter_patch = patches.Rectangle(
            (self._filter_center - self._filter_width / 2, 0),
            self._filter_width,
            1.1,
            facecolor=fc,
            alpha=0.35,
        )
        self._ax.add_patch(self._filter_patch)
        # Dashed affordance border — makes it obvious the band is interactive.
        if not phase_a_done:
            border = patches.Rectangle(
                (self._filter_center - self._filter_width / 2, 0),
                self._filter_width,
                1.1,
                fill=False,
                edgecolor="#58a6ff",
                linestyle="--",
                linewidth=1.5,
            )
            self._ax.add_patch(border)
            # Drag-handle label centred at the top of the filter band.
            self._ax.text(
                self._filter_center,
                1.07,
                "◀ drag ▶",
                ha="center",
                va="top",
                color="#58a6ff",
                fontsize=8,
                fontweight="bold",
            )

    def _slide1_render_markers(self, dye_a, band_x: float, x_grid) -> None:
        self._slide1_markers = {}
        for name, y_grid in self._slide1_curves.items():
            if name == dye_a:
                continue
            y_val = float(np.interp(band_x, x_grid, y_grid))
            self._slide1_markers[name] = (band_x, y_val)
            self._ax.plot(band_x, y_val, "o", color="white", ms=6, mfc="none")

    def _slide1_filter_ok(self) -> bool:
        return self._slide1_filter_done

    # ==========================================================================
    # SLIDE 2: Setting the Zero — Unstained Control
    # ==========================================================================
    def _render_slide_2_unstained(self, fluors):
        self._step_label.setText("Step 2: Setting the Zero")
        html = """
        <h3 style="color: #58a6ff;">Finding "Zero"</h3>
        <p>Before we can fix spillover, we need to know what "zero" looks like. Cells have a
        natural background glow called autofluorescence — even with absolutely no dye, they
        produce a faint signal. We run an <b>Unstained Control</b> (a sample with no dyes at
        all) to measure this baseline.</p>
        """
        if not self._slide2_predicted:
            html += (
                "<p style='color: #3fb950; font-weight: bold;'>Quick check first: should the "
                "threshold sit at the CENTER of the unstained cloud, or PAST its edge?</p>"
                "<p><a href='predict_wrong' style='color:#58a6ff;'>A) At the center of the cloud</a><br>"
                "<a href='predict_correct' style='color:#58a6ff;'>B) Past the edge, so every negative cell falls below it</a></p>"
            )
            if self._slide2_wrong_hint:
                html += f"<p style='color: #ff7b72;'>{self._slide2_wrong_hint}</p>"
        elif 1 not in self._completed_steps:
            html += (
                "<p style='color: #3fb950; font-weight: bold;'>Right — a threshold through the "
                "middle of the cloud would call half your true negatives 'positive'. Now drag "
                "the crosshair so ALL of these unstained cells fall in the bottom-left quadrant.</p>"
            )
        else:
            pass  # init_val derived below after this block

        self._explanation.setHtml(html)
        if not self._slide2_predicted:
            self._ax.set_title("Unstained Cells", color=Colors.FG_PRIMARY, pad=15)
            self._set_axes_labels("Detector 1", "Detector 2")
            rng = np.random.default_rng(42)
            self._ax.scatter(
                rng.normal(100, 30, 500),
                rng.normal(100, 30, 500),
                color=Colors.FG_SECONDARY,
                alpha=0.5,
                s=10,
            )
            self._ax.set_xlim(0, 1000)
            self._ax.set_ylim(0, 1000)
            return

        init_val = 800 if 1 not in self._completed_steps else 200
        self._ax.set_title("Unstained Cells", color=Colors.FG_PRIMARY, pad=15)
        self._set_axes_labels("Detector 1", "Detector 2")

        rng = np.random.default_rng(42)
        self._ax.scatter(
            rng.normal(100, 30, 500),
            rng.normal(100, 30, 500),
            color=Colors.FG_SECONDARY,
            alpha=0.5,
            s=10,
        )

        self._slide2_hline = self._ax.axhline(init_val, color=Colors.BORDER, ls="--")
        self._slide2_vline = self._ax.axvline(init_val, color=Colors.BORDER, ls="--")
        self._slide2_crosshair = self._ax.plot(
            [init_val],
            [init_val],
            marker="+",
            color="white",
            markersize=20,
            markeredgewidth=2,
        )[0]

        self._ax.set_xlim(0, 1000)
        self._ax.set_ylim(0, 1000)

    # ==========================================================================
    # SLIDE 3: Measure the Leak — the Ruler Tool
    # ==========================================================================
    def _render_slide_3_ruler(self, fluors):
        self._step_label.setText("Step 3: Measure the Leak")
        dye_a, dye_b, pct = self._teaching_pair()
        label_a = fluors[dye_a].get("display_label", dye_a)
        label_b = fluors[dye_b].get("display_label", dye_b)

        # Clear any stale ruler whenever the step is not yet completed so that
        # navigating back never shows a pre-set ruler from a previous attempt.
        if not self._ruler_ok and self._drag_state != "ruler":
            self._ruler_points = []

        html = f"""
        <h3 style="color: #3fb950;">Doing the Math</h3>
        <p>We run a <b>Single Stain Control</b>: a sample stained with ONLY {label_a}. If there
        were no spillover, these cells would form a flat horizontal line. Because {label_b}'s
        detector is picking up leaked {label_a} signal, the population slants upward instead.</p>
        <p>To measure exactly how severe the leak is, we need the <b>slope</b> of that slant —
        for every unit of true brightness in {label_a}'s detector (the Run), how much false
        brightness appears in {label_b}'s detector (the Rise)?</p>
        """
        if not self._ruler_ok:
            html += (
                "<p style='color: #3fb950; font-weight: bold;'>Action Required: Click near "
                "the <b>← dim</b> marker, drag to the <b>bright →</b> marker, then release "
                "— the further apart your two points, the more reliable the reading.</p>"
            )
            if self._ruler_hint:
                html += f"<p style='color: #ff7b72;'>{self._ruler_hint}</p>"
        elif 2 not in self._completed_steps:  # noqa: PLR2004
            html += "<p style='color: #3fb950; font-weight: bold;'>Good measurement! Now type the spillover percentage your ruler implies (Rise ÷ Run × 100).</p>"
        else:
            html += f"<p style='color: #3fb950; font-weight: bold;'>Correct — the real spillover here is {pct:.1f}%.</p>"

        self._explanation.setHtml(html)
        self._ax.set_title(
            f"{label_a} Single Stain → {label_b} Detector", color=Colors.FG_PRIMARY, pad=15
        )
        self._set_axes_labels(f"{label_a} Detector", f"{label_b} Detector")

        self._slide3_x, self._slide3_y = leaked_single_stain(pct, seed=7)
        self._ax.scatter(self._slide3_x, self._slide3_y, color="#d2a8ff", alpha=0.5, s=15)
        self._ax.set_xlim(0, 1000)
        self._ax.set_ylim(0, 1000)
        self._slide3_true_pct = pct

        # Zone markers — show where to place each ruler endpoint. Derived
        # from the actual population's own x-range (10th/90th percentile)
        # rather than fixed pixel positions, so they always sit ON the real
        # cloud — a fixed "← dim" at x=200 could land well to the left of
        # every real point (the cloud is centred at x=800), which forced
        # every dim-side snap into the same narrow leftmost sliver of data
        # no matter where within that empty region you actually clicked.
        dim_x = float(np.percentile(self._slide3_x, 10))
        bright_x = float(np.percentile(self._slide3_x, 90))
        self._slide3_dim_x = dim_x
        self._slide3_bright_x = bright_x
        if not self._ruler_ok:
            for x_pos, label, ha in ((dim_x, "← dim", "left"), (bright_x, "bright →", "right")):
                self._ax.axvline(x_pos, color=Colors.FG_DISABLED, lw=1, ls="--", alpha=0.5)
                self._ax.text(
                    x_pos,
                    950,
                    label,
                    ha=ha,
                    va="top",
                    color=Colors.FG_DISABLED,
                    fontsize=8,
                )

        self._draw_ruler()
        if self._ruler_points:
            self._show_ruler_readout()

        if self._ruler_ok and 2 not in self._completed_steps:  # noqa: PLR2004
            self._add_answer_input("Enter % (e.g. 15)", self._check_slide3_pct)

    def _draw_ruler(self):
        if not self._ruler_points:
            return
        color = "#3fb950" if self._ruler_ok else "#58a6ff"
        if len(self._ruler_points) == 1:
            # A single endpoint placed so far (mid-drag, before the second
            # point exists) — draw it now instead of waiting for a second
            # point, so the very first click gives visible feedback.
            x0, y0 = self._ruler_points[0]
            self._ax.plot([x0], [y0], color=color, marker="o", ms=9, zorder=5)
            return
        (x0, y0), (x1, y1) = self._ruler_points
        self._ax.plot([x0, x1], [y0, y1], color=color, lw=2, marker="o", zorder=5)

    def _show_ruler_readout(self):
        (x0, y0), (x1, y1) = (
            self._ruler_points
            if len(self._ruler_points) == 2  # noqa: PLR2004
            else (self._ruler_points[0], self._ruler_points[0])
        )
        rise, run, slope = rise_run_slope(x0, y0, x1, y1)
        self._readout_label.setText(
            f"Rise: {rise:.0f}   Run: {run:.0f}   Slope: {slope:.3f}   (≈ {slope * 100:.1f}%)"
        )

    def _add_answer_input(self, placeholder: str, on_submit):
        self._answer_input = QLineEdit()
        self._answer_input.setPlaceholderText(placeholder)
        self._answer_input.setStyleSheet(
            f"background: {Colors.BG_DARKEST}; color: {Colors.FG_PRIMARY}; border: 1px solid {Colors.BORDER}; padding: 5px;"
        )
        btn = QPushButton("Submit")
        btn.setStyleSheet(
            "background: #3fb950; color: #ffffff; border-radius: 4px; padding: 5px 10px;"
        )
        btn.clicked.connect(on_submit)

        self._answer_error = QLabel()
        self._answer_error.setStyleSheet("color: #ff7b72;")
        self._answer_error.hide()

        row = QHBoxLayout()
        row.addWidget(self._answer_input)
        row.addWidget(btn)
        self._interactive_layout.addLayout(row)
        self._interactive_layout.addWidget(self._answer_error)

    def _check_pct_answer(self, true_pct: float) -> bool:
        val = self._answer_input.text().strip().rstrip("%")
        try:
            guess = float(val)
        except ValueError:
            self._answer_error.setText("Enter a number, e.g. 15")
            self._answer_error.show()
            return False
        if abs(guess - true_pct) <= _PCT_TOLERANCE:
            return True
        self._answer_error.setText("Not quite — re-check your Rise ÷ Run measurement.")
        self._answer_error.show()
        return False

    def _check_tube_count_answer(self, true_n: int) -> bool:
        val = self._answer_input.text().strip()
        try:
            guess = int(val)
        except ValueError:
            self._answer_error.setText("Enter a whole number.")
            self._answer_error.show()
            return False
        if guess == true_n:
            return True
        self._answer_error.setText(
            "Not quite — count one tube per dye, plus the unstained control."
        )
        self._answer_error.show()
        return False

    def _check_slide3_pct(self):
        if self._check_pct_answer(self._slide3_true_pct):
            self._defer(self._finish_slide3_pct)

    def _finish_slide3_pct(self):
        self._complete_step()
        self.update_view()

    # ==========================================================================
    # SLIDE 4: Predict, Then Correct
    # ==========================================================================
    def _render_slide_4_predict_correct(self, fluors):
        self._step_label.setText("Step 4: Predict, Then Correct")
        dye_a, dye_b, pct = self._teaching_pair()
        label_a = fluors[dye_a].get("display_label", dye_a)
        label_b = fluors[dye_b].get("display_label", dye_b)
        leak_x, leak_y = 800.0, 800.0 * pct / 100.0
        # The autofluorescence floor — the y-level a fully-compensated cell
        # reaches (it can't go below this because cells always have some
        # background signal even with no dye).
        _AUTOFLUO_FLOOR = 40.0

        html = f"""
        <h3 style="color: #3fb950;">Applying the Math</h3>
        <p>Step 3 gave us the slope — {pct:.1f}% of every unit of true {label_a} signal
        shows up as FALSE {label_b} signal. Compensation reverses that: for a cell measuring
        some brightness in the leaking ({label_b}) detector, we subtract (spillover % × the
        true {label_a} reading) to strip out exactly the false portion, leaving only what
        {label_b} actually saw on its own.</p>
        <p>Here's one real leaked cell — the <b>orange cell</b> on the plot, sitting at
        ({leak_x:.0f}, {leak_y:.0f}). Its x-position ({label_a}) is real and shouldn't move;
        only its inflated y-position ({label_b}) is the artifact we're correcting. Before we
        correct it —</p>
        """
        if self._predicted_point is None:
            html += "<p style='color: #3fb950; font-weight: bold;'>Action Required: Click on the plot where YOU think this cell should land once it's correctly compensated.</p>"
        elif 3 not in self._completed_steps:  # noqa: PLR2004
            px, py = self._predicted_point
            html += (
                f"<p>You predicted ({px:.0f}, {py:.0f}) — that's the blue X. The bright "
                "orange dot is the corrected position, driven by the slider below: it "
                f"recomputes {leak_y:.0f} − (slider% × {leak_x:.0f}) live as you drag, the "
                "same subtraction from the paragraph above.</p>"
                "<p>Why aim for the dashed line and not zero? Even a cell with NO dye at all "
                "still gives off a faint natural glow (autofluorescence, from Step 2's "
                "unstained control) — so a perfectly compensated cell settles there, not at "
                "y = 0. Too little slider and the dot stays stranded above the line (some "
                "leaked signal still uncorrected); too much and you'd be subtracting more "
                "than was ever really there.</p>"
                "<p style='color: #3fb950; font-weight: bold;'>Action Required: Drag the "
                "slider until the orange dot lands on the dashed "
                "<b>autofluorescence floor</b> line — that slider % is your answer for "
                "the spillover here.</p>"
            )
        else:
            html += f"<p style='color: #3fb950; font-weight: bold;'>Corrected! {pct:.1f}% compensation brought it right down to the autofluorescence floor.</p>"

        self._explanation.setHtml(html)
        self._ax.set_title("Correcting a Single Cell", color=Colors.FG_PRIMARY, pad=15)
        self._set_axes_labels("True Detector", "Leaking Detector")

        applied = self._slider_pct if self._predicted_point is not None else 0.0
        corrected_y = max(0.0, leak_y - (applied / 100.0) * leak_x)
        self._active_leak_x = leak_x
        self._active_leak_pct = pct

        # The leaked cell — large, orange, clearly annotated.
        self._ax.scatter(
            [leak_x], [leak_y], color="#f0883e", s=120, alpha=0.9, zorder=4, label="Leaked cell"
        )
        self._ax.annotate(
            "leaked cell",
            xy=(leak_x, leak_y),
            xytext=(leak_x - 200, leak_y + 60),
            color="#f0883e",
            fontsize=8,
            arrowprops={"arrowstyle": "->", "color": "#f0883e", "lw": 1.2},
        )

        # Corrected dot — only shown after the user has clicked a prediction.
        self._corrected_scatter = None
        if self._predicted_point is not None:
            self._corrected_scatter = self._ax.scatter(
                [leak_x],
                [corrected_y],
                color="#ffa657",
                s=120,
                edgecolor="white",
                zorder=5,
                label="Corrected (slider)",
            )
            px, py = self._predicted_point
            self._ax.scatter(
                [px], [py], marker="x", color="#58a6ff", s=120, label="Your prediction"
            )
            # Autofluorescence floor line — only shown once the user has
            # placed their prediction so it doesn't telegraph the answer.
            self._ax.axhline(
                _AUTOFLUO_FLOOR,
                color=Colors.BORDER,
                ls="--",
                label="Autofluorescence floor",
            )
            self._ax.text(
                30,
                _AUTOFLUO_FLOOR + 15,
                "autofluorescence floor",
                color=Colors.FG_DISABLED,
                fontsize=8,
            )

        self._ax.legend(
            facecolor=Colors.BG_DARKEST,
            edgecolor=Colors.BORDER,
            labelcolor=Colors.FG_PRIMARY,
            fontsize=8,
        )
        self._ax.set_xlim(0, 1000)
        self._ax.set_ylim(0, 1000)

        if self._predicted_point is not None and 3 not in self._completed_steps:  # noqa: PLR2004
            self._add_slider(self._on_slide4_slider_release)

    def _add_slider(self, on_release):
        self._slider = QSlider()
        from PyQt6.QtCore import Qt as _Qt

        self._slider.setOrientation(_Qt.Orientation.Horizontal)
        self._slider.setRange(0, 100)
        self._slider.setValue(int(self._slider_pct))
        self._slider.valueChanged.connect(self._on_slider_moved)
        self._slider.sliderReleased.connect(on_release)
        self._slider_readout = QLabel(f"{self._slider_pct:.0f}%")
        self._slider_readout.setStyleSheet(f"color: {Colors.FG_PRIMARY};")
        row = QHBoxLayout()
        row.addWidget(self._slider, stretch=1)
        row.addWidget(self._slider_readout)
        self._interactive_layout.addLayout(row)

    def _on_slider_moved(self, value: int):
        # Deliberately does NOT call update_view(): that clears and rebuilds
        # every interactive widget, including this very slider, while Qt
        # still has an active mouse grab on it mid-drag — destroying/
        # replacing a widget mid-grab crashes (segfault), it doesn't just
        # misbehave. Move only the plotted point instead.
        self._slider_pct = float(value)
        self._slider_readout.setText(f"{value}%")
        if self._corrected_scatter is None:
            return
        corrected_y = max(
            0.0,
            (self._active_leak_x * self._active_leak_pct / 100.0)
            - (value / 100.0) * self._active_leak_x,
        )
        self._corrected_scatter.set_offsets([[self._active_leak_x, corrected_y]])
        self._canvas.draw_idle()

    def _on_slide4_slider_release(self):
        # Deferred for the same reason as _on_slider_moved: sliderReleased
        # still fires from inside the slider's own event processing, so
        # rebuilding _interactive_layout (destroying this slider) here
        # synchronously is just as unsafe as doing it during the drag.
        self._defer(self._finish_slide4_slider_release)

    def _finish_slide4_slider_release(self):
        _dye_a, _dye_b, pct = self._teaching_pair()
        # Pass condition: slider value is within tolerance of the real spillover %,
        # which is exactly when the corrected dot reaches the autofluorescence floor.
        if abs(self._slider_pct - pct) <= _PCT_TOLERANCE:
            self._complete_step()
        self.update_view()

    # ==========================================================================
    # SLIDE 5: Compensate All — Predict the Shift
    # ==========================================================================
    def _render_slide_5_compensate_all(self, fluors):
        self._step_label.setText("Step 5: Compensate All")
        html = """
        <h3 style="color: #58a6ff;">Compensate All</h3>
        <p>We don't correct cells one at a time — real software uses matrix inversion to apply
        this subtraction to millions of events at once, instantly "straightening out" every
        slanted population.</p>
        """
        if self._anim_prediction is None:
            html += "<p style='color: #3fb950; font-weight: bold;'>Action Required: Before pressing the button, click where you predict the WHOLE population will end up.</p>"
        elif 4 not in self._completed_steps and not self._is_animating:  # noqa: PLR2004
            html += "<p style='color: #3fb950; font-weight: bold;'>Now click 'Compensate All' and watch.</p>"
        elif self._is_animating:
            html += "<p style='color: #3fb950; font-weight: bold;'>Compensating...</p>"
        else:
            html += "<p style='color: #3fb950; font-weight: bold;'>Compare your prediction (X) to where it really landed.</p>"

        self._explanation.setHtml(html)
        self._ax.set_title("Applying Compensation", color=Colors.FG_PRIMARY, pad=15)
        self._set_axes_labels("Detector 1", "Detector 2")

        _dye_a, _dye_b, pct = self._teaching_pair()
        scene = uncompensated_scene(pct, seed=99)
        p = self._anim_progress
        end_x, end_y = 600.0, 100.0

        self._ax.scatter(scene["bg_x"], scene["bg_y"], color=Colors.FG_SECONDARY, alpha=0.3, s=10)
        self._ax.scatter(
            scene["p1_x"],
            scene["p1_y"] * (1 - p) + (scene["p1_x"] * 0 + 100) * p,
            color="#3fb950",
            alpha=0.6,
            s=15,
        )
        self._ax.axhline(200, color=Colors.BORDER, ls="--")
        self._ax.axvline(200, color=Colors.BORDER, ls="--")

        if self._anim_prediction is not None:
            px, py = self._anim_prediction
            self._ax.scatter(
                [px], [py], marker="x", color="#58a6ff", s=150, label="Your prediction"
            )
            if p >= 1.0:
                self._ax.scatter(
                    [end_x], [end_y], marker="*", color="#d29922", s=200, label="Actual result"
                )
                self._ax.legend(
                    facecolor=Colors.BG_DARKEST,
                    edgecolor=Colors.BORDER,
                    labelcolor=Colors.FG_PRIMARY,
                    fontsize=8,
                )

        self._ax.set_xlim(0, 1000)
        self._ax.set_ylim(0, 1000)

        if (
            self._anim_prediction is not None
            and 4 not in self._completed_steps  # noqa: PLR2004
            and not self._is_animating
        ):
            btn = QPushButton("⚙️ Compensate All")
            btn.setStyleSheet(
                "background: #58a6ff; color: #ffffff; border-radius: 4px; padding: 10px; font-weight: bold;"
            )
            btn.clicked.connect(self._start_animation)
            self._interactive_layout.addWidget(btn)

    def _start_animation(self):
        # _clear_interactive_widgets() would destroy the very "Compensate
        # All" button whose click we're still handling — defer it, same
        # reasoning as _on_slide4_slider_release.
        self._is_animating = True
        self._anim_progress = 0.0
        self._defer(self._begin_animation_timer)

    def _begin_animation_timer(self):
        self._clear_interactive_widgets()
        self._animation_timer.start(30)

    def _animate_step(self):
        self._anim_progress = min(1.0, self._anim_progress + 0.02)
        eased = 1 - (1 - self._anim_progress) ** 2
        self._anim_progress_eased = eased
        if self._anim_progress >= 1.0:
            self._animation_timer.stop()
            self._is_animating = False
            self._complete_step()
        self.update_view(from_animation=True)

    # ==========================================================================
    # SLIDE 6: Gate the Cleaned Data
    # ==========================================================================
    def _render_slide_6_gate(self, fluors):
        self._step_label.setText("Step 6: Gate the Cleaned Data")
        html = """
        <h3 style="color: #58a6ff;">Reading the Result</h3>
        <p>This is the corrected data — single positives now sit flat on their own axes instead
        of slanting, so the true Double Positive population is clearly separated from noise.</p>
        <p>Just like in Course 1, we isolate it by drawing a gate around it.</p>
        """
        if 5 not in self._completed_steps:  # noqa: PLR2004
            html += "<p style='color: #3fb950; font-weight: bold;'>Action Required: Drag a rectangle around the true Double Positive population (top right).</p>"
        else:
            html += "<p style='color: #3fb950; font-weight: bold;'>Nicely gated — that's a clean population, ready for analysis.</p>"

        self._explanation.setHtml(html)
        self._ax.set_title("Compensated Sample", color=Colors.FG_PRIMARY, pad=15)
        self._set_axes_labels("Detector 1", "Detector 2")

        scene = compensated_scene(seed=99)
        self._ax.scatter(scene["bg_x"], scene["bg_y"], color=Colors.FG_SECONDARY, alpha=0.3, s=10)
        self._ax.scatter(scene["p1_x"], scene["p1_y"], color="#3fb950", alpha=0.6, s=15)
        self._ax.scatter(scene["p2_x"], scene["p2_y"], color="#3fb950", alpha=0.6, s=15)
        self._ax.scatter(scene["dp_x"], scene["dp_y"], color="#58a6ff", alpha=0.9, s=15)
        self._ax.axhline(200, color=Colors.BORDER, ls="--")
        self._ax.axvline(200, color=Colors.BORDER, ls="--")
        self._ax.set_xlim(0, 1000)
        self._ax.set_ylim(0, 1000)

        if self._gate_rect is not None:
            self._ax.add_patch(self._gate_rect)

    # ==========================================================================
    # SLIDE 7: Building the Compensation Matrix
    # ==========================================================================
    def _render_slide_7_matrix(self, fluors):
        self._step_label.setText("Step 7: Building the Compensation Matrix")
        dye_a, dye_b, _pct = self._teaching_pair()
        label_a = fluors[dye_a].get("display_label", dye_a)
        label_b = fluors[dye_b].get("display_label", dye_b)
        names = [n for n, d in fluors.items() if "em_data" in d]
        n_dyes = len(names)

        self._explanation.setHtml(self._slide7_html(label_a, label_b, n_dyes))
        self._render_slide7_heatmap(fluors, names)

        if self._slide7_mc_correct and not self._slide7_count_correct:
            self._add_answer_input("Enter a number", self._check_slide7_count)

    def _slide7_html(self, label_a: str, label_b: str, n_dyes: int) -> str:
        html = """
        <h3 style="color: #58a6ff;">What It Takes to Build the Matrix</h3>
        <p>Every slide so far measured spillover for ONE pair of dyes. A real panel has many —
        correcting all of them at once needs a full <b>compensation matrix</b>: one row and one
        column per dye, where each cell is how much that dye's signal spills into every other
        detector. "Compensate All" back in Step 5 is really just this matrix, inverted and
        applied to every event at once.</p>
        <p>Two rules decide which control tubes you actually need to run to fill that matrix in:</p>
        <p><b>1. An unstained control</b> — sets the true "zero" (autofluorescence) shared by
        every column, exactly like the threshold you dragged back in Step 2.</p>
        <p><b>2. One single-stain tube per dye</b> — stained with ONLY that dye, nothing else.</p>
        """
        if not self._slide7_mc_correct:
            html += (
                f"<p style='color: #3fb950; font-weight: bold;'>Action Required: you want to "
                f"measure exactly how much {label_a} leaks into {label_b}'s detector. Which "
                "control tube gives you that?</p>"
                "<p>"
                "<a href='mc_unstained' style='color:#58a6ff;'>A) Unstained cells only</a><br>"
                f"<a href='mc_single' style='color:#58a6ff;'>B) Cells stained with {label_a} only</a><br>"
                f"<a href='mc_both' style='color:#58a6ff;'>C) Cells stained with both {label_a} and {label_b}</a><br>"
                "<a href='mc_full' style='color:#58a6ff;'>D) The fully-stained panel (all dyes)</a>"
                "</p>"
            )
            if self._slide7_mc_hint:
                html += f"<p style='color: #ff7b72;'>{self._slide7_mc_hint}</p>"
        elif not self._slide7_count_correct:
            html += (
                "<p style='color: #3fb950; font-weight: bold;'>Right — a single-stain tube is "
                "the only sample where 100% of any off-peak signal can be blamed on that one "
                "dye. Mix in a second dye, or the whole panel, and you can no longer tell which "
                "dye caused what you're seeing.</p>"
                f"<p style='color: #3fb950; font-weight: bold;'>Action Required: your panel has "
                f"{n_dyes} dyes loaded. Counting one single-stain tube per dye, PLUS the "
                "unstained control, how many total tubes do you need to run before you can "
                "build the compensation matrix?</p>"
            )
        else:
            html += (
                f"<p style='color: #3fb950; font-weight: bold;'>Exactly — {n_dyes} dyes need "
                f"{n_dyes + 1} tubes. The heatmap on the right IS that matrix: every cell is a "
                "real overlap % measured from the panel's own emission spectra, and inverting "
                "this exact grid is what 'Compensate All' does under the hood.</p>"
            )
        return html

    def _render_slide7_heatmap(self, fluors, names: list[str]) -> None:
        n = len(names)
        labels = [fluors[name].get("display_label", name) for name in names]
        matrix = np.eye(n) * 100.0
        for i in range(n):
            for j in range(i + 1, n):
                pct = spectral_overlap_pct(
                    np.asarray(fluors[names[i]]["em_data"], dtype=float),
                    np.asarray(fluors[names[j]]["em_data"], dtype=float),
                )
                matrix[i, j] = pct
                matrix[j, i] = pct

        self._ax.set_title("Real Compensation Matrix (% overlap)", color=Colors.FG_PRIMARY, pad=15)
        im = self._ax.imshow(matrix, cmap="viridis", vmin=0, vmax=100)
        self._ax.set_xticks(range(n))
        self._ax.set_yticks(range(n))
        self._ax.set_xticklabels(
            labels, color=Colors.FG_SECONDARY, fontsize=8, rotation=45, ha="right"
        )
        self._ax.set_yticklabels(labels, color=Colors.FG_SECONDARY, fontsize=8)
        for i in range(n):
            for j in range(n):
                # A single fixed text color reads badly against a colormap
                # that spans dark purple to bright yellow (viridis) — white
                # text on a yellow cell is the classic low-contrast mistake.
                # Pick per-cell from the cell's own rendered color instead —
                # against the colormap's own fixed RGB (not theme-dependent),
                # so literal black/white, not Colors.*, is the correct check.
                r, g, b, _a = im.cmap(im.norm(matrix[i, j]))
                luminance = 0.299 * r + 0.587 * g + 0.114 * b
                text_color = "#0d1117" if luminance > 0.6 else "#f0f6fc"  # noqa: PLR2004
                self._ax.text(
                    j,
                    i,
                    f"{matrix[i, j]:.0f}",
                    ha="center",
                    va="center",
                    color=text_color,
                    fontsize=7,
                )

    def _check_slide7_count(self):
        n_dyes = len([d for d in self._viewer._active_fluors.values() if "em_data" in d])
        if self._check_tube_count_answer(n_dyes + 1):
            self._defer(self._finish_slide7_count)

    def _finish_slide7_count(self):
        self._slide7_count_correct = True
        self._complete_step()
        self.update_view()

    # ==========================================================================
    # EVENT HANDLERS
    # ==========================================================================
    def _on_html_link_clicked(self, url):
        link = url.toString()
        if self._current_step == 1 and not self._slide2_predicted:  # noqa: PLR2004
            if link == "predict_correct":
                # Correct — advance to the drag phase.
                self._slide2_predicted = True
                self._slide2_wrong_hint = None
            else:
                # Wrong — block progression and show a persistent hint.
                self._slide2_wrong_hint = (
                    "Not quite — placing the threshold through the middle of the "
                    "cloud would still call half the true negatives 'positive'. "
                    "The threshold needs to clear the whole cloud."
                )
            self.update_view()
        elif self._current_step == 6 and not self._slide7_mc_correct:  # noqa: PLR2004
            if link == "mc_single":
                self._slide7_mc_correct = True
                self._slide7_mc_hint = None
            else:
                self._slide7_mc_hint = {
                    "mc_unstained": "Unstained tells you the baseline, not how much this dye spills anywhere.",
                    "mc_both": "With both dyes present you can't tell which one is responsible for the signal you see.",
                    "mc_full": "With every dye mixed together there's no way to isolate any single dye's contribution.",
                }.get(link, "Not quite — think about which tube isolates ONE dye's contribution.")
            self.update_view()

    def _on_canvas_click(self, event):  # noqa: PLR0912
        if not event.inaxes:
            return
        cs = self._current_step
        if cs == 0:
            self._handle_slide1_click(event)
        elif cs == 1:
            if self._slide2_predicted and 1 not in self._completed_steps:
                x = self._slide2_crosshair.get_xdata()[0]
                y = self._slide2_crosshair.get_ydata()[0]
                if abs(event.xdata - x) < 50 and abs(event.ydata - y) < 50:  # noqa: PLR2004
                    self._drag_state = "crosshair"
        elif cs == 2:  # noqa: PLR2004
            if not self._ruler_ok:
                # A true free-form drag: the start point is exactly where you
                # click, no snapping onto the population.
                self._ruler_points = [(event.xdata, event.ydata)]
                self._drag_state = "ruler"
                # Render the first point immediately — otherwise nothing is
                # visible until the mouse actually moves, which reads as the
                # click having done nothing.
                self.update_view()
        elif cs == 3:  # noqa: PLR2004
            if self._predicted_point is None:
                self._predicted_point = (event.xdata, event.ydata)
                self.update_view()
        elif cs == 4:  # noqa: PLR2004
            if self._anim_prediction is None:
                self._anim_prediction = (event.xdata, event.ydata)
                self.update_view()
        elif cs == 5 and 5 not in self._completed_steps:  # noqa: PLR2004
            self._gate_start = (event.xdata, event.ydata)
            self._drag_state = "gate"

    def _handle_slide1_click(self, event):
        phase_a_done = self._slide1_filter_ok()
        if not phase_a_done:
            if abs(event.xdata - self._filter_center) < self._filter_width:
                self._drag_state = "filter"
            return
        if self._slide1_pair_done or not hasattr(self, "_slide1_markers"):
            return

        # Every marker sits at the same x (the detector band's center) by
        # construction — an x/y Euclidean distance would let a few nm of x
        # error dwarf the actual y (intensity) comparison that matters here,
        # so match on y alone, but first require the click to land in the band.
        if abs(event.xdata - self._target_peak_x) > self._filter_width:
            self._slide1_wrong_hint = "Click inside the shaded detector band."
            self.update_view()
            return

        best_name, best_dist = None, float("inf")
        for name, (_mx, my) in self._slide1_markers.items():
            dist = abs(event.ydata - my)
            if dist < best_dist:
                best_name, best_dist = name, dist

        if best_name == self._slide1_correct_dye and best_dist < 0.15:  # noqa: PLR2004
            self._slide1_pair_done = True
            self._slide1_wrong_hint = None
            self._complete_step()
        else:
            self._slide1_wrong_hint = (
                "Not quite — look for the curve still riding high in the band."
            )
        self.update_view()

    def _on_canvas_mouse_move(self, event):
        if not event.inaxes or self._drag_state is None:
            return
        cs = self._current_step
        if self._drag_state == "filter" and cs == 0:
            self._filter_center = event.xdata
            self._filter_patch.set_x(self._filter_center - self._filter_width / 2)
            self._canvas.draw()
        elif self._drag_state == "crosshair" and cs == 1:
            self._slide2_crosshair.set_data([event.xdata], [event.ydata])
            self._slide2_hline.set_ydata([event.ydata, event.ydata])
            self._slide2_vline.set_xdata([event.xdata, event.xdata])
            self._canvas.draw()
        elif self._drag_state == "ruler":
            if self._ruler_points:
                # End point tracks the cursor exactly too — release wherever
                # you like, the reading is evaluated afterward.
                self._ruler_points = [self._ruler_points[0], (event.xdata, event.ydata)]
                self.update_view()
        elif self._drag_state == "gate":
            self._update_gate_drag(event)

    def _update_gate_drag(self, event):
        if self._gate_start is None:
            return
        x0, y0 = self._gate_start
        if self._gate_rect is None:
            self._gate_rect = patches.Rectangle(
                (min(x0, event.xdata), min(y0, event.ydata)),
                abs(event.xdata - x0),
                abs(event.ydata - y0),
                facecolor="#58a6ff",
                edgecolor="#58a6ff",
                alpha=0.2,
                lw=2,
            )
            self._ax.add_patch(self._gate_rect)
        else:
            self._gate_rect.set_x(min(x0, event.xdata))
            self._gate_rect.set_y(min(y0, event.ydata))
            self._gate_rect.set_width(abs(event.xdata - x0))
            self._gate_rect.set_height(abs(event.ydata - y0))
        self._canvas.draw()

    def _on_canvas_mouse_release(self, event):
        cs = self._current_step
        if self._drag_state == "filter" and cs == 0:
            self._drag_state = None
            if abs(self._filter_center - self._target_peak_x) < 30:  # noqa: PLR2004
                self._slide1_filter_done = True
                self.update_view()
        elif self._drag_state == "crosshair" and cs == 1:
            self._drag_state = None
            x = self._slide2_crosshair.get_xdata()[0]
            y = self._slide2_crosshair.get_ydata()[0]
            if 150 < x < 250 and 150 < y < 250:  # noqa: PLR2004
                self._complete_step()
                self.update_view()
        elif self._drag_state == "ruler":
            self._drag_state = None
            self._finish_ruler()
        elif self._drag_state == "gate":
            self._drag_state = None
            self._finish_gate_drag(event)

    def _finish_ruler(self):
        if len(self._ruler_points) != 2:  # noqa: PLR2004
            return
        (x0, y0), (x1, y1) = self._ruler_points
        _rise, run, slope = rise_run_slope(x0, y0, x1, y1)

        if abs(run) < _MIN_RULER_RUN:
            self._ruler_hint = "Drag your two points further apart for a reliable reading."
            self.update_view()
            return

        _dye_a, _dye_b, true_pct = self._teaching_pair()
        if abs(slope - true_pct / 100.0) <= _SLOPE_TOLERANCE:
            self._ruler_ok = True
            self._ruler_hint = None
        else:
            self._ruler_hint = "Not quite — try placing your points closer to the dim and bright ends of the population."
        self.update_view()

    def _finish_gate_drag(self, event):
        if self._gate_rect is None or self._gate_start is None:
            return
        x0, y0 = self._gate_start
        x1, y1 = event.xdata, event.ydata
        dp_ok = point_in_rect(600, 600, x0, y0, x1, y1)
        excludes_bg = not point_in_rect(100, 100, x0, y0, x1, y1)
        if dp_ok and excludes_bg:
            self._complete_step()
        self.update_view()
