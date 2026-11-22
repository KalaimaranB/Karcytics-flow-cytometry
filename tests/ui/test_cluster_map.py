"""A clustering method's own picture: the headless renderers and the view's hover."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
from matplotlib.collections import LineCollection

from karcytics_plugins.flow_cytometry.ui.widgets.cluster_map_renderer import (
    ClusterMapPicture,
    ClusterMapRenderer,
    MapLabel,
    MapLines,
    MapTheme,
    PhenotypeHeatmapRenderer,
)
from karcytics_plugins.flow_cytometry.ui.widgets.phenograph_graph import PhenographGraphView

pytestmark = pytest.mark.ui

THEME = MapTheme("#101010", "#000000", "#eeeeee", "#999999", "#333333")
LAYOUT = np.array([[0.0, 0.0], [4.0, 0.0], [0.0, 4.0]])


def _picture(**changes) -> ClusterMapPicture:
    fields = {
        "layout": LAYOUT,
        "counts": np.array([10, 40, 5]),
        "clusters": np.array([0, 1, 2]),
        "lines": MapLines(LAYOUT[[[0, 1]]], widths=1.0, alphas=0.5),
        "title": "Three clusters",
        "labels": (MapLabel("A", (0.0, 0.0)), MapLabel("B", (4.0, 0.0))),
    }
    return ClusterMapPicture(**{**fields, **changes})


def test_coloured_by_cluster_the_map_names_clusters_and_has_no_scale():
    fig = ClusterMapRenderer().render(picture=_picture(), theme=THEME)

    (ax,) = fig.axes
    assert ax.get_title() == "Three clusters"
    assert [t.get_text() for t in ax.texts] == ["A", "B"]
    assert len(ax.collections) == 2  # the lines, then the circles  # noqa: PLR2004
    assert isinstance(ax.collections[0], LineCollection)
    sizes = ax.collections[1].get_sizes()
    assert sizes[1] == sizes.max()  # the biggest cluster draws the biggest circle


def test_coloured_by_a_marker_the_map_adds_its_scale_and_drops_the_names():
    picture = _picture(marker="CD4", marker_values=np.array([1.0, 5.0, 3.0]), lines=None)

    fig = ClusterMapRenderer().render(picture=picture, theme=THEME)

    ax, scale = fig.axes
    assert scale.get_ylabel() == "CD4: dimmest to brightest"
    assert len(ax.texts) == 0
    assert len(ax.collections) == 1  # no lines given


def test_the_heatmap_leaves_markers_that_barely_differ_blank():
    levels = np.array([[0.0, np.nan], [1.0, np.nan]])

    fig = PhenotypeHeatmapRenderer().render(
        rows=["A", "B"], markers=["CD3", "CD4"], levels=levels, theme=THEME
    )

    ax = fig.axes[0]
    assert len(ax.texts) == 2  # one call per informative cell  # noqa: PLR2004
    assert [t.get_text() for t in ax.get_xticklabels()] == ["CD3", "CD4"]


def _phenograph_run() -> dict:
    rng = np.random.default_rng(0)
    clusters = np.repeat([0, 1, 2], 30)
    intensities = rng.normal(size=(90, 2)) + clusters[:, None] * [3.0, 0.0]
    return {
        "method": "phenograph",
        "resolution": 1.0,
        "channel_labels": ["CD3", "CD4"],
        "clusters": clusters,
        "intensities": intensities,
        "layout": LAYOUT,
        "cluster_edges": np.array([[0, 1]]),
        "cluster_connectivity": np.array([0.4]),
    }


@pytest.fixture
def graph(qtbot):
    view = PhenographGraphView(_phenograph_run())
    qtbot.addWidget(view)
    qtbot.waitUntil(lambda: view._map.figure is not None and not view._map.is_rendering())
    return view


def _hover(view, x, y, axes):
    view._on_hover(SimpleNamespace(inaxes=axes, xdata=x, ydata=y))
    return view._hover_lbl.text()


def test_the_map_and_heatmap_draw_in_the_background(graph, qtbot):
    qtbot.waitUntil(lambda: graph._heatmap.figure is not None)
    assert graph._map.figure.axes[0].get_title().startswith("PhenoGraph: 3 clusters")
    assert graph._map.objectName() == "PhenographGraphCanvas"  # what the Academy targets


def test_hovering_a_circle_describes_its_cluster(graph):
    ax = graph._map.figure.axes[0]

    text = _hover(graph, 0.05, 3.95, ax)

    assert text.startswith("<b>C2</b> · 30 cells (33.3%)")
    assert "stands apart" in text  # cluster 2 has no links


def test_hovering_the_colour_scale_is_ignored(graph, qtbot):
    graph._color_combo.setCurrentIndex(1)  # by CD3: a colour scale appears
    qtbot.waitUntil(lambda: len(graph._map.figure.axes) == 2 and not graph._map.is_rendering())
    before = graph._hover_lbl.text()

    # (0, 4) in the scale's own units would land on cluster 2.
    assert _hover(graph, 0.0, 4.0, graph._map.figure.axes[1]) == before
