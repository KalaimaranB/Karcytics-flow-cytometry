"""The one serializer between a live ``FlowState`` and plain data.

Every path that turns the workspace into data or back goes through here:
workflow save/load (``WorkflowService``), the undo history (``FlowStore``)
and ``FlowState.to_dict``/``from_dict``. There used to be three hand-written
copies (the state's own ``to_dict``/``from_dict``, the panel's
``export_state``/``load_state``, and ``WorkflowService``), and they had
already drifted — different view defaults, different field sets.

Two shapes come out of it:

* the **workflow document** (``serialize_workspace``/``apply_workspace``)
  — everything a saved workflow holds: the experiment, compensation, and the
  persisted view settings. ``WorkflowService`` adds ``sample_paths`` and
  binary attachments around it.
* the **model snapshot** (``capture_model``) — just the part of that an undo
  step restores. See ``capture_model`` for what is left out and why.

Identity contract: ``apply_*`` never replaces ``state``, ``state.data`` or
``state.view`` — dozens of services and widgets hold those references for
their whole lifetime. They *do* replace ``state.data.experiment`` (and with
it every ``Sample``/``Group``/``GateNode``), so nothing may cache those
across a load or an undo; look them up by id through ``state`` instead.
"""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any

from .compensation import CompensationMatrix
from .config import RenderConfig
from .experiment import Experiment
from .experiment_io import ExperimentSerializer

if TYPE_CHECKING:
    from .state import FlowState, ViewState

#: View settings persisted in a workflow, in save order. Everything else on
#: ``ViewState`` (live widget references, the group filter, the FMO overlay,
#: fallback scales) is session-only and reset to its default on load.
PERSISTED_VIEW_FIELDS: tuple[str, ...] = (
    "current_sample_id",
    "current_gate_id",
    "active_x_param",
    "active_y_param",
    "active_transform_x",
    "active_transform_y",
    "active_plot_type",
    "auto_range_on_quality",
)

#: Per-sample / per-group keys a model snapshot leaves out (see capture_model).
_SAMPLE_NAVIGATION_KEYS = ("last_viewed_axes",)
_GROUP_DISPLAY_KEYS = ("channel_scales",)


def detached(value: Any) -> Any:
    """Copy every dict/list/set in `value`; share tuples and scalars.

    Serializers hand back references to live containers (a sample's
    ``group_ids`` list, a group's ``sample_ids``...). A snapshot that kept
    those would silently change the next time the live list is appended to.
    Tuples are treated as immutable and shared, which is what keeps large
    index payloads (``SubsetGate``) from being copied into every step.
    """
    if isinstance(value, dict):
        return {k: detached(v) for k, v in value.items()}
    if isinstance(value, list):
        return [detached(v) for v in value]
    if isinstance(value, set):
        return {detached(v) for v in value}
    return value


# ── Workflow document ─────────────────────────────────────────────────


def serialize_view(view: ViewState) -> dict[str, Any]:
    data = {name: copy.deepcopy(getattr(view, name)) for name in PERSISTED_VIEW_FIELDS}
    data["render_config"] = view.render_config.to_dict()
    return data


def apply_view(view: ViewState, data: dict[str, Any]) -> None:
    """Reset every view setting from `data`, defaulting what it lacks.

    Defaults come from a fresh ``ViewState`` rather than literals here, so a
    load and a brand-new workspace always agree on them.
    """
    from .state import ViewState

    defaults = ViewState()
    for name in PERSISTED_VIEW_FIELDS:
        setattr(view, name, copy.deepcopy(data.get(name, getattr(defaults, name))))
    view.render_config = RenderConfig.from_dict(data.get("render_config") or {})
    # Session-only settings don't carry over from the previous workspace.
    view.active_group_filter = defaults.active_group_filter
    view.active_fmo_sample_id = defaults.active_fmo_sample_id
    view.fallback_scales = {}


def serialize_compensation(comp: CompensationMatrix | None) -> dict[str, Any] | None:
    return comp.to_dict() if comp is not None else None


def deserialize_compensation(data: dict[str, Any] | None) -> CompensationMatrix | None:
    return CompensationMatrix.from_dict(data) if data else None


def serialize_workspace(state: FlowState) -> dict[str, Any]:
    """The workflow document for `state` (no event data, no attachments)."""
    return {
        "experiment": ExperimentSerializer.serialize_experiment(state.data.experiment),
        "compensation": serialize_compensation(state.data.compensation),
        "view": serialize_view(state.view),
    }


def apply_workspace(state: FlowState, document: dict[str, Any]) -> None:
    """Replace `state`'s contents with `document`, in place.

    The previous workspace is discarded entirely — including any UMAP runs,
    which a document never carries (they come back from attachments, if the
    workflow has any). Event data is not loaded here; samples come back with
    ``fcs_data=None`` until the caller reloads it.
    """
    exp_data = document.get("experiment")
    state.data.experiment = (
        ExperimentSerializer.deserialize_experiment(detached(exp_data))
        if exp_data
        else Experiment()
    )
    state.data.compensation = deserialize_compensation(document.get("compensation"))
    state.data.umap_results = {}
    apply_view(state.view, document.get("view") or {})


# ── Undo snapshot ─────────────────────────────────────────────────────


def capture_model(state: FlowState, umap_run_ids: dict[str, list[str]]) -> dict[str, Any]:
    """The analysis model as an undo step sees it.

    Left out on purpose, and kept from the live state on restore instead:

    * event data and UMAP embeddings — far too large to copy per step; the
      store reattaches them by sample id / run id.
    * each group's ``channel_scales`` — rendering writes auto-ranged
      defaults into them on every first draw, so they'd turn every redraw
      into an undoable change. Saved with the workflow, but not undoable.
    * each sample's ``last_viewed_axes`` and the whole ``ViewState`` —
      navigation, which undo should never jump around.

    The result is detached from the live objects (see ``detached``).
    """
    experiment = ExperimentSerializer.serialize_experiment(state.data.experiment)
    for sample_data in experiment["samples"].values():
        for key in _SAMPLE_NAVIGATION_KEYS:
            sample_data.pop(key, None)
    for group_data in experiment["groups"].values():
        for key in _GROUP_DISPLAY_KEYS:
            group_data.pop(key, None)
    return detached(
        {
            "experiment": experiment,
            "compensation": serialize_compensation(state.data.compensation),
            "umap_runs": {key: list(ids) for key, ids in umap_run_ids.items()},
        }
    )


def model_experiment(snapshot: dict[str, Any]) -> Experiment:
    """A fresh ``Experiment`` built from a model snapshot (no event data)."""
    return ExperimentSerializer.deserialize_experiment(detached(snapshot["experiment"]))
