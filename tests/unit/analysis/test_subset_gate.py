"""SubsetGate: a population named by its events' ids (a cluster, a drawn UMAP region)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from karcytics_plugins.flow_cytometry.analysis.gating.gate_factory import gate_from_dict
from karcytics_plugins.flow_cytometry.analysis.gating.subset import SubsetGate


def _events(index: list[int]) -> pd.DataFrame:
    return pd.DataFrame({"FSC-A": np.zeros(len(index))}, index=index)


def test_membership_follows_the_event_ids_not_the_row_positions():
    gate = SubsetGate([3, 7, 42])
    events = _events([42, 0, 3, 5])  # a filtered parent: ids, not positions 0..n

    assert gate.contains(events).tolist() == [True, False, True, False]


def test_ids_absent_from_the_events_match_nothing():
    assert not SubsetGate([100, 200]).contains(_events([0, 1, 2])).any()


def test_an_empty_subset_matches_nothing():
    assert SubsetGate([]).contains(_events([0, 1])).tolist() == [False, False]


def test_it_has_no_geometry_to_draw():
    gate = SubsetGate([1])
    assert (gate.x_param, gate.y_param) == ("Subset", None)


def test_a_copy_keeps_the_ids_and_the_gate_id_but_is_its_own_object():
    gate = SubsetGate([5, 1, 9], gate_id="g1")

    copy = gate.copy()

    assert copy is not gate
    assert copy.gate_id == "g1"
    assert copy.contains(_events([1, 2, 5, 9])).tolist() == [True, False, True, True]


def test_it_round_trips_through_a_workspace_file_in_its_original_order():
    gate = SubsetGate([9, 2, 5], gate_id="g2")

    restored = gate_from_dict(gate.to_dict())

    assert isinstance(restored, SubsetGate)
    assert restored.to_dict()["indices"] == (9, 2, 5)
    assert restored.gate_id == "g2"
