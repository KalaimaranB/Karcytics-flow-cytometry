"""The plugin's worker process: the `DaemonCall` analysis code is given, and its warm-up."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from karcytics_sdk.plugin import FunctionalTask, PluginDaemon, get_logger
from karcytics_sdk.plugin.runtime_services import task_scheduler

logger = get_logger(__name__, "flow_cytometry")

PLUGIN_ID = "flow_cytometry"


def call_flow_daemon(
    method: str,
    kwargs: dict[str, Any],
    *,
    cancel_poll: Callable[[], bool] | None = None,
    timeout: float = 120.0,
) -> dict[str, Any]:
    """`analysis.daemon_port.DaemonCall` on the real worker (PluginDaemon serialises calls)."""
    return PluginDaemon.get_instance(PLUGIN_ID).call(
        method, kwargs, cancel_poll=cancel_poll, timeout=timeout
    )


def _start_daemon() -> None:
    try:
        PluginDaemon.start_instance(PLUGIN_ID)
    except Exception as exc:  # noqa: BLE001 - the first real call starts it again
        logger.warning("FCS daemon warm-up failed (will retry lazily on first load): %s", exc)


def warm_up_flow_daemon() -> None:
    """Starts the worker on the task pool so the session's first import skips its startup.

    Spawning it and importing FlowKit, fcsparser and numpy there takes several
    seconds; the first `load_fcs` lands on a warm process instead.
    """
    task_scheduler.submit(FunctionalTask(_start_daemon, PLUGIN_ID, "Start the FCS worker"))
