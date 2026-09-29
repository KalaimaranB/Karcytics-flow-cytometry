"""UMAP Animator Widget — Pre-computed, lag-free 25-second educational animation."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from karcytics_sdk.plugin.theme_fallback import Colors
from matplotlib.figure import Figure
from mpl_toolkits.mplot3d.art3d import Line3DCollection
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from karcytics_plugins.flow_cytometry.analysis.animation.animation_phases import (
    AnimationPhase,
    Phase1HighDim,
    Phase2TopologicalGraph,
    Phase3Initialization,
    Phase4ForceDirected,
    Phase5Final,
)
from karcytics_plugins.flow_cytometry.analysis.animation.animation_prep import (
    UmapAnimationDataPrep,
)
from karcytics_plugins.flow_cytometry.ui.graph._mpl_compat import (
    LockedFigureCanvas as FigureCanvasQTAgg,  # thread-safe vs RenderTask's Agg rasterization
)


@dataclass
class _FrameData:
    """All data needed to render a single animation frame — pre-computed."""

    pts: np.ndarray  # (N, 3)
    segs: list  # list of [(x0,y0,z0),(x1,y1,z1)] or []
    edge_alpha: float
    elev: float
    azim: float
    caption: str


def build_umap_animation_frames(
    prep_data: UmapAnimationDataPrep, fps: int
) -> tuple[list[_FrameData], np.ndarray]:
    """Compute every animation frame from prep_data — pure numpy/Python, no
    widget access, so it's safe to call from a background thread.

    This is the ~750-frame (25s @ 30fps) per-frame math that used to run
    synchronously on the GUI thread inside `UmapAnimatorWidget.prepare_animation()`,
    right after the (already-backgrounded) UMAP prep finished — reported live
    as a UI freeze/spinning-beachball immediately following the "quick UMAP
    run on a small subset" that builds this preview. Callers should run this
    on the same background thread as the UMAP prep itself and hand the result
    to `UmapAnimatorWidget.apply_precomputed_frames()`, which only does the
    cheap, main-thread-only artist priming.
    """
    if prep_data.high_dim_3d is None or prep_data.final_2d is None:
        return [], np.zeros(0)

    # Normalise colours → [0, 1]
    assert prep_data.color_data is not None
    c = prep_data.color_data.astype(float)
    lo, hi = np.percentile(c, [2, 98])
    if hi > lo:
        c = np.clip((c - lo) / (hi - lo), 0.0, 1.0)
    else:
        c[:] = 0.5

    # Build phases — 25 s total @ 30 fps = 750 frames
    p3 = Phase3Initialization(1, prep_data.high_dim_3d, prep_data.knn_edges)
    p3_end = p3.end_2d
    p4 = Phase4ForceDirected(1, p3_end, prep_data.final_2d, prep_data.knn_edges)
    p4_end = p4.end

    phases: list[AnimationPhase] = [
        Phase1HighDim(fps * 4, prep_data.high_dim_3d),
        Phase2TopologicalGraph(fps * 5, prep_data.high_dim_3d, prep_data.knn_edges),
        Phase3Initialization(fps * 4, prep_data.high_dim_3d, prep_data.knn_edges),
        Phase4ForceDirected(fps * 9, p3_end, prep_data.final_2d, prep_data.knn_edges),
        Phase5Final(fps * 3, p4_end),
    ]

    # Build a throw-away DrawCapture that collects each frame's data
    capture = _DrawCapture()
    frames: list[_FrameData] = []

    for phase in phases:
        for f in range(phase.duration_frames):
            capture.reset()
            phase.render(f, capture)

            # Convert edges to 3-D segments once per frame
            data = capture.pts
            segs: list = []
            if capture.edge_pairs and capture.edge_alpha > 0.0 and data is not None:
                for i, j in capture.edge_pairs:
                    segs.append([data[i].tolist(), data[j].tolist()])

            frames.append(
                _FrameData(
                    pts=data.copy() if data is not None else np.zeros((1, 3)),
                    segs=segs,
                    edge_alpha=capture.edge_alpha,
                    elev=capture.elev,
                    azim=capture.azim,
                    caption=capture.caption,
                )
            )

    return frames, c


class UmapAnimatorWidget(QWidget):
    """Renders the 25-second educational UMAP animation.

    All per-frame math is pre-computed in prepare_animation() so the live
    update callback is a pure data-copy — immune to GIL contention from the
    background UMAP thread.
    """

    animation_finished = pyqtSignal()

    # ── Construction ──────────────────────────────────────────────────────────

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.fps = 30
        self._frames: list[_FrameData] = []
        self._rendered_frame: int = -1  # last frame index that update() actually drew
        self._anim_timer: QTimer | None = None

        # Safety: poll every 300 ms to emit finished after the last frame is drawn
        self._poll = QTimer(self)
        self._poll.setInterval(300)
        self._poll.timeout.connect(self._on_poll)

        self._setup_ui()

    def _setup_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── Matplotlib canvas fills all space ─────────────────────────────────
        self._figure = Figure(facecolor=Colors.BG_DARK)
        self._figure.subplots_adjust(left=0, right=1, top=1, bottom=0)
        self._canvas = FigureCanvasQTAgg(self._figure)
        outer.addWidget(self._canvas, stretch=1)

        # 3D axes — zero margin, fills entire figure
        self._ax = self._figure.add_axes([0.0, 0.0, 1.0, 1.0], projection="3d")  # type: ignore
        self._ax.set_facecolor(Colors.BG_DARK)
        self._figure.patch.set_facecolor(Colors.BG_DARK)
        # Hide every visual decoration
        self._ax.set_axis_off()
        self._ax.xaxis.pane.fill = False
        self._ax.yaxis.pane.fill = False
        self._ax.zaxis.pane.fill = False
        self._ax.xaxis.pane.set_edgecolor("none")
        self._ax.yaxis.pane.set_edgecolor("none")
        self._ax.zaxis.pane.set_edgecolor("none")

        self._ax.dist = 7.0

        # Fixed bounding box to prevent data clipping, with 10% padding for point radius
        self._ax.set_xlim(-1.1, 1.1)
        self._ax.set_ylim(-1.1, 1.1)
        self._ax.set_zlim(-1.1, 1.1)

        # Expand the view using the zoom parameter. 1.3 pushes it to the edge of the canvas
        # without pushing the actual data points off-screen.
        try:
            self._ax.set_box_aspect((1, 1, 1), zoom=1.3)
        except TypeError:
            self._ax.set_box_aspect((1, 1, 1))
            self._ax.dist = 5.0

        self._ax.autoscale(False)

        # Scatter — pre-initialised with 1 dummy point
        dummy = np.zeros((1, 3))
        self._scatter = self._ax.scatter(
            dummy[:, 0],
            dummy[:, 1],
            dummy[:, 2],
            s=55,
            c=[0.5],
            cmap="plasma",
            vmin=0.0,
            vmax=1.0,
            depthshade=True,
            edgecolors="none",
            alpha=0.85,
        )

        # Edge collection — always add once so Matplotlib's internal state is valid
        self._lines = Line3DCollection(
            [[(0, 0, 0), (0, 0, 0)]], colors="#64b5f6", linewidths=0.7, alpha=0.0
        )
        self._ax.add_collection3d(self._lines, autolim=False)

        # ── Caption overlay (absolute position over canvas) ───────────────────
        self._caption_lbl = QLabel("", self._canvas)
        self._caption_lbl.setStyleSheet(f"""
            QLabel {{
                color: {Colors.FG_PRIMARY};
                font-size: 13px;
                font-style: italic;
                background-color: rgba(10, 14, 26, 200);
                padding: 5px 12px;
                border-radius: 5px;
            }}
        """)
        self._caption_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._caption_lbl.setWordWrap(True)
        self._caption_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._caption_lbl.hide()  # shown once animation starts

        self._canvas.resizeEvent = self._on_canvas_resize  # type: ignore

    def _apply_theme_styles(self) -> None:
        self._figure.patch.set_facecolor(Colors.BG_DARK)
        self._ax.set_facecolor(Colors.BG_DARK)
        self._caption_lbl.setStyleSheet(f"""
            QLabel {{
                color: {Colors.FG_PRIMARY};
                font-size: 13px;
                font-style: italic;
                background-color: rgba(10, 14, 26, 200);
                padding: 5px 12px;
                border-radius: 5px;
            }}
        """)
        self._canvas.draw_idle()

    def _on_canvas_resize(self, event) -> None:
        FigureCanvasQTAgg.resizeEvent(self._canvas, event)
        w = event.size().width()
        h = event.size().height()
        lbl_h = 36
        margin = 12
        self._caption_lbl.setGeometry(margin, h - lbl_h - margin, w - 2 * margin, lbl_h)

    # ── Public API ────────────────────────────────────────────────────────────

    def prepare_animation(self, prep_data: UmapAnimationDataPrep) -> None:
        """Pre-compute every frame (points, edges, camera, caption) so the live
        update callback does zero math — just array assignment.

        Synchronous convenience wrapper that does the frame math on whatever
        thread it's called from. Prefer computing frames on the same
        background thread as the UMAP prep via `build_umap_animation_frames()`
        and handing the result to `apply_precomputed_frames()` instead — this
        method's own frame-building loop is exactly what used to block the
        GUI thread for the animation's ~750 frames.
        """
        frames, colors = build_umap_animation_frames(prep_data, self.fps)
        self.apply_precomputed_frames(frames, colors)

    def apply_precomputed_frames(self, frames: list[_FrameData], colors: np.ndarray | None) -> None:
        """Adopt already-computed frames and prime the scatter artist.

        Only touches widget/artist state — safe and cheap to call on the
        main thread even though the frames themselves were built elsewhere.
        """
        self.stop()
        self._frames = list(frames)
        self._rendered_frame = -1

        if not self._frames:
            return

        # Prime the scatter with the correct number of points & colours
        d0 = self._frames[0].pts
        self._scatter._offsets3d = (d0[:, 0], d0[:, 1], d0[:, 2])
        self._scatter.set_array(colors)
        self._scatter.set_sizes(np.full(len(d0), 55.0))

    def start(self) -> None:
        if not self._frames:
            return

        self._rendered_frame = -1

        self._caption_lbl.show()

        if self._anim_timer is None:
            self._anim_timer = QTimer(self)
            self._anim_timer.timeout.connect(self._on_anim_timer_tick)

        self._anim_timer.start(1000 // self.fps)

        self._poll.setSingleShot(False)
        self._poll.setInterval(300)
        self._poll.start()

    def _on_anim_timer_tick(self) -> None:
        """Called by QTimer to render the next frame."""
        if self._rendered_frame + 1 >= len(self._frames):
            if self._anim_timer:
                self._anim_timer.stop()
            return

        self._rendered_frame += 1
        fd = self._frames[self._rendered_frame]

        # Points
        self._scatter._offsets3d = (fd.pts[:, 0], fd.pts[:, 1], fd.pts[:, 2])

        # Edges
        if fd.edge_alpha > 0.0 and fd.segs:
            self._lines.set_segments(fd.segs)
            self._lines.set_alpha(fd.edge_alpha)
        else:
            self._lines.set_alpha(0.0)

        # Camera
        self._ax.view_init(elev=fd.elev, azim=fd.azim)

        # Caption
        self._caption_lbl.setText(fd.caption)

        self._canvas.draw_idle()

    def stop(self) -> None:
        """Stop the animation and polling timer."""
        self._poll.stop()
        if self._anim_timer:
            self._anim_timer.stop()

    def show_loading(self) -> None:
        """Show a 'preparing animation...' message while the prep thread runs."""
        # Stop any previous animation and reset frame tracking so a re-run doesn't
        # immediately fire animation_finished with the last frame of the previous run.
        self.stop()
        self._rendered_frame = -1
        self._frames.clear()

        self._caption_lbl.setText("Preparing animation…")
        self._caption_lbl.show()
        # Clear the scatter so we don't show stale data
        dummy = np.zeros((1, 3))
        self._scatter._offsets3d = (dummy[:, 0], dummy[:, 1], dummy[:, 2])
        self._lines.set_alpha(0.0)
        self._canvas.draw_idle()

    def _on_poll(self) -> None:
        """Only emit finished when update() has actually drawn near the last frame."""
        total = len(self._frames)
        import logging

        logger = logging.getLogger(__name__)
        logger.debug(f"[ANIM-POLL] total={total}, rendered={self._rendered_frame}")
        if total > 0 and self._rendered_frame >= total - 5:
            logger.info("[ANIM-POLL] Animation finished! Stopping poll and emitting signal.")
            self._poll.stop()
            self.animation_finished.emit()


# ── Internal helper ────────────────────────────────────────────────────────────


class _DrawCapture:
    """Implements IFigureDrawer to capture one frame's data without drawing."""

    def reset(self) -> None:
        self.pts: np.ndarray | None = None
        self.edge_pairs: list[tuple[int, int]] = []
        self.edge_alpha: float = 0.0
        self.elev: float = 20.0
        self.azim: float = -60.0
        self.caption: str = ""

    def set_points(self, data: np.ndarray) -> None:
        self.pts = data

    def set_edges(self, edge_pairs: list[tuple[int, int]], data: np.ndarray, alpha: float) -> None:
        self.edge_pairs = edge_pairs
        self.edge_alpha = alpha

    def set_camera(self, elev: float, azim: float) -> None:
        self.elev = elev
        self.azim = azim

    def set_caption(self, text: str) -> None:
        self.caption = text
