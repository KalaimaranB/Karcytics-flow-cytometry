"""PhenoGraph without the daemon process: the daemon's own handler, called in-process."""

import base64
import io

import numpy as np


def _encode(array):
    buf = io.BytesIO()
    np.save(buf, np.asarray(array), allow_pickle=False)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _decode(text):
    return np.load(io.BytesIO(base64.b64decode(text)), allow_pickle=False)


def in_process_compute(x, params, run_uid, cancelled=None):  # noqa: ARG001 - compute()'s signature
    """Stands in for ``phenograph_analysis.compute``: same handler, same cache, no process."""
    from karcytics_plugins.flow_cytometry.analysis.daemon_worker import handle_run_phenograph

    reply = handle_run_phenograph({"x_b64": _encode(x), "params": params, "run_uid": run_uid})
    if "error" in reply:
        raise RuntimeError(reply["error"])
    return {k: _decode(reply[f"{k}_b64"]) for k in ("clusters", "edges", "connectivity", "layout")}
