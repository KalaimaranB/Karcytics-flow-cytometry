"""SOLID animation phases for the UMAP educational animation."""

from typing import Protocol

import numpy as np

from ..constants import ANIMATION_FADE_THRESHOLD


class IFigureDrawer(Protocol):
    """Interface for manipulating the animation plot elements."""

    def set_points(self, data: np.ndarray) -> None:
        """Update scatter point coordinates. data shape: (N, 3)."""
        ...

    def set_edges(self, edge_pairs: list[tuple[int, int]], data: np.ndarray, alpha: float) -> None:
        """Update connecting lines between points."""
        ...

    def set_camera(self, elev: float, azim: float) -> None:
        """Update the 3D camera angle."""
        ...

    def set_caption(self, text: str) -> None:
        """Update the informational caption."""
        ...


class AnimationPhase:
    """Base interface for a temporal segment of the animation."""

    def __init__(self, duration_frames: int):
        self.duration_frames = duration_frames

    def render(self, frame_in_phase: int, drawer: IFigureDrawer) -> None:
        """Render the specific frame of this phase."""
        pass


# ── Concrete Phases ────────────────────────────────────────────────────────


class Phase1HighDim(AnimationPhase):
    """0-3s: Rotate the 3D PCA projection without edges."""

    def __init__(self, duration_frames: int, high_dim_data: np.ndarray):
        super().__init__(duration_frames)
        self.data = high_dim_data

    def render(self, _frame: int, drawer: IFigureDrawer) -> None:
        # Smoothly rotate the camera
        """The high-dimensional cloud, the camera turning slowly round it."""
        progress = _frame / float(self.duration_frames)
        azim = -60 + (progress * 60)

        drawer.set_points(self.data)
        drawer.set_edges([], self.data, 0.0)
        drawer.set_camera(elev=20, azim=azim)
        drawer.set_caption("Mapping cells in high-dimensional marker space...")


class Phase2TopologicalGraph(AnimationPhase):
    """3-6s: Fade in the KNN edges to show the fuzzy simplicial complex."""

    def __init__(
        self,
        duration_frames: int,
        high_dim_data: np.ndarray,
        edges: list[tuple[int, int]],
    ):
        super().__init__(duration_frames)
        self.data = high_dim_data
        self.edges = edges

    def render(self, _frame: int, drawer: IFigureDrawer) -> None:
        """The cloud with its neighbour graph's edges fading in."""
        progress = _frame / float(self.duration_frames)

        # Fade in edges from 0.0 to 0.15 alpha
        alpha = min(0.15, progress * 0.3)

        drawer.set_points(self.data)
        drawer.set_edges(self.edges, self.data, alpha)
        drawer.set_camera(elev=20, azim=0)  # Lock camera
        drawer.set_caption("Building a fuzzy topological graph of nearest neighbors...")


class Phase3Initialization(AnimationPhase):
    """6-9s: Morph from 3D PCA down to a random 2D plane (Z=0)."""

    def __init__(
        self,
        duration_frames: int,
        start_3d: np.ndarray,
        edges: list[tuple[int, int]],
        random_seed: int = 42,
    ):
        super().__init__(duration_frames)
        self.start = start_3d
        self.edges = edges

        # Create a randomized starting 2D layout in the same scale
        np.random.seed(random_seed)
        scale = np.std(start_3d) * 2
        self.end_2d = np.random.uniform(-scale, scale, size=(len(start_3d), 3))
        self.end_2d[:, 2] = 0.0  # Force flat 2D

    def render(self, _frame: int, drawer: IFigureDrawer) -> None:
        # Ease-in-out interpolation
        """The points easing to their 2-D start positions as the camera tips to top-down."""
        t = _frame / float(self.duration_frames)
        progress = t * t * (3.0 - 2.0 * t)

        current_data = self.start + (self.end_2d - self.start) * progress

        # Slowly flatten camera from elev=20 to elev=90 (top-down view)
        elev = 20 + (progress * 70)

        drawer.set_points(current_data)
        drawer.set_edges(self.edges, current_data, 0.15)
        drawer.set_camera(elev=elev, azim=0)
        drawer.set_caption("Initializing low-dimensional embedding plane...")


class Phase4ForceDirected(AnimationPhase):
    """9-18s: Slowly interpolate from random 2D to final UMAP 2D."""

    def __init__(
        self,
        duration_frames: int,
        start_2d: np.ndarray,
        final_2d: np.ndarray,
        edges: list[tuple[int, int]],
    ):
        super().__init__(duration_frames)
        self.start = start_2d
        self.edges = edges

        # Ensure final_2d is embedded in 3D with Z=0
        self.end = np.zeros((len(final_2d), 3))
        self.end[:, 0:2] = final_2d

        # Scale final_2d to visually match the screen bounds of start_2d
        start_scale = np.std(start_2d[:, 0:2])
        end_scale = np.std(self.end[:, 0:2])
        if end_scale > 0:
            self.end[:, 0:2] = (self.end[:, 0:2] / end_scale) * start_scale

    def render(self, _frame: int, drawer: IFigureDrawer) -> None:
        # Smooth step interpolation
        """The points moving to their final layout, slow at both ends."""
        t = _frame / float(self.duration_frames)
        # Custom ease: slow start, fast middle, slow end (sigmoid-like)
        progress = 1 / (1 + np.exp(-10 * (t - 0.5)))

        current_data = self.start + (self.end - self.start) * progress

        # Edges start to fade out near the end
        alpha = 0.15
        if t > ANIMATION_FADE_THRESHOLD:
            alpha = 0.15 * (1.0 - ((t - ANIMATION_FADE_THRESHOLD) * 5))

        drawer.set_points(current_data)
        drawer.set_edges(self.edges, current_data, alpha)
        drawer.set_camera(elev=90, azim=0)  # Top-down
        drawer.set_caption(
            "Optimizing layout: pulling similar cells together, pushing different cells apart..."
        )


class Phase5Final(AnimationPhase):
    """18-20s: Hold the final layout."""

    def __init__(self, duration_frames: int, final_2d_scaled: np.ndarray):
        super().__init__(duration_frames)
        self.data = final_2d_scaled

    def render(self, _frame: int, drawer: IFigureDrawer) -> None:
        """The final 2-D layout from above, the edges gone."""
        drawer.set_points(self.data)
        drawer.set_edges([], self.data, 0.0)  # Edges fully gone
        drawer.set_camera(elev=90, azim=0)
        drawer.set_caption("Final UMAP manifold.")
