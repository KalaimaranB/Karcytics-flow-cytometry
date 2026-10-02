"""Flow cytometry workspace state container.

``FlowState`` is the single source of truth for the entire analysis
session: a plain dataclass holding every intermediate result. One instance
lives for the whole session — loads and undo/redo change its contents in
place and never replace it (or ``.data``/``.view``), so every service and
widget can keep the reference it was constructed with.

Serialization lives in ``workspace_document`` (the only serializer); undo
history in ``store.FlowStore``. Kept free of Qt so tests can inspect it
without a GUI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from karcytics_sdk.plugin import CentralEventBus, PluginState, get_logger

from . import events
from .compensation import CompensationMatrix
from .config import FlowConfig, RenderConfig
from .experiment import Experiment

logger = get_logger(__name__, "flow_cytometry")


@dataclass
class ExperimentState:
    """Domain model state layer."""

    experiment: Experiment = field(default_factory=Experiment)
    compensation: CompensationMatrix | None = None
    umap_results: dict[str, list[dict]] = field(default_factory=dict)


@dataclass
class ViewState:
    """UI and presentation state layer."""

    current_sample_id: str | None = None
    current_gate_id: str | None = None
    active_x_param: str = field(default_factory=lambda: FlowConfig.get_last_params()[0])
    active_y_param: str = field(default_factory=lambda: FlowConfig.get_last_params()[1])
    active_transform_x: str = "linear"
    active_transform_y: str = "linear"
    active_main_tab_index: int = 0
    active_plot_type: str = "pseudocolor"
    active_group_filter: str = "__all__"
    active_fmo_sample_id: str | None = None
    auto_range_on_quality: bool = field(default_factory=FlowConfig.get_auto_range)
    fallback_scales: dict[str, Any] = field(default_factory=dict)
    _render_config: RenderConfig = field(default_factory=RenderConfig)

    # Live widget references bolted on by WorkspaceBuilder so tutorial
    # validators can introspect UI state without importing Qt widget
    # classes here. Never serialized (to_dict below is hand-written and
    # omits them) and excluded from repr/eq since widgets aren't picklable.
    _graph_manager: Any | None = field(default=None, repr=False, compare=False)
    _pipeline_ribbon: Any | None = field(default=None, repr=False, compare=False)
    _spectral_viewer: Any | None = field(default=None, repr=False, compare=False)
    _statistics_explorer: Any | None = field(default=None, repr=False, compare=False)
    _comparisons_viewer: Any | None = field(default=None, repr=False, compare=False)
    _population_analysis_viewer: Any | None = field(default=None, repr=False, compare=False)
    _derived_editor: Any | None = field(default=None, repr=False, compare=False)

    @property
    def render_config(self) -> RenderConfig:
        return self._render_config

    @render_config.setter
    def render_config(self, value: RenderConfig) -> None:
        self._render_config = value
        CentralEventBus.publish(events.RENDER_CONFIG_CHANGED, {"config": value})


@dataclass
class FlowState(PluginState):
    """Mutable state for one flow cytometry analysis session.

    Now layered into 'data' (ExperimentState) and 'view' (ViewState).
    """

    # ── Layers ────────────────────────────────────────────────────────
    data: ExperimentState = field(default_factory=ExperimentState)
    view: ViewState = field(default_factory=ViewState)

    # ── Services ──────────────────────────────────────────────────────
    axis_manager: Any | None = None
    population_service: Any | None = None

    def to_dict(self) -> dict:
        """The workflow document for this state (see ``workspace_document``)."""
        from .workspace_document import serialize_workspace

        return serialize_workspace(self)

    @classmethod
    def from_dict(cls, data: dict) -> FlowState:
        """A new state loaded from a workflow document (no event data)."""
        from .workspace_document import apply_workspace

        state = cls()
        apply_workspace(state, data)
        return state
