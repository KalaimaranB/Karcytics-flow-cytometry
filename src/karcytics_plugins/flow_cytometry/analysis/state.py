"""Flow cytometry workspace state container.

``FlowState`` is the single source of truth for the entire analysis
session.  It follows the same pattern as the Western Blot
``AnalysisState``: a plain dataclass that holds every intermediate
result, with ``to_workflow_dict`` / ``from_workflow_dict`` for
serialization.

The state is intentionally kept separate from both the UI and the
analysis engines so that:
- Undo/Redo can snapshot it cheaply via ``export_state`` / ``load_state``.
- It can be serialized to disk independently of the GUI.
- Tests can inspect it without importing PyQt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from karcytics_sdk.plugin import CentralEventBus, PluginState, get_logger

from . import events
from .compensation import CompensationMatrix
from .config import FlowConfig, RenderConfig
from .experiment import Experiment
from .experiment_io import ExperimentSerializer

if TYPE_CHECKING:
    pass

logger = get_logger(__name__, "flow_cytometry")


@dataclass
class ExperimentState:
    """Domain model state layer."""

    experiment: Experiment = field(default_factory=Experiment)
    compensation: CompensationMatrix | None = None
    umap_results: dict[str, list[dict]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "experiment": ExperimentSerializer.serialize_experiment(self.experiment)
            if self.experiment
            else None,
            "compensation": self.compensation.to_dict()
            if self.compensation and hasattr(self.compensation, "to_dict")
            else None,
            "umap_results": {},  # Stripped to prevent massive history/JSON bloat
        }


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

    @property
    def render_config(self) -> RenderConfig:
        return self._render_config

    @render_config.setter
    def render_config(self, value: RenderConfig) -> None:
        self._render_config = value
        CentralEventBus.publish(events.RENDER_CONFIG_CHANGED, {"config": value})

    def to_dict(self) -> dict:
        return {
            "current_sample_id": self.current_sample_id,
            "current_gate_id": self.current_gate_id,
            "active_x_param": self.active_x_param,
            "active_y_param": self.active_y_param,
            "active_transform_x": self.active_transform_x,
            "active_transform_y": self.active_transform_y,
            "active_plot_type": self.active_plot_type,
            "active_group_filter": self.active_group_filter,
            "auto_range_on_quality": self.auto_range_on_quality,
            "render_config": self.render_config.to_dict(),
        }


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
        """Standard serialization for undo history snapshots."""
        return {
            "data": self.data.to_dict(),
            "view": self.view.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> FlowState:
        """Reconstruct the nested state objects properly from dict for Undo/Redo."""
        state = cls()
        if "data" in data:
            d_data = data["data"]
            if "experiment" in d_data and d_data["experiment"]:
                state.data.experiment = ExperimentSerializer.deserialize_experiment(
                    d_data["experiment"]
                )
            if "compensation" in d_data and d_data["compensation"]:
                state.data.compensation = CompensationMatrix.from_dict(d_data["compensation"])
            if "umap_results" in d_data and d_data["umap_results"]:
                import numpy as np

                loaded_umap = {}
                for key, runs in d_data["umap_results"].items():
                    loaded_runs = []
                    for run in runs:
                        run_copy = run.copy()
                        if "embedding" in run_copy and isinstance(run_copy["embedding"], list):
                            run_copy["embedding"] = np.array(
                                run_copy["embedding"], dtype=np.float32
                            )
                        loaded_runs.append(run_copy)
                    loaded_umap[key] = loaded_runs
                state.data.umap_results = loaded_umap
        if "view" in data:
            v_data = data["view"]
            state.view.current_sample_id = v_data.get("current_sample_id")
            state.view.current_gate_id = v_data.get("current_gate_id")
            state.view.active_x_param = v_data.get("active_x_param", "FSC-A")
            state.view.active_y_param = v_data.get("active_y_param", "SSC-A")
            state.view.active_transform_x = v_data.get("active_transform_x", "linear")
            state.view.active_transform_y = v_data.get("active_transform_y", "linear")
            state.view.active_plot_type = v_data.get("active_plot_type", "pseudocolor")
            state.view.active_group_filter = v_data.get("active_group_filter", "__all__")
            state.view.auto_range_on_quality = v_data.get("auto_range_on_quality", True)
            if "render_config" in v_data:
                state.view.render_config = RenderConfig.from_dict(v_data["render_config"])
        return state
