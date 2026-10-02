import pytest


@pytest.fixture
def service(flow_state):
    return flow_state.population_service


@pytest.fixture
def sample_with_data(flow_state):
    return flow_state.data.experiment.samples["test_sample_1"]


def test_population_service_get_events(service, sample_with_data):
    events = service.get_gated_events(sample_with_data.sample_id, None)
    assert len(events) == 1000


def test_population_service_find_node(service, sample_with_data):
    sample_with_data.gate_tree.node_id = "root"
    node = service.find_node(sample_with_data.sample_id, "root")
    assert node is not None
    assert node.node_id == "root"
