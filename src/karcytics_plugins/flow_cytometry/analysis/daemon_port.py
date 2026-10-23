"""The worker process as analysis code sees it: one blocking call, no Qt.

`ui/services/flow_daemon.py` supplies the real one (the SDK's `PluginDaemon`);
tests pass `tests.fixtures.daemon.in_process_daemon`, which runs the worker's
handlers in-process.
"""

from __future__ import annotations

import base64
import io
from collections.abc import Callable
from typing import Any, Protocol

import numpy as np


class DaemonCall(Protocol):
    def __call__(
        self,
        method: str,
        kwargs: dict[str, Any],
        *,
        cancel_poll: Callable[[], bool] | None = None,
        timeout: float = 120.0,
    ) -> dict[str, Any]:
        """Runs `method` in the worker; a failure comes back as ``{"error": ...}``."""
        ...


# The wire format for arrays (daemon_worker.py, a standalone script, has its own copy).
def encode_array(array: np.ndarray) -> str:
    buf = io.BytesIO()
    np.save(buf, np.asarray(array), allow_pickle=False)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def decode_array(text: str) -> np.ndarray:
    return np.load(io.BytesIO(base64.b64decode(text.encode("ascii"))), allow_pickle=False)
