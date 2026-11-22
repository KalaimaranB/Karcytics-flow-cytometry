"""What a population's plot opens on, and the scales fitted to it."""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from karcytics_plugins.flow_cytometry.analysis.experiment import Experiment, Sample
from karcytics_plugins.flow_cytometry.analysis.gating.rectangle import RectangleGate
from karcytics_plugins.flow_cytometry.analysis.gating.subset import SubsetGate
from karcytics_plugins.flow_cytometry.analysis.plot_view import (
    OpeningView,
    fitted_scales,
    opening_view,
)
from karcytics_plugins.flow_cytometry.analysis.scaling import AxisScale
from karcytics_plugins.flow_cytometry.analysis.transforms import TransformType

DEFAULTS = ("FSC-A", "SSC-A")


@pytest.fixture
def sample():
    """Lymphocytes (FSC/SSC) > T cells (CD3/CD4) > CD4+ (CD4/CD8)."""
    sample = Sample(sample_id="s", display_name="S")
    lymph = sample.gate_tree.add_child(RectangleGate("FSC-A", "SSC-A", x_min=1), "Lymphocytes")
    t_cells = lymph.add_child(RectangleGate("CD3", "CD4", x_min=1), "T cells")
    t_cells.add_child(RectangleGate("CD4", "CD8", x_min=1), "CD4+")
    return sample


def _node(sample, *names):
    node = sample.gate_tree
    for name in names:
        node = next(c for c in node.children if c.name == name)
    return node


def test_with_nothing_remembered_the_whole_sample_opens_on_the_defaults(sample):
    assert opening_view(sample, None, *DEFAULTS) == OpeningView(*DEFAULTS)


def test_a_population_opens_on_the_view_its_child_gate_was_drawn_on(sample):
    lymph = _node(sample, "Lymphocytes")
    lymph.creation_view = {
        "x_param": "CD3",
        "y_param": "CD4",
        "x_scale": AxisScale(TransformType.BIEXPONENTIAL).to_dict(),
        "plot_type": "contour",
    }

    view = opening_view(sample, lymph.node_id, *DEFAULTS)

    assert (view.x_param, view.y_param, view.plot_type) == ("CD3", "CD4", "contour")
    assert view.x_scale.transform_type is TransformType.BIEXPONENTIAL
    assert view.y_scale is None


def test_the_drawn_view_wins_over_the_last_viewed_axes(sample):
    lymph = _node(sample, "Lymphocytes")
    lymph.creation_view = {"x_param": "CD3", "y_param": "CD4"}
    sample.last_viewed_axes[lymph.node_id] = {"x_param": "A", "y_param": "B"}

    assert opening_view(sample, lymph.node_id, *DEFAULTS) == OpeningView("CD3", "CD4")


def test_without_its_own_drawn_view_a_population_takes_its_parents(sample):
    lymph = _node(sample, "Lymphocytes")
    lymph.creation_view = {"x_param": "CD3", "view_y_param": "CD4"}  # a range on a scatter

    view = opening_view(sample, _node(sample, "Lymphocytes", "T cells").node_id, *DEFAULTS)

    assert (view.x_param, view.y_param) == ("CD3", "CD4")


def test_last_viewed_axes_come_next_then_the_nearest_ancestors(sample):
    t_cells = _node(sample, "Lymphocytes", "T cells")
    cd4 = _node(sample, "Lymphocytes", "T cells", "CD4+")
    sample.last_viewed_axes["root"] = {"x_param": "A", "y_param": "B"}
    sample.last_viewed_axes[t_cells.node_id] = {"x_param": "C", "y_param": "D"}

    assert opening_view(sample, cd4.node_id, *DEFAULTS) == OpeningView("C", "D")
    del sample.last_viewed_axes[t_cells.node_id]
    assert opening_view(sample, cd4.node_id, *DEFAULTS) == OpeningView("A", "B")


def test_otherwise_a_population_opens_on_the_axes_of_its_first_sub_population(sample):
    t_cells = _node(sample, "Lymphocytes", "T cells")

    assert opening_view(sample, t_cells.node_id, *DEFAULTS) == OpeningView("CD4", "CD8")


def test_a_subset_child_has_no_axes_to_reuse(sample):
    leaf = _node(sample, "Lymphocytes", "T cells", "CD4+")
    leaf.add_child(SubsetGate(indices=[0, 1]), "Picked")

    assert opening_view(sample, leaf.node_id, *DEFAULTS) == OpeningView(*DEFAULTS)


def _loaded(sample, events: pd.DataFrame) -> Experiment:
    sample.fcs_data = MagicMock()
    sample.fcs_data.events = events
    sample.fcs_data.channels = list(events.columns)
    experiment = Experiment()
    experiment.samples[sample.sample_id] = sample
    return experiment


def test_fitted_scales_are_copies_ranged_to_the_whole_sample(sample):
    rng = np.random.default_rng(0)
    events = pd.DataFrame({"FSC-A": rng.uniform(0, 1000, 500), "SSC-A": rng.uniform(0, 50, 500)})
    experiment = _loaded(sample, events)
    scales = (AxisScale(TransformType.LINEAR), AxisScale(TransformType.LINEAR))
    lymph = _node(sample, "Lymphocytes")

    fitted = fitted_scales(experiment, sample, lymph.node_id, DEFAULTS, scales)

    assert fitted is not None
    assert all(f is not s for f, s in zip(fitted, scales, strict=True))
    assert fitted[0].max_val >= events["FSC-A"].max() * 0.9
    assert scales[0].max_val is None  # the caller's scales are left alone


def test_no_events_no_scales(sample):
    scales = (AxisScale(TransformType.LINEAR), AxisScale(TransformType.LINEAR))
    assert fitted_scales(Experiment(), sample, None, DEFAULTS, scales) is None
