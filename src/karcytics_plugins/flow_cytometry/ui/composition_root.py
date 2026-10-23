"""Composition root: builds and wires every service the panel uses, in dependency order.

`build_services()` is the one place a service is constructed; widgets receive the
ones they need from the `FlowServices` it returns.
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

from karcytics_sdk.plugin import CentralEventBus, get_logger
from karcytics_sdk.plugin.runtime_services import task_scheduler

from ..analysis.api_cache import CacheManager
from ..analysis.attachment_manager import AttachmentManager
from ..analysis.axis_manager import AxisManager
from ..analysis.biology_services import FluorophoreService
from ..analysis.gate_coordinator import GateCoordinator
from ..analysis.population_service import PopulationService
from ..analysis.services.data_loader_service import DataLoaderService
from ..analysis.services.derived_parameter_service import DerivedParameterService
from ..analysis.services.umap_service import UmapService
from ..analysis.store import FlowStore
from .controllers.derived_editor_controller import DerivedEditorController
from .services.flow_daemon import call_flow_daemon
from .services.workflow_service import WorkflowService
from .services.workspace_io_handler import WorkspaceIOHandler

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

    from ..analysis.gate_propagator import GatePropagator
    from ..analysis.state import FlowState

# The [phase1] breadcrumbs show which construction a stalled daemon never got past.
logger = get_logger(__name__, "flow_cytometry")


@dataclass(frozen=True)
class FlowServices:
    """Every service one panel uses, built once by `build_services()`."""

    axis_manager: AxisManager
    population_service: PopulationService
    derived_parameter_service: DerivedParameterService
    fluor_service: FluorophoreService
    gate_coordinator: GateCoordinator
    data_loader_service: DataLoaderService
    workflow_service: WorkflowService
    umap_service: UmapService
    workspace_io_handler: WorkspaceIOHandler
    store: FlowStore
    derived_editor: DerivedEditorController

    @property
    def gate_propagator(self) -> GatePropagator:
        return self.gate_coordinator.propagator


def build_services(state: FlowState, parent_widget: QWidget) -> FlowServices:
    """Builds every service for `state`; `parent_widget` (the panel) parents their dialogs."""
    logger.debug("[phase1] build_services: constructing domain services")
    axis_manager = AxisManager(state)
    population_service = PopulationService(state)
    state.axis_manager = axis_manager
    state.population_service = population_service

    cache_dir = pathlib.Path.home() / ".karcytics" / "cache" / "biology"
    fluor_service = FluorophoreService(CacheManager(cache_dir))
    derived_parameter_service = DerivedParameterService(state)
    gate_coordinator = GateCoordinator(state, axis_manager, population_service, task_scheduler)

    logger.debug("[phase1] build_services: constructing DataLoaderService")
    data_loader_service = DataLoaderService(task_scheduler, call_flow_daemon)
    workflow_service = WorkflowService(state, data_loader_service, AttachmentManager(axis_manager))
    umap_service = UmapService(state, task_scheduler, call_flow_daemon)

    logger.debug("[phase1] build_services: constructing WorkspaceIOHandler")
    workspace_io_handler = WorkspaceIOHandler(
        workflow_service=workflow_service, parent_widget=parent_widget
    )
    # The store snapshots `state` itself (never a copy) into an SDK UndoHistory.
    store = FlowStore(state, CentralEventBus.publish)
    derived_editor = DerivedEditorController(
        state,
        derived_parameter_service,
        remove_population=gate_coordinator.remove_population,
        parent=parent_widget,
    )
    logger.debug("[phase1] build_services: done")

    return FlowServices(
        axis_manager=axis_manager,
        population_service=population_service,
        derived_parameter_service=derived_parameter_service,
        fluor_service=fluor_service,
        gate_coordinator=gate_coordinator,
        data_loader_service=data_loader_service,
        workflow_service=workflow_service,
        umap_service=umap_service,
        workspace_io_handler=workspace_io_handler,
        store=store,
        derived_editor=derived_editor,
    )
