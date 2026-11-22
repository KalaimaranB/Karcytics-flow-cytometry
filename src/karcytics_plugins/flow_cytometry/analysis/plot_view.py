"""What a population's plot opens on, and the axis scales fitted to it.

Qt-free: the graph window asks these, then applies the answers to its
controls and canvas.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .population_service import population_events
from .scaling import AxisScale, fit_scale

if TYPE_CHECKING:
    from .experiment import Experiment, Sample
    from .gating import GateNode

ROOT_KEY = "root"  # ``Sample.last_viewed_axes`` key of the whole sample


@dataclass(frozen=True)
class OpeningView:
    """The axes (and, when remembered, the scales and plot type) a plot opens on."""

    x_param: str
    y_param: str
    x_scale: AxisScale | None = None
    y_scale: AxisScale | None = None
    plot_type: str | None = None


def opening_view(
    sample: Sample, node_id: str | None, default_x: str, default_y: str
) -> OpeningView:
    """The view a plot of ``node_id``'s population (None: the whole sample) opens on.

    In order of preference:

    1. The view a gate was drawn on: the population's own, else its parent's
       (where the gate coordinator records it), so a child opens in the view
       it was carved out of. It brings its scales and plot type.
    2. The axes last viewed on this population, else on the nearest ancestor.
    3. For a population with sub-populations, the axes the first was drawn on.
    4. ``default_x`` / ``default_y``.
    """
    node = sample.gate_tree.find_node_by_id(node_id) if node_id else None
    if (drawn := _drawn_on(node, default_y)) is not None:
        return drawn
    if (remembered := _last_viewed(sample, node_id)) is not None:
        return remembered
    if node is not None and node.children and node.children[0].gate is not None:
        gate = node.children[0].gate
        gate_x = getattr(gate, "x_param", None)
        gate_y = getattr(gate, "y_param", None)
        if gate_x != "Subset" and gate_y:  # a subset or a range has no 2-D view to reuse
            return OpeningView(gate_x or default_x, gate_y)
    return OpeningView(default_x, default_y)


def _drawn_on(node: GateNode | None, default_y: str) -> OpeningView | None:
    if node is None:
        return None
    source = node.parents[0] if not node.creation_view and node.parents else node
    view = source.creation_view
    if not view or "x_param" not in view:
        return None
    y_param = view.get("y_param") or view.get("view_y_param") or default_y
    return OpeningView(
        view["x_param"],
        y_param,
        AxisScale.from_dict(view["x_scale"]) if view.get("x_scale") is not None else None,
        AxisScale.from_dict(view["y_scale"]) if view.get("y_scale") is not None else None,
        view.get("plot_type"),
    )


def _last_viewed(sample: Sample, node_id: str | None) -> OpeningView | None:
    """The axes last viewed on ``node_id``'s population or its nearest ancestor."""
    while True:
        remembered = sample.last_viewed_axes.get(node_id or ROOT_KEY, {})
        if "x_param" in remembered and "y_param" in remembered:
            return OpeningView(remembered["x_param"], remembered["y_param"])
        if node_id is None:
            return None
        node = sample.gate_tree.find_node_by_id(node_id)
        parent = node.parents[0] if node is not None and node.parents else None
        if parent is None:
            return None
        node_id = None if parent.is_root else parent.node_id


def fitted_scales(
    experiment: Experiment,
    sample: Sample,
    node_id: str | None,
    axes: tuple[str, str],
    scales: tuple[AxisScale, AxisScale],
) -> tuple[AxisScale, AxisScale] | None:
    """Copies of ``scales`` fitted to the data on ``axes``; None if the sample has no events.

    The transform's shape (W and A) comes from the *parent* population, the
    events the gate was drawn on, as FlowJo does; the range from the whole
    sample (see ``fit_scale``). A population at the top falls back to the
    whole sample, and so does an empty parent.
    """
    sample_events = population_events(experiment, sample)
    if sample_events is None:
        return None
    node = sample.gate_tree.find_node_by_id(node_id) if node_id else None
    parent = node.parents[0] if node is not None and node.parents else None
    parent_events = population_events(experiment, sample, parent) if parent is not None else None
    if parent_events is None or len(parent_events) == 0:
        parent_events = sample_events
    (x_param, y_param), (x_scale, y_scale) = axes, scales
    return (
        fit_scale(x_scale.copy(), x_param, sample_events, parent_events),
        fit_scale(y_scale.copy(), y_param, sample_events, parent_events),
    )
