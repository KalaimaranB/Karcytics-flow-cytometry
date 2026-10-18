"""A PhenoGraph run from a sample to a stored, saved, reloaded and re-clustered run."""

import json
from pathlib import Path

import numpy as np
import pytest
from sklearn.metrics import adjusted_rand_score

from karcytics_plugins.flow_cytometry.analysis import phenograph_analysis
from karcytics_plugins.flow_cytometry.analysis.axis_manager import AxisManager
from karcytics_plugins.flow_cytometry.analysis.clustering import PHENOGRAPH, method_of
from karcytics_plugins.flow_cytometry.analysis.phenograph_analysis import (
    PhenographAnalysis,
    PhenographReclusterAnalysis,
    apply_clusters,
)
from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.ui.services.attachment_manager import AttachmentManager
from tests.fixtures.lens import make_sample
from tests.fixtures.phenograph import in_process_compute
from tests.unit.analysis.test_flowsom_analysis import FakeContext


@pytest.fixture(scope="module")
def planted():
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(phenograph_analysis, "compute", in_process_compute)
        state = FlowState()
        sample, events, truth = make_sample("s1")
        state.data.experiment.add_sample(sample)
        analysis = PhenographAnalysis()
        analysis.target_sample_id = "s1"
        analysis.n_events = len(events)
        analysis.resolution = 0.1
        analysis.channels = ["CD3", "CD4", "CD8", "CD56"]
        yield state, events, truth, analysis.run(state)


@pytest.fixture
def in_process(monkeypatch):
    monkeypatch.setattr(phenograph_analysis, "compute", in_process_compute)


def _expected(events, truth, run):
    by_label = dict(zip(events.index, truth, strict=True))
    return [by_label[i] for i in run["indices"]]


def test_a_run_covers_the_population_and_finds_the_cell_types(planted):
    _state, events, truth, run = planted
    assert "error" not in run
    assert method_of(run) is PHENOGRAPH
    assert run["n_events"] == run["parent_total_events"] == len(events)
    assert adjusted_rand_score(_expected(events, truth, run), run["clusters"]) > 0.9  # noqa: PLR2004


def test_the_run_has_a_cluster_graph_a_map_and_the_usual_tables(planted):
    *_, run = planted
    n_clusters = int(run["clusters"].max()) + 1
    assert run["layout"].shape == (n_clusters, 2)
    assert run["cluster_edges"].shape[1] == 2  # noqa: PLR2004
    assert len(run["cluster_connectivity"]) == len(run["cluster_edges"])
    assert run["embedding"].shape == (run["n_events"], 2)
    assert run["embedding_kind"] == "graph"
    assert len(run["cluster_stats"]["data"]) == n_clusters
    assert run["run_uid"]


def test_reclustering_at_a_higher_resolution_gives_more_clusters(planted, in_process):  # noqa: ARG001
    *_, run = planted
    run = dict(run, custom_clusters=[{"name": "Mine", "mask": [0, 1, 2]}], cluster_names={"0": "x"})
    before = int(run["clusters"].max()) + 1
    arrays = PhenographReclusterAnalysis(run, 2.0).run()
    assert "error" not in arrays
    apply_clusters(run, arrays)
    assert run["resolution"] == 2.0  # noqa: PLR2004
    assert int(run["clusters"].max()) + 1 > before
    assert (run["clusters"][:3] == -1).all()  # custom population cells stay out
    assert run["cluster_names"] == {}
    assert len(run["layout"]) == int(run["clusters"].max()) + 1


def test_a_saved_run_loads_back_and_reclusters_without_its_graph(planted, tmp_path, in_process):  # noqa: ARG001
    state, events, truth, run = planted
    manager = AttachmentManager(AxisManager(state))
    manager.temp_dir = tmp_path
    context = FakeContext()

    meta = manager.serialize_umap_results({"s1::root": [dict(run)]}, context)
    json.dumps(meta)  # the metadata is plain JSON
    loaded = manager.hydrate_umap_results(json.loads(json.dumps(meta)), state, context)

    again = loaded["s1::root"][0]
    for key in ("indices", "clusters", "embedding", "layout", "cluster_connectivity"):
        np.testing.assert_allclose(again[key], run[key], err_msg=key)
    # Rebuilt from the FCS data: equal up to float rounding.
    np.testing.assert_allclose(again["intensities"], run["intensities"], atol=1e-3)
    assert again["resolution"] == run["resolution"]
    assert [row[:2] for row in again["cluster_stats"]["data"]] == [
        row[:2] for row in run["cluster_stats"]["data"]
    ]

    again["run_uid"] = "not-in-the-cache"  # as after a restart: the graph is rebuilt
    arrays = PhenographReclusterAnalysis(again, again["resolution"]).run()
    # A rebuilt graph can differ by a neighbour or two: the same clusters, near enough.
    assert adjusted_rand_score(arrays["clusters"], run["clusters"]) > 0.95  # noqa: PLR2004


def test_too_few_events_for_the_neighbours_is_refused(planted):
    state, *_ = planted
    analysis = PhenographAnalysis()
    analysis.target_sample_id = "s1"
    analysis.n_events = 20
    assert "more than 30 events" in analysis.run(state)["error"]


def test_the_daemon_clusters_and_keeps_the_graph():
    from karcytics_sdk.plugin import PluginDaemon

    from karcytics_plugins.flow_cytometry.analysis import daemon_worker

    script = Path(daemon_worker.__file__)
    daemon = PluginDaemon.get_instance("flow_cytometry_phenograph_test", daemon_script_path=script)
    try:
        x = np.vstack([np.random.default_rng(0).normal(c, 0.2, (300, 3)) for c in (0, 3)])
        payload = {
            "x_b64": daemon_worker._encode_array(x),
            "params": {"k": 15, "resolution": 0.3, "min_size": 10, "random_seed": 42},
            "run_uid": "r1",
        }
        first = daemon.call("run_phenograph", payload, timeout=180.0)
        assert first.get("status") == "ok", first
        clusters = daemon_worker._decode_array(first["clusters_b64"])
        assert not set(clusters[:300]) & set(clusters[300:])  # no cluster spans both blobs
        again = daemon.call("run_phenograph", payload, timeout=60.0)
        assert again["clusters_b64"] == first["clusters_b64"]
    finally:
        PluginDaemon.stop_instance("flow_cytometry_phenograph_test")
