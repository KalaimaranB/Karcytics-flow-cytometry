"""Lines the final UMAP map up with the animation's last frame."""

from __future__ import annotations

import numpy as np
import scipy.linalg
from karcytics_sdk.plugin import get_logger

logger = get_logger(__name__, "flow_cytometry")


def align_to_frame(embedding: np.ndarray, frame: np.ndarray) -> np.ndarray:
    """`embedding` rotated, scaled and shifted onto `frame` (orthogonal Procrustes).

    The animation is computed on a subsample whose events are `embedding`'s
    first rows, so the results map appears exactly where the animation ended
    instead of in UMAP's arbitrary orientation. Returned unchanged when it
    can't be aligned.
    """
    n = len(frame)
    if len(embedding) < n:
        return embedding
    x_mean, y_mean = embedding[:n].mean(axis=0), frame.mean(axis=0)
    x_c, y_c = embedding[:n] - x_mean, frame - y_mean
    scale_x, scale_y = np.linalg.norm(x_c), np.linalg.norm(y_c)
    if scale_x <= 0:
        return embedding
    try:
        u, _, vt = scipy.linalg.svd((x_c / scale_x).T @ (y_c / scale_y))
    except Exception as e:
        logger.warning(f"Failed to align embedding with animation frame: {e}")
        return embedding
    return ((embedding - x_mean) / scale_x) @ (u @ vt) * scale_y + y_mean
