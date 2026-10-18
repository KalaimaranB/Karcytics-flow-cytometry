"""A FlowSOM run from a sample to a stored, saved and reloaded run."""

import json
from unittest.mock import MagicMock

import numpy as np
import pytest
from sklearn.metrics import adjusted_rand_score

from karcytics_plugins.flow_cytometry.analysis.clustering import FLOWSOM, method_of
from karcytics_plugins.flow_cytometry.analysis.flowsom_analysis import FlowsomAnalysis
from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.ui.services.attachment_manager import AttachmentManager
from tests.fixtures.lens import make_sample


class FakeContext:
    def __init__(self) -> None:
        self.paths: dict = {}

    def add_attachment(self, key, path, _label):
        self.paths[key] = path

    def get_path(self, key):
        return self.paths.get(key)


@pytest.fixture(scope="module")
def planted():
    state = FlowState()
    sample, events, truth = make_sample("s1")
    state.data.experiment.add_sample(sample)
    analysis = FlowsomAnalysis()
    analysis.target_sample_id = "s1"
    analysis.n_events = len(events)
    analysis.k = 5
    analysis.channels = ["CD3", "CD4", "CD8", "CD56"]
    return state, events, truth, analysis.run(state)


def test_a_run_covers_every_event_of_the_population(planted):
    _state, events, _truth, run = planted
    assert "error" not in run
    assert method_of(run) is FLOWSOM
    assert run["n_events"] == run["parent_total_events"] == len(events)
    assert sorted(run["indices"]) == sorted(events.index)


def test_the_metaclusters_find_the_cell_types(planted):
    _state, events, truth, run = planted
    by_label = dict(zip(events.index, truth, strict=True))
    expected = [by_label[i] for i in run["indices"]]
    assert adjusted_rand_score(expected, run["clusters"]) > 0.9  # noqa: PLR2004


def test_the_run_has_a_map_and_the_usual_tables(planted):
    *_, run = planted
    assert run["embedding"].shape == (run["n_events"], 2)
    assert run["embedding_kind"] == "tree"
    assert len(run["cluster_stats"]["data"]) == run["k"]


def test_a_gate_with_too_few_events_for_the_grid_is_refused(planted):
    state, *_ = planted
    analysis = FlowsomAnalysis()
    analysis.target_sample_id = "s1"
    analysis.n_events = 50
    assert "at least 100 events" in analysis.run(state)["error"]


def test_a_saved_run_loads_back_the_same(planted, tmp_path):
    state, _events, _truth, run = planted
    manager = AttachmentManager(MagicMock())
    manager.temp_dir = tmp_path
    context = FakeContext()

    meta = manager.serialize_umap_results({"s1::root": [dict(run)]}, context)
    json.dumps(meta)  # the metadata is plain JSON
    loaded = manager.hydrate_umap_results(json.loads(json.dumps(meta)), state, context)

    again = loaded["s1::root"][0]
    for key in ("indices", "nodes", "clusters", "embedding", "layout", "linkage"):
        np.testing.assert_allclose(again[key], run[key], err_msg=key)
    assert again["k"] == run["k"]
    assert again["cluster_stats"]["data"] == run["cluster_stats"]["data"]


def test_recut_keeps_custom_population_cells_out(planted):
    from karcytics_plugins.flow_cytometry.analysis.flowsom_analysis import recut_run

    *_, run = planted
    run = dict(run, custom_clusters=[{"name": "Mine", "mask": [0, 1, 2]}], cluster_names={"0": "x"})
    recut_run(run, 3)
    assert run["k"] == 3  # noqa: PLR2004
    assert (run["clusters"][:3] == -1).all()
    assert set(run["clusters"][3:]) == {0, 1, 2}
    assert run["cluster_names"] == {}


def test_summaries_name_the_markers_that_set_a_metacluster_apart(planted):
    from karcytics_plugins.flow_cytometry.analysis.clustering import summarize_clusters

    *_, run = planted
    summaries = summarize_clusters(run["intensities"], run["clusters"], run["channel_labels"])
    assert len(summaries) == run["k"]
    assert sum(s.share for s in summaries) == pytest.approx(1.0)
    assert any(s.up == ("CD4",) or "CD4↑" in s.signature for s in summaries)
