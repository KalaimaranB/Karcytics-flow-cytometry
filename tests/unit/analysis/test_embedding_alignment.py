"""The final UMAP map is rotated, scaled and shifted onto the animation's last frame."""

import numpy as np

from karcytics_plugins.flow_cytometry.analysis.animation.alignment import align_to_frame


def test_a_rotated_scaled_shifted_map_lands_on_the_frame():
    rng = np.random.default_rng(0)
    frame = rng.normal(size=(40, 2))
    angle = 0.7
    rotation = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
    extra = rng.normal(size=(10, 2))  # events beyond the animation's subsample
    embedding = np.vstack([frame, extra]) @ rotation * 3.0 + [5.0, -2.0]

    aligned = align_to_frame(embedding, frame)

    np.testing.assert_allclose(aligned[:40], frame, atol=1e-9)
    np.testing.assert_allclose(aligned[40:], extra, atol=1e-9)


def test_a_map_smaller_than_the_frame_is_left_alone():
    embedding = np.ones((3, 2))
    assert align_to_frame(embedding, np.zeros((5, 2))) is embedding
