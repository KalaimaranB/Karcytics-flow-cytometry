"""Tests for the shared scope-resolution helper used by gate deletion, population
rename, and logic-link deletion to figure out which samples a scoped action touches.
"""

from unittest.mock import MagicMock

from karcytics_plugins.flow_cytometry.ui.scope_resolution import resolve_target_samples


def _experiment_with_groups():
    experiment = MagicMock()
    experiment.samples = {"s1": MagicMock(), "s2": MagicMock(), "s3": MagicMock()}
    group = MagicMock()
    group.sample_ids = ["s1", "s2"]
    experiment.groups = {"group-a": group}
    return experiment


def test_scope_sample_returns_only_the_origin_sample():
    experiment = _experiment_with_groups()
    assert resolve_target_samples("sample", None, "s3", experiment) == ["s3"]


def test_scope_group_returns_that_groups_sample_ids():
    experiment = _experiment_with_groups()
    assert resolve_target_samples("group", "group-a", "s1", experiment) == ["s1", "s2"]


def test_scope_group_all_returns_every_sample():
    experiment = _experiment_with_groups()
    assert set(resolve_target_samples("group", "all", "s1", experiment)) == {"s1", "s2", "s3"}


def test_scope_group_missing_group_falls_back_to_origin_sample():
    experiment = _experiment_with_groups()
    assert resolve_target_samples("group", "no-such-group", "s1", experiment) == ["s1"]
