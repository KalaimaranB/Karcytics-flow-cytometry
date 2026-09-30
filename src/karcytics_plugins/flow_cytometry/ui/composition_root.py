"""Composition Root for Flow Cytometry Plugin.

This module provides the ServiceFactory which centralizes the instantiation
and wiring of all domain and infrastructure services, adhering to the
Dependency Inversion Principle.
"""

import pathlib
from typing import Any

from karcytics_sdk.plugin import get_logger

from karcytics_plugins.flow_cytometry.analysis.state import FlowState

# TEMPORARY diagnostic instrumentation (see PR discussion) — pinpoints
# exactly which service construction a stalled daemon subprocess never gets
# past. .warning() is the lowest level guaranteed visible in captured
# stderr without a configured handler — same reasoning as main_panel.py's
# [phase2] breadcrumbs.
logger = get_logger(__name__, "flow_cytometry")


class ServiceFactory:
    """Manages creation and dependency injection of all core services."""

    def __init__(self, state: FlowState, parent_widget: Any | None = None):
        """Initialize the factory with the root state and UI parent.

        Args:
            state: The global flow state object.
            parent_widget: The main UI panel (used as QWidget parent for dialogs).
        """
        self.state = state
        self.parent_widget = parent_widget
        self._services: dict = {}

    def build_all(self) -> None:
        """Instantiates all services and wires them up."""
        logger.warning("[phase1] ServiceFactory.build_all: importing task_scheduler")
        from karcytics_sdk.plugin.runtime_services import task_scheduler

        logger.warning("[phase1] ServiceFactory.build_all: importing service modules")
        from ..analysis.api_cache import CacheManager
        from ..analysis.axis_manager import AxisManager
        from ..analysis.biology_services import FluorophoreService, MarkerService
        from ..analysis.gate_coordinator import GateCoordinator
        from ..analysis.population_service import PopulationService
        from ..analysis.services.data_loader_service import DataLoaderService
        from ..analysis.services.derived_parameter_service import DerivedParameterService
        from ..analysis.services.umap_service import UmapService
        from .services.attachment_manager import AttachmentManager
        from .services.workflow_service import WorkflowService
        from .services.workspace_io_handler import WorkspaceIOHandler

        logger.warning("[phase1] ServiceFactory.build_all: service modules imported")

        # Domain Services
        # Domain Services
        axis_manager = AxisManager(self.state)
        population_service = PopulationService(self.state)

        self.state.axis_manager = axis_manager
        self.state.population_service = population_service

        # Biology Cache & Services
        logger.warning("[phase1] ServiceFactory.build_all: constructing CacheManager")
        cache_dir = pathlib.Path.home() / ".karcytics" / "cache" / "biology"
        cache_manager = CacheManager(cache_dir)
        fluor_service = FluorophoreService(cache_manager)
        marker_service = MarkerService(cache_manager)
        logger.warning("[phase1] ServiceFactory.build_all: CacheManager/bio services done")

        derived_parameter_service = DerivedParameterService(self.state)

        # Gate Coordination
        gate_coordinator = GateCoordinator(
            self.state, axis_manager, population_service, task_scheduler
        )

        # Computation & Analysis
        logger.warning("[phase1] ServiceFactory.build_all: constructing DataLoaderService")
        data_loader_service = DataLoaderService(task_scheduler)
        attachment_manager = AttachmentManager(axis_manager)
        workflow_service = WorkflowService(self.state, data_loader_service, attachment_manager)
        umap_service = UmapService(self.state, task_scheduler)
        logger.warning("[phase1] ServiceFactory.build_all: analysis services done")

        # UI Services
        logger.warning("[phase1] ServiceFactory.build_all: constructing WorkspaceIOHandler")
        workspace_io_handler = WorkspaceIOHandler(
            workflow_service=workflow_service, parent_widget=self.parent_widget
        )
        logger.warning("[phase1] ServiceFactory.build_all: WorkspaceIOHandler done")

        # Store in registry
        self._services["axis_manager"] = axis_manager
        self._services["population_service"] = population_service
        self._services["derived_parameter_service"] = derived_parameter_service
        self._services["cache_manager"] = cache_manager
        self._services["fluor_service"] = fluor_service
        self._services["marker_service"] = marker_service
        self._services["gate_coordinator"] = gate_coordinator
        self._services["gate_propagator"] = gate_coordinator.propagator
        self._services["workflow_service"] = workflow_service
        self._services["umap_service"] = umap_service
        self._services["data_loader_service"] = data_loader_service
        self._services["workspace_io_handler"] = workspace_io_handler

    def get(self, service_name: str) -> Any:
        """Retrieve a registered service by name.

        Args:
            service_name: The internal name of the service (e.g., 'gate_coordinator').

        Returns:
            The service instance.
        """
        return self._services.get(service_name)
