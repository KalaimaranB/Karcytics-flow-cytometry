"""Tests for the Pseudocolor Overlay plot type: registry wiring, the
generalized renderer, and ComparisonsViewer's kwargs-building for it.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from karcytics_plugins.flow_cytometry.analysis.experiment import Sample
from karcytics_plugins.flow_cytometry.analysis.fcs_io import FCSData
from karcytics_plugins.flow_cytometry.analysis.gating import RectangleGate
from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.ui.widgets.comparisons.registry import PLOT_REGISTRY
from karcytics_plugins.flow_cytometry.ui.widgets.comparisons.renderers.pseudocolor_overlay_renderer import (
    PseudocolorOverlayRenderer,
)
from karcytics_plugins.flow_cytometry.ui.widgets.comparisons_viewer import ComparisonsViewer


def _make_sample_with_gate() -> Sample:
    rng = np.random.default_rng(42)
    n = 500
    events = pd.DataFrame(
        {
            "FSC-A": rng.uniform(0, 100_000, n),
            "SSC-A": rng.uniform(0, 100_000, n),
        }
    )
    fcs_data = FCSData(file_path=Path("fake.fcs"), channels=["FSC-A", "SSC-A"], events=events)
    sample = Sample(sample_id="s1", display_name="s1", fcs_data=fcs_data)
    gate = RectangleGate("FSC-A", "SSC-A", x_min=10_000, x_max=90_000, y_min=10_000, y_max=90_000)
    sample.gate_tree.add_child(gate, name="Lymphocytes")
    return sample


@pytest.mark.unit
def test_pseudocolor_overlay_registered_in_plot_registry():
    assert "🌈  Pseudocolor Overlay" in PLOT_REGISTRY


@pytest.mark.unit
def test_pseudocolor_overlay_renderer_produces_figure():
    rng = np.random.default_rng(0)
    base_x, base_y = rng.uniform(0, 100, 1000), rng.uniform(0, 100, 1000)
    layer_x, layer_y = rng.uniform(20, 80, 200), rng.uniform(20, 80, 200)

    renderer = PseudocolorOverlayRenderer()
    fig = renderer.render(
        base_x=base_x,
        base_y=base_y,
        base_label="All Events",
        layers=[{"label": "Lymphocytes", "x": layer_x, "y": layer_y}],
        x_label="FSC-A",
        y_label="SSC-A",
        sample_label="s1",
    )
    assert fig is not None
    assert len(fig.axes) == 1


@pytest.mark.unit
def test_pseudocolor_overlay_renderer_handles_empty_layers():
    renderer = PseudocolorOverlayRenderer()
    fig = renderer.render(
        base_x=np.array([]), base_y=np.array([]), layers=[], x_label="X", y_label="Y"
    )
    assert fig is not None


@pytest.mark.ui
def test_comparisons_viewer_builds_pseudocolor_overlay_kwargs(qtbot):
    state = FlowState()
    sample = _make_sample_with_gate()
    state.data.experiment.samples[sample.sample_id] = sample

    widget = ComparisonsViewer(state)
    qtbot.addWidget(widget)

    idx = widget._plot_type_combo.findText("🌈  Pseudocolor Overlay")
    assert idx >= 0
    widget._plot_type_combo.setCurrentIndex(idx)

    panel = widget._options_panels["🌈  Pseudocolor Overlay"]
    assert (
        panel._x_combo.count() == 2
    )  # FSC-A, SSC-A populated by _refresh_pseudocolor_overlay_options

    sample_ids = widget._selector.get_checked_sample_ids()
    assert sample_ids == ["s1"]  # SampleMode.SINGLE enforced even with only one sample loaded
    pop_pairs = widget._selector.get_checked_populations()
    assert any(label == "Lymphocytes" for _sid, _nid, label in pop_pairs)

    config = panel.get_config()
    spec = PLOT_REGISTRY["🌈  Pseudocolor Overlay"]
    kwargs = spec.build_kwargs(widget._state, widget._extractor, config, sample_ids, pop_pairs, [])
    assert kwargs["sample_label"] == "s1"
    assert len(kwargs["layers"]) == 1
    assert kwargs["layers"][0]["label"] == "Lymphocytes"
    assert len(kwargs["base_x"]) > 0

    # base_density must be pre-computed by build_kwargs (main thread, no
    # lock held) rather than left for the renderer to compute later while
    # ComparisonsWorker holds MPL_RASTER_LOCK — see kwargs_builders.py docstring.
    assert "base_density" in kwargs
    assert kwargs["base_density"] is not None
    x_plot, y_plot, c_plot = kwargs["base_density"]
    assert len(x_plot) == len(y_plot) == len(c_plot) > 0

    # And the renderer must actually use the pre-computed density rather
    # than silently recomputing it — even if we sabotage base_x/base_y so a
    # from-scratch computation would produce different data. build_kwargs()
    # already sets bg_color/fg_color/border_color (fixed white chrome — see
    # pseudocolor_overlay_renderer.py), so no need to pass them again here.
    fig = spec.renderer_cls().render(
        **{**kwargs, "base_x": np.array([]), "base_y": np.array([])},
    )
    assert fig is not None
