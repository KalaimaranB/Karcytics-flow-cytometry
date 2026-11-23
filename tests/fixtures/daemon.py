"""The worker process without the process: its own handlers, called in-process."""

from typing import Any

from karcytics_plugins.flow_cytometry.analysis import daemon_worker


def in_process_daemon(
    method: str,
    kwargs: dict[str, Any],
    *,
    cancel_poll: Any = None,
    timeout: float = 120.0,
) -> dict[str, Any]:
    """`analysis.daemon_port.DaemonCall`: same handlers (and PhenoGraph graph cache), no process."""
    return daemon_worker.dispatch(method, kwargs)
