def test_gate_node_serialization_excludes_runtime_statistics():
    """GateNode.to_dict() must not leak runtime statistics into the saved workflow."""
    from karcytics_plugins.flow_cytometry.analysis.gating import GateNode, RectangleGate

    gate = RectangleGate(x_param="FSC-A", y_param="SSC-A", x_min=0, x_max=100, y_min=0, y_max=100)
    node = GateNode(gate=gate, name="Lymphocytes")
    node.statistics = {"count": 1000}

    data = node.to_dict()
    node_data = data["nodes"][0]
    assert "statistics" not in node_data
    assert node_data["name"] == "Lymphocytes"


def test_gate_node_estimation_fields_round_trip():
    """A UMAP-exported node's scale_factor/is_estimated survive save/load,
    same as is_umap_parent — see GateNode.to_dict/from_dict.
    """
    from karcytics_plugins.flow_cytometry.analysis.gating import GateNode

    node = GateNode(name="UMAP B Cells")
    node.scale_factor = 4.0
    node.is_estimated = True

    data = node.to_dict()
    node_data = data["nodes"][0]
    assert node_data["scale_factor"] == 4.0
    assert node_data["is_estimated"] is True

    restored = GateNode.from_dict(data)
    assert restored is not None
    assert restored.scale_factor == 4.0
    assert restored.is_estimated is True


def test_gate_node_estimation_fields_default_when_absent():
    """A legacy save (predating this feature) has neither key — from_dict
    must fall back to the non-estimated defaults, not KeyError.
    """
    from karcytics_plugins.flow_cytometry.analysis.gating import GateNode

    node = GateNode(name="B-cells")
    data = node.to_dict()
    del data["nodes"][0]["scale_factor"]
    del data["nodes"][0]["is_estimated"]

    restored = GateNode.from_dict(data)
    assert restored is not None
    assert restored.scale_factor == 1.0
    assert restored.is_estimated is False


def test_state_serialization_avoids_recursive_objects(flow_state):
    """Verify that to_dict() handles non-serializable fields like EventBus."""
    data = flow_state.to_dict()
    assert isinstance(data, dict)
    assert "event_bus" not in data
    assert "data" in data
    assert "view" in data
    assert "experiment" in data["data"]


def test_state_active_params(flow_state):
    flow_state.view.active_x_param = "FSC-A"
    flow_state.view.active_y_param = "SSC-A"
    assert flow_state.view.active_x_param == "FSC-A"
    assert flow_state.view.active_y_param == "SSC-A"


def test_render_config_serialization(flow_state):
    from karcytics_plugins.flow_cytometry.analysis.config import (
        PseudocolorConfig,
        RenderConfig,
    )

    custom_config = RenderConfig(
        pseudocolor=PseudocolorConfig(max_events=42000, population_detail=3.5)
    )
    flow_state.view.render_config = custom_config

    workflow_dict = flow_state.to_dict()
    assert "view" in workflow_dict
    assert "render_config" in workflow_dict["view"]
    assert workflow_dict["view"]["render_config"]["pseudocolor"]["max_events"] == 42000
    assert workflow_dict["view"]["render_config"]["pseudocolor"]["population_detail"] == 3.5

    # Test round trip
    new_state = type(flow_state)()
    new_state = new_state.from_dict(workflow_dict)
    assert new_state.view.render_config.max_events == 42000
    assert new_state.view.render_config.nbins_scaling == 3.5
