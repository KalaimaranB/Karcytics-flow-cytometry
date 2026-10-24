"""Data preparation and layout calculation for the educational UMAP animation."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from karcytics_sdk.plugin import get_logger

from ..constants import ANIMATION_MAX_KNN_EDGES, ANIMATION_MIN_EVENTS
from ..transforms import biexponential_transform

logger = get_logger(__name__, "flow_cytometry")


class UmapAnimationDataPrep:
    """Pre-calculates all layouts and graph structures needed for the 20s animation.

    To ensure smooth 30fps animation, we subsample the real data to ~500 points
    and compute a mini-UMAP synchronously just for visual purposes. The real
    background UMAP calculation on the full 10,000+ points continues independently.
    """

    def __init__(self, n_neighbors: int = 15, min_dist: float = 0.1, random_seed: int = 42):
        self.n_neighbors = n_neighbors
        self.min_dist = min_dist
        self.random_seed = random_seed

        # Will be populated during prepare()
        self.high_dim_3d: np.ndarray | None = None  # (N, 3) PCA projected
        self.final_2d: np.ndarray | None = None  # (N, 2) mini-UMAP result
        self.knn_edges: list[tuple[int, int]] = []  # List of connected index pairs
        self.color_data: np.ndarray | None = None  # (N,) intensity values for coloring

    def prepare(  # noqa: C901, PLR0912, PLR0913, PLR0915
        self,
        events_df: pd.DataFrame,
        fluo_channels: list[str],
        state: Any,
        sample_id: str,
        min_dist: float | None = None,
        color_marker_idx: int = 0,
    ) -> bool:
        """Subsample, transform, and compute all layouts. Returns True if successful."""
        # Allow per-call override of min_dist (so the mini-UMAP matches real params)
        effective_min_dist = min_dist if min_dist is not None else self.min_dist
        num_total_events = len(events_df)
        if num_total_events < ANIMATION_MIN_EVENTS:
            logger.warning("AnimationPrep: Too few events to animate.")
            return False

        # 1. Deterministic subsampling
        np.random.seed(self.random_seed)
        n_sub = min(1200, num_total_events)  # 1200 pts: dense but fast to prep
        subsample_idx = np.random.choice(num_total_events, size=n_sub, replace=False)
        subsample_df = events_df.iloc[subsample_idx].copy()

        # 2. Logicle Transform the channels (just like real UMAP)
        transformed_columns = []
        for ch in fluo_channels:
            raw_vals = subsample_df[ch].values.astype(np.float64)
            scale = state.axis_manager.get_scale(ch, sample_id)

            top = getattr(scale, "logicle_t", 262144.0)
            width = getattr(scale, "logicle_w", 1.0)
            positive = getattr(scale, "logicle_m", 4.5)
            negative = getattr(scale, "logicle_a", 0.0)

            trans_vals = biexponential_transform(
                raw_vals, top=top, width=width, positive=positive, negative=negative
            )
            transformed_columns.append(trans_vals)

        x_mat = np.column_stack(transformed_columns)

        # Store color data
        if 0 <= color_marker_idx < len(fluo_channels):
            self.color_data = x_mat[:, color_marker_idx]
        else:
            self.color_data = x_mat[:, 0]

        # 3. Compute 3D High-Dimensional proxy (PCA)
        try:
            from sklearn.decomposition import PCA  # karcytics: allow KS360 - heavy library

            pca = PCA(n_components=3, random_state=self.random_seed)
            self.high_dim_3d = pca.fit_transform(x_mat)
            # Per-axis robust scale to [-1, 1] so points fill the entire 3D cube
            for ax_i in range(3):
                col = self.high_dim_3d[:, ax_i]
                p1, p99 = np.percentile(col, [1, 99])
                col = np.clip(col, p1, p99)
                col -= col.mean()
                mx = np.abs(col).max()
                if mx > 0:
                    col /= mx
                self.high_dim_3d[:, ax_i] = col
        except Exception as e:
            logger.error(f"AnimationPrep: PCA failed: {e}")
            return False

        # 4. Compute KNN Graph (Fuzzy Simplicial Complex proxy)
        try:
            from sklearn.neighbors import NearestNeighbors  # karcytics: allow KS360 - heavy library

            nn = NearestNeighbors(n_neighbors=self.n_neighbors + 1)  # +1 because point finds itself
            nn.fit(x_mat)
            distances, indices = nn.kneighbors(x_mat)

            edges = set()
            for i in range(n_sub):
                for j in range(1, self.n_neighbors + 1):
                    neighbor_idx = indices[i, j]
                    # Sort to prevent duplicate bidirectional edges
                    edge = tuple(sorted((i, neighbor_idx)))
                    edges.add(edge)

            self.knn_edges = list(edges)
            # To keep drawing fast with 2000 points, limit edges
            if len(self.knn_edges) > ANIMATION_MAX_KNN_EDGES:
                edge_idx = np.random.choice(
                    len(self.knn_edges), size=ANIMATION_MAX_KNN_EDGES, replace=False
                )
                self.knn_edges = [self.knn_edges[i] for i in edge_idx]

        except Exception as e:
            logger.error(f"AnimationPrep: KNN failed: {e}")
            return False

        # 5. Compute Final 2D Layout (Mini-UMAP — real, not faked)
        # This runs BEFORE the background full-UMAP starts (sequential, not concurrent),
        # so there is no numba threading conflict. The animation is honest.
        try:
            import umap as umap_lib  # karcytics: allow KS360 - heavy library

            reducer = umap_lib.UMAP(
                n_neighbors=self.n_neighbors,
                min_dist=effective_min_dist,
                n_epochs=100,
                random_state=self.random_seed,
                init="pca",
                low_memory=False,
                verbose=False,
            )
            self.final_2d = reducer.fit_transform(x_mat)
            # Per-axis robust scale mapping the 1st-99th percentiles roughly to [-1, 1].
            # We do NOT use np.clip, because clipping creates unnatural hard edges/walls.
            for ax_i in range(2):
                col = self.final_2d[:, ax_i]
                p1, p99 = np.percentile(col, [1, 99])
                span = p99 - p1
                col = (col - p1) / span * 2.0 - 1.0 if span > 0 else col - col.mean()
                self.final_2d[:, ax_i] = col
        except Exception as e:
            logger.error(f"AnimationPrep: Mini-UMAP failed: {e}")
            return False

        return True
