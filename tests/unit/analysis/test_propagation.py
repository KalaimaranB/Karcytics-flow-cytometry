"""Which samples a gate change spreads to."""

from unittest.mock import MagicMock

import pytest

from karcytics_plugins.flow_cytometry.analysis.experiment import Group, Sample
from karcytics_plugins.flow_cytometry.analysis.propagation import propagation_targets
from karcytics_plugins.flow_cytometry.analysis.state import FlowState


@pytest.fixture
def state():
    """a, b in group g1; c in g2; d unloaded."""
    state = FlowState()
    experiment = state.data.experiment
    for sid in "abcd":
        sample = Sample(sample_id=sid, display_name=sid)
        sample.fcs_data = None if sid == "d" else MagicMock()
        experiment.samples[sid] = sample
    for gid, members in (("g1", ["a", "b", "d"]), ("g2", ["c"])):
        experiment.groups[gid] = Group(group_id=gid, name=gid, sample_ids=members)
        for sid in members:
            experiment.samples[sid].group_ids.append(gid)
    return state


def ids(samples):
    return sorted(s.sample_id for s in samples)


def test_with_no_group_filter_every_other_loaded_sample(state):
    assert ids(propagation_targets(state, "a")) == ["b", "c"]


def test_a_group_filter_holding_the_source_limits_it_to_that_group(state):
    state.view.active_group_filter = "g1"
    assert ids(propagation_targets(state, "a")) == ["b"]
    assert propagation_targets(state, "c") == []  # c is not in the filtered group


def test_cross_group_follows_the_source_s_own_groups(state):
    state.view.active_group_filter = "g2"
    assert ids(propagation_targets(state, "a", cross_group=True)) == ["b"]
    assert propagation_targets(state, "missing") == []
